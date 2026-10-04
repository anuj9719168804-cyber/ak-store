"""Shared helpers ported from Multi-FileStoreBot utils/helpers.py."""
import asyncio
import base64
import logging
import os
import re

import aiohttp
from pyrogram import Client
from pyrogram.types import Message

log = logging.getLogger(__name__)


# ── Deep-link encoding / decoding ────────────────────────────────────────────

async def encode(string: str) -> str:
    return base64.urlsafe_b64encode(string.encode("ascii")).decode("ascii").strip("=")


async def decode(base64_string: str) -> str:
    base64_string = base64_string.strip("=")
    padded = base64_string + "=" * (-len(base64_string) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii")).decode("ascii")


# ── Time helpers ──────────────────────────────────────────────────────────────

def get_exp_time(seconds: int) -> str:
    periods = [("days", 86400), ("hours", 3600), ("mins", 60), ("secs", 1)]
    result = ""
    for name, p in periods:
        if seconds >= p:
            val, seconds = divmod(seconds, p)
            result += f"{int(val)} {name} "
    return result.strip() or "0 secs"


def get_readable_time(seconds: int) -> str:
    parts, suffix = [], ["s", "m", "h", "days"]
    count = 0
    while count < 4:
        count += 1
        remainder, result = divmod(seconds, 60) if count < 3 else divmod(seconds, 24)
        if seconds == 0 and remainder == 0:
            break
        parts.append(int(result))
        seconds = int(remainder)
    for i in range(len(parts)):
        parts[i] = str(parts[i]) + suffix[i]
    if len(parts) == 4:
        head = parts.pop() + ", "
    else:
        head = ""
    parts.reverse()
    return head + ":".join(parts)


# ── Bot token validation ──────────────────────────────────────────────────────

async def validate_bot_token(token: str) -> dict | None:
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    data = await r.json()
                    if data.get("ok"):
                        return data["result"]
    except asyncio.TimeoutError:
        log.warning("validate_bot_token: timed out")
    except Exception as e:
        log.error(f"validate_bot_token: {e}")
    return None


# ── Message ID extraction ─────────────────────────────────────────────────────

async def get_message_id(client: Client, message: Message, log_channel_id: int):
    """Get a message's log-channel ID (forwarded) or forward it there."""
    forward_chat_id = forward_msg_id = None

    origin = getattr(message, "forward_origin", None)
    if origin:
        chat = getattr(origin, "chat", None) or getattr(origin, "sender_chat", None)
        if chat:
            forward_chat_id = chat.id
        forward_msg_id = getattr(origin, "message_id", None)
    else:
        ff = getattr(message, "forward_from_chat", None)
        if ff:
            forward_chat_id = ff.id
            forward_msg_id = getattr(message, "forward_from_message_id", None)

    if forward_chat_id == log_channel_id:
        return forward_msg_id

    if message.text:
        m = re.search(r"https?://t\.me/(?:c/)?([^/]+)/(\d+)", message.text)
        if m:
            chat_id_str, msg_id = m.group(1), int(m.group(2))
            if chat_id_str.isdigit():
                if int("-100" + chat_id_str) == log_channel_id:
                    return msg_id
            try:
                chat = await client.get_chat(log_channel_id)
                if chat.username and chat.username.lower() == chat_id_str.lower():
                    return msg_id
            except Exception:
                pass

    if getattr(message, "service", None):
        return None

    try:
        fwd = await message.forward(log_channel_id)
        return fwd.id if fwd else None
    except Exception as e:
        log.error(f"get_message_id forward error: {e}")
        return None


async def get_messages(client: Client, channel_id: int, ids: list):
    from pyrogram.errors import FloodWait
    result = []
    for i in range(0, len(ids), 200):
        batch = ids[i:i + 200]
        try:
            msgs = await client.get_messages(channel_id, message_ids=batch)
        except FloodWait as e:
            await asyncio.sleep(e.value)
            msgs = await client.get_messages(channel_id, message_ids=batch)
        except Exception as e:
            log.error(f"get_messages: {e}")
            msgs = []
        if isinstance(msgs, list):
            result.extend(msgs)
        else:
            result.append(msgs)
    return result


# ── Image upload (freeimage.host) ─────────────────────────────────────────────

async def upload_to_telegraph(client: Client, message: Message) -> str | None:
    file_path = None
    try:
        if not (message.photo or message.document):
            return None
        temp = await message.reply("⏳ <i>Uploading image…</i>")
        file_path = await client.download_media(message)
        if not file_path:
            await temp.edit("❌ Download failed.")
            return None
        with open(file_path, "rb") as f:
            data = aiohttp.FormData()
            data.add_field("key", "6d207e02198a847aa98d0a2a901485a5")
            data.add_field("source", f, filename=file_path)
            async with aiohttp.ClientSession() as s:
                async with s.post("https://freeimage.host/api/1/upload", data=data) as r:
                    if r.status == 200:
                        j = await r.json()
                        if j.get("status_code") == 200:
                            url = j["image"]["url"]
                            if url:
                                await temp.delete()
                                return url
                    await temp.edit("❌ Upload failed.")
        return None
    except Exception as e:
        log.error(f"upload_to_telegraph: {e}")
        return None
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass


# ── Main log channel ──────────────────────────────────────────────────────────

_main_bot_ref = None  # set by main.py after Pro bot.start()


def set_main_bot(bot):
    global _main_bot_ref
    _main_bot_ref = bot


async def send_main_log(client: Client, text: str):
    async def _send():
        try:
            from config import MAIN_LOG_CHANNEL
            if not MAIN_LOG_CHANNEL:
                return
            bot = _main_bot_ref or client
            await bot.send_message(MAIN_LOG_CHANNEL, text)
        except Exception as e:
            log.error(f"send_main_log: {e}")
    asyncio.create_task(_send())
