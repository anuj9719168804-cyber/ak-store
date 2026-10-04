"""Referral + daily bonus credits.

    users doc fields used:  referred_by, referrals (count rewarded), last_daily (epoch), joined (epoch)
    referrals collection:   _id = invited user id  (one reward per invited account, ever)

Anti-abuse, all server side:
  * a user can only be referred once, never by themselves, and only if the account is brand new
    (created within REFERRAL_WINDOW_HOURS: old users cannot be "invited" for credits)
  * the inviter gets credits per NEW account only, at most REFERRAL_MAX_PER_USER times
  * /daily: one claim per 24 h, atomic (two taps at once pay once)
"""
import re
import time

from config import (
    DAILY_BONUS_CREDITS, REFERRAL_CREDITS, REFERRAL_MAX_PER_USER, REFERRAL_NEW_USER_CREDITS,
    REFERRAL_QUALIFY, REFERRAL_WINDOW_HOURS,
)
from helper import ledger

QUALIFY = REFERRAL_QUALIFY    # file | verify | join  (tests change this)

PREFIX = "ref_"
_REF_RE = re.compile(r"^ref_(\d{1,15})$")
DAY = 86400


def parse_ref(arg: str):
    """'ref_123' -> 123, anything else -> None"""
    m = _REF_RE.match(arg or "")
    return int(m.group(1)) if m else None


def ref_link(bot, user_id: int) -> str:
    return f"https://t.me/{bot.username}?start={PREFIX}{user_id}"


async def claim_daily(db, user_id: int, now: float = None):
    """-> (ok, credits_or_seconds_left). ok False = already claimed, second value = seconds to wait."""
    if DAILY_BONUS_CREDITS <= 0:
        return False, -1
    now = time.time() if now is None else now
    users = db["users"]
    # atomic: only matches when never claimed or the last claim is >= 24h old
    res = await users.update_one(
        {"_id": user_id, "$or": [{"last_daily": None}, {"last_daily": {"$lte": now - DAY}}]},
        {"$set": {"last_daily": now}, "$inc": {"credits": DAILY_BONUS_CREDITS}},
    )
    if res.modified_count == 1:
        await ledger.record(db, user_id, DAILY_BONUS_CREDITS, "daily")
        return True, DAILY_BONUS_CREDITS
    doc = await users.find_one({"_id": user_id})
    if not doc:
        return False, DAY
    return False, max(int(doc.get("last_daily", 0) + DAY - now), 1)


async def register_referral(db, new_user_id: int, inviter_id: int, now: float = None):
    """Call right after a brand-new user was created from a ref link.
    -> (rewarded, reason) with reason in: ok | self | disabled | not_new | already | no_inviter | cap"""
    if REFERRAL_CREDITS <= 0 and REFERRAL_NEW_USER_CREDITS <= 0:
        return False, "disabled"
    now = time.time() if now is None else now
    if new_user_id == inviter_id:
        return False, "self"
    users = db["users"]
    new = await users.find_one({"_id": new_user_id})
    # No `joined` stamp = an account from before v9: never "new", so old users can't be farmed.
    if not new or "joined" not in new or (now - float(new["joined"])) > REFERRAL_WINDOW_HOURS * 3600:
        return False, "not_new"
    inviter = await users.find_one({"_id": inviter_id})
    if not inviter or inviter.get("ban"):
        return False, "no_inviter"
    # one reward per invited account: the _id insert is the lock
    res = await db["referrals"].update_one(
        {"_id": new_user_id}, {"$setOnInsert": {"inviter": inviter_id, "at": now, "qualified": False}}, upsert=True)
    if getattr(res, "upserted_id", None) is None:
        return False, "already"
    await users.update_one({"_id": new_user_id}, {"$set": {"referred_by": inviter_id}})
    if QUALIFY != "join":
        return False, "pending"          # paid later, see qualify()
    return await _pay(db, new_user_id, inviter_id)


async def _pay(db, new_user_id: int, inviter_id: int):
    """Pay out one referral (called exactly once per invited account)."""
    users = db["users"]
    inviter = await users.find_one({"_id": inviter_id})
    if not inviter or inviter.get("ban"):
        return False, "no_inviter"
    if REFERRAL_MAX_PER_USER > 0 and int(inviter.get("referrals", 0)) >= REFERRAL_MAX_PER_USER:
        return False, "cap"
    if REFERRAL_CREDITS > 0:
        await users.update_one({"_id": inviter_id}, {"$inc": {"credits": REFERRAL_CREDITS, "referrals": 1}})
        await ledger.record(db, inviter_id, REFERRAL_CREDITS, "referral", str(new_user_id))
    else:
        await users.update_one({"_id": inviter_id}, {"$inc": {"referrals": 1}})
    if REFERRAL_NEW_USER_CREDITS > 0:
        await users.update_one({"_id": new_user_id}, {"$inc": {"credits": REFERRAL_NEW_USER_CREDITS}})
        await ledger.record(db, new_user_id, REFERRAL_NEW_USER_CREDITS, "referral_bonus", str(inviter_id))
    return True, "ok"


async def qualify(db, user_id: int, event: str):
    """The invited user just did `event` ('file' = got a file, 'verify' = completed a verification).
    Pays the inviter if that is the event REFERRAL_QUALIFY waits for. -> inviter id when paid, else None.
    One cheap update per call; does nothing for users nobody invited."""
    if event != QUALIFY:
        return None
    won = await db["referrals"].find_one_and_update(
        {"_id": user_id, "qualified": False}, {"$set": {"qualified": True}})
    if not won:
        return None
    ok, _ = await _pay(db, user_id, won["inviter"])
    return won["inviter"] if ok else None


async def referral_stats(db, user_id: int) -> dict:
    doc = await db["users"].find_one({"_id": user_id}) or {}
    return {"referrals": int(doc.get("referrals", 0)), "earned": int(doc.get("referrals", 0)) * REFERRAL_CREDITS}
