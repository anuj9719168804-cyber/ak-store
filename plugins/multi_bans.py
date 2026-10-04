"""Owner-level commands for the multi-bot system.

  /mban   [user_id]  – ban a user from creating bots (controller level)
  /munban [user_id]  – unban
  /mcast              – broadcast to all multi-system users (reply to msg)
  /check              – show all registered bots + status (owner only)
  /sysstats           – system statistics (owner only)

Using /mban and /munban prefixes to avoid clashing with Pro's own /ban /unban.
"""
import asyncio
import logging

from pyrogram import Client, filters
from pyrogram.types import Message

from config import OWNER_ID
from multi.registry import RegistryDB

log = logging.getLogger(__name__)
_registry = RegistryDB()


# ── /mban ─────────────────────────────────────────────────────────────────────

@Client.on_message(filters.command("mban") & filters.private & filters.user(OWNER_ID))
async def mban_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply("<b>Usage:</b> <code>/mban [user_id]</code>")
    try:
        tid = int(message.command[1])
        await _registry.add_ban_user(tid)
        await message.reply(f"<b>✅ User <code>{tid}</code> banned from multi-bot system.</b>")
    except ValueError:
        await message.reply("<b>❌ Invalid user ID.</b>")


# ── /munban ───────────────────────────────────────────────────────────────────

@Client.on_message(filters.command("munban") & filters.private & filters.user(OWNER_ID))
async def munban_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply("<b>Usage:</b> <code>/munban [user_id]</code>")
    try:
        tid = int(message.command[1])
        await _registry.del_ban_user(tid)
        await message.reply(f"<b>✅ User <code>{tid}</code> unbanned from multi-bot system.</b>")
    except ValueError:
        await message.reply("<b>❌ Invalid user ID.</b>")


# ── /mcast ────────────────────────────────────────────────────────────────────

@Client.on_message(filters.command("mcast") & filters.private & filters.user(OWNER_ID))
async def mcast_cmd(client: Client, message: Message):
    if not message.reply_to_message:
        return await message.reply("<b>❌ Reply to a message to broadcast to all multi-system users.</b>")

    b = await message.reply("<b>⏳ Broadcasting to multi-system users…</b>")
    users = await _registry.get_all_users()
    ok = fail = 0
    for uid in users:
        try:
            await message.reply_to_message.copy(uid)
            ok += 1
            await asyncio.sleep(0.05)
        except Exception:
            fail += 1

    await b.edit(
        f"<b>✅ Broadcast Done</b>\n\n"
        f"<b>Total:</b> {len(users)}\n"
        f"<b>Success:</b> {ok}  <b>Failed:</b> {fail}"
    )


# ── /check ────────────────────────────────────────────────────────────────────

@Client.on_message(filters.command("check") & filters.private & filters.user(OWNER_ID))
async def check_cmd(client: Client, message: Message):
    from multi.engine import worker_engine
    from multi.security import mask_token, decrypt_token

    bots = await _registry.get_all_active_bots()
    if not bots:
        return await message.reply("<b>📭 No registered bots.</b>")

    lines = [f"<b>🤖 Registered Bots ({len(bots)})</b>\n"]
    for bot in bots:
        bid   = bot["_id"]
        live  = worker_engine.get_worker(bid) is not None
        icon  = "🟢" if live else "🔴"
        uname = bot.get("bot_username", "?")
        owner = bot.get("owner_id", "?")
        try:
            raw = decrypt_token(bot.get("bot_token_encrypted", ""))
            tok = mask_token(raw)
        except Exception:
            tok = "⚠️ decrypt error"
        lines.append(
            f"{icon} @{uname}\n"
            f"  ID: <code>{bid}</code>  Owner: <code>{owner}</code>\n"
            f"  Token: <code>{tok}</code>\n"
            f"  Channel: <code>{bot.get('log_channel_id', '?')}</code>\n"
        )

    # Split into chunks of 10 to avoid message-too-long errors
    chunk = []
    for line in lines:
        chunk.append(line)
        if len(chunk) >= 11:
            await message.reply("\n".join(chunk))
            chunk = []
    if chunk:
        await message.reply("\n".join(chunk))


# ── /sysstats ─────────────────────────────────────────────────────────────────

@Client.on_message(filters.command("sysstats") & filters.private & filters.user(OWNER_ID))
async def sysstats_cmd(client: Client, message: Message):
    from multi.engine import worker_engine

    total_users = await _registry.total_users()
    all_bots    = await _registry.get_all_active_bots()
    running     = worker_engine.active_count

    try:
        import psutil
        proc = psutil.Process()
        mem_mb = proc.memory_info().rss / 1024 / 1024
        mem_txt = f"{mem_mb:.1f} MB"
    except Exception:
        mem_txt = "N/A"

    await message.reply(
        f"<b>━━━━━━━━━━━━━━━━━━━━━\n📊 𝗦𝗬𝗦𝗧𝗘𝗠 𝗦𝗧𝗔𝗧𝗦\n━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        f"<blockquote>"
        f"◈ <b>Multi Users:</b> {total_users}\n"
        f"◈ <b>Total Bots:</b> {len(all_bots)}\n"
        f"◈ <b>Running Bots:</b> {running}\n"
        f"◈ <b>Memory:</b> {mem_txt}"
        f"</blockquote>"
    )
