"""Panel queries, written against Pro's own MongoDB helper (`bot.mongodb`)
so the web panel and the Telegram commands always see the same data."""
import re
from datetime import datetime, timedelta

from helper.helper_func import encode
from helper.permanent_link import build_link
from helper.utils import format_bytes

# helper/database.py keeps bookkeeping documents (channels list, bot settings,
# admins list, ...) in the *same* collection as users, with `_id` = 1 or a string.
# Real users have an integer `_id` > 1.
USER_FILTER = {"_id": {"$type": ["int", "long"], "$gt": 1}}


async def counts(bot):
    m = bot.mongodb
    users = await m.user_data.count_documents(USER_FILTER)
    banned = await m.user_data.count_documents({**USER_FILTER, "ban": True})
    pros = len(await m.get_pros_list())
    files = await file_totals(bot)
    return {"users": users, "banned": banned, "premium": pros, "admins": len(bot.admins), **files}


async def file_totals(bot) -> dict:
    """Stored files, their combined size and the total download count (from the file index)."""
    rows = await bot.mongodb.files.aggregate([
        {"$group": {"_id": None, "files": {"$sum": 1}, "size": {"$sum": "$size"}, "downloads": {"$sum": "$downloads"}}}
    ]).to_list(length=1)
    row = rows[0] if rows else {}
    return {
        "files": row.get("files", 0),
        "files_size": format_bytes(row.get("size", 0)),
        "downloads": row.get("downloads", 0),
    }


_FILE_SORTS = {
    "new": [("added", -1)],
    "old": [("added", 1)],
    "downloads": [("downloads", -1), ("added", -1)],
    "size": [("size", -1), ("added", -1)],
}


async def list_files(bot, page: int, per_page: int = 50, query: str = "", sort: str = "new"):
    """Page of the file index. `query` matches name/caption (case-insensitive) or an exact message id."""
    flt = {}
    query = (query or "").strip()[:100]
    if query:
        rx = {"$regex": re.escape(query), "$options": "i"}  # escaped: the user's text is never a pattern
        flt = {"$or": [{"name": rx}, {"caption": rx}] + ([{"msg_id": int(query)}] if query.isdigit() else [])}
    col = bot.mongodb.files
    total = await col.count_documents(flt)
    cursor = (
        col.find(flt)
        .sort(_FILE_SORTS.get(sort, _FILE_SORTS["new"]))
        .skip(max(page - 1, 0) * per_page)
        .limit(per_page)
    )
    username = getattr(bot, "username", None)
    rows = []
    for d in await cursor.to_list(length=per_page):
        link = ""
        if username and d.get("chat_id") is not None and d.get("msg_id") is not None:
            payload = await encode(f"get-{d['msg_id'] * abs(d['chat_id'])}")
            link = build_link(bot, payload)
        rows.append({
            "id": d["_id"],
            "name": d.get("name", "?"),
            "caption": d.get("caption", ""),
            "kind": d.get("kind", ""),
            "size_text": format_bytes(d.get("size", 0)),
            "downloads": d.get("downloads", 0),
            "added": d.get("added"),
            "uploader": d.get("uploader"),
            "link": link,
        })
    return rows, total


async def list_users(bot, page: int, per_page: int = 50, query: str = ""):
    flt = dict(USER_FILTER)
    query = (query or "").strip()
    if query:
        if not query.lstrip("-").isdigit():
            return [], 0
        flt = {"_id": int(query)}
    m = bot.mongodb
    total = await m.user_data.count_documents(flt)
    cursor = (
        m.user_data.find(flt)
        .sort("_id", -1)
        .skip(max(page - 1, 0) * per_page)
        .limit(per_page)
    )
    docs = await cursor.to_list(length=per_page)
    pro_ids = set(await m.get_pros_list())
    users = [
        {
            "id": d["_id"],
            "banned": bool(d.get("ban")),
            "credits": d.get("credits", "-"),
            "pro": d["_id"] in pro_ids,
        }
        for d in docs
    ]
    return users, total


async def list_premium(bot):
    now = datetime.now()  # Pro stores naive local datetimes
    docs = await bot.mongodb.premium_users.find({}).to_list(length=1000)
    rows = []
    for d in docs:
        expiry = d.get("expiry_date")
        rows.append({
            "id": d["_id"],
            "expiry": expiry,
            "permanent": expiry is None,
            "active": expiry is None or expiry > now,
        })
    rows.sort(key=lambda r: (not r["active"], r["id"]))
    return rows


async def set_premium(bot, user_id: int, days: int = 0):
    expiry = datetime.now() + timedelta(days=days) if days > 0 else None
    return await bot.mongodb.add_pro(user_id, expiry)


async def add_admin(bot, user_id: int):
    if user_id not in bot.admins:
        bot.admins.append(user_id)
    await bot.mongodb.add_admin(user_id)  # survive restarts


async def remove_admin(bot, user_id: int) -> bool:
    if user_id == bot.owner:
        return False
    if user_id in bot.admins:
        bot.admins.remove(user_id)
    await bot.mongodb.remove_admin(user_id)
    return True


def current_settings(bot) -> dict:
    return {
        "protect": bool(bot.protect),
        "auto_del": int(bot.auto_del),
        "shortner": bool(getattr(bot, "shortner_enabled", True)),
        "permanent_link": bool(getattr(bot, "permanent_link", False)),
    }


async def save_settings(bot, protect: bool, auto_del: int, shortner: bool, permanent_link=None) -> list:
    """Apply + persist the settings; returns a list like ['protect=on'] of what changed."""
    changed = []
    if protect != bool(bot.protect):
        bot.protect = protect
        changed.append(f"protect={'on' if protect else 'off'}")
    if auto_del != int(bot.auto_del):
        bot.auto_del = auto_del
        changed.append(f"auto_del={auto_del}s")
    if permanent_link is not None and permanent_link != bool(getattr(bot, "permanent_link", False)):
        bot.permanent_link = permanent_link
        changed.append(f"permanent_link={'on' if permanent_link else 'off'}")
    if changed:
        stored = await bot.mongodb.get_bot_settings()
        stored.update({"protect": bool(bot.protect), "auto_del": int(bot.auto_del),
                       "permanent_link": bool(getattr(bot, "permanent_link", False))})
        await bot.mongodb.set_bot_settings(stored)
    if shortner != bool(getattr(bot, "shortner_enabled", True)):
        bot.shortner_enabled = shortner
        await bot.mongodb.set_shortner_status(shortner)
        changed.append(f"shortner={'on' if shortner else 'off'}")
    return changed


async def iter_user_ids(bot):
    cursor = bot.mongodb.user_data.find(USER_FILTER, {"_id": 1})
    async for doc in cursor:
        yield doc["_id"]


def channels(bot):
    """(db_channels, fsub_channels) as plain lists for the read-only Channels page."""
    primary = getattr(bot, "primary_db_channel", bot.db)
    db_rows = [{"id": primary, "name": getattr(getattr(bot, "db_channel", None), "title", "") or "-",
                "primary": True, "active": True}]
    for cid, data in getattr(bot, "db_channels", {}).items():
        if int(cid) == primary:
            continue
        db_rows.append({"id": int(cid), "name": data.get("name", "-"),
                        "primary": False, "active": data.get("is_active", True)})
    fsub_rows = []
    for cid, data in getattr(bot, "fsub_dict", {}).items():
        fsub_rows.append({"id": cid, "name": data[0], "request": bool(data[2]), "timer": data[3]})
    return db_rows, fsub_rows


def allowed_channels(bot) -> set:
    """DB channels a stream link may point at (primary + active extra ones)."""
    ids = {int(bot.db), int(getattr(bot, "primary_db_channel", bot.db))}
    for cid, data in getattr(bot, "db_channels", {}).items():
        if data.get("is_active", True):
            ids.add(int(cid))
    return ids
