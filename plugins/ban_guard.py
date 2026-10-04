"""Global ban guard: a banned user gets the ban notice for ANY message or button press, in private chat.

Before this, only some commands checked the ban flag (/start, /daily, /search, ...), so a banned user could
still use /credits, /profile, /request, /bots and every inline button. Admins are never blocked.
Runs in group -25: before maintenance (-20) and every other handler. Fails open: a database hiccup
must not lock everybody out.
"""
import time

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message

from helper import banguard
from helper.utils import ban_notice

_NOTICE_EVERY = 60
_last_notice: dict = {}


async def _banned(client, user) -> bool:
    if not user or user.id in client.admins:
        return False
    hit = banguard.get(user.id)
    if hit is not None:
        return hit
    try:
        banned = await client.mongodb.is_banned(user.id)
    except Exception:
        return False
    banguard.put(user.id, banned)
    return banned


@Client.on_message(filters.private & filters.incoming, group=-25)
async def guard_message(client: Client, message: Message):
    if not await _banned(client, message.from_user):
        return
    uid, now = message.from_user.id, time.monotonic()
    if now - _last_notice.get(uid, -_NOTICE_EVERY) >= _NOTICE_EVERY:
        _last_notice[uid] = now
        if len(_last_notice) > 5000:
            _last_notice.clear()
        try:
            await message.reply(await ban_notice(client.mongodb, uid))
        except Exception:
            pass
    message.stop_propagation()


@Client.on_callback_query(group=-25)
async def guard_callback(client: Client, query: CallbackQuery):
    if not await _banned(client, query.from_user):
        return
    try:
        await query.answer("🚫 You are banned from using this bot.", show_alert=True)
    except Exception:
        pass
    query.stop_propagation()
