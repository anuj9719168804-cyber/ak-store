"""Auto-batch: when several QUALITIES of the same title are posted by hand in a DB channel within a
short time, make one batch link for them and send it to the owner.

Ported from the src bot's Akbots/auto_batch.py. Changes for File Store:
  * the batch is stored the same way as /custom_batch (collection `custom_batches`, link `getc-<token>`),
    so start.py already knows how to deliver it — nothing else had to change;
  * a title is grouped together with its episode (S01E01), so 720p+1080p of episode 1 become one batch
    and episode 2 is a separate one;
  * the link goes to the owner, not into the DB channel (a text post there would sit inside /batch ranges);
  * the wait restarts with every new upload of the title, so a slow uploader does not get split batches.

Off by default: /autobatch on | off | <seconds>.
"""
import asyncio

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import AUTO_BATCH_WINDOW
from helper import autobatch
from helper.activity import log_activity
from helper.helper_func import encode
from helper.permanent_link import build_link
from helper.quality import display_title
from helper.utils import generate_token

_buffer: dict = {}   # (chat_id, key) -> {msg_id: Upload}
_timers: dict = {}   # (chat_id, key) -> asyncio.Task


def _db_channel_ids(client) -> set:
    ids = {int(client.db)}
    ids |= {int(c) for c in getattr(client, "db_channels", {}) or {}}
    return ids


async def _settings(client):
    on = bool(await client.mongodb.get_bot_setting("auto_batch", False))
    window = int(await client.mongodb.get_bot_setting("auto_batch_window", AUTO_BATCH_WINDOW) or AUTO_BATCH_WINDOW)
    return on, window


async def _flush(client: Client, slot: tuple, window: int):
    try:
        await asyncio.sleep(window)
    except asyncio.CancelledError:
        return
    _timers.pop(slot, None)
    uploads = autobatch.ready((_buffer.pop(slot, {}) or {}).values())
    if not uploads:
        return
    chat_id = slot[0]
    try:   # drop posts that were deleted meanwhile (e.g. removed as duplicates)
        msgs = await client.get_messages(chat_id, [u.msg_id for u in uploads])
        alive = {m.id for m in msgs if m and not m.empty}
        uploads = autobatch.ready(u for u in uploads if u.msg_id in alive)
    except Exception as e:
        client.LOGGER(__name__, client.name).warning(f"auto-batch: could not re-check posts: {e}")
    if not uploads:
        return
    token = generate_token(8)
    ids = [u.msg_id for u in uploads]
    await client.mongodb.db["custom_batches"].insert_one({"_id": token, "chat_id": chat_id, "ids": ids, "by": "auto-batch"})
    link = build_link(client, await encode(f"getc-{token}"))
    await log_activity(client, "link_generated", "auto-batch", link, f"{len(ids)} files")
    title = display_title(uploads[0].filename)
    qualities = " | ".join(u.quality for u in uploads)
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔁 Share URL", url=f"https://telegram.me/share/url?url={link}")]])
    try:
        await client.send_message(
            client.owner,
            f"<blockquote>💯 <b>Auto-batch ready</b></blockquote>\n<b>{title}</b>\n{qualities}\n\n<code>{link}</code>",
            reply_markup=markup, disable_web_page_preview=True)
    except Exception as e:
        client.LOGGER(__name__, client.name).warning(f"auto-batch: could not message the owner: {e}")


# group 5: runs next to channel_post.new_post (group 0) instead of competing with it
@Client.on_message(filters.channel & filters.incoming & (filters.document | filters.video), group=5)
async def collect(client: Client, message: Message):
    if message.chat.id not in _db_channel_ids(client):
        return
    on, window = await _settings(client)
    if not on:
        return
    media = message.document or message.video
    made = autobatch.make_upload(message.id, getattr(media, "file_name", None) or "")
    if not made:
        return
    key, upload = made
    slot = (message.chat.id, key)
    _buffer.setdefault(slot, {})[upload.msg_id] = upload
    old = _timers.get(slot)
    if old:
        old.cancel()
    _timers[slot] = asyncio.create_task(_flush(client, slot, window))


@Client.on_message(filters.command("autobatch") & filters.private)
async def autobatch_command(client: Client, message: Message):
    if message.from_user.id not in client.admins:
        return await message.reply(client.reply_text)
    on, window = await _settings(client)
    arg = message.command[1].lower() if len(message.command) > 1 else ""
    if arg in ("on", "off"):
        on = arg == "on"
        await client.mongodb.update_bot_setting("auto_batch", on)
    elif arg:
        new = autobatch.parse_window(arg, window)
        if new is None:
            return await message.reply("Usage: <code>/autobatch on</code>, <code>/autobatch off</code> or <code>/autobatch 45</code> (seconds, 5-600).")
        window = new
        await client.mongodb.update_bot_setting("auto_batch_window", window)
    await message.reply(
        f"<blockquote>💯 <b>Auto-batch</b></blockquote>\nStatus: <b>{'ON' if on else 'OFF'}</b>\nWait after the last upload: <b>{window}s</b>\n\n"
        "When 2+ qualities of the same title/episode are posted in a DB channel, one batch link is sent to the owner.\n"
        "<code>/autobatch on|off</code> · <code>/autobatch 45</code>")
