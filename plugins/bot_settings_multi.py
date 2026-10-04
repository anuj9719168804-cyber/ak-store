"""Per-bot settings panel for the multi-user system.

Ported from Multi-FileStoreBot main_bot/plugins/bot_settings.py.
All DB imports use multi.registry instead of Multi's database layer.
"""
import logging
import re

from pyrogram import Client, filters
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from config import API_ID, API_HASH
from multi.helpers import upload_to_telegraph
from multi.registry import RegistryDB, WorkerDB
from multi.security import encrypt_token, decrypt_token, mask_api_key

log = logging.getLogger(__name__)
_registry = RegistryDB()


def _state():
    from plugins.create_bot import _creation_state
    return _creation_state


async def _verify(query: CallbackQuery, bot_id: int):
    bot = await _registry.get_bot(bot_id)
    if not bot or bot["owner_id"] != query.from_user.id:
        await query.answer("❌ Access denied!", show_alert=True)
        return None
    return bot


def _bid(pat: str, data: str) -> int:
    return int(re.match(pat, data).group(1))


async def _restart(bot_id: int):
    from multi.engine import worker_engine
    try:
        await worker_engine.stop_worker(bot_id)
        doc = await _registry.get_bot(bot_id)
        await worker_engine.start_worker(doc)
    except Exception as e:
        log.error(f"restart_worker {bot_id}: {e}")


# ═══════════════════════════════════════════════════════════════════
# LOG CHANNEL
# ═══════════════════════════════════════════════════════════════════

@Client.on_callback_query(filters.regex(r"^set_channel_(\d+)$"))
async def set_channel_cb(client: Client, query: CallbackQuery):
    bot_id = _bid(r"^set_channel_(\d+)$", query.data)
    bot = await _verify(query, bot_id)
    if not bot:
        return
    _state()[query.from_user.id] = {"step": "awaiting_new_log_channel", "data": {"bot_id": bot_id}}
    await query.message.edit_text(
        f"<b>📢 Set Log Channel</b>\n\n"
        f"<blockquote>Current: <code>{bot.get('log_channel_id','?')}</code>\n\n"
        f"Send the new channel ID.\n"
        f"Make sure @{bot.get('bot_username','')} is admin there.</blockquote>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"dashboard_{bot_id}")]]),
    )
    await query.answer()


async def handle_log_channel_input(client: Client, message: Message, state: dict):
    uid = message.from_user.id
    bot_id = state["data"]["bot_id"]
    try:
        channel_id = int(message.text.strip())
    except ValueError:
        await message.reply("<b>❌ Invalid ID. Send like <code>-1001234567890</code></b>")
        return
    bot = await _registry.get_bot(bot_id)
    token = decrypt_token(bot["bot_token_encrypted"])
    try:
        tmp = Client(f"verify_{bot_id}", api_id=API_ID, api_hash=API_HASH, bot_token=token, in_memory=True)
        await tmp.start()
        t = await tmp.send_message(channel_id, "✅ Channel verified.")
        await t.delete()
        await tmp.stop()
    except Exception as e:
        await message.reply(f"<b>❌ Cannot access channel!</b>\n<code>{str(e)[:100]}</code>")
        return
    await _registry.update_log_channel(bot_id, channel_id)
    _state().pop(uid, None)
    await _restart(bot_id)
    await message.reply(
        f"<b>✅ Log channel updated to <code>{channel_id}</code></b>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Dashboard", callback_data=f"dashboard_{bot_id}")]]),
    )


# ═══════════════════════════════════════════════════════════════════
# AUTO-DELETE
# ═══════════════════════════════════════════════════════════════════

@Client.on_callback_query(filters.regex(r"^auto_delete_(\d+)$"))
async def auto_delete_cb(client: Client, query: CallbackQuery):
    bot_id = _bid(r"^auto_delete_(\d+)$", query.data)
    bot = await _verify(query, bot_id)
    if not bot:
        return
    _state().pop(query.from_user.id, None)
    cur = await WorkerDB(bot_id).get_del_timer()
    cur_txt = f"{cur}s" if cur else "Disabled"
    await query.message.edit_text(
        f"<b>⏱ Auto-Delete</b>\n\n<blockquote>Current: <b>{cur_txt}</b></blockquote>",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("5 min",  callback_data=f"setdel_{bot_id}_300"),
                InlineKeyboardButton("30 min", callback_data=f"setdel_{bot_id}_1800"),
                InlineKeyboardButton("1 hr",   callback_data=f"setdel_{bot_id}_3600"),
            ],
            [
                InlineKeyboardButton("6 hr",   callback_data=f"setdel_{bot_id}_21600"),
                InlineKeyboardButton("12 hr",  callback_data=f"setdel_{bot_id}_43200"),
                InlineKeyboardButton("24 hr",  callback_data=f"setdel_{bot_id}_86400"),
            ],
            [
                InlineKeyboardButton("❌ Disable", callback_data=f"setdel_{bot_id}_0"),
                InlineKeyboardButton("✏️ Custom",  callback_data=f"customdel_{bot_id}"),
            ],
            [InlineKeyboardButton("🔙 Back", callback_data=f"dashboard_{bot_id}")],
        ]),
    )
    await query.answer()


@Client.on_callback_query(filters.regex(r"^setdel_(\d+)_(\d+)$"))
async def setdel_cb(client: Client, query: CallbackQuery):
    m = re.match(r"^setdel_(\d+)_(\d+)$", query.data)
    bot_id, secs = int(m.group(1)), int(m.group(2))
    if not await _verify(query, bot_id):
        return
    await WorkerDB(bot_id).set_del_timer(secs)
    await query.answer(f"✅ Auto-delete: {secs}s" if secs else "✅ Disabled", show_alert=True)
    await auto_delete_cb(client, query)


@Client.on_callback_query(filters.regex(r"^customdel_(\d+)$"))
async def customdel_cb(client: Client, query: CallbackQuery):
    bot_id = _bid(r"^customdel_(\d+)$", query.data)
    if not await _verify(query, bot_id):
        return
    _state()[query.from_user.id] = {"step": "awaiting_auto_delete_time", "data": {"bot_id": bot_id}}
    await query.message.edit_text(
        "<b>✏️ Custom Auto-Delete</b>\n\n<blockquote>Send time in <b>seconds</b>. Example: <code>600</code></blockquote>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"auto_delete_{bot_id}")]]),
    )
    await query.answer()


async def handle_auto_delete_input(client: Client, message: Message, state: dict):
    uid = message.from_user.id
    bot_id = state["data"]["bot_id"]
    try:
        secs = int(message.text.strip())
        if secs < 0:
            raise ValueError
    except ValueError:
        await message.reply("<b>❌ Send a valid number (0 = disable).</b>")
        return
    await WorkerDB(bot_id).set_del_timer(secs)
    _state().pop(uid, None)
    txt = f"{secs}s" if secs else "disabled"
    await message.reply(
        f"<b>✅ Auto-delete: {txt}</b>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=f"dashboard_{bot_id}")]]),
    )


# ═══════════════════════════════════════════════════════════════════
# FORCE SUBSCRIBE
# ═══════════════════════════════════════════════════════════════════

@Client.on_callback_query(filters.regex(r"^fsub_(\d+)$"))
async def fsub_cb(client: Client, query: CallbackQuery):
    bot_id = _bid(r"^fsub_(\d+)$", query.data)
    bot = await _verify(query, bot_id)
    if not bot:
        return
    _state().pop(query.from_user.id, None)
    wdb = WorkerDB(bot_id)
    channels = await wdb.show_channels()
    if channels:
        lines = ""
        for i, cid in enumerate(channels, 1):
            mode = await wdb.get_channel_mode(cid)
            lines += f"  {i}. <code>{cid}</code> — {'📩 Request' if mode=='on' else '🔒 Force Join'}\n"
    else:
        lines = "  <i>None added</i>\n"
    await query.message.edit_text(
        f"<b>🔒 Force Subscribe</b>\n\n<blockquote><b>Channels:</b>\n{lines}</blockquote>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add",      callback_data=f"add_fsub_{bot_id}")],
            [InlineKeyboardButton("➖ Remove",   callback_data=f"rem_fsub_{bot_id}")],
            [InlineKeyboardButton("🔄 Mode",    callback_data=f"toggle_fsub_{bot_id}")],
            [InlineKeyboardButton("🔙 Back",    callback_data=f"dashboard_{bot_id}")],
        ]),
    )
    await query.answer()


@Client.on_callback_query(filters.regex(r"^add_fsub_(\d+)$"))
async def add_fsub_cb(client: Client, query: CallbackQuery):
    bot_id = _bid(r"^add_fsub_(\d+)$", query.data)
    bot = await _verify(query, bot_id)
    if not bot:
        return
    _state()[query.from_user.id] = {"step": "awaiting_fsub_channel", "data": {"bot_id": bot_id, "action": "add"}}
    await query.message.edit_text(
        f"<b>➕ Add Force-Sub Channel</b>\n\n"
        f"<blockquote>Send channel ID.\nMake sure @{bot.get('bot_username','')} is admin.\nExample: <code>-1001234567890</code></blockquote>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"fsub_{bot_id}")]]),
    )
    await query.answer()


@Client.on_callback_query(filters.regex(r"^rem_fsub_(\d+)$"))
async def rem_fsub_cb(client: Client, query: CallbackQuery):
    bot_id = _bid(r"^rem_fsub_(\d+)$", query.data)
    if not await _verify(query, bot_id):
        return
    channels = await WorkerDB(bot_id).show_channels()
    if not channels:
        await query.answer("No channels!", show_alert=True)
        return
    btns = [[InlineKeyboardButton(f"🗑 {cid}", callback_data=f"do_rem_fsub_{bot_id}_{cid}")] for cid in channels]
    btns.append([InlineKeyboardButton("🔙 Back", callback_data=f"fsub_{bot_id}")])
    await query.message.edit_text("<b>➖ Remove Channel</b>\n\n<blockquote>Select one:</blockquote>",
                                  reply_markup=InlineKeyboardMarkup(btns))
    await query.answer()


@Client.on_callback_query(filters.regex(r"^do_rem_fsub_(\d+)_(-?\d+)$"))
async def do_rem_fsub_cb(client: Client, query: CallbackQuery):
    m = re.match(r"^do_rem_fsub_(\d+)_(-?\d+)$", query.data)
    bot_id, cid = int(m.group(1)), int(m.group(2))
    if not await _verify(query, bot_id):
        return
    await WorkerDB(bot_id).rem_channel(cid)
    await query.answer(f"✅ {cid} removed!", show_alert=True)
    await fsub_cb(client, query)


@Client.on_callback_query(filters.regex(r"^toggle_fsub_(\d+)$"))
async def toggle_fsub_cb(client: Client, query: CallbackQuery):
    bot_id = _bid(r"^toggle_fsub_(\d+)$", query.data)
    if not await _verify(query, bot_id):
        return
    wdb = WorkerDB(bot_id)
    channels = await wdb.show_channels()
    if not channels:
        await query.answer("No channels!", show_alert=True)
        return
    btns = []
    for cid in channels:
        mode = await wdb.get_channel_mode(cid)
        label = "Request → Force" if mode == "on" else "Force → Request"
        btns.append([InlineKeyboardButton(f"🔄 {cid} ({label})", callback_data=f"do_toggle_{bot_id}_{cid}")])
    btns.append([InlineKeyboardButton("🔙 Back", callback_data=f"fsub_{bot_id}")])
    await query.message.edit_text(
        "<b>🔄 Toggle Mode</b>\n\n<blockquote>Force Join: user must join.\nRequest: user sends join request.</blockquote>",
        reply_markup=InlineKeyboardMarkup(btns),
    )
    await query.answer()


@Client.on_callback_query(filters.regex(r"^do_toggle_(\d+)_(-?\d+)$"))
async def do_toggle_fsub_cb(client: Client, query: CallbackQuery):
    m = re.match(r"^do_toggle_(\d+)_(-?\d+)$", query.data)
    bot_id, cid = int(m.group(1)), int(m.group(2))
    if not await _verify(query, bot_id):
        return
    wdb = WorkerDB(bot_id)
    cur = await wdb.get_channel_mode(cid)
    new = "off" if cur == "on" else "on"
    await wdb.set_channel_mode(cid, new)
    await query.answer(f"✅ {'Request' if new=='on' else 'Force Join'} mode!", show_alert=True)
    await fsub_cb(client, query)


async def handle_fsub_channel_input(client: Client, message: Message, state: dict):
    uid = message.from_user.id
    bot_id = state["data"]["bot_id"]
    try:
        cid = int(message.text.strip())
    except ValueError:
        await message.reply("<b>❌ Invalid ID.</b>")
        return
    st = await message.reply("<b>⏳ Verifying…</b>")
    bot = await _registry.get_bot(bot_id)
    token = decrypt_token(bot["bot_token_encrypted"])
    try:
        tmp = Client(f"verify_fsub_{bot_id}", api_id=API_ID, api_hash=API_HASH, bot_token=token, in_memory=True)
        await tmp.start()
        await tmp.get_chat(cid)
        inv = await tmp.create_chat_invite_link(cid, creates_join_request=True)
        await tmp.revoke_chat_invite_link(cid, inv.invite_link)
        await tmp.stop()
    except Exception as e:
        await st.edit_text(
            f"<b>❌ Verification Failed!</b>\n\n"
            f"<blockquote>Ensure bot is admin with Invite rights.\n\nError: <code>{str(e)[:100]}</code></blockquote>",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=f"fsub_{bot_id}")]]),
        )
        return
    await WorkerDB(bot_id).add_channel(cid, mode="off")
    await _restart(bot_id)
    _state().pop(uid, None)
    await st.edit_text(
        f"<b>✅ Channel <code>{cid}</code> added (Force Join mode)!</b>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=f"fsub_{bot_id}")]]),
    )


# ═══════════════════════════════════════════════════════════════════
# SHORTENER
# ═══════════════════════════════════════════════════════════════════

@Client.on_callback_query(filters.regex(r"^shortener_(\d+)$"))
async def shortener_cb(client: Client, query: CallbackQuery):
    bot_id = _bid(r"^shortener_(\d+)$", query.data)
    bot = await _verify(query, bot_id)
    if not bot:
        return
    _state().pop(query.from_user.id, None)
    sh = bot.get("shortener", {})
    enabled = sh.get("enabled", False)
    domain  = sh.get("domain", "") or "ɴᴏᴛ sᴇᴛ"
    _raw_key = sh.get("api_key_encrypted", "")
    masked  = mask_api_key(decrypt_token(_raw_key) if _raw_key else "")
    expire  = sh.get("verify_expire", 86400) // 3600
    tut_on  = sh.get("tutorial_enabled", False)
    tut_set = "sᴇᴛ" if sh.get("tutorial_link") else "ɴᴏᴛ sᴇᴛ"

    await query.message.edit_text(
        f"<b>━━━━━━━━━━━━━━━━━━━━━\n🔗 𝗦𝗛𝗢𝗥𝗧𝗘𝗡𝗘𝗥\n━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        f"<blockquote>"
        f"◈ <b>sᴛᴀᴛᴜs:</b> {'✅' if enabled else '❌'}\n"
        f"◈ <b>ᴅᴏᴍᴀɪɴ:</b> {domain}\n"
        f"◈ <b>ᴀᴘɪ ᴋᴇʏ:</b> {masked}\n"
        f"◈ <b>ᴇxᴘɪʀʏ:</b> {expire}h\n"
        f"◈ <b>ᴛᴜᴛᴏʀɪᴀʟ:</b> {'✅' if tut_on else '❌'}  ({tut_set})"
        f"</blockquote>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ ᴅɪsᴀʙʟᴇ" if enabled else "✅ ᴇɴᴀʙʟᴇ", callback_data=f"short_toggle_{bot_id}")],
            [
                InlineKeyboardButton("🌐 ᴅᴏᴍᴀɪɴ",   callback_data=f"short_domain_{bot_id}"),
                InlineKeyboardButton("🔑 ᴀᴘɪ ᴋᴇʏ",  callback_data=f"short_api_{bot_id}"),
            ],
            [
                InlineKeyboardButton("⏱ ᴇxᴘɪʀʏ",    callback_data=f"short_expire_{bot_id}"),
                InlineKeyboardButton("📹 ᴛᴜᴛ " + ("ᴏꜰꜰ" if tut_on else "ᴏɴ"), callback_data=f"short_tuttoggle_{bot_id}"),
            ],
            [InlineKeyboardButton("📹 sᴇᴛ ᴛᴜᴛᴏʀɪᴀʟ", callback_data=f"short_tutorial_{bot_id}")],
            [InlineKeyboardButton("🔙 ʙᴀᴄᴋ",          callback_data=f"dashboard_{bot_id}")],
        ]),
    )
    await query.answer()


@Client.on_callback_query(filters.regex(r"^short_toggle_(\d+)$"))
async def short_toggle_cb(client: Client, query: CallbackQuery):
    bot_id = _bid(r"^short_toggle_(\d+)$", query.data)
    bot = await _verify(query, bot_id)
    if not bot:
        return
    cur = bot.get("shortener", {}).get("enabled", False)
    await _registry.update_shortener(bot_id, "enabled", not cur)
    await query.answer(f"🔗 Shortener {'disabled' if cur else 'enabled'}!", show_alert=True)
    await shortener_cb(client, query)


@Client.on_callback_query(filters.regex(r"^short_tuttoggle_(\d+)$"))
async def short_tuttoggle_cb(client: Client, query: CallbackQuery):
    bot_id = _bid(r"^short_tuttoggle_(\d+)$", query.data)
    bot = await _verify(query, bot_id)
    if not bot:
        return
    cur = bot.get("shortener", {}).get("tutorial_enabled", False)
    await _registry.update_shortener(bot_id, "tutorial_enabled", not cur)
    await query.answer(f"📹 Tutorial {'off' if cur else 'on'}!", show_alert=True)
    await shortener_cb(client, query)


def _short_state(bot_id: int, action: str, uid: int):
    _state()[uid] = {"step": "settings", "action": action, "data": {"bot_id": bot_id}}


@Client.on_callback_query(filters.regex(r"^short_domain_(\d+)$"))
async def short_domain_cb(client: Client, query: CallbackQuery):
    bot_id = _bid(r"^short_domain_(\d+)$", query.data)
    if not await _verify(query, bot_id):
        return
    _short_state(bot_id, "short_domain", query.from_user.id)
    await query.message.edit_text(
        "<b>🌐 Set Domain</b>\n\n<blockquote>Example: <code>example.com</code></blockquote>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"shortener_{bot_id}")]]),
    )
    await query.answer()


@Client.on_callback_query(filters.regex(r"^short_api_(\d+)$"))
async def short_api_cb(client: Client, query: CallbackQuery):
    bot_id = _bid(r"^short_api_(\d+)$", query.data)
    if not await _verify(query, bot_id):
        return
    _short_state(bot_id, "short_api", query.from_user.id)
    await query.message.edit_text(
        "<b>🔑 Set API Key</b>\n\n<blockquote>Send your shortener API key.</blockquote>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"shortener_{bot_id}")]]),
    )
    await query.answer()


@Client.on_callback_query(filters.regex(r"^short_expire_(\d+)$"))
async def short_expire_cb(client: Client, query: CallbackQuery):
    bot_id = _bid(r"^short_expire_(\d+)$", query.data)
    bot = await _verify(query, bot_id)
    if not bot:
        return
    cur = bot.get("shortener", {}).get("verify_expire", 86400) // 3600
    _short_state(bot_id, "short_expire", query.from_user.id)
    await query.message.edit_text(
        f"<b>⏱ Set Verify Expiry</b>\n\n<blockquote>Current: <b>{cur}h</b>\nSend new value in hours (1-720).</blockquote>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"shortener_{bot_id}")]]),
    )
    await query.answer()


@Client.on_callback_query(filters.regex(r"^short_tutorial_(\d+)$"))
async def short_tutorial_cb(client: Client, query: CallbackQuery):
    bot_id = _bid(r"^short_tutorial_(\d+)$", query.data)
    if not await _verify(query, bot_id):
        return
    _short_state(bot_id, "short_tutorial", query.from_user.id)
    await query.message.edit_text(
        "<b>📹 Set Tutorial Link</b>\n\n<blockquote>Any video link. Send <code>0</code> to remove.</blockquote>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"shortener_{bot_id}")]]),
    )
    await query.answer()


async def handle_shortener_input(client: Client, message: Message, state: dict, field: str = None):
    """Process shortener text inputs (called from create_bot.py dispatch)."""
    uid = message.from_user.id
    bot_id = state["data"]["bot_id"]
    action = field or state.get("action", "")
    text = (message.text or "").strip()
    if not text:
        await message.reply("<b>❌ Please send text.</b>")
        return

    back_cb = f"shortener_{bot_id}"

    if action in ("short_domain", "domain"):
        await _registry.update_shortener(bot_id, "domain", text)
        msg = "✅ Domain updated!"
    elif action in ("short_api", "api_key"):
        await _registry.update_shortener(bot_id, "api_key_encrypted", encrypt_token(text))
        msg = f"✅ API key set: {mask_api_key(text)}"
    elif action == "short_expire":
        try:
            hrs = int(text)
            if not 1 <= hrs <= 720:
                raise ValueError
            await _registry.update_shortener(bot_id, "verify_expire", hrs * 3600)
            msg = f"✅ Expiry: {hrs}h"
        except ValueError:
            await message.reply("<b>❌ Send 1-720 hours.</b>")
            return
    elif action == "short_tutorial":
        await _registry.update_shortener(bot_id, "tutorial_link", "" if text == "0" else text)
        msg = "✅ Tutorial updated!"
    else:
        msg = "❌ Unknown field"

    await _restart(bot_id)
    _state().pop(uid, None)
    await message.reply(
        f"<b>{msg}</b>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=back_cb)]]),
    )


# ═══════════════════════════════════════════════════════════════════
# ADMINS
# ═══════════════════════════════════════════════════════════════════

@Client.on_callback_query(filters.regex(r"^admins_(\d+)$"))
async def admins_cb(client: Client, query: CallbackQuery):
    bot_id = _bid(r"^admins_(\d+)$", query.data)
    bot = await _verify(query, bot_id)
    if not bot:
        return
    _state().pop(query.from_user.id, None)
    admins = await WorkerDB(bot_id).get_all_admins()
    admin_list = "\n".join(f"  • <code>{a}</code>" for a in admins) or "  <i>None (owner has full access)</i>"
    await query.message.edit_text(
        f"<b>👥 Admins</b>\n\n"
        f"<blockquote><b>Owner:</b> <code>{bot['owner_id']}</code> (always)\n\n"
        f"<b>Additional:</b>\n{admin_list}</blockquote>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add",    callback_data=f"add_admin_{bot_id}")],
            [InlineKeyboardButton("➖ Remove", callback_data=f"rem_admin_{bot_id}")],
            [InlineKeyboardButton("🔙 Back",  callback_data=f"dashboard_{bot_id}")],
        ]),
    )
    await query.answer()


@Client.on_callback_query(filters.regex(r"^add_admin_(\d+)$"))
async def add_admin_cb(client: Client, query: CallbackQuery):
    bot_id = _bid(r"^add_admin_(\d+)$", query.data)
    if not await _verify(query, bot_id):
        return
    _state()[query.from_user.id] = {"step": "awaiting_admin_id", "data": {"bot_id": bot_id, "action": "add"}}
    await query.message.edit_text(
        "<b>➕ Add Admin</b>\n\n<blockquote>Send user ID. Example: <code>123456789</code></blockquote>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"admins_{bot_id}")]]),
    )
    await query.answer()


@Client.on_callback_query(filters.regex(r"^rem_admin_(\d+)$"))
async def rem_admin_cb(client: Client, query: CallbackQuery):
    bot_id = _bid(r"^rem_admin_(\d+)$", query.data)
    if not await _verify(query, bot_id):
        return
    admins = await WorkerDB(bot_id).get_all_admins()
    if not admins:
        await query.answer("No admins!", show_alert=True)
        return
    btns = [[InlineKeyboardButton(f"🗑 {a}", callback_data=f"do_rem_admin_{bot_id}_{a}")] for a in admins]
    btns.append([InlineKeyboardButton("🔙 Back", callback_data=f"admins_{bot_id}")])
    await query.message.edit_text("<b>➖ Remove Admin</b>\n\n<blockquote>Select:</blockquote>",
                                  reply_markup=InlineKeyboardMarkup(btns))
    await query.answer()


@Client.on_callback_query(filters.regex(r"^do_rem_admin_(\d+)_(\d+)$"))
async def do_rem_admin_cb(client: Client, query: CallbackQuery):
    m = re.match(r"^do_rem_admin_(\d+)_(\d+)$", query.data)
    bot_id, admin_id = int(m.group(1)), int(m.group(2))
    if not await _verify(query, bot_id):
        return
    await WorkerDB(bot_id).del_admin(admin_id)
    await query.answer(f"✅ {admin_id} removed!", show_alert=True)
    await admins_cb(client, query)


async def handle_admin_input(client: Client, message: Message, state: dict):
    uid = message.from_user.id
    bot_id = state["data"]["bot_id"]
    try:
        admin_id = int(message.text.strip())
    except ValueError:
        await message.reply("<b>❌ Invalid ID.</b>")
        return
    await WorkerDB(bot_id).add_admin(admin_id)
    _state().pop(uid, None)
    await message.reply(
        f"<b>✅ Admin <code>{admin_id}</code> added!</b>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=f"admins_{bot_id}")]]),
    )


# ═══════════════════════════════════════════════════════════════════
# STATISTICS
# ═══════════════════════════════════════════════════════════════════

@Client.on_callback_query(filters.regex(r"^stats_(\d+)$"))
async def stats_cb(client: Client, query: CallbackQuery):
    bot_id = _bid(r"^stats_(\d+)$", query.data)
    bot = await _verify(query, bot_id)
    if not bot:
        return
    wdb = WorkerDB(bot_id)
    total  = await wdb.total_users()
    admins = len(await wdb.get_all_admins())
    chans  = len(await wdb.show_channels())
    banned = len(await wdb.get_ban_users())
    ca = bot.get("created_at", "?")
    if hasattr(ca, "strftime"):
        ca = ca.strftime("%Y-%m-%d %H:%M UTC")
    try:
        await query.message.edit_text(
            f"<b>━━━━━━━━━━━━━━━━━━━━━\n📊 𝗦𝗧𝗔𝗧𝗦\n━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
            f"<blockquote>"
            f"◈ <b>ʙᴏᴛ:</b> @{bot.get('bot_username','?')}\n"
            f"◈ <b>ᴄʀᴇᴀᴛᴇᴅ:</b> {ca}\n\n"
            f"👥 <b>ᴜsᴇʀs:</b> {total}\n"
            f"👨‍💼 <b>ᴀᴅᴍɪɴs:</b> {admins}\n"
            f"📢 <b>ꜰsᴜʙ ᴄʜs:</b> {chans}\n"
            f"🚫 <b>ʙᴀɴɴᴇᴅ:</b> {banned}"
            f"</blockquote>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Refresh", callback_data=f"stats_{bot_id}")],
                [InlineKeyboardButton("🔙 Back",    callback_data=f"dashboard_{bot_id}")],
            ]),
        )
    except Exception:
        pass
    await query.answer()


# ═══════════════════════════════════════════════════════════════════
# START CONFIG
# ═══════════════════════════════════════════════════════════════════

@Client.on_callback_query(filters.regex(r"^startcfg_(\d+)$"))
async def startcfg_cb(client: Client, query: CallbackQuery):
    bot_id = _bid(r"^startcfg_(\d+)$", query.data)
    bot = await _verify(query, bot_id)
    if not bot:
        return
    _state().pop(query.from_user.id, None)
    s = bot.get("settings", {})
    sm = (s.get("start_message", "") or "ᴅᴇꜰᴀᴜʟᴛ")[:47] + ("…" if len(s.get("start_message",""))>47 else "")
    sp = s.get("start_pic", "") or "ɴᴏɴᴇ"
    await query.message.edit_text(
        f"<b>━━━━━━━━━━━━━━━━━━━━━\n📩 𝗦𝗧𝗔𝗥𝗧 𝗖𝗢𝗡𝗙𝗜𝗚\n━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        f"<blockquote>◈ <b>ᴍᴇssᴀɢᴇ:</b>\n{sm}\n\n◈ <b>ᴘʜᴏᴛᴏ:</b> {sp}</blockquote>",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📝 ᴍᴇssᴀɢᴇ", callback_data=f"set_startmsg_{bot_id}"),
                InlineKeyboardButton("🖼 ᴘʜᴏᴛᴏ",   callback_data=f"set_startpic_{bot_id}"),
            ],
            [InlineKeyboardButton("🔙 ʙᴀᴄᴋ", callback_data=f"dashboard_{bot_id}")],
        ]),
    )
    await query.answer()


@Client.on_callback_query(filters.regex(r"^set_startmsg_(\d+)$"))
async def set_startmsg_cb(client: Client, query: CallbackQuery):
    bot_id = _bid(r"^set_startmsg_(\d+)$", query.data)
    if not await _verify(query, bot_id):
        return
    _state()[query.from_user.id] = {"step": "settings", "action": "set_startmsg", "data": {"bot_id": bot_id}}
    await query.message.edit_text(
        "<b>📝 Send Start Message</b>\n\n<i>HTML supported. Placeholders: {mention} {first} {id} {bot_mention}</i>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"startcfg_{bot_id}")]]),
    )
    await query.answer()


@Client.on_callback_query(filters.regex(r"^set_startpic_(\d+)$"))
async def set_startpic_cb(client: Client, query: CallbackQuery):
    bot_id = _bid(r"^set_startpic_(\d+)$", query.data)
    if not await _verify(query, bot_id):
        return
    _state()[query.from_user.id] = {"step": "settings", "action": "set_startpic", "data": {"bot_id": bot_id}}
    await query.message.edit_text(
        "<b>🖼 Send Start Photo</b>\n\n<blockquote>Send a photo OR a direct image URL.\nSend <code>0</code> to remove.</blockquote>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"startcfg_{bot_id}")]]),
    )
    await query.answer()


@Client.on_callback_query(filters.regex(r"^captioncfg_(\d+)$"))
async def captioncfg_cb(client: Client, query: CallbackQuery):
    bot_id = _bid(r"^captioncfg_(\d+)$", query.data)
    if not await _verify(query, bot_id):
        return
    _state()[query.from_user.id] = {"step": "settings", "action": "set_custom_caption", "data": {"bot_id": bot_id}}
    await query.message.edit_text(
        "<b>📝 Custom Caption</b>\n\n"
        "<blockquote>Appended below existing file caption.\n"
        "Placeholders: <code>{size}</code> <code>{name}</code> <code>{language}</code>\n\n"
        "Send <code>0</code> to remove.</blockquote>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"dashboard_{bot_id}")]]),
    )
    await query.answer()


async def handle_startcfg_input(client: Client, message: Message, state: dict):
    uid    = message.from_user.id
    bot_id = state["data"]["bot_id"]
    action = state.get("action", "")

    if action == "set_startmsg":
        txt = message.text
        if not txt:
            await message.reply("<b>❌ Send text.</b>")
            return
        await _registry.update_setting(bot_id, "start_message", "" if txt.strip()=="0" else txt)
        reply = "✅ Start message updated!"
        back  = f"startcfg_{bot_id}"

    elif action == "set_startpic":
        if message.photo or message.document:
            url = await upload_to_telegraph(client, message)
            if not url:
                return
        elif message.text:
            url = "" if message.text.strip()=="0" else message.text.strip()
        else:
            await message.reply("<b>❌ Send a photo or link.</b>")
            return
        await _registry.update_setting(bot_id, "start_pic", url)
        reply = "✅ Start photo updated!"
        back  = f"startcfg_{bot_id}"

    elif action == "set_custom_caption":
        txt = message.text.html if message.text else ""
        if not txt:
            await message.reply("<b>❌ Send text.</b>")
            return
        await _registry.update_setting(bot_id, "custom_caption", "" if txt.strip()=="0" else txt)
        reply = "✅ Caption updated!"
        back  = f"dashboard_{bot_id}"
    else:
        reply = "❌ Unknown action."
        back  = f"dashboard_{bot_id}"

    await _restart(bot_id)
    _state().pop(uid, None)
    await message.reply(
        f"<b>{reply}</b>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=back)]]),
    )
