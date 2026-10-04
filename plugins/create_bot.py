"""Bot creation flow for the multi-user bot creation system.

Ported from Multi-FileStoreBot main_bot/plugins/create_bot.py.
Users interact with the Pro controller bot to create their own file-store bots.
"""
import asyncio
import logging
from datetime import datetime, timezone

from pyrogram import Client, filters
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from config import API_ID, API_HASH, MAX_BOTS_PER_USER, BOT_CREATION_COOLDOWN
from multi.helpers import validate_bot_token, send_main_log
from multi.registry import RegistryDB
from multi.security import encrypt_token

log = logging.getLogger(__name__)
_registry = RegistryDB()

# Shared state dict used by bot_settings_multi.py as well
_creation_state: dict[int, dict] = {}   # user_id → {"step": str, "data": dict, "action": str}


# ── Entry: /bots ──────────────────────────────────────────────────────────────

@Client.on_message(filters.command("bots") & filters.private)
async def multi_menu_cmd(client: Client, message: Message):
    """Open the multi-bot menu via /bots command."""
    uid = message.from_user.id
    _creation_state.pop(uid, None)
    # Register user on first visit
    await _registry.add_user(uid)
    # Ban check
    if await _registry.ban_user_exist(uid):
        await message.reply(
            "<b>⛔ Access Denied</b>\n\n"
            "<blockquote>You have been banned from the multi-bot system.</blockquote>"
        )
        return
    await _show_main_menu(client, message.from_user, reply_to=message)


async def _show_main_menu(client, user, *, reply_to=None, edit_msg=None):
    count = await _registry.count_user_bots(user.id)
    from config import MAX_BOTS_PER_USER as MB
    text = (
        "<b>━━━━━━━━━━━━━━━━━━━━━\n"
        "🤖 𝗠𝗨𝗟𝗧𝗜-𝗕𝗢𝗧 𝗠𝗘𝗡𝗨\n"
        "━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        f"<blockquote>ʜᴇʏ {user.mention}!\n\n"
        f"◈ <b>ʏᴏᴜʀ ʙᴏᴛs:</b> {count} / {MB}\n\n"
        "ᴄʀᴇᴀᴛᴇ ʏᴏᴜʀ ᴏᴡɴ ꜰɪʟᴇ-sᴛᴏʀᴇ ʙᴏᴛ ᴏʀ ᴍᴀɴᴀɢᴇ ᴇxɪsᴛɪɴɢ ᴏɴᴇs.</blockquote>"
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚡ ᴄʀᴇᴀᴛᴇ ʙᴏᴛ", callback_data="create_bot"),
            InlineKeyboardButton("📋 ᴍʏ ʙᴏᴛs",    callback_data="my_bots"),
        ],
    ])
    if edit_msg:
        try:
            await edit_msg.edit_text(text, reply_markup=kb)
        except Exception:
            pass
    elif reply_to:
        await reply_to.reply(text, reply_markup=kb)


# ── Callback: back to multi menu ──────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^back_menu$"))
async def back_menu_cb(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    _creation_state.pop(uid, None)
    await _show_main_menu(client, query.from_user, edit_msg=query.message)
    await query.answer()


# ── Callback: create_bot ──────────────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^create_bot$"))
async def create_bot_cb(client: Client, query: CallbackQuery):
    uid = query.from_user.id

    # Banned users must not get in through an old menu message either
    if await _registry.ban_user_exist(uid):
        await query.answer("⛔ You are banned from the multi-bot system.", show_alert=True)
        return

    # Limit check
    count = await _registry.count_user_bots(uid)
    if count >= MAX_BOTS_PER_USER:
        await query.answer(
            f"❌ Limit reached: {MAX_BOTS_PER_USER} bots max!", show_alert=True
        )
        return

    # Cooldown check
    last = await _registry.get_cooldown(uid)
    if last:
        elapsed = (datetime.now(timezone.utc) - last.replace(tzinfo=timezone.utc)).total_seconds()
        if elapsed < BOT_CREATION_COOLDOWN:
            await query.answer(
                f"⏳ Wait {int(BOT_CREATION_COOLDOWN - elapsed)}s before creating another bot.",
                show_alert=True,
            )
            return

    _creation_state[uid] = {"step": "awaiting_token", "data": {}}

    await query.message.edit_text(
        "<b>🤖 Create a New Bot</b>\n\n"
        "<blockquote><b>Step 1/2:</b> Send your bot token.\n\n"
        "Get one from @BotFather.\n"
        "Example: <code>123456:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw</code></blockquote>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_creation")],
        ]),
    )
    await query.answer()


# ── Callback: cancel creation ─────────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^cancel_creation$"))
async def cancel_creation_cb(client: Client, query: CallbackQuery):
    _creation_state.pop(query.from_user.id, None)
    await query.message.edit_text(
        "<b>❌ Cancelled.</b>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="back_menu")],
        ]),
    )
    await query.answer()


# ── Message handler: creation input (group -1 fires before others) ────────────

@Client.on_message(
    filters.private
    & (filters.text | filters.photo | filters.document)
    & ~filters.command(
        ["start", "bots", "check", "ban", "unban", "sysstats", "users", "broadcast"]
    )
    & ~filters.bot,
    group=-1,
)
async def handle_creation_input(client: Client, message: Message):
    uid = message.from_user.id
    if uid not in _creation_state:
        return  # not in creation flow

    state = _creation_state[uid]
    step  = state["step"]

    # Require text for most steps (photo only for set_startpic)
    if not message.text:
        is_pic = step == "settings" and state.get("action") == "set_startpic"
        if not is_pic:
            await message.reply("<b>❌ Please send text.</b>")
            message.stop_propagation()
            return

    # ── Step 1: bot token ─────────────────────────────────────────────────────
    if step == "awaiting_token":
        token = message.text.strip()
        if ":" not in token or len(token) < 20:
            await message.reply(
                "<b>❌ Invalid token format.</b>\n"
                "Example: <code>123456:AAH…</code>",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_creation")]]
                ),
            )
            message.stop_propagation()
            return

        st = await message.reply("<b>⏳ Validating token…</b>")
        info = await validate_bot_token(token)
        if not info:
            await st.edit_text(
                "<b>❌ Invalid token!</b> Telegram rejected it. Please try again.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_creation")]]
                ),
            )
            message.stop_propagation()
            return

        bid = info["id"]
        existing = await _registry.get_bot(bid)
        if existing and not (existing.get("is_deleted") and existing.get("owner_id") == uid):
            await st.edit_text(
                f"<b>❌ @{info.get('username','?')} is already registered!</b>",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Back", callback_data="back_menu")]]
                ),
            )
            _creation_state.pop(uid, None)
            message.stop_propagation()
            return

        state["data"]["token"] = token
        state["data"]["bot_info"] = info
        state["step"] = "awaiting_channel"

        await st.edit_text(
            f"<b>✅ Token verified!</b>\n\n"
            f"<blockquote>Bot: <b>{info.get('first_name','?')}</b> (@{info.get('username','?')})\n\n"
            f"<b>Step 2/2:</b> Send the <b>Log Channel ID</b>.\n"
            f"Make sure @{info.get('username','')} is admin in that channel.\n\n"
            f"Example: <code>-1001234567890</code></blockquote>",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_creation")]]
            ),
        )
        message.stop_propagation()
        return

    # ── Step 2: log channel ───────────────────────────────────────────────────
    if step == "awaiting_channel":
        try:
            channel_id = int(message.text.strip())
        except ValueError:
            await message.reply(
                "<b>❌ Invalid channel ID.</b> Example: <code>-1001234567890</code>",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_creation")]]
                ),
            )
            message.stop_propagation()
            return

        st = await message.reply("<b>⏳ Verifying channel access…</b>")
        token    = state["data"]["token"]
        bot_info = state["data"]["bot_info"]

        try:
            tmp = Client(
                name=f"verify_{bot_info['id']}",
                api_id=API_ID, api_hash=API_HASH,
                bot_token=token, in_memory=True,
            )
            await tmp.start()
            try:
                await tmp.get_chat(channel_id)
                test = await tmp.send_message(channel_id, "✅ Channel verified for FileStore bot.")
                await test.delete()
            except Exception as e:
                await st.edit_text(
                    f"<b>❌ Cannot access channel!</b>\n\n"
                    f"<blockquote>Make sure the bot is admin with post rights.\n\n"
                    f"Error: <code>{str(e)[:100]}</code></blockquote>",
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_creation")]]
                    ),
                )
                await tmp.stop()
                message.stop_propagation()
                return
            await tmp.stop()
        except Exception as e:
            await st.edit_text(
                f"<b>❌ Verification failed!</b>\n<code>{str(e)[:150]}</code>",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_creation")]]
                ),
            )
            message.stop_propagation()
            return

        enc_token  = encrypt_token(token)
        bot_id     = bot_info["id"]
        bot_uname  = bot_info.get("username", "unknown")

        await _registry.add_bot(bot_id, uid, enc_token, bot_uname, channel_id)
        await _registry.set_cooldown(uid)
        _creation_state.pop(uid, None)

        # Start worker
        worker_started = False
        try:
            from multi.engine import worker_engine
            bot_doc = await _registry.get_bot(bot_id)
            await worker_engine.start_worker(bot_doc)
            worker_started = True
            await send_main_log(
                client,
                f"<b>🤖 New Bot Created</b>\n\n"
                f"<b>• User:</b> <code>{uid}</code>\n"
                f"<b>• Bot:</b> @{bot_uname} (<code>{bot_id}</code>)\n"
                f"<b>• Channel:</b> <code>{channel_id}</code>",
            )
        except Exception as e:
            log.error(f"start_worker after creation: {e}")

        icon = "🟢" if worker_started else "🟡"
        await st.edit_text(
            f"<b>✅ Bot Created!</b>\n\n"
            f"<blockquote>◈ <b>Bot:</b> @{bot_uname}\n"
            f"◈ <b>Channel:</b> <code>{channel_id}</code>\n"
            f"◈ <b>Status:</b> {icon} {'Running' if worker_started else 'Pending'}\n\n"
            "Use the dashboard to configure it.</blockquote>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ Dashboard", callback_data=f"dashboard_{bot_id}")],
                [InlineKeyboardButton("🔙 My Bots",   callback_data="my_bots")],
            ]),
        )
        message.stop_propagation()
        return

    # ── Delegated steps (from bot_settings_multi.py) ──────────────────────────
    from plugins.bot_settings_multi import (
        handle_shortener_input, handle_fsub_channel_input,
        handle_admin_input, handle_log_channel_input,
        handle_auto_delete_input, handle_startcfg_input,
    )

    dispatch = {
        "awaiting_shortener_api_key":  lambda: handle_shortener_input(client, message, state, "api_key"),
        "awaiting_shortener_domain":   lambda: handle_shortener_input(client, message, state, "domain"),
        "awaiting_fsub_channel":       lambda: handle_fsub_channel_input(client, message, state),
        "awaiting_admin_id":           lambda: handle_admin_input(client, message, state),
        "awaiting_new_log_channel":    lambda: handle_log_channel_input(client, message, state),
        "awaiting_auto_delete_time":   lambda: handle_auto_delete_input(client, message, state),
    }

    if step in dispatch:
        await dispatch[step]()
        message.stop_propagation()
        return

    if step == "settings":
        action = state.get("action", "")
        if action.startswith("short_"):
            await handle_shortener_input(client, message, state)
        else:
            await handle_startcfg_input(client, message, state)
        message.stop_propagation()
