"""My Bots dashboard — list, start/stop, delete, transfer worker bots.

Ported from Multi-FileStoreBot main_bot/plugins/my_bots.py.
"""
import logging

from pyrogram import Client, filters
from pyrogram.errors import MessageNotModified
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from multi.helpers import send_main_log
from multi.registry import RegistryDB, WorkerDB
from multi.security import mask_token, decrypt_token

log = logging.getLogger(__name__)
_registry = RegistryDB()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _state():
    from plugins.create_bot import _creation_state
    return _creation_state


async def _verify(query: CallbackQuery, bot_id: int):
    bot = await _registry.get_bot(bot_id)
    if not bot or bot["owner_id"] != query.from_user.id:
        await query.answer("❌ Access denied!", show_alert=True)
        return None
    return bot


# ── My Bots list ──────────────────────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^my_bots$"))
async def my_bots_cb(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    _state().pop(uid, None)
    bots = await _registry.get_user_bots(uid)

    if not bots:
        await query.message.edit_text(
            "<b>━━━━━━━━━━━━━━━━━━━━━\n📋 𝗠𝗬 𝗕𝗢𝗧𝗦\n━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
            "<blockquote>ʏᴏᴜ ʜᴀᴠᴇɴ'ᴛ ᴄʀᴇᴀᴛᴇᴅ ᴀɴʏ ʙᴏᴛs ʏᴇᴛ.\n"
            "ᴛᴀᴘ <b>⚡ ᴄʀᴇᴀᴛᴇ ʙᴏᴛ</b> ᴛᴏ ɢᴇᴛ sᴛᴀʀᴛᴇᴅ!</blockquote>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚡ ᴄʀᴇᴀᴛᴇ ʙᴏᴛ", callback_data="create_bot")],
                [InlineKeyboardButton("🔙 ʙᴀᴄᴋ",         callback_data="back_menu")],
            ]),
        )
        await query.answer()
        return

    from multi.engine import worker_engine
    from config import MAX_BOTS_PER_USER
    buttons = []
    for bot in bots:
        bid  = bot["_id"]
        live = worker_engine.get_worker(bid) is not None
        icon = "🟢" if live else "🔴"
        buttons.append([InlineKeyboardButton(
            f"{icon} @{bot.get('bot_username', 'unknown')}",
            callback_data=f"dashboard_{bid}",
        )])
    buttons.append([InlineKeyboardButton("🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴇɴᴜ", callback_data="back_menu")])

    await query.message.edit_text(
        f"<b>━━━━━━━━━━━━━━━━━━━━━\n📋 𝗠𝗬 𝗕𝗢𝗧𝗦  [{len(bots)}/{MAX_BOTS_PER_USER}]\n"
        f"━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        "<blockquote>sᴇʟᴇᴄᴛ ᴀ ʙᴏᴛ ᴛᴏ ᴏᴘᴇɴ ɪᴛs ᴅᴀsʜʙᴏᴀʀᴅ:</blockquote>",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    await query.answer()


# ── Bot dashboard ─────────────────────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^dashboard_(\d+)$"))
async def dashboard_cb(client: Client, query: CallbackQuery):
    import re
    bot_id = int(re.search(r"(\d+)$", query.data).group(1))
    _state().pop(query.from_user.id, None)

    bot = await _verify(query, bot_id)
    if not bot:
        return

    from multi.engine import worker_engine
    live    = worker_engine.get_worker(bot_id) is not None
    status  = "🟢 ʀᴜɴɴɪɴɢ" if live else "🔴 sᴛᴏᴘᴘᴇᴅ"
    settings  = bot.get("settings", {})
    shortener = bot.get("shortener", {})

    _del = await WorkerDB(bot_id).get_del_timer()   # the timer is stored per worker bot
    auto_del_txt = f"{_del}s" if _del else "ᴅɪsᴀʙʟᴇᴅ"
    sh_icon  = "✅" if shortener.get("enabled") else "❌"
    pr_icon  = "✅ ᴏɴ" if settings.get("protect_content", True) else "❌ ᴏꜰꜰ"
    pl_icon  = "✅ ᴏɴ" if settings.get("permanent_link") else "❌ ᴏꜰꜰ"

    text = (
        f"<b>━━━━━━━━━━━━━━━━━━━━━\n⚙️ 𝗕𝗢𝗧 𝗗𝗔𝗦𝗛𝗕𝗢𝗔𝗥𝗗\n━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        f"<blockquote>"
        f"◈ <b>ʙᴏᴛ:</b> @{bot.get('bot_username','?')}\n"
        f"◈ <b>sᴛᴀᴛᴜs:</b> {status}\n"
        f"◈ <b>ᴄʜᴀɴɴᴇʟ:</b> <code>{bot.get('log_channel_id','?')}</code>\n"
        f"◈ <b>ᴀᴜᴛᴏ-ᴅᴇʟ:</b> {auto_del_txt}\n"
        f"◈ <b>sʜᴏʀᴛᴇɴᴇʀ:</b> {sh_icon}\n"
        f"◈ <b>ᴘʀᴏᴛᴇᴄᴛɪᴏɴ:</b> {pr_icon}\n"
        f"◈ <b>ᴘᴇʀᴍ ʟɪɴᴋ:</b> {pl_icon}"
        f"</blockquote>"
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📢 ʟᴏɢ ᴄʜ",      callback_data=f"set_channel_{bot_id}"),
            InlineKeyboardButton("⏱ ᴀᴜᴛᴏ-ᴅᴇʟ",     callback_data=f"auto_delete_{bot_id}"),
        ],
        [InlineKeyboardButton("🔗 ᴘᴇʀᴍ ʟɪɴᴋ",       callback_data=f"toggle_permanent_link_{bot_id}")],
        [
            InlineKeyboardButton("🔒 ꜰsᴜʙ",         callback_data=f"fsub_{bot_id}"),
            InlineKeyboardButton("🔗 sʜᴏʀᴛᴇɴᴇʀ",    callback_data=f"shortener_{bot_id}"),
        ],
        [
            InlineKeyboardButton("👥 ᴀᴅᴍɪɴs",       callback_data=f"admins_{bot_id}"),
            InlineKeyboardButton("📩 sᴛᴀʀᴛ ᴄꜰɢ",    callback_data=f"startcfg_{bot_id}"),
        ],
        [
            InlineKeyboardButton("📝 ᴄᴀᴘᴛɪᴏɴ",      callback_data=f"captioncfg_{bot_id}"),
            InlineKeyboardButton("📊 sᴛᴀᴛs",         callback_data=f"stats_{bot_id}"),
        ],
        [
            InlineKeyboardButton("🛡️ ᴘʀᴏᴛᴇᴄᴛ",     callback_data=f"toggle_protect_{bot_id}"),
            InlineKeyboardButton("📦 ᴛʀᴀɴsꜰᴇʀ",     callback_data=f"transfer_{bot_id}"),
        ],
        [InlineKeyboardButton("🗑 ᴅᴇʟᴇᴛᴇ",           callback_data=f"confirm_delete_{bot_id}")],
        [InlineKeyboardButton(
            "🔴 sᴛᴏᴘ" if live else "🟢 sᴛᴀʀᴛ",
            callback_data=f"toggle_bot_{bot_id}",
        )],
        [InlineKeyboardButton("🔙 ʙᴀᴄᴋ ᴛᴏ ᴍʏ ʙᴏᴛs", callback_data="my_bots")],
    ])

    try:
        await query.message.edit_text(text, reply_markup=kb)
    except MessageNotModified:
        pass
    try:
        await query.answer()
    except Exception:
        pass


# ── Toggle start/stop ─────────────────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^toggle_bot_(\d+)$"))
async def toggle_bot_cb(client: Client, query: CallbackQuery):
    import re
    bot_id = int(re.match(r"^toggle_bot_(\d+)$", query.data).group(1))
    bot = await _verify(query, bot_id)
    if not bot:
        return

    from multi.engine import worker_engine
    live = worker_engine.get_worker(bot_id) is not None

    if live:
        await query.answer("🔴 sᴛᴏᴘᴘɪɴɢ…")
        await worker_engine.stop_worker(bot_id)
        await _registry.set_bot_active(bot_id, False)
    else:
        await query.answer("🟢 sᴛᴀʀᴛɪɴɢ…")
        try:
            await worker_engine.start_worker(await _registry.get_bot(bot_id))
            await _registry.set_bot_active(bot_id, True)
        except Exception as e:
            log.error(f"toggle_bot start {bot_id}: {e}")

    await dashboard_cb(client, query)


# ── Toggle protect content ────────────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^toggle_protect_(\d+)$"))
async def toggle_protect_cb(client: Client, query: CallbackQuery):
    import re
    bot_id = int(re.match(r"^toggle_protect_(\d+)$", query.data).group(1))
    bot = await _verify(query, bot_id)
    if not bot:
        return
    cur = bot.get("settings", {}).get("protect_content", True)
    await _registry.update_setting(bot_id, "protect_content", not cur)
    await _restart_worker(bot_id)
    await query.answer(f"🛡️ Protection: {'On' if not cur else 'Off'}")
    await dashboard_cb(client, query)


# ── Toggle permanent link ─────────────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^toggle_permanent_link_(\d+)$"))
async def toggle_perm_link_cb(client: Client, query: CallbackQuery):
    import re, aiohttp
    bot_id = int(re.match(r"^toggle_permanent_link_(\d+)$", query.data).group(1))
    bot = await _verify(query, bot_id)
    if not bot:
        return
    cur = bot.get("settings", {}).get("permanent_link", False)

    if not cur:  # enabling needs the Cloudflare Worker URL (backend/)
        from config import BACKEND_API_URL
        if not BACKEND_API_URL:
            await query.answer(
                "⚠️ Permanent links are not set up on this server (BACKEND_API_URL is empty).",
                show_alert=True,
            )
            return

    await _registry.update_setting(bot_id, "permanent_link", not cur)
    await _restart_worker(bot_id)
    await query.answer(f"🔗 Perm Link: {'On' if not cur else 'Off'}")
    await dashboard_cb(client, query)


# ── Confirm delete ────────────────────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^confirm_delete_(\d+)$"))
async def confirm_delete_cb(client: Client, query: CallbackQuery):
    import re
    bot_id = int(re.match(r"^confirm_delete_(\d+)$", query.data).group(1))
    bot = await _verify(query, bot_id)
    if not bot:
        return
    uname = bot.get("bot_username", "unknown")
    await query.message.edit_text(
        f"<b>━━━━━━━━━━━━━━━━━━━━━\n⚠️ 𝗗𝗘𝗟𝗘𝗧𝗘 @{uname}?\n━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        "<blockquote>ᴛʜɪs ᴡɪʟʟ ʀᴇᴍᴏᴠᴇ ᴛʜᴇ ʙᴏᴛ ꜰʀᴏᴍ ᴛʜᴇ sʏsᴛᴇᴍ.\n"
        "(ʏᴏᴜʀ ᴅᴀᴛᴀ ɪs ᴋᴇᴘᴛ ꜰᴏʀ ᴛʀᴀɴsꜰᴇʀ.)\n\n"
        "<b>ᴛʜɪs ᴀᴄᴛɪᴏɴ ᴄᴀɴɴᴏᴛ ʙᴇ ᴜɴᴅᴏɴᴇ!</b></blockquote>",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ ʏᴇs", callback_data=f"delete_bot_{bot_id}"),
            InlineKeyboardButton("❌ ɴᴏ",  callback_data=f"dashboard_{bot_id}"),
        ]]),
    )
    await query.answer()


@Client.on_callback_query(filters.regex(r"^delete_bot_(\d+)$"))
async def delete_bot_cb(client: Client, query: CallbackQuery):
    import re
    bot_id = int(re.match(r"^delete_bot_(\d+)$", query.data).group(1))
    bot = await _verify(query, bot_id)
    if not bot:
        return

    from multi.engine import worker_engine
    await worker_engine.stop_worker(bot_id)
    await _registry.delete_bot(bot_id)
    uname = bot.get("bot_username", "unknown")
    await send_main_log(
        client,
        f"<b>🗑 Bot Deleted</b>\n\n"
        f"<b>• User:</b> <code>{query.from_user.id}</code>\n"
        f"<b>• Bot:</b> @{uname} (<code>{bot_id}</code>)",
    )
    await query.message.edit_text(
        f"<b>━━━━━━━━━━━━━━━━━━━━━\n🗑 𝗗𝗘𝗟𝗘𝗧𝗘𝗗\n━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        f"<blockquote>@{uname} ʀᴇᴍᴏᴠᴇᴅ.\n\n"
        "📦 ᴅᴀᴛᴀ ᴘʀᴇsᴇʀᴠᴇᴅ ꜰᴏʀ ᴛʀᴀɴsꜰᴇʀ ᴠɪᴀ ʏᴏᴜʀ ɴᴇᴡ ʙᴏᴛ's ᴅᴀsʜʙᴏᴀʀᴅ.</blockquote>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 ᴍʏ ʙᴏᴛs", callback_data="my_bots")],
        ]),
    )
    await query.answer("✅ Deleted!", show_alert=True)


# ── Data transfer ─────────────────────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^transfer_(\d+)$"))
async def transfer_cb(client: Client, query: CallbackQuery):
    import re
    target_id = int(re.match(r"^transfer_(\d+)$", query.data).group(1))
    uid = query.from_user.id
    target = await _registry.get_bot(target_id)
    if not target or target["owner_id"] != uid:
        await query.answer("❌ Access denied!", show_alert=True)
        return

    deleted = [b for b in await _registry.get_deleted_user_bots(uid) if b["_id"] != target_id]
    if not deleted:
        await query.answer("📭 No deleted bots to transfer from.", show_alert=True)
        return

    btns = [
        [InlineKeyboardButton(f"📦 @{b.get('bot_username','?')}", callback_data=f"dotransfer_{target_id}_{b['_id']}")]
        for b in deleted
    ]
    btns.append([InlineKeyboardButton("🔙 ʙᴀᴄᴋ", callback_data=f"dashboard_{target_id}")])
    await query.message.edit_text(
        "<b>━━━━━━━━━━━━━━━━━━━━━\n📦 𝗧𝗥𝗔𝗡𝗦𝗙𝗘𝗥 𝗗𝗔𝗧𝗔\n━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        "<blockquote>sᴇʟᴇᴄᴛ ᴀ ᴅᴇʟᴇᴛᴇᴅ ʙᴏᴛ ᴛᴏ ᴛʀᴀɴsꜰᴇʀ ɪᴛs ᴅᴀᴛᴀ (ᴜsᴇʀs, ᴀᴅᴍɪɴs, ᴄʜᴀɴɴᴇʟs) ʜᴇʀᴇ.</blockquote>",
        reply_markup=InlineKeyboardMarkup(btns),
    )
    await query.answer()


@Client.on_callback_query(filters.regex(r"^dotransfer_(\d+)_(\d+)$"))
async def do_transfer_cb(client: Client, query: CallbackQuery):
    import re
    m = re.match(r"^dotransfer_(\d+)_(\d+)$", query.data)
    target_id, source_id = int(m.group(1)), int(m.group(2))
    uid = query.from_user.id

    target = await _registry.get_bot(target_id)
    source = await _registry.get_bot(source_id)
    if not target or target["owner_id"] != uid:
        await query.answer("❌ Access denied!", show_alert=True)
        return
    if not source or source["owner_id"] != uid:
        await query.answer("❌ Source not found!", show_alert=True)
        return

    await query.message.edit_text("<b>⏳ ᴛʀᴀɴsꜰᴇʀʀɪɴɢ…</b>")
    target_db = WorkerDB(target_id)
    try:
        stats = await target_db.copy_data_from(source_id)
    except Exception as e:
        await query.message.edit_text(
            f"<b>❌ Transfer failed</b>\n\n<blockquote>{e}</blockquote>",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data=f"dashboard_{target_id}")]]
            ),
        )
        return

    stats_txt = "\n".join(f"◈ <b>{k}:</b> {v}" for k, v in stats.items()) or "ɴᴏ ᴅᴀᴛᴀ"
    # Purge source
    await WorkerDB(source_id).drop_all_collections()
    await _registry.purge_bot(source_id)

    src_uname = source.get("bot_username", "unknown")
    await query.message.edit_text(
        f"<b>━━━━━━━━━━━━━━━━━━━━━\n✅ 𝗧𝗥𝗔𝗡𝗦𝗙𝗘𝗥 𝗗𝗢𝗡𝗘\n━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        f"<blockquote>ᴅᴀᴛᴀ ꜰʀᴏᴍ @{src_uname}:\n{stats_txt}</blockquote>",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 ᴅᴀsʜʙᴏᴀʀᴅ", callback_data=f"dashboard_{target_id}")]]
        ),
    )
    await query.answer("✅ Done!", show_alert=True)


# ── Internal: restart worker after settings change ────────────────────────────

async def _restart_worker(bot_id: int):
    from multi.engine import worker_engine
    try:
        await worker_engine.stop_worker(bot_id)
        doc = await _registry.get_bot(bot_id)
        await worker_engine.start_worker(doc)
    except Exception as e:
        log.error(f"_restart_worker {bot_id}: {e}")
