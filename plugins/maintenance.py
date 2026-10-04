"""Maintenance mode: while ON, everyone except admins gets an "under maintenance" notice.

Ported from the src bot's Akbots/maintenance.py. /maintenance on | off (admins only, and admins are never
blocked). Works on messages, button presses and inline search in private chats; channel posts and
force-sub join requests are untouched, so uploads to the DB channel keep being recorded.
The gate runs in group -20, before every other handler (create_bot.py uses -1, auto_react -10).
"""
import time

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, InlineQuery, Message

from helper.switch import CachedFlag

TEXT = "🛠 <b>The bot is under maintenance.</b>\n\nPlease try again in a little while."
_NOTICE_EVERY = 60          # seconds between notices to the same person, so spam is not answered with spam
_last_notice: dict = {}
_flag = None


def _state(client) -> CachedFlag:
    global _flag
    if _flag is None:
        _flag = CachedFlag(lambda: client.mongodb.get_bot_setting("maintenance", False))
    return _flag


def _blocked_user(client, user) -> bool:
    return bool(user) and user.id not in client.admins


async def is_on(client) -> bool:
    return await _state(client).get()


async def set_on(client, on: bool):
    """Save + apply at once (used by the web panel; the /maintenance command does the same)."""
    await client.mongodb.update_bot_setting("maintenance", bool(on))
    _state(client).set(bool(on))


@Client.on_message(filters.command("maintenance") & filters.private)
async def maintenance_command(client: Client, message: Message):
    if message.from_user.id not in client.admins:
        return await message.reply(client.reply_text)
    arg = message.command[1].lower() if len(message.command) > 1 else ""
    if arg not in ("on", "off"):
        now = await _state(client).get()
        return await message.reply(f"🛠 Maintenance mode is <b>{'ON' if now else 'OFF'}</b>.\nUse <code>/maintenance on</code> or <code>/maintenance off</code>.")
    on = arg == "on"
    await client.mongodb.update_bot_setting("maintenance", on)
    _state(client).set(on)
    await message.reply(f"🛠 Maintenance mode is now <b>{'ON' if on else 'OFF'}</b>." + ("\nAdmins can still use the bot." if on else ""))


@Client.on_message(filters.private & filters.incoming, group=-20)
async def gate_message(client: Client, message: Message):
    if not _blocked_user(client, message.from_user) or not await _state(client).get():
        return
    uid, now = message.from_user.id, time.monotonic()
    if now - _last_notice.get(uid, -_NOTICE_EVERY) >= _NOTICE_EVERY:
        _last_notice[uid] = now
        if len(_last_notice) > 5000:
            _last_notice.clear()
        try:
            await message.reply(TEXT)
        except Exception:
            pass
    message.stop_propagation()


@Client.on_callback_query(group=-20)
async def gate_callback(client: Client, query: CallbackQuery):
    if not _blocked_user(client, query.from_user) or not await _state(client).get():
        return
    try:
        await query.answer("🛠 The bot is under maintenance. Please try again later.", show_alert=True)
    except Exception:
        pass
    query.stop_propagation()


@Client.on_inline_query(group=-20)
async def gate_inline(client: Client, query: InlineQuery):
    if not _blocked_user(client, query.from_user) or not await _state(client).get():
        return
    try:
        await query.answer([], cache_time=5)
    except Exception:
        pass
    query.stop_propagation()
