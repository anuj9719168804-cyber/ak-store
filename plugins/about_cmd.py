"""/about — shows the About text (same text as the About button, editable from /settings)."""
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from helper.utils import ban_notice


@Client.on_message(filters.command("about") & filters.private)
async def about_command(client: Client, message: Message):
    user = message.from_user
    if await client.mongodb.is_banned(user.id):
        return await message.reply(await ban_notice(client.mongodb, user.id))
    text = client.messages.get("ABOUT", "No About Message").format(
        owner_id=client.owner,
        bot_username=client.username,
        first=user.first_name,
        last=user.last_name,
        username=None if not user.username else "@" + user.username,
        mention=user.mention,
        id=user.id,
    )
    await message.reply(
        text,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("•ᴄʜᴀɴɴᴇʟs•", callback_data="channels"),
            InlineKeyboardButton("• ᴄʟᴏsᴇ •", callback_data="close"),
        ]]),
        disable_web_page_preview=True,
    )
