"""/set_expiry - how long NEW web (Watch / Download) links stay valid (idea from the src bot).

    /set_expiry            show the current value
    /set_expiry 1h         1 hour      (also 30m, 1h30m, 2d, 3600)
    /set_expiry 0          never expire
    /set_expiry reset      back to STREAM_LINK_TTL from the environment
"""
from pyrogram import Client, filters
from pyrogram.types import Message

from config import STREAM_LINK_TTL
from helper import linkttl
from helper.activity import log_activity


@Client.on_message(filters.command("set_expiry") & filters.private)
async def set_expiry_command(client: Client, message: Message):
    if message.from_user.id not in client.admins:
        return await message.reply(client.reply_text)
    arg = message.command[1].strip().lower() if len(message.command) > 1 else ""
    if not arg:
        src = "admin setting" if linkttl.is_override() else "default (STREAM_LINK_TTL)"
        return await message.reply(
            f"⏳ Web links expire after: <b>{linkttl.readable(linkttl.get())}</b>\nSource: {src}\n\n"
            "Change: <code>/set_expiry 1h</code> · <code>30m</code> · <code>1h30m</code> · <code>2d</code> · "
            "<code>0</code> (never) · <code>reset</code>")
    if arg == "reset":
        await linkttl.save(client.mongodb, None)
        await log_activity(client, "link_expiry_reset", message.from_user.id)
        return await message.reply(f"↩️ Back to the default: <b>{linkttl.readable(STREAM_LINK_TTL)}</b>.")
    seconds = linkttl.parse_duration(arg)
    if seconds is None:
        return await message.reply("I did not understand that. Try <code>/set_expiry 1h</code>, "
                                   "<code>45m</code>, <code>2d</code> or <code>0</code> (max 365 days).")
    await linkttl.save(client.mongodb, seconds)
    await log_activity(client, "link_expiry_changed", message.from_user.id, "", linkttl.readable(seconds))
    await message.reply(f"✅ New web links now expire after: <b>{linkttl.readable(seconds)}</b>.\n"
                        "<i>Links already sent keep their old expiry.</i>")
