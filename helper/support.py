"""Support inbox (ported idea: AK Ultra's /contact live chat, reduced to what a file-store bot needs).

A user writes `/contact <message>`; every message lands in a per-user thread. Admins read the
threads in the web panel (Support) and answer there; the answer is sent to the user by the bot.
Nothing here imports Telegram or the panel, so it can be unit-tested with the in-memory fake DB.

    support_threads   _id = user id, name, username, open, unread (user msgs not yet read by an admin),
                      msgs, last_at (naive UTC), last_from (user|admin), last_user_epoch (rate limit)
    support_msgs      user_id, sender (user|admin), text, at (naive UTC), admin (who answered, admin msgs only)

Logging/stat helpers never raise on a missing thread: they return None / [] instead.
"""
import html
import math
import time
from datetime import datetime, timezone

MAX_TEXT = 1000


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC, what the rest of the bot stores


def clean(text) -> str:
    """Trim and cut to MAX_TEXT. Empty string = nothing worth sending."""
    return (text or "").strip()[:MAX_TEXT]


async def seconds_until_allowed(db, user_id: int, cooldown: int, now: float = None) -> int:
    """0 when the user may write again, otherwise how many seconds to wait (flood guard for /contact)."""
    if cooldown <= 0:
        return 0
    now = time.time() if now is None else now
    doc = await db["support_threads"].find_one({"_id": int(user_id)})
    last = float((doc or {}).get("last_user_epoch", 0) or 0)
    wait = last + cooldown - now
    return math.ceil(wait) if wait > 0 else 0


async def add_user_message(db, user_id: int, text: str, name: str = "", username: str = "") -> dict:
    """Store a message from a user and (re)open the thread. Returns the thread document."""
    text = clean(text)
    if not text:
        raise ValueError("empty message")
    user_id = int(user_id)
    now = _now()
    await db["support_msgs"].insert_one({"user_id": user_id, "sender": "user", "text": text, "at": now})
    await db["support_threads"].update_one(
        {"_id": user_id},
        {"$set": {"name": (name or "")[:64], "username": (username or "")[:64], "open": True,
                  "last_at": now, "last_from": "user", "last_user_epoch": time.time()},
         "$inc": {"unread": 1, "msgs": 1}},
        upsert=True,
    )
    return await db["support_threads"].find_one({"_id": user_id})


async def add_admin_reply(db, user_id: int, text: str, admin: str = "") -> dict:
    """Store an admin answer. The thread stays open until an admin closes it."""
    text = clean(text)
    if not text:
        raise ValueError("empty message")
    user_id = int(user_id)
    if not await db["support_threads"].find_one({"_id": user_id}):
        raise LookupError("no such thread")
    now = _now()
    await db["support_msgs"].insert_one(
        {"user_id": user_id, "sender": "admin", "text": text, "at": now, "admin": str(admin)[:40]})
    await db["support_threads"].update_one(
        {"_id": user_id},
        {"$set": {"last_at": now, "last_from": "admin", "unread": 0}, "$inc": {"msgs": 1}},
    )
    return await db["support_threads"].find_one({"_id": user_id})


async def mark_read(db, user_id: int):
    await db["support_threads"].update_one({"_id": int(user_id)}, {"$set": {"unread": 0}})


async def set_open(db, user_id: int, is_open: bool) -> bool:
    res = await db["support_threads"].update_one({"_id": int(user_id)}, {"$set": {"open": bool(is_open)}})
    return bool(getattr(res, "matched_count", 1))


async def get_thread(db, user_id: int):
    return await db["support_threads"].find_one({"_id": int(user_id)})


async def messages(db, user_id: int, limit: int = 200) -> list:
    """Oldest first, at most `limit` (the newest ones when the thread is longer)."""
    rows = await db["support_msgs"].find({"user_id": int(user_id)}).sort([("at", -1)]).limit(limit).to_list(length=limit)
    rows.reverse()
    return rows


async def threads(db, only_open: bool = True, limit: int = 100) -> list:
    """Threads with unread messages first, then the most recently active."""
    flt = {"open": True} if only_open else {}
    rows = await db["support_threads"].find(flt).sort([("last_at", -1)]).limit(limit).to_list(length=limit)
    rows.sort(key=lambda r: 0 if r.get("unread", 0) > 0 else 1)  # stable: keeps newest-first inside each group
    return rows


async def counts(db) -> dict:
    """{'open': threads waiting, 'unread': threads with a message no admin has read yet}"""
    col = db["support_threads"]
    return {
        "open": await col.count_documents({"open": True}),
        "unread": await col.count_documents({"unread": {"$gt": 0}}),
    }


async def send_reply(bot, user_id: int, text: str, admin: str = ""):
    """Store an admin answer AND send it to the user. Used by the panel and by /reply.

    -> (delivered, note). delivered False = saved in the thread but Telegram refused (user blocked the bot...).
    Raises ValueError (empty text) / LookupError (the user never wrote to support)."""
    text = clean(text)
    await add_admin_reply(bot.mongodb.db, user_id, text, admin)
    try:
        await bot.send_message(
            int(user_id),
            "<blockquote>💬 <b>Support reply</b></blockquote>\n"
            f"{html.escape(text)}\n\n<i>Write back with</i> <code>/contact your message</code>",
        )
        return True, ""
    except Exception as e:  # blocked the bot, deactivated, ...
        return False, type(e).__name__
