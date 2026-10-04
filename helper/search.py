"""File search over the file index (`files` collection, see helper/file_index.py).

Used by /search and by inline mode (@bot name). Matching is case-insensitive on the file name and
caption; the words of a query must ALL appear (any order), so "avengers 1080" finds
"Avengers.Endgame.2019.1080p.mkv". User text is always escaped: it is never a regex.
"""
import re

from config import SEARCH_ACCESS, SEARCH_PAGE_SIZE

_SEP = re.compile(r"[\s._\-+]+")


def words(query: str, limit: int = 6) -> list:
    return [w for w in _SEP.split((query or "").strip().lower()) if w][:limit]


def build_filter(query: str):
    """Mongo filter where every word must appear in name or caption; None for an empty query."""
    ws = words(query)
    if not ws:
        return None
    clauses = []
    for w in ws:
        rx = {"$regex": re.escape(w), "$options": "i"}
        clauses.append({"$or": [{"name": rx}, {"caption": rx}]})
    return {"$and": clauses}


async def search(db, query: str, page: int = 1, per_page: int = None, allowed_chats=None):
    """-> (rows, total). rows are file-index documents, newest first.
    allowed_chats limits results to DB channels that are still usable (their links work)."""
    per_page = per_page or SEARCH_PAGE_SIZE
    flt = build_filter(query)
    if flt is None:
        return [], 0
    if allowed_chats is not None:
        flt = {"$and": flt["$and"] + [{"chat_id": {"$in": sorted(allowed_chats)}}]}
    col = db["files"]
    total = await col.count_documents(flt)
    cursor = col.find(flt).sort([("added", -1)]).skip(max(page - 1, 0) * per_page).limit(per_page)
    return await cursor.to_list(length=per_page), total


def pages(total: int, per_page: int = None) -> int:
    per_page = per_page or SEARCH_PAGE_SIZE
    return max((total + per_page - 1) // per_page, 1)


async def may_search(bot, user_id: int) -> bool:
    if SEARCH_ACCESS == "off":
        return False
    if SEARCH_ACCESS == "all":
        return True
    if user_id in bot.admins:
        return True
    return SEARCH_ACCESS == "premium" and bool(await bot.mongodb.is_pro(user_id))


async def payload_for(doc) -> str:
    """The normal base64 link payload of one indexed file."""
    from helper.helper_func import encode
    return await encode(f"get-{int(doc['msg_id']) * abs(int(doc['chat_id']))}")


def short_title(doc, limit: int = 60) -> str:
    name = doc.get("name") or "file"
    return name if len(name) <= limit else name[: limit - 1] + "…"
