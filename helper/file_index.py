"""File index: one small MongoDB document per file stored in a DB channel.

The DB channel itself is the real storage; this index only remembers *what* is in
it, so the panel can list/search/delete files, show sizes and download counts,
and so a re-upload of the same file can be answered with the old link.

    files collection, _id = "<abs channel id>_<message id>"  (same as stream refs)
        chat_id, msg_id, name, caption, kind, mime, size,
        unique_id (Telegram file_unique_id), has_name,
        uploader, added (naive UTC), downloads, last_download

Nothing here may break the bot: every database/Telegram error is logged and
swallowed, because indexing is bookkeeping and must never block a file upload
or a file delivery.
"""
import asyncio
import mimetypes
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from pyrogram.errors import FloodWait

from config import DEDUPE_UPLOADS, LOGGER
from helper.helper_func import encode
from helper.stream_links import make_ref

log = LOGGER("file_index", "bot")

_KINDS = ("document", "video", "audio", "animation", "voice", "video_note", "photo", "sticker")
_SCAN_BATCH = 200  # get_messages() accepts up to 200 ids per call


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC, what Mongo stores


def _to_utc(dt):
    """Pyrogram dates are naive local time; Mongo wants naive UTC."""
    if dt is None:
        return _now()
    try:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        return _now()


def _wait_seconds(exc) -> int:
    return int(getattr(exc, "value", None) or getattr(exc, "x", None) or 5)


# ----------------------------------------------------------------- describing

def describe(message, chat_id=None):
    """Metadata dict for the media in `message`, or None (text, empty, service message)."""
    if message is None or getattr(message, "empty", False):
        return None
    for kind in _KINDS:
        media = getattr(message, kind, None)
        if media is None:
            continue
        uid = getattr(media, "file_unique_id", None) or None
        real_name = getattr(media, "file_name", None) or None
        mime = getattr(media, "mime_type", None) or ("image/jpeg" if kind == "photo" else "")
        if real_name:
            name = real_name
        else:
            ext = ".jpg" if kind == "photo" else ((mimetypes.guess_extension(mime) if mime else None) or "")
            name = f"{kind}_{uid or getattr(message, 'id', '')}"[:48] + ext
        caption = " ".join(str(getattr(message, "caption", None) or "").split())[:200]

        chat = chat_id if chat_id is not None else getattr(getattr(message, "chat", None), "id", None)
        msg_id = getattr(message, "id", None)
        ref = make_ref(chat, msg_id) if chat is not None and msg_id is not None else None
        return {
            "_id": ref,
            "chat_id": int(chat) if chat is not None else None,
            "msg_id": int(msg_id) if msg_id is not None else None,
            "name": name,
            "caption": caption,
            "kind": kind,
            "mime": mime,
            "size": int(getattr(media, "file_size", 0) or 0),
            "unique_id": uid,
            "has_name": bool(real_name),
            "added": _to_utc(getattr(message, "date", None)),
        }
    return None


async def start_link(bot, chat_id, msg_id) -> str:
    """The normal t.me deep link of a DB-channel message (same format as /genlink)."""
    payload = await encode(f"get-{int(msg_id) * abs(int(chat_id))}")
    from helper.permanent_link import build_link
    return build_link(bot, payload)


async def ensure_indexes(bot):
    try:
        col = bot.mongodb.files
        await col.create_index("unique_id")
        await col.create_index([("name", 1), ("size", 1)])
        await col.create_index([("added", -1)])
        await col.create_index([("downloads", -1)])
    except Exception as e:
        log.warning(f"Could not create file indexes: {e}")


# ------------------------------------------------------------------ recording

async def record(bot, message, uploader=None, chat_id=None):
    """Add a DB-channel message to the index (no-op if it is already there)."""
    try:
        meta = describe(message, chat_id)
        if not meta or not meta["_id"]:
            return None
        _id = meta.pop("_id")
        meta["uploader"] = uploader
        await bot.mongodb.files.update_one(
            {"_id": _id}, {"$setOnInsert": {**meta, "downloads": 0}}, upsert=True
        )
        return meta
    except Exception as e:
        log.warning(f"Could not index file: {e}")
        return None


async def count_downloads(bot, messages):
    """+1 download for every file message that was delivered to a user.

    Files stored before the index existed are indexed on their first download,
    so old uploads start showing up in the panel by themselves.
    """
    now = _now()
    for message in messages:
        try:
            meta = describe(message)
            if not meta or not meta["_id"]:
                continue
            _id = meta.pop("_id")
            meta["uploader"] = None
            await bot.mongodb.files.update_one(
                {"_id": _id},
                {"$inc": {"downloads": 1}, "$set": {"last_download": now}, "$setOnInsert": meta},
                upsert=True,
            )
        except Exception as e:
            log.warning(f"Could not count download: {e}")


# ----------------------------------------------------------------- duplicates

class _KeyedLocks:
    """One asyncio.Lock per key, removed again when nobody waits for it."""

    def __init__(self):
        self._locks = {}

    @asynccontextmanager
    async def hold(self, key):
        entry = self._locks.setdefault(key, [asyncio.Lock(), 0])
        entry[1] += 1
        try:
            async with entry[0]:
                yield
        finally:
            entry[1] -= 1
            if entry[1] == 0:
                self._locks.pop(key, None)


_upload_locks = _KeyedLocks()


@asynccontextmanager
async def upload_guard(message):
    """Serialise uploads of the *same* file, so two copies sent at once can't both slip past the check."""
    meta = describe(message)
    if not meta or not meta["unique_id"]:
        yield
        return
    async with _upload_locks.hold(meta["unique_id"]):
        yield


def _candidate_filters(meta):
    filters = []
    if meta["unique_id"]:
        filters.append({"unique_id": meta["unique_id"]})
    # A fresh upload of the same bytes gets a new file_unique_id, so also match on the
    # real file name + exact size (never on generated names like "photo_AbC.jpg").
    if meta["has_name"] and meta["size"]:
        filters.append({"name": meta["name"], "size": meta["size"], "kind": meta["kind"]})
    return filters


async def _still_stored(bot, doc):
    """True/False, or None if Telegram couldn't tell us right now."""
    try:
        message = await bot.get_messages(doc["chat_id"], doc["msg_id"])
    except Exception as e:
        log.warning(f"Could not check {doc.get('_id')}: {e}")
        return None
    return message is not None and not getattr(message, "empty", False)


async def find_duplicate(bot, message, exclude_id=None):
    """Index entry of an identical file that is still in a usable DB channel, else None.
    `exclude_id` (a files-collection _id) is never returned: used when the message itself may already be indexed."""
    if not DEDUPE_UPLOADS:
        return None
    try:
        meta = describe(message)
        if not meta:
            return None
        from web.data import allowed_channels  # imported late: web/ imports this module too
        usable = allowed_channels(bot)
        files = bot.mongodb.files
        for flt in _candidate_filters(meta):
            docs = await files.find(flt).sort("added", 1).limit(5).to_list(length=5)
            for doc in docs:
                if exclude_id is not None and doc.get("_id") == exclude_id:
                    continue
                if doc.get("chat_id") not in usable:
                    continue  # that DB channel was removed from the bot, its links are dead
                alive = await _still_stored(bot, doc)
                if alive:
                    return doc
                if alive is False:  # deleted from the channel by hand: forget it
                    await files.delete_one({"_id": doc["_id"]})
        return None
    except Exception as e:
        log.warning(f"Duplicate check failed, storing the file normally: {e}")
        return None


# -------------------------------------------------------------------- deleting

async def remove(bot, file_id):
    """Delete a file from its DB channel and from the index -> (ok, name or error text)."""
    files = bot.mongodb.files
    doc = await files.find_one({"_id": file_id})
    if not doc:
        return False, "That file is not in the index (already deleted?)."
    try:
        await bot.delete_messages(doc["chat_id"], doc["msg_id"])
    except Exception as e:
        return False, f"Telegram would not delete it ({e}). Is the bot an admin with delete rights in that channel?"
    await files.delete_one({"_id": file_id})
    return True, doc.get("name", file_id)


# -------------------------------------------------------------------- scanning

async def _last_message_id(bot, chat_id):
    """Newest message id of a channel, found by posting (silently) and deleting a dot."""
    probe = await bot.send_message(chat_id, ".", disable_notification=True)
    await probe.delete()
    return probe.id


async def _get_batch(bot, chat_id, ids):
    for _ in range(3):
        try:
            return await bot.get_messages(chat_id, ids)
        except FloodWait as e:
            await asyncio.sleep(_wait_seconds(e) + 1)
    return []


async def scan(bot, state):
    """Index every file already sitting in the DB channels. `state` is updated live for the panel.

    Bots cannot read channel history, so this walks message ids 1..newest in batches.
    """
    from web.data import allowed_channels
    files = bot.mongodb.files
    try:
        plan = []
        for chat_id in sorted(allowed_channels(bot)):
            try:
                plan.append((chat_id, await _last_message_id(bot, chat_id)))
            except Exception as e:
                log.warning(f"Scan skipped channel {chat_id}: {e}")
        state["total"] = sum(last for _, last in plan)

        for chat_id, last in plan:
            for start in range(1, last + 1, _SCAN_BATCH):
                ids = list(range(start, min(start + _SCAN_BATCH, last + 1)))
                for message in await _get_batch(bot, chat_id, ids):
                    meta = describe(message, chat_id)
                    if not meta or not meta["_id"]:
                        continue
                    _id = meta.pop("_id")
                    meta["uploader"] = None
                    result = await files.update_one(
                        {"_id": _id}, {"$setOnInsert": {**meta, "downloads": 0}}, upsert=True
                    )
                    if getattr(result, "upserted_id", None) is not None:
                        state["added"] += 1
                state["scanned"] += len(ids)
    except Exception as e:
        log.exception("File scan crashed")
        state["error"] = str(e)
    finally:
        state["running"] = False
        state["finished"] = datetime.now()
