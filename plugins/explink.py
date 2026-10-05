"""/explink  /links  /revoke  — links that stop working after a time or N downloads.

    /explink 24h 100 <link>     24 hours OR 100 people, whichever comes first
    /explink 7d 0 <link>        7 days, unlimited people
    /explink 0 50 <link>        no time limit, first 50 people
    (or reply to a message that contains the link, or send just /explink and answer the questions)

<link> is any link the bot made before: /genlink, /batch, /nbatch, /custom_batch, a /flink line,
or a permanent link. The original link keeps working: only the new lk_ link is limited.
"""
from pyrogram import Client, filters
from pyrogram.errors.pyromod import ListenerTimeout
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from helper import links
from helper.activity import log_activity
from helper.helper_func import decode
from helper.permanent_link import build_link
from helper.upload_access import has_premium_access

USAGE = (
    "<b>Usage:</b> <code>/explink [time] [max people] [link]</code>\n\n"
    "• <code>/explink 24h 100 &lt;link&gt;</code> — 24 hours or 100 people\n"
    "• <code>/explink 7d 0 &lt;link&gt;</code> — 7 days, any number of people\n"
    "• <code>/explink 0 50 &lt;link&gt;</code> — no time limit, first 50 people\n\n"
    "Time: <code>30m</code>, <code>24h</code>, <code>7d</code>, <code>2w</code> (a bare number = hours, 0 = never).\n"
    "Reply to a message that has the link, or leave the link out and I will ask for it."
)


async def _ask(client, message, prompt):
    try:
        reply = await client.ask(chat_id=message.from_user.id, text=prompt, timeout=90)
    except ListenerTimeout:
        await message.reply("⌛ Timed out. Start again with /explink.")
        return None
    return (reply.text or "").strip()


def _int(text):
    try:
        value = int(str(text).strip())
        return value if value >= 0 else None
    except (TypeError, ValueError):
        return None


async def _valid_payload(payload):
    """Only real file links (single, batch, custom batch) can be wrapped."""
    if not payload or links.is_managed(payload) or payload.startswith(("yu3elk", "vt_", "ref_")):
        return False
    try:
        parts = (await decode(payload)).split("-")
    except Exception:
        return False
    return parts[0] in ("get", "getc") and 2 <= len(parts) <= 3 and all(p for p in parts)


@Client.on_message(filters.command("explink") & filters.private)
async def explink_command(client: Client, message: Message):
    if not await has_premium_access(client, message.from_user.id):
        return await message.reply(client.reply_text)
    args = message.command[1:]

    ttl_text = args[0] if len(args) >= 1 else await _ask(client, message, "⏱ <b>How long should the link work?</b>\nExamples: <code>24h</code>, <code>7d</code>, <code>0</code> = no time limit.")
    if ttl_text is None:
        return
    uses_text = args[1] if len(args) >= 2 else await _ask(client, message, "👥 <b>How many people may use it?</b>\nA number, or <code>0</code> = unlimited.")
    if uses_text is None:
        return
    ttl, max_uses = links.parse_duration(ttl_text), _int(uses_text)
    if ttl is None or max_uses is None:
        return await message.reply("⚠️ I could not read the time or the number.\n\n" + USAGE)
    if ttl == 0 and max_uses == 0:
        return await message.reply("⚠️ A link with no time limit <b>and</b> no user limit is just a normal link. Set at least one limit.")

    source = " ".join(args[2:]).strip() if len(args) >= 3 else ""
    if not source and message.reply_to_message:
        source = (message.reply_to_message.text or message.reply_to_message.caption or "").strip()
    if not source:
        source = await _ask(client, message, "🔗 <b>Send the link</b> you want to limit (made with /genlink, /batch, ...).")
        if source is None:
            return
    payload = links.extract_payload(source)
    if not await _valid_payload(payload):
        return await message.reply("⚠️ That is not a link made by this bot (or it is already a limited link).")

    doc = await links.create(client.mongodb.db, payload, message.from_user.id, ttl, max_uses)
    link = build_link(client, links.PREFIX + doc["_id"])
    rules = []
    if ttl:
        rules.append(f"⏱ valid for <b>{links.describe_seconds(ttl)}</b>")
    if max_uses:
        rules.append(f"👥 first <b>{max_uses}</b> people")
    await log_activity(client, "explink_created", message.from_user.id, links.PREFIX + doc["_id"],
                       f"ttl={links.describe_seconds(ttl) if ttl else 'none'} max_uses={max_uses or 'none'}")
    await message.reply(
        "<blockquote>✓ ʜᴇʀᴇ ɪs ʏᴏᴜʀ ʟɪᴍɪᴛᴇᴅ ʟɪɴᴋ</blockquote>\n\n"
        f"<code>{link}</code>\n\n" + "\n".join(rules) +
        f"\n\nStop it any time: <code>/revoke {links.PREFIX}{doc['_id']}</code>",
        quote=True, disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔁 sʜᴀʀᴇ ᴜʀʟ", url=f"https://telegram.me/share/url?url={link}")]]),
    )


@Client.on_message(filters.command("links") & filters.private)
async def links_command(client: Client, message: Message):
    uid = message.from_user.id
    if not await has_premium_access(client, uid):
        return await message.reply(client.reply_text)
    # admins see every limited link, premium members only their own
    docs = await links.recent(client.mongodb.db, 15, None if uid in client.admins else uid)
    if not docs:
        return await message.reply("No limited links yet. Make one with /explink.")
    await message.reply("<b>Your latest limited links</b>\n\n" + "\n".join(links.summary_line(d) for d in docs)
                        + "\n\n<i>🟢 live · ⌛ expired · 🔒 limit reached · ⛔ revoked</i>")


@Client.on_message(filters.command("revoke") & filters.private)
async def revoke_command(client: Client, message: Message):
    uid = message.from_user.id
    if not await has_premium_access(client, uid):
        return await message.reply(client.reply_text)
    if len(message.command) < 2:
        return await message.reply("Usage: <code>/revoke lk_XXXXXXXXXXXX</code> (or paste the whole link)")
    payload = links.extract_payload(message.command[1])
    if not payload or not links.is_managed(payload):
        return await message.reply("⚠️ That is not a limited link (they start with <code>lk_</code>).")
    if uid not in client.admins and not await links.is_owned_by(client.mongodb.db, payload, uid):
        return await message.reply("⚠️ You can only revoke links you made yourself.")
    if await links.revoke(client.mongodb.db, payload):
        await log_activity(client, "explink_revoked", message.from_user.id, payload)
        return await message.reply("⛔ Link revoked. It stops working immediately, for everyone.")
    await message.reply("⚠️ I could not find that link.")
