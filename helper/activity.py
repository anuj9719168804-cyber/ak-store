"""Small audit trail: what happened, who did it, when.

Stored in the `activity` collection (auto-deleted after ACTIVITY_KEEP_DAYS) and,
if LOG_CHANNEL_ID is set, also posted to that Telegram channel.
"""
import asyncio
import html
from datetime import datetime, timezone

from config import ACTIVITY_KEEP_DAYS, LOG_CHANNEL_ID, LOGGER

log = LOGGER("activity", "web")
_tasks = set()  # keep references so fire-and-forget tasks aren't garbage collected


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC, what Mongo stores


async def ensure_indexes(bot):
    try:
        col = bot.mongodb.db["activity"]
        await col.create_index("ts", expireAfterSeconds=max(ACTIVITY_KEEP_DAYS, 1) * 86400)
    except Exception as e:  # e.g. ACTIVITY_KEEP_DAYS changed: index exists with another TTL
        log.warning(f"Could not create activity index: {e}")


async def _to_channel(bot, doc):
    text = (
        f"<b>{html.escape(doc['action'])}</b>\n"
        f"by: <code>{html.escape(str(doc['actor']))}</code>"
    )
    if doc["target"] != "":
        text += f"\ntarget: <code>{html.escape(str(doc['target']))}</code>"
    if doc["detail"]:
        text += f"\n{html.escape(doc['detail'])}"
    try:
        await bot.send_message(LOG_CHANNEL_ID, text, disable_web_page_preview=True)
    except Exception as e:
        log.warning(f"Could not post to LOG_CHANNEL_ID: {e}")


async def log_activity(bot, action, actor="", target="", detail=""):
    """Never raises: logging must not break the action being logged."""
    doc = {"ts": _now(), "action": action, "actor": str(actor), "target": target, "detail": detail}
    try:
        await bot.mongodb.db["activity"].insert_one(dict(doc))
    except Exception as e:
        log.warning(f"Could not store activity: {e}")
    if LOG_CHANNEL_ID:
        task = asyncio.create_task(_to_channel(bot, doc))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)


async def recent(bot, page=1, per_page=50):
    col = bot.mongodb.db["activity"]
    total = await col.count_documents({})
    cursor = col.find({}).sort("ts", -1).skip(max(page - 1, 0) * per_page).limit(per_page)
    return await cursor.to_list(length=per_page), total
