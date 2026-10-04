"""Flood protection for private chats.

Runs in handler group -1, i.e. BEFORE every other plugin, and stops the update
when a user is too fast. Owner + admins are never limited.

  * commands (/start, /profile, ...): one per RATE_LIMIT_SECONDS (config.py, 0 = off)
  * button presses: one per second
File uploads and plain text replies are NOT limited (albums, listen() prompts).
"""
import math

from pyrogram import Client, filters

from config import RATE_LIMIT_SECONDS
from helper.rate_limit import limiter

CALLBACK_COOLDOWN = 1  # seconds between button presses


def _is_command(_, __, message):
    return bool(message.text and message.text.startswith("/"))


is_command = filters.create(_is_command)


@Client.on_message(filters.private & is_command, group=-1)
async def throttle_commands(client: Client, message):
    if RATE_LIMIT_SECONDS <= 0 or not message.from_user:
        return
    user_id = message.from_user.id
    if user_id in client.admins:
        return
    allowed, wait, first = limiter.check(("cmd", user_id), RATE_LIMIT_SECONDS)
    if allowed:
        return
    if first:  # answer once per window, otherwise the warning itself becomes spam
        try:
            await message.reply(f"⏳ Slow down! Try again in {math.ceil(wait)}s.", quote=True)
        except Exception:
            pass
    message.stop_propagation()


@Client.on_callback_query(group=-1)
async def throttle_buttons(client: Client, query):
    if RATE_LIMIT_SECONDS <= 0 or not query.from_user:
        return
    if query.from_user.id in client.admins:
        return
    allowed, _, _ = limiter.check(("cb", query.from_user.id), CALLBACK_COOLDOWN)
    if allowed:
        return
    try:
        await query.answer("⏳ Slow down!")
    except Exception:
        pass
    query.stop_propagation()
