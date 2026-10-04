"""Pay-online buttons for /buy and /cplan: Razorpay (UPI/cards) and crypto.

Callbacks (all short, Telegram allows 64 bytes):
    apay:<kind>:<plan>             pick a payment method (skipped when only one is set up)
    apm:<kind>:<plan>:<method>     create the order, show the pay button
    apchk:<order id>               "I paid": show where the order stands
The money side is handled by the webhooks (web/pay_routes.py), never by these buttons.
"""
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import CREDIT_PLANS, LOGGER, PREMIUM_PLANS
from helper import payments

log = LOGGER("autopay", "bot")
_METHOD_LABEL = {"razorpay": "💳 UPI / Card / Netbanking", "crypto": "🪙 Crypto"}


def online_rows(kind: str, plan_key: str) -> list:
    """Keyboard rows to append under a plan, [] when no gateway is configured."""
    if not payments.methods():
        return []
    return [[InlineKeyboardButton("⚡ ᴘᴀʏ ᴏɴʟɪɴᴇ (ᴀᴜᴛᴏ ᴀᴄᴛɪᴠᴀᴛᴇ)", callback_data=f"apay:{kind}:{plan_key}")]]


def credit_plan_rows() -> list:
    if not payments.methods():
        return []
    rows, row = [], []
    for key, plan in CREDIT_PLANS.items():
        row.append(InlineKeyboardButton(f"{plan['label']} · ₹{plan['inr']:g}", callback_data=f"apay:credits:{key}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    return rows


def _plan_title(kind, key):
    plan = payments.find_plan(kind, key)
    if not plan:
        return None
    return plan["label"] + (" premium" if kind == "premium" else "")


@Client.on_callback_query(filters.regex(r"^apay:(premium|credits):[A-Za-z0-9]{1,8}$"))
async def pick_method(client, query):
    _, kind, key = query.data.split(":")
    title = _plan_title(kind, key)
    if not title or not payments.methods():
        return await query.answer("This plan is not available right now.", show_alert=True)
    available = payments.methods()
    if len(available) == 1:
        query.data = f"apm:{kind}:{key}:{available[0]}"
        return await create_payment(client, query)
    plan = payments.find_plan(kind, key)
    rows = [[InlineKeyboardButton(_METHOD_LABEL[m] + (f" · ₹{plan['inr']:g}" if m == "razorpay" else f" · ${plan['usd']:g}"),
                                  callback_data=f"apm:{kind}:{key}:{m}")] for m in available]
    rows.append([InlineKeyboardButton("• ᴄʟᴏsᴇ •", callback_data="close")])
    await query.message.reply(f"<blockquote>✦ <b>{title}</b></blockquote>\nChoose how you want to pay:",
                              reply_markup=InlineKeyboardMarkup(rows))
    await query.answer()


@Client.on_callback_query(filters.regex(r"^apm:(premium|credits):[A-Za-z0-9]{1,8}:(razorpay|crypto)$"))
async def create_payment(client, query):
    _, kind, key, method = query.data.split(":")
    uid = query.from_user.id
    if await client.mongodb.is_banned(uid):
        return await query.answer("You are banned.", show_alert=True)
    if not await client.mongodb.present_user(uid):
        await client.mongodb.add_user(uid)
    await query.answer("Creating your payment link…")
    try:
        order = await payments.create_order(client.mongodb.db, uid, kind, key, method)
    except ValueError as e:
        return await query.message.reply(f"⚠️ {e}.")
    except Exception as e:
        log.warning("Could not create the %s order for %s: %s", method, uid, e)
        return await query.message.reply("⚠️ The payment gateway did not answer. Please try again in a minute, "
                                         "or pay with the QR code and /bought.")
    expiry = "about an hour" if method == "razorpay" else "a short while"
    text = (f"<blockquote>✦ <b>{_plan_title(kind, key)}</b></blockquote>\n"
            f"▪️ Amount: <code>{payments.amount_text(order)}</code>\n"
            f"▪️ Order: <code>{order['_id']}</code>\n\n"
            f"Tap <b>Pay now</b>, complete the payment (link valid for {expiry}). "
            "It is activated <b>automatically</b> within a minute after you pay: no screenshot needed.")
    await query.message.reply(text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 ᴘᴀʏ ɴᴏᴡ", url=order["pay_url"])],
        [InlineKeyboardButton("🔄 ᴄʜᴇᴄᴋ sᴛᴀᴛᴜs", callback_data=f"apchk:{order['_id']}")],
    ]))


@Client.on_callback_query(filters.regex(r"^apchk:o[0-9a-f]{14}$"))
async def check_status(client, query):
    order = await client.mongodb.db["orders"].find_one({"_id": query.data.split(":", 1)[1]})
    if not order or order["user_id"] != query.from_user.id:
        return await query.answer("Order not found.", show_alert=True)
    if order["status"] == "paid":
        return await query.answer("✅ Paid and activated. Check /profile.", show_alert=True)
    await query.answer("Not paid yet. After you pay it is activated automatically. "
                       "If money was taken and nothing happens in 5 minutes, contact the owner with your order id.",
                       show_alert=True)
