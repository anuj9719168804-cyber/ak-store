"""/flink - formatted link list for many files (admins only).

Multi-FileStoreBot has a "formatted link generator" (/flink) whose source is Pyarmor-protected, so this
is a fresh implementation of the same idea: send/forward DB-channel posts one by one, send /done, and
get ONE ready-to-paste message with a title, the size and a link per post. Unlike /custom_batch (one
link that delivers all files) this makes one link per file, handy for posting a release list.

  /flink            ask for posts (forward from the DB channel, or send the post link)
  /done             finish and get the list      /cancel   stop, nothing is generated
"""
import html
import re

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from helper.helper_func import encode, get_message_id
from helper.caption_logic import get_file_details
from helper.permanent_link import build_link
from helper.activity import log_activity

MAX_POSTS = 100          # per /flink run
CHUNK = 3800             # stay under Telegram's 4096-character message limit


async def _resolve(client, message):
    """(msg_id, channel_id) of a DB-channel post, or (0, 0). Never raises."""
    try:
        result = await get_message_id(client, message)
    except Exception:
        return 0, 0
    if not result or not result[0]:
        return 0, 0
    return result


async def _title_and_size(client, channel_id, msg_id):
    """Best-effort human title + size for a stored post."""
    try:
        post = await client.get_messages(channel_id, msg_id)
    except Exception:
        post = None
    if not post or getattr(post, "empty", False):
        return f"Post {msg_id}", ""
    details = get_file_details(post) if getattr(post, "media", None) else {}
    title = (details.get("file_name") or "").strip()
    if not title:
        text = (post.caption or post.text or "").strip()
        title = text.splitlines()[0].strip() if text else ""
    title = re.sub(r"\s+", " ", title)[:80] or f"Post {msg_id}"
    return title, details.get("file_size", "")


def _chunks(blocks):
    """Join blocks with a blank line, starting a new message before CHUNK characters."""
    out, cur = [], ""
    for block in blocks:
        if cur and len(cur) + len(block) + 2 > CHUNK:
            out.append(cur)
            cur = ""
        cur = f"{cur}\n\n{block}" if cur else block
    if cur:
        out.append(cur)
    return out


@Client.on_message(filters.private & filters.command("flink"))
async def flink(client: Client, message):
    if message.from_user.id not in client.admins:
        return await message.reply(client.reply_text)

    from plugins.link_generator import get_db_channels_info
    db_info = await get_db_channels_info(client)
    prompt = (f"<blockquote>sᴇɴᴅ ᴇᴀᴄʜ ᴅʙ ᴄʜᴀɴɴᴇʟ ᴘᴏsᴛ (ꜰᴏʀᴡᴀʀᴅ ᴏʀ ʟɪɴᴋ) ᴏɴᴇ ʙʏ ᴏɴᴇ.\n"
              f"sᴇɴᴅ /done ᴡʜᴇɴ ꜰɪɴɪsʜᴇᴅ, /cancel ᴛᴏ sᴛᴏᴘ.</blockquote>\n{db_info}")

    posts = []  # (msg_id, channel_id), in the order they were sent
    while True:
        try:
            reply = await client.ask(
                text=prompt, chat_id=message.from_user.id,
                filters=(filters.forwarded | filters.text), timeout=120,
            )
        except Exception:
            return await message.reply("<blockquote>⌛ ᴛɪᴍᴇᴅ ᴏᴜᴛ, ɴᴏᴛʜɪɴɢ ɢᴇɴᴇʀᴀᴛᴇᴅ.</blockquote>")

        text = (reply.text or "").strip().lower()
        if text == "/cancel":
            return await reply.reply("<blockquote>ᴄᴀɴᴄᴇʟʟᴇᴅ.</blockquote>")
        if text == "/done":
            break

        msg_id, channel_id = await _resolve(client, reply)
        if not msg_id:
            prompt = "<blockquote>✗ ɴᴏᴛ ꜰʀᴏᴍ ᴀ ᴅʙ ᴄʜᴀɴɴᴇʟ — sᴋɪᴘᴘᴇᴅ. sᴇɴᴅ ɴᴇxᴛ ᴏʀ /done</blockquote>"
            continue
        if (msg_id, channel_id) not in posts:
            posts.append((msg_id, channel_id))
        if len(posts) >= MAX_POSTS:
            break
        prompt = f"<blockquote>✓ ᴀᴅᴅᴇᴅ: {len(posts)} — sᴇɴᴅ ɴᴇxᴛ ᴏʀ /done</blockquote>"

    if not posts:
        return await message.reply("<blockquote>✗ ɴᴏ ᴘᴏsᴛs ᴡᴇʀᴇ ᴀᴅᴅᴇᴅ.</blockquote>")

    status = await message.reply("<blockquote>⏳ ʙᴜɪʟᴅɪɴɢ ʟɪɴᴋs...</blockquote>")
    blocks = []
    for number, (msg_id, channel_id) in enumerate(posts, start=1):
        payload = await encode(f"get-{msg_id * abs(channel_id)}")
        link = build_link(client, payload)
        title, size = await _title_and_size(client, channel_id, msg_id)
        size_part = f" [{html.escape(size)}]" if size else ""
        blocks.append(f"<b>{number}. {html.escape(title)}</b>{size_part}\n<code>{link}</code>")

    await status.delete()
    pages = _chunks(blocks)
    for i, page in enumerate(pages):
        markup = None
        if i == len(pages) - 1:
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔁 sʜᴀʀᴇ ʙᴏᴛ", url=f"https://t.me/{client.username}")]])
        await message.reply(page, disable_web_page_preview=True, reply_markup=markup)
    await log_activity(client, "link_generated", message.from_user.id, f"{len(posts)} links", "/flink")
