"""Auto payments: Razorpay (UPI / cards / netbanking) and NOWPayments (crypto).

Flow: /buy -> user picks a plan + method -> create_order() stores an order and returns a pay URL ->
gateway calls our webhook (web/pay_routes.py) -> verify signature -> fulfill() adds premium or
credits, exactly once, and tells the user.

    orders   _id = our order id ("o" + 14 hex), user_id, kind (premium|credits), plan, method,
             amount (inr paise or usd), currency, status (created|paid|failed), gateway_id,
             pay_url, created, paid_at, payment_id

Safety rules:
  * signatures are checked against the RAW request body before anything is parsed
  * the paid amount must match the order (and the currency), so a cheap payment cannot unlock an
    expensive plan; credits/premium come from OUR order record, never from webhook fields
  * fulfillment is guarded by an atomic created->paid switch: a replayed webhook pays nothing twice
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timedelta, timezone

import aiohttp

from config import (
    CREDIT_PLANS, LOGGER, NOWPAYMENTS_API_KEY, NOWPAYMENTS_API_URL, NOWPAYMENTS_IPN_SECRET,
    PAYMENT_LINK_EXPIRE_MIN, PREMIUM_PLANS, RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET,
    RAZORPAY_WEBHOOK_SECRET, WEB_URL,
)

log = LOGGER("payments", "bot")
_TIMEOUT = aiohttp.ClientTimeout(total=20)


def razorpay_on() -> bool:
    return bool(RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET and RAZORPAY_WEBHOOK_SECRET)


def crypto_on() -> bool:
    return bool(NOWPAYMENTS_API_KEY and NOWPAYMENTS_IPN_SECRET and WEB_URL)


def methods() -> list:
    out = []
    if razorpay_on():
        out.append("razorpay")
    if crypto_on():
        out.append("crypto")
    return out


def find_plan(kind: str, key: str):
    table = PREMIUM_PLANS if kind == "premium" else CREDIT_PLANS if kind == "credits" else {}
    return table.get(key)


def new_order_id() -> str:
    return "o" + secrets.token_hex(7)


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ------------------------------------------------------------ signature checks

def verify_razorpay(raw_body: bytes, signature: str, secret: str = None) -> bool:
    """HMAC-SHA256 hex of the raw body with the webhook secret (X-Razorpay-Signature)."""
    secret = RAZORPAY_WEBHOOK_SECRET if secret is None else secret
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip())


def _sort_keys(obj):
    if isinstance(obj, dict):
        return {k: _sort_keys(obj[k]) for k in sorted(obj)}
    if isinstance(obj, list):
        return [_sort_keys(v) for v in obj]
    return obj


def verify_nowpayments(raw_body: bytes, signature: str, secret: str = None) -> bool:
    """HMAC-SHA512 (hex) of the body re-serialised with keys sorted (x-nowpayments-sig)."""
    secret = NOWPAYMENTS_IPN_SECRET if secret is None else secret
    if not secret or not signature:
        return False
    try:
        body = json.loads(raw_body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return False
    msg = json.dumps(_sort_keys(body), separators=(",", ":"), ensure_ascii=False)
    expected = hmac.new(secret.encode(), msg.encode("utf-8"), hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())


# ------------------------------------------------------------------ gateways

async def _razorpay_create_link(order: dict, plan: dict, description: str) -> dict:
    auth = base64.b64encode(f"{RAZORPAY_KEY_ID}:{RAZORPAY_KEY_SECRET}".encode()).decode()
    payload = {
        "amount": order["amount"],                 # paise
        "currency": "INR",
        "accept_partial": False,
        "reference_id": order["_id"],
        "description": description[:2000],
        "expire_by": int(time.time()) + PAYMENT_LINK_EXPIRE_MIN * 60,
        "notes": {"order": order["_id"], "user": str(order["user_id"])},
        "reminder_enable": False,
    }
    async with aiohttp.ClientSession(timeout=_TIMEOUT) as s:
        async with s.post("https://api.razorpay.com/v1/payment_links", json=payload,
                          headers={"Authorization": f"Basic {auth}"}) as r:
            data = await r.json(content_type=None)
            if r.status >= 300 or not data.get("short_url"):
                err = (data.get("error") or {}).get("description") if isinstance(data, dict) else None
                raise RuntimeError(f"Razorpay refused the link ({r.status}): {err or 'unknown error'}")
            return {"gateway_id": data.get("id", ""), "pay_url": data["short_url"]}


async def _nowpayments_create_invoice(order: dict, description: str) -> dict:
    payload = {
        "price_amount": order["amount"], "price_currency": "usd",
        "order_id": order["_id"], "order_description": description[:200],
        "ipn_callback_url": f"{WEB_URL.rstrip('/')}/webhook/nowpayments",
        "is_fixed_rate": True, "is_fee_paid_by_user": False,
    }
    async with aiohttp.ClientSession(timeout=_TIMEOUT) as s:
        async with s.post(f"{NOWPAYMENTS_API_URL}/invoice", json=payload,
                          headers={"x-api-key": NOWPAYMENTS_API_KEY}) as r:
            data = await r.json(content_type=None)
            if r.status >= 300 or not data.get("invoice_url"):
                raise RuntimeError(f"NOWPayments refused the invoice ({r.status}): {str(data)[:150]}")
            return {"gateway_id": str(data.get("id", "")), "pay_url": data["invoice_url"]}


async def create_order(db, user_id: int, kind: str, plan_key: str, method: str) -> dict:
    """Store an order and open it at the gateway. Raises ValueError (bad input) or RuntimeError (gateway)."""
    plan = find_plan(kind, plan_key)
    if not plan:
        raise ValueError("unknown plan")
    if method not in methods():
        raise ValueError("that payment method is not available")
    # Tapped twice? Hand back the open order instead of creating another gateway link every time.
    recent = await db["orders"].find_one({
        "user_id": int(user_id), "kind": kind, "plan": plan_key, "method": method,
        "status": "created", "created": {"$gt": _now() - timedelta(minutes=min(PAYMENT_LINK_EXPIRE_MIN, 10))},
    })
    if recent and recent.get("pay_url"):
        return recent
    what = plan["label"] + (" premium" if kind == "premium" else "")
    order = {
        "_id": new_order_id(), "user_id": int(user_id), "kind": kind, "plan": plan_key, "method": method,
        "status": "created", "created": _now(), "pay_url": "", "gateway_id": "",
        "currency": "INR" if method == "razorpay" else "USD",
        "amount": int(round(plan["inr"] * 100)) if method == "razorpay" else float(plan["usd"]),
    }
    desc = f"{what} for user {user_id}"
    gw = await (_razorpay_create_link(order, plan, desc) if method == "razorpay"
                else _nowpayments_create_invoice(order, desc))
    order.update(gw)
    await db["orders"].insert_one(order)
    return order


# ------------------------------------------------------------------ fulfilment

def parse_razorpay_event(body: dict):
    """-> (event, order_id, amount_paise, payment_id) from a payment_link.* webhook, or None."""
    try:
        event = body.get("event", "")
        link = body["payload"]["payment_link"]["entity"]
        order_id = link.get("reference_id") or (link.get("notes") or {}).get("order") or ""
        pay = (body["payload"].get("payment") or {}).get("entity") or {}
        return event, order_id, int(link.get("amount_paid", 0)), pay.get("id", "")
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def parse_nowpayments_event(body: dict):
    """-> (status, order_id, price_amount, price_currency, payment_id) or None"""
    try:
        return (str(body["payment_status"]), str(body["order_id"]), float(body["price_amount"]),
                str(body.get("price_currency", "")).lower(), str(body.get("payment_id", "")))
    except (KeyError, TypeError, ValueError):
        return None


async def mark_paid(db, order_id: str, paid_amount, currency: str, payment_id: str = ""):
    """Atomically move an order created -> paid after checking amount and currency.
    -> ('paid', order) | ('already', order) | ('unknown', None) | ('mismatch', order)
    An order that is not 'created' any more (paid, cancelled) is reported as 'already'."""
    order = await db["orders"].find_one({"_id": order_id})
    if not order:
        return "unknown", None
    if order["status"] == "paid":
        return "already", order
    if currency.upper() != order["currency"] or abs(float(paid_amount) - float(order["amount"])) > (0 if order["currency"] == "INR" else 0.01):
        # Only a note: the order stays open, so the correct payment (if it comes) still unlocks it.
        await db["orders"].update_one({"_id": order_id, "status": "created"},
                                      {"$set": {"mismatch": f"{paid_amount} {currency}", "mismatch_at": _now()}})
        return "mismatch", order
    took = await db["orders"].update_one({"_id": order_id, "status": "created"},
                                         {"$set": {"status": "paid", "paid_at": _now(), "payment_id": payment_id}})
    if took.modified_count != 1:
        return "already", order
    return "paid", order


async def fulfill(bot, order: dict) -> str:
    """Give what was bought. Returns a short description for logs. Called once, after mark_paid()."""
    from helper import grants
    uid = order["user_id"]
    plan = find_plan(order["kind"], order["plan"]) or {}
    if order["kind"] == "premium":
        return await grants.grant_premium(bot.mongodb, uid, int(plan.get("days", 0)))
    return await grants.grant_credits(bot.mongodb, uid, int(plan.get("credits", 0)), "payment", order.get("_id", ""), order.get("method", ""))


def amount_text(order: dict) -> str:
    return f"₹{order['amount'] / 100:g}" if order["currency"] == "INR" else f"${order['amount']:g}"


async def notify_paid(bot, order: dict, result: str):
    from helper import stats
    from helper.activity import log_activity
    await stats.bump(bot.mongodb.db, "orders")
    if order["currency"] == "INR":
        await stats.bump(bot.mongodb.db, "revenue", int(order["amount"] // 100))
    await log_activity(bot, "payment_received", order["user_id"], order["_id"],
                       f"{amount_text(order)} via {order['method']} -> {result}")
    try:
        await bot.send_message(
            order["user_id"],
            f"<blockquote>✅ <b>Payment received</b></blockquote>\n"
            f"<b>{amount_text(order)}</b> · {result}\n\nThank you! It is active now. Use /profile to check.")
    except Exception as e:
        log.warning("Could not tell user %s about the payment: %s", order["user_id"], e)
    try:
        await bot.send_message(bot.owner, f"💰 <b>New payment</b>\nuser <code>{order['user_id']}</code> · "
                                          f"{amount_text(order)} · {order['method']}\n{result}")
    except Exception:
        pass


async def process_paid(bot, order_id: str, paid_amount, currency: str, payment_id: str = "") -> str:
    """Everything a verified 'paid' webhook has to do. -> 'ok' | 'duplicate' | 'unknown' | 'mismatch' | 'retry'

    'retry' tells the web route to answer 5xx so the gateway delivers the event again: the order is
    paid but the goods could not be given (database hiccup). The next delivery picks it up."""
    from helper.activity import log_activity
    db = bot.mongodb.db
    code, order = await mark_paid(db, order_id, paid_amount, currency, payment_id)
    if code == "unknown":
        await log_activity(bot, "payment_unknown_order", "gateway", order_id, f"{paid_amount} {currency}")
        return "unknown"
    if code == "mismatch":
        await log_activity(bot, "payment_mismatch", order["user_id"], order_id,
                           f"paid {paid_amount} {currency}, expected {amount_text(order)}")
        try:
            await bot.send_message(bot.owner, f"⚠️ <b>Payment amount mismatch</b>\norder <code>{order_id}</code> "
                                              f"user <code>{order['user_id']}</code>\npaid {paid_amount} {currency}, "
                                              f"expected {amount_text(order)}. Nothing was given; check the gateway.")
        except Exception:
            pass
        return "mismatch"
    # claim the right to give the goods: exactly one delivery gets past this line
    claim = await db["orders"].update_one({"_id": order_id, "status": "paid", "fulfilled": {"$ne": True}},
                                          {"$set": {"fulfilled": True}})
    if claim.modified_count != 1:
        return "duplicate"
    try:
        result = await fulfill(bot, order)
        await db["orders"].update_one({"_id": order_id}, {"$set": {"result": result}})
    except Exception as e:
        log.exception("Could not fulfil order %s", order_id)
        await db["orders"].update_one({"_id": order_id}, {"$set": {"fulfilled": False}})
        try:
            await bot.send_message(bot.owner, f"🚨 <b>Paid order NOT fulfilled</b>\n<code>{order_id}</code> user "
                                              f"<code>{order['user_id']}</code>: {type(e).__name__}. The gateway will retry; "
                                              "if it keeps failing, add it by hand with /addpremium or /add_credit.")
        except Exception:
            pass
        return "retry"
    await notify_paid(bot, order, result)
    return "ok"
