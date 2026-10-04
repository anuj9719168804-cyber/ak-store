"""/info — the user's own Telegram details plus their account here (ported from AK Ultra plugins/info.py).

AK Ultra read a Mongo document of its own; this version reads File Store's user record
(joined date, credits) and premium state instead.
"""
from datetime import datetime, timedelta, timezone

from pyrogram import Client, filters
from helper.utils import ban_notice
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import OWNER_ID

IST = timezone(timedelta(hours=5, minutes=30))


def _joined_text(ts) -> str:
    try:
        return datetime.fromtimestamp(float(ts), IST).strftime("%d-%m-%Y %I:%M %p IST")
    except (TypeError, ValueError, OverflowError, OSError):
        return "—"


@Client.on_message(filters.command("info") & filters.private)
async def info_command(client: Client, message: Message):
    user = message.from_user
    uid = user.id
    mongo = client.mongodb
    if await mongo.is_banned(uid):
        return await message.reply(await ban_notice(client.mongodb, message.from_user.id))
    if not await mongo.present_user(uid):
        await mongo.add_user(uid)

    doc = await mongo.user_data.find_one({"_id": uid}) or {}
    if uid == OWNER_ID:
        plan = "Owner"
    elif uid in client.admins:
        plan = "Admin"
    elif await mongo.is_pro(uid):
        expiry = await mongo.get_expiry_date(uid)
        plan = f"Premium (until {expiry:%d-%m-%Y})" if expiry else "Premium (lifetime)"
    else:
        plan = "Free"

    name = " ".join(p for p in (user.first_name, user.last_name) if p) or "—"
    text = (
        "<blockquote>👤 <b>Your info</b></blockquote>\n"
        f"➲ <b>Name:</b> {name}\n"
        f"➲ <b>Username:</b> {'@' + user.username if user.username else '—'}\n"
        f"➲ <b>ID:</b> <code>{uid}</code>\n"
        f"➲ <b>Data centre:</b> {user.dc_id or '—'}\n"
        f"➲ <b>Plan:</b> {plan}\n"
        f"➲ <b>Credits:</b> {await mongo.get_credits(uid)}\n"
        f"➲ <b>First used the bot:</b> {_joined_text(doc.get('joined'))}"
    )
    await message.reply(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("• ᴄʟᴏsᴇ •", callback_data="close")]]))
