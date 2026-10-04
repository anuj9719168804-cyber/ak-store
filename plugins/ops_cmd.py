"""/logs and /restart for the OWNER (ideas from the src bot's botadmin.py).

/logs      the end of bot.log as a file, with tokens / passwords / DB URI blanked out
/restart   restart the whole process (bot + panel + streams). Needs Render / Docker / systemd to start it again.
"""
import asyncio
import io
import os
import sys

from pyrogram import Client, filters
from pyrogram.types import Message

import config
from helper import logview
from helper.activity import log_activity


def _secrets() -> list:
    names = ("TOKEN", "API_HASH", "DB_URI", "ADMIN_PASSWORD", "STREAM_SECRET", "PANEL_SECRET", "SHORT_API",
             "BACKEND_API_SECRET", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET", "NOWPAYMENTS_API_KEY",
             "NOWPAYMENTS_IPN_SECRET", "TURNSTILE_SECRET_KEY")
    return [getattr(config, n, "") for n in names]


@Client.on_message(filters.command("logs") & filters.private)
async def logs_command(client: Client, message: Message):
    if message.from_user.id != client.owner:
        return await message.reply(client.reply_text)
    text = logview.tail(config.LOG_FILE_NAME)
    if not text.strip():
        return await message.reply("No log lines yet.")
    data = io.BytesIO(logview.redact(text, _secrets()).encode("utf-8"))
    data.name = "bot-log.txt"
    await message.reply_document(data, caption="📄 Latest log lines (secrets blanked out).")
    await log_activity(client, "logs_requested", message.from_user.id)


@Client.on_message(filters.command("restart") & filters.private)
async def restart_command(client: Client, message: Message):
    if message.from_user.id != client.owner:
        return await message.reply(client.reply_text)
    await log_activity(client, "bot_restart", message.from_user.id, "", "/restart")
    await message.reply("♻️ Restarting now. If the bot does not come back, your host does not auto-start it.")
    await asyncio.sleep(1)
    os.execv(sys.executable, [sys.executable] + sys.argv)
