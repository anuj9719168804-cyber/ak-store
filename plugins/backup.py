from pyrogram import Client, filters
from pyrogram.types import Message

from config import OWNER_ID
from helper.activity import log_activity
from helper.scheduler import run_backup


@Client.on_message(filters.command("backup") & filters.private)
async def backup_command(client: Client, message: Message):
    """Owner only: back up MongoDB now and get the file here (the bot also does this on a schedule)."""
    if message.from_user.id != OWNER_ID:
        return await message.reply_text("Only Owner can use this command...!")

    status = await message.reply_text("🔄 Creating the backup, this can take a minute...", quote=True)
    ok, summary = await run_backup(client, "manual")
    await log_activity(client, "backup_manual", message.from_user.id, "", summary)
    # On success the file itself arrived as a separate message; on failure run_backup already
    # sent the reason as a separate message, so this only closes the status line.
    if ok:
        await status.edit_text("✅ " + summary)
    else:
        await status.edit_text("⚠️ The backup did not complete, see the message below.")
