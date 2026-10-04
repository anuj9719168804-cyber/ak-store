"""Gift codes and the credit ledger.

Users:   /redeem CODE
Admins:  /gencode credits 20 50 7d        20 credits each, first 50 people, valid 7 days
         /gencode premium 30 10 0 MYCODE  30 days premium (0 days = lifetime), 10 people, no expiry, custom code
         /codes  (list)   /delcode CODE (switch off)   /ledger <user id> (where did their credits come from)
"""
from pyrogram import Client, filters
from pyrogram.types import Message

from helper import codes, ledger, links
from helper.utils import ban_notice
from helper.activity import log_activity

USAGE = (
    "<b>Usage:</b> <code>/gencode credits|premium &lt;amount&gt; &lt;people&gt; [time] [CODE]</code>\n\n"
    "• <code>/gencode credits 20 50 7d</code> — 20 credits each, first 50 people, valid 7 days\n"
    "• <code>/gencode premium 30 10 0</code> — 30 days premium, 10 people, never expires\n"
    "• amount for premium = days (<code>0</code> = lifetime)\n"
    "• add your own code as the last word, e.g. <code>/gencode credits 5 100 0 WELCOME5</code>"
)
_REASON = {
    "missing": "❌ That code does not exist.",
    "inactive": "❌ That code is no longer active.",
    "expired": "⌛ That code has expired.",
    "full": "🔒 That code has been used by everyone it was made for.",
    "already": "⚠️ You already used that code.",
}


@Client.on_message(filters.command("redeem") & filters.private)
async def redeem_command(client: Client, message: Message):
    uid = message.from_user.id
    if await client.mongodb.is_banned(uid):
        return await message.reply(await ban_notice(client.mongodb, message.from_user.id))
    if len(message.command) < 2:
        return await message.reply("Usage: <code>/redeem YOURCODE</code>")
    if not await client.mongodb.present_user(uid):
        await client.mongodb.add_user(uid)
    code, text = await codes.redeem(client.mongodb, uid, message.command[1])
    if code != "ok":
        return await message.reply(_REASON[code])
    await log_activity(client, "code_redeemed", uid, codes.normalize(message.command[1]), text)
    await message.reply(f"<blockquote>🎁 <b>Code redeemed</b></blockquote>\n{text} added to your account. Check /profile or /credits.")


@Client.on_message(filters.command("gencode") & filters.private)
async def gencode_command(client: Client, message: Message):
    if message.from_user.id not in client.admins:
        return await message.reply(client.reply_text)
    a = message.command[1:]
    if len(a) < 3:
        return await message.reply(USAGE)
    try:
        kind, amount, people = a[0].lower(), int(a[1]), int(a[2])
    except ValueError:
        return await message.reply("⚠️ Amount and people must be whole numbers.\n\n" + USAGE)
    ttl = links.parse_duration(a[3]) if len(a) >= 4 else 0
    if ttl is None:
        return await message.reply("⚠️ I could not read the time (use 30m, 24h, 7d or 0).\n\n" + USAGE)
    try:
        doc = await codes.create(client.mongodb.db, kind, amount, people, message.from_user.id, ttl, a[4] if len(a) >= 5 else "")
    except ValueError as e:
        return await message.reply(f"⚠️ {e}.\n\n" + USAGE)
    what = f"{amount} credits" if kind == "credits" else (f"{amount} days premium" if amount else "lifetime premium")
    await log_activity(client, "code_created", message.from_user.id, doc["_id"], f"{what} x{people}")
    await message.reply(
        f"<blockquote>✓ ᴄᴏᴅᴇ ᴄʀᴇᴀᴛᴇᴅ</blockquote>\n\n<code>{doc['_id']}</code>\n\n"
        f"🎁 {what}\n👥 first {people} people" + (f"\n⏱ valid {links.describe_seconds(ttl)}" if ttl else "") +
        f"\n\nUsers send: <code>/redeem {doc['_id']}</code>")


@Client.on_message(filters.command("codes") & filters.private)
async def codes_command(client: Client, message: Message):
    if message.from_user.id not in client.admins:
        return await message.reply(client.reply_text)
    docs = await codes.recent(client.mongodb.db, 15)
    if not docs:
        return await message.reply("No codes yet. Make one with /gencode.")
    now = codes._now()
    lines = []
    for d in docs:
        if not d["active"]:
            icon = "⛔"
        elif d.get("expires_at") and d["expires_at"] <= now:
            icon = "⌛"
        elif d["left"] <= 0:
            icon = "🔒"
        else:
            icon = "🟢"
        what = f"{d['amount']}cr" if d["kind"] == "credits" else (f"{d['amount']}d" if d["amount"] else "lifetime")
        lines.append(f"{icon} <code>{d['_id']}</code> · {what} · {d['uses']}/{d['max_uses']}")
    await message.reply("<b>Latest codes</b>\n\n" + "\n".join(lines) + "\n\n<i>🟢 live · ⌛ expired · 🔒 used up · ⛔ off</i>")


@Client.on_message(filters.command("delcode") & filters.private)
async def delcode_command(client: Client, message: Message):
    if message.from_user.id not in client.admins:
        return await message.reply(client.reply_text)
    if len(message.command) < 2:
        return await message.reply("Usage: <code>/delcode CODE</code>")
    if await codes.deactivate(client.mongodb.db, message.command[1]):
        await log_activity(client, "code_disabled", message.from_user.id, codes.normalize(message.command[1]))
        return await message.reply("⛔ Code switched off.")
    await message.reply("⚠️ I could not find that code.")


@Client.on_message(filters.command("ledger") & filters.private)
async def ledger_command(client: Client, message: Message):
    if message.from_user.id not in client.admins:
        return await message.reply(client.reply_text)
    if len(message.command) < 2 or not message.command[1].lstrip("-").isdigit():
        return await message.reply("Usage: <code>/ledger user_id</code>")
    uid = int(message.command[1])
    rows = await ledger.recent(client.mongodb.db, uid, 15)
    if not rows:
        return await message.reply("No credit grants recorded for that user.")
    total = await ledger.totals(client.mongodb.db, uid)
    balance = await client.mongodb.get_credits(uid)
    lines = [f"{r['at']:%m-%d %H:%M} · <b>{r['delta']:+d}</b> · {r['kind']}" + (f" · <code>{r['ref']}</code>" if r["ref"] else "") for r in rows]
    await message.reply(f"<b>Credits of</b> <code>{uid}</code> · balance <b>{balance}</b>\n"
                        f"Granted: " + ", ".join(f"{k} {v}" for k, v in sorted(total.items())) +
                        "\n\n" + "\n".join(lines) + "\n\n<i>Only grants are logged; spending is not.</i>")
