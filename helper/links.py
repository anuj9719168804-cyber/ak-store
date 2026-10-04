"""Expiring / limited links.

A normal link carries its payload inside the URL, so it can never be switched off. A *managed*
link is only a short token (`lk_<12 chars>`); the real payload lives in MongoDB next to the
rules, so the link can stop working after a time or after N people got the files, and can be
revoked at any moment.

    links       _id = token. payload (the real base64 payload), created, created_by, note,
                expires_at (naive UTC or None), max_uses (0 = unlimited), left (slots still free,
                -1 = unlimited), uses, clicks, revoked
    link_hits   _id = "<token>:<user id>"   one document per user who received the files

"Use" = one *person* who received the files. The same person opening the link again (for
example "Get files again" after auto-delete) does not burn another slot.
"""
import re
import secrets
import string
from datetime import datetime, timedelta, timezone

PREFIX = "lk_"
_ALPHABET = string.ascii_letters + string.digits
_TOKEN_LEN = 12
_DURATION_RE = re.compile(r"^(\d+)\s*(m|min|h|hr|d|day|days|w|week|weeks)?$", re.I)
_UNIT_SECONDS = {"m": 60, "min": 60, "h": 3600, "hr": 3600, "d": 86400, "day": 86400, "days": 86400,
                 "w": 604800, "week": 604800, "weeks": 604800}


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_token() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(_TOKEN_LEN))


def is_managed(payload: str) -> bool:
    return bool(payload) and payload.startswith(PREFIX) and len(payload) == len(PREFIX) + _TOKEN_LEN


def token_of(payload: str) -> str:
    return payload[len(PREFIX):] if payload.startswith(PREFIX) else payload


def parse_duration(text: str):
    """'24h' -> 86400, '7d' -> 604800, '90m' -> 5400, '0' / 'never' / 'no' -> 0, junk -> None.
    A bare number means hours."""
    text = (text or "").strip().lower()
    if text in ("0", "never", "no", "none", "off", "-"):
        return 0
    m = _DURATION_RE.match(text)
    if not m:
        return None
    unit = (m.group(2) or "h").lower()
    return int(m.group(1)) * _UNIT_SECONDS[unit]


def describe_seconds(seconds: int) -> str:
    seconds = int(seconds)
    if seconds >= 86400 and seconds % 86400 == 0:
        return f"{seconds // 86400}d"
    if seconds >= 3600:
        h, rest = divmod(seconds, 3600)
        return f"{h}h" + (f" {rest // 60}m" if rest >= 60 else "")
    return f"{max(seconds // 60, 1)}m"


_PAYLOAD_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def extract_payload(text: str):
    """The deep-link payload out of whatever an admin pastes:
    https://t.me/<bot>?start=<payload>, <worker>/?url=<payload>, or the bare payload. None if there is none."""
    text = (text or "").strip()
    m = re.search(r"[?&](?:start|url)=([A-Za-z0-9_-]{1,64})", text)
    if m:
        return m.group(1)
    return text if _PAYLOAD_RE.match(text) else None          # a bare payload must be the whole text


async def create(db, payload: str, created_by, ttl_seconds: int = 0, max_uses: int = 0, note: str = "") -> dict:
    """Make a managed link for `payload` (the normal base64 payload). -> the stored document."""
    if is_managed(payload):
        raise ValueError("that is already a managed link")
    token = new_token()
    now = _now()
    doc = {
        "_id": token,
        "payload": payload,
        "created": now,
        "created_by": created_by,
        "note": (note or "")[:80],
        "expires_at": now + timedelta(seconds=int(ttl_seconds)) if ttl_seconds and ttl_seconds > 0 else None,
        "max_uses": int(max_uses) if max_uses and max_uses > 0 else 0,
        "left": int(max_uses) if max_uses and max_uses > 0 else -1,
        "uses": 0,
        "clicks": 0,
        "revoked": False,
    }
    await db["links"].insert_one(doc)
    return doc


async def get(db, token: str):
    return await db["links"].find_one({"_id": token_of(token)})


def state_of(doc, now=None) -> str:
    """'ok' | 'revoked' | 'expired' | 'full' for a link document."""
    now = now or _now()
    if doc.get("revoked"):
        return "revoked"
    exp = doc.get("expires_at")
    if exp is not None and exp <= now:
        return "expired"
    if doc.get("max_uses", 0) > 0 and doc.get("left", 0) <= 0:
        return "full"
    return "ok"


async def check(db, token: str, user_id=None):
    """Read-only look before the shortener / credits gate -> (state, doc).

    state: 'missing' | 'revoked' | 'expired' | 'full' | 'ok'.  A full link is still 'ok' for
    someone who already received the files (they may fetch them again)."""
    doc = await get(db, token)
    if not doc:
        return "missing", None
    state = state_of(doc)
    if state == "full" and user_id is not None:
        if await db["link_hits"].find_one({"_id": f"{doc['_id']}:{user_id}"}):
            state = "ok"
    return state, doc


async def count_click(db, token: str):
    await db["links"].update_one({"_id": token_of(token)}, {"$inc": {"clicks": 1}})


async def reserve(db, token: str, user_id) -> str:
    """Claim a slot for `user_id` right before sending the files.

    -> 'ok' (slot taken, or this user already had one) | 'revoked' | 'expired' | 'full' | 'missing'.
    Atomic: two people racing for the last slot cannot both get it."""
    token = token_of(token)
    hits = db["link_hits"]
    now = _now()
    hit_id = f"{token}:{user_id}"
    res = await hits.update_one({"_id": hit_id}, {"$setOnInsert": {"token": token, "user_id": user_id, "at": now}}, upsert=True)
    if getattr(res, "upserted_id", None) is None:
        # Already received before: allowed again as long as the link is neither revoked nor expired.
        doc = await get(db, token)
        if not doc:
            return "missing"
        state = state_of(doc, now)
        return "ok" if state in ("ok", "full") else state

    take = {"$inc": {"uses": 1}}
    live = {"_id": token, "revoked": False,
            "$and": [{"$or": [{"expires_at": None}, {"expires_at": {"$gt": now}}]}]}
    # limited link: take one of the free slots; unlimited link: just count the use
    limited = await db["links"].update_one({**live, "left": {"$gt": 0}}, {"$inc": {"uses": 1, "left": -1}})
    if limited.modified_count == 1:
        return "ok"
    unlimited = await db["links"].update_one({**live, "left": -1}, take)
    if unlimited.modified_count == 1:
        return "ok"
    await hits.delete_one({"_id": hit_id})  # nothing was taken: forget the claim
    doc = await get(db, token)
    return state_of(doc, now) if doc else "missing"


async def release(db, token: str, user_id):
    """Give the slot back (nothing could be delivered after reserve())."""
    token = token_of(token)
    res = await db["link_hits"].delete_one({"_id": f"{token}:{user_id}"})
    if res.deleted_count:
        doc = await get(db, token)
        if doc and doc.get("max_uses", 0) > 0:
            await db["links"].update_one({"_id": token}, {"$inc": {"uses": -1, "left": 1}})
        else:
            await db["links"].update_one({"_id": token}, {"$inc": {"uses": -1}})


async def revoke(db, token: str) -> bool:
    res = await db["links"].update_one({"_id": token_of(token)}, {"$set": {"revoked": True}})
    return res.matched_count == 1


async def recent(db, limit: int = 20) -> list:
    return await db["links"].find({}).sort([("created", -1)]).limit(limit).to_list(length=limit)


def summary_line(doc, now=None) -> str:
    """One readable line for lists."""
    now = now or _now()
    state = state_of(doc, now)
    icon = {"ok": "🟢", "revoked": "⛔", "expired": "⌛", "full": "🔒"}[state]
    parts = [f"{icon} <code>{PREFIX}{doc['_id']}</code>"]
    if doc.get("max_uses"):
        parts.append(f"{doc.get('uses', 0)}/{doc['max_uses']} uses")
    else:
        parts.append(f"{doc.get('uses', 0)} uses")
    parts.append(f"{doc.get('clicks', 0)} clicks")
    exp = doc.get("expires_at")
    if exp is not None:
        left = exp - now
        parts.append("expired" if left.total_seconds() <= 0 else f"ends in {describe_seconds(left.total_seconds())}")
    if doc.get("note"):
        parts.append(doc["note"])
    return " · ".join(parts)
