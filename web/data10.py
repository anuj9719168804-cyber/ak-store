"""Panel queries added in v10 (ideas from AK Ultra's admin panel): user detail, bans, referrals, codes.

Written against `bot.mongodb` (helper/database.py) and plain collections, so the in-memory fake DB in
tests/ can drive it. Nothing here touches Quart or Telegram.
"""
import time
from datetime import datetime, timezone

from helper import grants, ledger, support
from web.data import USER_FILTER


def _epoch_to_dt(value):
    """Epoch seconds (how users.joined / banned_at are stored) -> naive UTC datetime, or None."""
    try:
        return datetime.fromtimestamp(float(value), timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


async def user_detail(mongo, user_id: int):
    """Everything the panel shows for one user, or None when the id is not a real user."""
    if not isinstance(user_id, int) or user_id <= 1:
        return None
    doc = await mongo.user_data.find_one({"_id": user_id})
    if not doc:
        return None
    db = mongo.db
    pro_doc = await mongo.premium_users.find_one({"_id": user_id})
    is_pro = await mongo.is_pro(user_id)
    expiry = pro_doc.get("expiry_date") if pro_doc else None
    invited_docs = await db["referrals"].find({"inviter": user_id}).sort([("at", -1)]).limit(20).to_list(length=20)
    invited = [{"id": r["_id"], "at": _epoch_to_dt(r.get("at")), "qualified": bool(r.get("qualified"))}
               for r in invited_docs]
    orders = await db["orders"].find({"user_id": user_id}).sort([("created", -1)]).limit(10).to_list(length=10)
    return {
        "id": user_id,
        "credits": doc.get("credits", 0),
        "banned": bool(doc.get("ban")),
        "ban_reason": doc.get("ban_reason", ""),
        "banned_at": _epoch_to_dt(doc.get("banned_at")),
        "joined": _epoch_to_dt(doc.get("joined")),
        "verified": bool(doc.get("verified")),
        "premium": is_pro,
        "premium_expired": bool(pro_doc) and not is_pro,
        "premium_until": expiry,
        "premium_lifetime": is_pro and expiry is None,
        "referrals": int(doc.get("referrals", 0)),
        "referred_by": doc.get("referred_by"),
        "invited": invited,
        "trial_used": bool(doc.get("trial_used")),
        "last_daily": _epoch_to_dt(doc.get("last_daily")),
        "ledger": await ledger.recent(db, user_id, 15),
        "orders": orders,
        "support": await support.get_thread(db, user_id),
    }


async def adjust_credits(mongo, user_id: int, mode: str, amount: int, who: str = "panel"):
    """mode add | deduct | set. -> (old, new). Credits never go below 0. Logged in the credit ledger."""
    if mode not in ("add", "deduct", "set"):
        raise ValueError("mode must be add, deduct or set")
    if amount < 0 or (mode != "set" and amount == 0):
        raise ValueError("amount must be a positive whole number")
    if not await mongo.present_user(user_id):
        raise LookupError("no such user")
    old = int(await mongo.get_credits(user_id))
    new = old + amount if mode == "add" else max(old - amount, 0) if mode == "deduct" else amount
    if new == old:
        return old, new
    await mongo.user_data.update_one({"_id": user_id}, {"$inc": {"credits": new - old}})
    await ledger.record(mongo.db, user_id, new - old, "admin", str(who), f"panel {mode}")
    return old, new


async def give_premium(mongo, user_id: int, days: int) -> str:
    """Same stacking rules as payments and gift codes (renewal adds to the time left)."""
    return await grants.grant_premium(mongo, user_id, days)


async def banned_users(mongo, limit: int = 300):
    """-> (rows, total). Newest ban first; bans from before v10 (no timestamp) come last."""
    flt = {**USER_FILTER, "ban": True}
    total = await mongo.user_data.count_documents(flt)
    docs = await mongo.user_data.find(flt).limit(limit).to_list(length=limit)
    rows = [{"id": d["_id"], "reason": d.get("ban_reason", ""), "at": _epoch_to_dt(d.get("banned_at")),
             "_t": d.get("banned_at") or 0} for d in docs]
    rows.sort(key=lambda r: r["_t"], reverse=True)
    return rows, total


async def referral_board(mongo, page: int = 1, per_page: int = 25):
    """Top inviters. -> (rows, total_inviters, summary)."""
    flt = {**USER_FILTER, "referrals": {"$gt": 0}}
    total = await mongo.user_data.count_documents(flt)
    docs = await (mongo.user_data.find(flt).sort([("referrals", -1), ("_id", 1)])
                  .skip(max(page - 1, 0) * per_page).limit(per_page).to_list(length=per_page))
    rows = [{"id": d["_id"], "referrals": int(d.get("referrals", 0)), "credits": d.get("credits", 0)} for d in docs]
    db = mongo.db
    summary = {
        "invited_total": await db["referrals"].count_documents({}),
        "paid_out": await db["referrals"].count_documents({"qualified": True}),
        "waiting": await db["referrals"].count_documents({"qualified": False}),
    }
    return rows, total, summary


def code_rows(docs) -> list:
    """Gift-code documents -> template rows with a ready 'state' (ok | off | full | expired)."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = []
    for d in docs:
        exp = d.get("expires_at")
        if not d.get("active", True):
            state = "off"
        elif exp and exp <= now:
            state = "expired"
        elif d.get("left", 0) <= 0:
            state = "full"
        else:
            state = "ok"
        rows.append({
            "code": d["_id"], "kind": d.get("kind", ""), "amount": d.get("amount", 0),
            "uses": d.get("uses", 0), "max_uses": d.get("max_uses", 0), "left": d.get("left", 0),
            "expires_at": exp, "state": state, "note": d.get("note", ""), "created": d.get("created"),
            "created_by": d.get("created_by", ""),
        })
    return rows


async def live_stats(bot) -> dict:
    """Numbers for the dashboard's auto-refresh (/api/stats)."""
    from web import data
    c = await data.counts(bot)
    sup = await support.counts(bot.mongodb.db)
    return {**c, "support_open": sup["open"], "support_unread": sup["unread"], "ts": int(time.time())}
