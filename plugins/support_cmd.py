"""/contact, /reply and /trial (ported ideas from AK Ultra).

Users:   /contact <message>   write to the admins (answered in the panel -> Support, or with /reply)
         /trial               one free premium trial per user (needs TRIAL_DAYS > 0 in config / env)
Admins:  /reply <user id> <text>   answer a support message from inside the bot
"""
import html

from pyrogram import Client, filters
from pyrogram.types import Message

from config import SUPPORT_COOLDOWN, TRIAL_DAYS
from helper import support, trial
from helper.activity import log_activity
from helper.utils import ban_notice


@Client.on_message(filters.command("contact") & filters.private)
async def contact_command(client: Client, message: Message):
    user = message.from_user
    if await client.mongodb.is_banned(user.id):
        return await message.reply(await ban_notice(client.mongodb, user.id))
    text = support.clean(message.text.split(None, 1)[1] if len(message.command) > 1 else "")
    if not text:
        return await message.reply("<b>Usage:</b> <code>/contact your message</code>\n\n"
                                   "Your message goes to the admins. The answer arrives in this chat.")
    db = client.mongodb.db
    wait = await support.seconds_until_allowed(db, user.id, SUPPORT_COOLDOWN)
    if wait:
        return await message.reply(f"⏳ Please wait <b>{wait}s</b> before sending another message.")
    if not await client.mongodb.present_user(user.id):
        await client.mongodb.add_user(user.id)
    await support.add_user_message(db, user.id, text, user.first_name or "", user.username or "")
    await log_activity(client, "support_message", user.id, "", text[:120])
    await message.reply("✅ <b>Sent.</b> An admin will answer you here.")
    try:  # tell the owner right away; the panel (Support) holds the full thread
        who = html.escape(user.first_name or "user") + (f" @{user.username}" if user.username else "")
        await client.send_message(
            client.owner,
            f"<blockquote>📩 <b>Support message</b></blockquote>\n<b>From:</b> {who} (<code>{user.id}</code>)\n\n"
            f"{html.escape(text)}\n\n<i>Answer:</i> <code>/reply {user.id} your answer</code> <i>or in the panel → Support</i>",
        )
    except Exception:
        pass  # owner never started the bot: the thread is still in the panel


@Client.on_message(filters.command("reply") & filters.private)
async def reply_command(client: Client, message: Message):
    if message.from_user.id not in client.admins:
        return await message.reply(client.reply_text)
    parts = message.text.split(None, 2)
    if len(parts) < 3 or not parts[1].lstrip("-").isdigit():
        return await message.reply("<b>Usage:</b> <code>/reply &lt;user id&gt; &lt;your answer&gt;</code>")
    uid = int(parts[1])
    try:
        delivered, note = await support.send_reply(client, uid, parts[2], str(message.from_user.id))
    except LookupError:
        return await message.reply("❌ That user has not written to support (no thread).")
    except ValueError:
        return await message.reply("❌ The answer is empty.")
    await log_activity(client, "support_reply", message.from_user.id, uid, parts[2][:120])
    await message.reply("✅ Sent." if delivered else f"⚠️ Saved, but Telegram would not deliver it ({note}).")


@Client.on_message(filters.command("trial") & filters.private)
async def trial_command(client: Client, message: Message):
    uid = message.from_user.id
    if TRIAL_DAYS <= 0:
        return await message.reply("The free trial is turned off.")
    if await client.mongodb.is_banned(uid):
        return await message.reply(await ban_notice(client.mongodb, uid))
    code, text = await trial.claim(client.mongodb, uid, TRIAL_DAYS)
    if code == "ok":
        await log_activity(client, "trial_claimed", uid, "", text)
        return await message.reply(f"<blockquote>🎯 <b>Free trial started</b></blockquote>\nYou got <b>{TRIAL_DAYS}</b> day(s) of premium ({text}). Enjoy!")
    if code == "premium":
        return await message.reply("You already have premium, so your trial is still unused.")
    await message.reply("You already used your free trial. See /buy for the premium plans.")
