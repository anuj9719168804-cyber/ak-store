"""Custom thumbnail for delivered files (/settings -> page 2 -> Thumbnail).

Telegram ignores a new thumbnail on a plain copy, so when a thumbnail is set a delivered video or
document is downloaded and uploaded again with it. Files above MAX_FILE, other media types and any
failure fall back to the normal copy, so a delivery is never lost because of the thumbnail.

The thumbnail is stored in MongoDB (base64 JPEG, <=200 KB) and written to a local file at start-up,
so it survives restarts on hosts with an ephemeral disk.
"""
import asyncio
import base64
import os
import shutil
import tempfile

from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait

DOC_ID = "custom_thumb"
MAX_THUMB_BYTES = 200 * 1024          # Telegram's limit for a thumbnail
MAX_FILE = 700 * 1024 * 1024          # bigger files are copied as they are (no re-upload)
THUMB_DIR = os.path.join(tempfile.gettempdir(), "fsp_thumb")
THUMB_PATH = os.path.join(THUMB_DIR, "custom_thumb.jpg")

_sem = None


def _semaphore():
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(2)   # at most two re-uploads at once (disk + bandwidth)
    return _sem


async def normalize(src: str, dst: str, ffmpeg: str = "ffmpeg") -> bool:
    """Any image -> JPEG, at most 320 px on the long side and 200 KB. True when `dst` is usable."""
    for q in (3, 6, 10, 16, 24):
        proc = await asyncio.create_subprocess_exec(
            ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-i", src, "-frames:v", "1",
            "-vf", "scale='min(320,iw)':'min(320,ih)':force_original_aspect_ratio=decrease",
            "-pix_fmt", "yuvj420p", "-q:v", str(q), dst,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await proc.wait()
        if proc.returncode != 0 or not os.path.exists(dst):
            return False
        if 0 < os.path.getsize(dst) <= MAX_THUMB_BYTES:
            return True
    return False


async def save(client, src: str) -> bool:
    """Convert `src`, store it in the DB and make it the active thumbnail."""
    os.makedirs(THUMB_DIR, exist_ok=True)
    tmp = THUMB_PATH + ".new.jpg"
    try:
        if not await normalize(src, tmp):
            return False
        with open(tmp, "rb") as f:
            data = f.read()
        await client.mongodb.user_data.update_one(
            {"_id": DOC_ID}, {"$set": {"data": base64.b64encode(data).decode()}}, upsert=True)
        os.replace(tmp, THUMB_PATH)
        client.custom_thumb = THUMB_PATH
        return True
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


async def remove(client):
    client.custom_thumb = ""
    try:
        await client.mongodb.user_data.delete_one({"_id": DOC_ID})
    finally:
        if os.path.exists(THUMB_PATH):
            os.remove(THUMB_PATH)


async def load(client):
    """Restore the saved thumbnail at start-up. Never raises."""
    client.custom_thumb = ""
    try:
        doc = await client.mongodb.user_data.find_one({"_id": DOC_ID})
        if doc and doc.get("data"):
            os.makedirs(THUMB_DIR, exist_ok=True)
            with open(THUMB_PATH, "wb") as f:
                f.write(base64.b64decode(doc["data"]))
            client.custom_thumb = THUMB_PATH
    except Exception as e:
        client.LOGGER(__name__, client.name).warning(f"Could not load custom thumbnail: {e}")


def exists(client) -> str:
    """Path of the saved thumbnail image (whether it is switched on or not), "" if none."""
    path = getattr(client, "custom_thumb", "") or ""
    return path if path and os.path.exists(path) else ""


def active(client) -> str:
    """Thumbnail to put on files right now: the saved image, only while the switch is ON."""
    return exists(client) if getattr(client, "thumb_enabled", True) else ""


async def send(client, msg, chat_id, caption, reply_markup, protect):
    """Deliver `msg` to `chat_id` (what msg.copy would do) with the custom thumbnail when one is set."""
    thumb = active(client)
    video, doc = getattr(msg, "video", None), getattr(msg, "document", None)
    media = video or doc
    if thumb and media and (getattr(media, "file_size", 0) or 0) <= MAX_FILE:
        try:
            return await _reupload(client, msg, chat_id, caption, reply_markup, protect, thumb, video)
        except FloodWait:
            raise
        except Exception as e:
            client.LOGGER(__name__, getattr(client, "name", "")).warning(f"Thumbnail upload failed, copying instead: {e}")
    return await msg.copy(chat_id=chat_id, caption=caption, reply_markup=reply_markup, protect_content=protect)


async def send_safe(client, msg, chat_id, caption, reply_markup, protect, plain_caption, plain_markup):
    """send() with a safety net: if Telegram refuses the customised caption / buttons (bad button url, markup
    problem), the file is sent once more with its own caption and buttons, so a setting never costs a delivery."""
    try:
        return await send(client, msg, chat_id, caption, reply_markup, protect)
    except FloodWait:
        raise
    except Exception as e:
        if caption == plain_caption and reply_markup is plain_markup:
            raise
        client.LOGGER(__name__, getattr(client, "name", "")).warning(f"Custom caption/buttons refused ({e}); sending plain")
        return await msg.copy(chat_id=chat_id, caption=plain_caption, reply_markup=plain_markup, protect_content=protect)


async def _reupload(client, msg, chat_id, caption, reply_markup, protect, thumb, video):
    async with _semaphore():
        tmp = tempfile.mkdtemp(prefix="fsp_dl_")
        try:
            path = await client.download_media(msg, file_name=tmp + os.sep)
            if not path:
                raise RuntimeError("download failed")
            kw = dict(chat_id=chat_id, caption=caption or None, parse_mode=ParseMode.HTML,
                      reply_markup=reply_markup, protect_content=protect, thumb=thumb)
            if video:
                return await client.send_video(
                    video=path, duration=video.duration or 0, width=video.width or 0, height=video.height or 0,
                    supports_streaming=True, file_name=video.file_name, **kw)
            return await client.send_document(document=path, file_name=msg.document.file_name, force_document=True, **kw)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
