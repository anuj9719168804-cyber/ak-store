"""Scheduled multi-channel posts (ported from ng-auto-post2.0, rewritten for File Store Pro).

Admins build a post (title + download link + optional preview link), pick a time and the bot posts
it to the saved post channels. The caption is plain text/HTML with links only; the branding line
and the button under the post come from AUTOPOST_BRAND / AUTOPOST_BUTTON_* (empty = nothing).

Collections (separate from Pro's own):  autopost_channels, autopost_posts, autopost_logs
"""
import asyncio
import html
import logging
import re
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import AUTOPOST_BRAND, AUTOPOST_BUTTON_TEXT, AUTOPOST_BUTTON_URL

log = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


def _cols(bot):
    db = bot.mongodb.db
    return db["autopost_channels"], db["autopost_posts"], db["autopost_logs"]


def as_utc(dt: datetime) -> datetime:
    """Mongo hands datetimes back naive (UTC); make them aware again."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def fmt_ist(dt: datetime) -> str:
    return as_utc(dt).astimezone(IST).strftime("%d-%m-%Y %H:%M IST")


def parse_when(text: str, now: datetime | None = None) -> datetime | None:
    """'now', '30m', '2h', or 'DD-MM HH:MM' (IST). Returns an aware UTC datetime, or None."""
    now = now or datetime.now(timezone.utc)
    t = (text or "").strip().lower()
    if t in ("now", "0", "0m"):
        return now
    m = re.fullmatch(r"(\d{1,4})\s*([mh])", t)
    if m:
        n = int(m.group(1))
        return now + (timedelta(minutes=n) if m.group(2) == "m" else timedelta(hours=n))
    try:
        dt = datetime.strptime(t, "%d-%m %H:%M")
    except ValueError:
        return None
    dt = dt.replace(year=now.astimezone(IST).year, tzinfo=IST).astimezone(timezone.utc)
    return dt


def valid_url(url: str) -> bool:
    return bool(re.match(r"https?://\S+$", (url or "").strip()))


def build_caption(title: str, preview: str | None, main_link: str) -> str:
    lines = ["<b>┏━━━━━ NEW POST ━━━━━┓</b>", "", f"🎬 <b>{html.escape(title)}</b>", ""]
    if preview:
        lines += ["👀 <b>PREVIEW</b>", f"➥ <a href=\"{html.escape(preview, quote=True)}\">Click Here</a>", ""]
    lines += ["📥 <b>DOWNLOAD &amp; WATCH</b>",
              f"➥ <a href=\"{html.escape(main_link, quote=True)}\">Click Here</a>", ""]
    if AUTOPOST_BRAND:
        lines.append(f"<b>┗━━━━ {html.escape(AUTOPOST_BRAND)} ━━━━┛</b>")
    else:
        lines.append("<b>┗━━━━━━━━━━━━━━━━━━┛</b>")
    return "\n".join(lines)


def build_buttons():
    if AUTOPOST_BUTTON_TEXT and AUTOPOST_BUTTON_URL:
        return InlineKeyboardMarkup([[InlineKeyboardButton(AUTOPOST_BUTTON_TEXT, url=AUTOPOST_BUTTON_URL)]])
    return None


async def send_post(bot, title, main_link, preview, channel_ids) -> int:
    caption, buttons, ok = build_caption(title, preview, main_link), build_buttons(), 0
    for cid in channel_ids:
        for _ in range(2):
            try:
                await bot.send_message(cid, caption, parse_mode=ParseMode.HTML,
                                       reply_markup=buttons, disable_web_page_preview=True)
                ok += 1
                break
            except FloodWait as e:
                await asyncio.sleep(getattr(e, "value", None) or getattr(e, "x", 5))
            except Exception as e:
                log.warning("autopost: could not post to %s: %s", cid, e)
                break
        await asyncio.sleep(0.3)  # stay well under Telegram's per-chat flood limits
    return ok


# ───────────────────────────── channels ─────────────────────────────

async def add_channel(bot, channel_id: int, title: str) -> bool:
    channels, _, _ = _cols(bot)
    if await channels.find_one({"_id": channel_id}):
        return False
    await channels.insert_one({"_id": channel_id, "title": title, "added_at": datetime.now(timezone.utc)})
    return True


async def remove_channel(bot, channel_id: int) -> bool:
    channels, _, _ = _cols(bot)
    return (await channels.delete_one({"_id": channel_id})).deleted_count > 0


async def list_channels(bot) -> list[dict]:
    channels, _, _ = _cols(bot)
    return await channels.find({}).sort("added_at", 1).to_list(length=None)


# ───────────────────────────── posts ─────────────────────────────

async def save_post(bot, data: dict):
    _, posts, _ = _cols(bot)
    data.update(status="pending", created_at=datetime.now(timezone.utc))
    return (await posts.insert_one(data)).inserted_id


async def pending_posts(bot) -> list[dict]:
    _, posts, _ = _cols(bot)
    return await posts.find({"status": "pending"}).sort("schedule_time", 1).to_list(length=None)


async def cancel_post(bot, post_id: str) -> bool:
    _, posts, _ = _cols(bot)
    try:
        oid = ObjectId(post_id)
    except Exception:
        return False
    res = await posts.update_one({"_id": oid, "status": "pending"}, {"$set": {"status": "cancelled"}})
    return res.modified_count > 0


async def autopost_job(bot):
    """Called every ~20 s by helper.scheduler: send every post whose time has come."""
    channels, posts, logs = _cols(bot)
    while True:
        now = datetime.now(timezone.utc)
        # claim atomically so two overlapping runs can never send the same post twice
        post = await posts.find_one_and_update(
            {"status": "pending", "schedule_time": {"$lte": now}}, {"$set": {"status": "sending"}}
        )
        if not post:
            return
        if post.get("channels_mode") == "all":  # resolved at send time: new channels are included
            ids = [c["_id"] for c in await channels.find({}).to_list(length=None)]
        else:
            ids = post.get("channels", [])
        sent = await send_post(bot, post["title"], post["main_link"], post.get("preview"), ids)
        await posts.update_one({"_id": post["_id"]},
                               {"$set": {"status": "sent", "sent_count": sent, "sent_at": datetime.now(timezone.utc)}})
        await logs.insert_one({"title": post["title"], "channels": ids, "sent": sent,
                               "posted_at": datetime.now(timezone.utc)})
        log.info("autopost: '%s' sent to %d/%d channels", post["title"], sent, len(ids))
        if post.get("created_by"):
            try:
                await bot.send_message(post["created_by"],
                                       f"✅ Auto-post <b>{html.escape(post['title'])}</b> sent to {sent}/{len(ids)} channels.")
            except Exception:
                pass
