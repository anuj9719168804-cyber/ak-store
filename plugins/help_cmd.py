"""/help — a command list (admins also see the admin commands, the owner the owner ones).

Modelled on AK Ultra's /help and /commands. The text lives in helper/help_text.py.
"""
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import OWNER_ID
from helper import help_text
from helper.utils import ban_notice


@Client.on_message(filters.command(["help", "commands"]) & filters.private)
async def help_command(client: Client, message: Message):
    uid = message.from_user.id
    if await client.mongodb.is_banned(uid):
        return await message.reply(await ban_notice(client.mongodb, message.from_user.id))
    text = help_text.render(is_admin=uid in client.admins, is_owner=uid == OWNER_ID,
                            is_premium=bool(await client.mongodb.is_pro(uid)))
    await message.reply(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("• ᴄʟᴏsᴇ •", callback_data="close")]]))
