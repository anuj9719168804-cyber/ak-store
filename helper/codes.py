"""Gift / redeem codes: a code gives credits or premium days. Single use per person, a fixed number
of people in total, optional expiry, can be switched off.

    codes       _id = CODE, kind (credits|premium), amount (credits, or days; 0 days = lifetime),
                max_uses, left, uses, expires_at (naive UTC or None), active, created_by, note
    code_uses   _id = "<CODE>:<user id>"
"""
import re
import secrets
import string
from datetime import datetime, timedelta, timezone

from helper import grants

_ALPHABET = string.ascii_uppercase + string.digits
_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{3,31}$")


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalize(text: str) -> str:
    return (text or "").strip().upper()


def valid_format(code: str) -> bool:
    return bool(_CODE_RE.match(code))


def random_code(prefix: str = "FS") -> str:
    return f"{prefix}-" + "".join(secrets.choice(_ALPHABET) for _ in range(10))


async def create(db, kind: str, amount: int, max_uses: int, created_by, ttl_seconds: int = 0, code: str = "", note: str = "") -> dict:
    """Raises ValueError for bad input / a code that already exists."""
    if kind not in ("credits", "premium"):
        raise ValueError("kind must be credits or premium")
    if kind == "credits" and amount < 1:
        raise ValueError("credits must be at least 1")
    if kind == "premium" and amount < 0:
        raise ValueError("days cannot be negative (0 = lifetime)")
    if max_uses < 1:
        raise ValueError("a code needs at least 1 use")
    code = normalize(code) or random_code()
    if not valid_format(code):
        raise ValueError("code: 4-32 letters, digits, - or _")
    if await db["codes"].find_one({"_id": code}):
        raise ValueError("that code already exists")
    now = _now()
    doc = {"_id": code, "kind": kind, "amount": int(amount), "max_uses": int(max_uses), "left": int(max_uses), "uses": 0,
           "expires_at": (now + timedelta(seconds=ttl_seconds)) if ttl_seconds > 0 else None,
           "active": True, "created_by": created_by, "created": now, "note": (note or "")[:80]}
    await db["codes"].insert_one(doc)
    return doc


async def redeem(mongo, user_id: int, raw_code: str):
    """-> (code, text) with code in: ok | missing | inactive | expired | full | already.
    text = what was given when ok."""
    db = mongo.db
    code = normalize(raw_code)
    doc = await db["codes"].find_one({"_id": code}) if valid_format(code) else None
    if not doc:
        return "missing", ""
    now = _now()
    if not doc["active"]:
        return "inactive", ""
    if doc.get("expires_at") and doc["expires_at"] <= now:
        return "expired", ""
    # one claim per person: the upsert is the lock
    hit_id = f"{code}:{user_id}"
    res = await db["code_uses"].update_one({"_id": hit_id}, {"$setOnInsert": {"code": code, "user_id": user_id, "at": now}}, upsert=True)
    if getattr(res, "upserted_id", None) is None:
        return "already", ""
    took = await db["codes"].update_one(
        {"_id": code, "active": True, "left": {"$gt": 0},
         "$or": [{"expires_at": None}, {"expires_at": {"$gt": now}}]},
        {"$inc": {"left": -1, "uses": 1}})
    if took.modified_count != 1:
        await db["code_uses"].delete_one({"_id": hit_id})
        fresh = await db["codes"].find_one({"_id": code}) or doc
        if fresh.get("left", 0) <= 0:
            return "full", ""
        return ("expired" if fresh.get("expires_at") and fresh["expires_at"] <= now else "inactive"), ""
    try:
        if doc["kind"] == "credits":
            text = await grants.grant_credits(mongo, user_id, doc["amount"], "gift", code)
        else:
            text = await grants.grant_premium(mongo, user_id, doc["amount"])
    except Exception:
        # nothing was given: give the slot back so the code is not wasted
        await db["codes"].update_one({"_id": code}, {"$inc": {"left": 1, "uses": -1}})
        await db["code_uses"].delete_one({"_id": hit_id})
        raise
    return "ok", text


async def deactivate(db, raw_code: str) -> bool:
    res = await db["codes"].update_one({"_id": normalize(raw_code)}, {"$set": {"active": False}})
    return res.matched_count == 1


async def recent(db, limit: int = 15) -> list:
    return await db["codes"].find({}).sort([("created", -1)]).limit(limit).to_list(length=limit)


async def set_active(db, raw_code: str, active: bool) -> bool:
    """Switch a code on or off again (the panel can undo /delcode)."""
    res = await db["codes"].update_one({"_id": normalize(raw_code)}, {"$set": {"active": bool(active)}})
    return res.matched_count == 1


async def remove(db, raw_code: str) -> bool:
    """Delete a code for good. Who already redeemed it keeps what they got; the redeem records go too."""
    code = normalize(raw_code)
    res = await db["codes"].delete_one({"_id": code})
    if res.deleted_count == 1:
        await db["code_uses"].delete_many({"code": code})
    return res.deleted_count == 1
