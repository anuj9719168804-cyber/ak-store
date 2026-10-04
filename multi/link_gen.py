"""genlink / batch / custom_batch / flink handlers for worker bots.

Ported from Multi-FileStoreBot worker_bot/link_gen.py.
Adapted to use multi.registry and multi.helpers instead of Multi's utils.
"""
import asyncio
import logging

import aiohttp
from pyrogram import Client, filters
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from multi.helpers import encode, get_message_id, send_main_log

log = logging.getLogger(__name__)

CANCEL_MARKUP = InlineKeyboardMarkup(
    [[InlineKeyboardButton("❌ ᴄᴀɴᴄᴇʟ", callback_data="link_gen:cancel")]]
)


def setup_link_gen(app: Client, log_channel_id: int, is_admin_func):
    """Bind genlink / batch / custom_batch / flink handlers to the given app."""

    _waiting: dict[int, asyncio.Future] = {}

    # ── Internal: wait for next user message ─────────────────────────────────

    async def _wait_input(user_id: int, timeout: int = 300) -> Message | str | None:
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        _waiting[user_id] = fut
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            _waiting.pop(user_id, None)

    @app.on_message(
        filters.private & ~filters.command(
            ["start", "genlink", "batch", "custom_batch", "flink"]
        ),
        group=2,
    )
    async def _input_catcher(client: Client, message: Message):
        uid = message.from_user.id
        if uid in _waiting and not _waiting[uid].done():
            _waiting[uid].set_result(message)
            message.stop_propagation()

    @app.on_callback_query(filters.regex(r"^link_gen:cancel$"))
    async def _cancel_cb(client: Client, query: CallbackQuery):
        uid = query.from_user.id
        if uid in _waiting and not _waiting[uid].done():
            _waiting[uid].set_result("CANCEL")
        await query.answer("Cancelled")

    # ── Permanent-link helper ─────────────────────────────────────────────────

    async def _process_link(encoded: str, user_id: int, bot_id: int) -> str:
        from multi.registry import RegistryDB
        db = RegistryDB()
        bot_doc = await db.get_bot(bot_id)
        me = await app.get_me()
        base = f"https://t.me/{me.username}?start={encoded}"
        if not bot_doc:
            return base
        from config import BACKEND_API_URL
        if bot_doc.get("settings", {}).get("permanent_link") and BACKEND_API_URL:
            # The Cloudflare Worker (backend/) is stateless: it redirects to t.me/<bot>?start=<payload>,
            # and the &bot= part tells it WHICH bot (every user bot has its own username).
            return f"{BACKEND_API_URL}/?url={encoded}&bot={me.username}"
        return base

    # ── /genlink ─────────────────────────────────────────────────────────────

    @app.on_message(filters.command("genlink") & filters.private)
    async def handle_genlink(client: Client, message: Message):
        if not await is_admin_func(message.from_user.id):
            return
        uid = message.from_user.id
        await message.reply(
            "<b>Sᴇɴᴅ ᴏʀ Fᴏʀᴡᴀʀᴅ ᴛʜᴇ Mᴇssᴀɢᴇ ᴛᴏ ɢᴇɴᴇʀᴀᴛᴇ ʟɪɴᴋ.</b>",
            reply_markup=CANCEL_MARKUP,
        )
        rcv = await _wait_input(uid)
        if not rcv or rcv == "CANCEL":
            return await message.reply("<b><i>🆑 Cᴀɴᴄᴇʟʟᴇᴅ / Tɪᴍᴇᴅ Oᴜᴛ</i></b>")

        wait = await message.reply("<b>⏳ Pʀᴏᴄᴇssɪɴɢ…</b>")
        msg_id = await get_message_id(client, rcv, log_channel_id)
        if not msg_id:
            return await wait.edit("<b>❌ Fᴀɪʟᴇᴅ ᴛᴏ ɢᴇᴛ ᴍᴇssᴀɢᴇ ID.</b>")

        encoded = await encode(f"get-{msg_id * abs(log_channel_id)}")
        me = await client.get_me()
        link = await _process_link(encoded, uid, me.id)
        await message.reply(
            f"<b>✅ Lɪɴᴋ Gᴇɴᴇʀᴀᴛᴇᴅ:\n\n<blockquote><code>{link}</code></blockquote></b>",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔗 Oᴘᴇɴ Lɪɴᴋ", url=link)]]
            ),
        )
        await wait.delete()
        await send_main_log(
            client,
            f"<b>🔗 Lɪɴᴋ Gᴇɴᴇʀᴀᴛᴇᴅ</b>\n\n"
            f"<b>• Bᴏᴛ:</b> @{me.username}\n"
            f"<b>• Oᴡɴᴇʀ:</b> <code>{uid}</code>\n"
            f"<b>• Mᴇᴛʜᴏᴅ:</b> /genlink\n"
            f"<b>• Lɪɴᴋ:</b> {link}",
        )

    # ── /batch ────────────────────────────────────────────────────────────────

    @app.on_message(filters.command("batch") & filters.private)
    async def handle_batch(client: Client, message: Message):
        if not await is_admin_func(message.from_user.id):
            return
        uid = message.from_user.id
        await message.reply(
            "<b>Fᴏʀᴡᴀʀᴅ ᴛʜᴇ FIRST ᴍᴇssᴀɢᴇ.</b>", reply_markup=CANCEL_MARKUP
        )
        first = await _wait_input(uid)
        if not first or first == "CANCEL":
            return await message.reply("<b><i>🆑 Cᴀɴᴄᴇʟʟᴇᴅ / Tɪᴍᴇᴅ Oᴜᴛ</i></b>")

        first_id = await get_message_id(client, first, log_channel_id)
        if not first_id:
            return await message.reply("<b>❌ Fᴀɪʟᴇᴅ ᴛᴏ ɢᴇᴛ FIRST ɪᴅ.</b>")

        await message.reply(
            "<b>Nᴏᴡ Fᴏʀᴡᴀʀᴅ ᴛʜᴇ LAST ᴍᴇssᴀɢᴇ.</b>", reply_markup=CANCEL_MARKUP
        )
        last = await _wait_input(uid)
        if not last or last == "CANCEL":
            return await message.reply("<b><i>🆑 Cᴀɴᴄᴇʟʟᴇᴅ / Tɪᴍᴇᴅ Oᴜᴛ</i></b>")

        last_id = await get_message_id(client, last, log_channel_id)
        if not last_id:
            return await message.reply("<b>❌ Fᴀɪʟᴇᴅ ᴛᴏ ɢᴇᴛ LAST ɪᴅ.</b>")

        encoded = await encode(
            f"get-{first_id * abs(log_channel_id)}-{last_id * abs(log_channel_id)}"
        )
        me = await client.get_me()
        link = await _process_link(encoded, uid, me.id)
        await message.reply(
            f"<b>✅ Bᴀᴛᴄʜ Lɪɴᴋ Gᴇɴᴇʀᴀᴛᴇᴅ:\n\n<blockquote><code>{link}</code></blockquote></b>",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔗 Oᴘᴇɴ Lɪɴᴋ", url=link)]]
            ),
        )
        await send_main_log(
            client,
            f"<b>🔗 Lɪɴᴋ Gᴇɴᴇʀᴀᴛᴇᴅ</b>\n\n"
            f"<b>• Bᴏᴛ:</b> @{me.username}\n"
            f"<b>• Oᴡɴᴇʀ:</b> <code>{uid}</code>\n"
            f"<b>• Mᴇᴛʜᴏᴅ:</b> /batch\n"
            f"<b>• Lɪɴᴋ:</b> {link}",
        )

    # ── /custom_batch ─────────────────────────────────────────────────────────

    @app.on_message(filters.command("custom_batch") & filters.private)
    async def handle_custom_batch(client: Client, message: Message):
        if not await is_admin_func(message.from_user.id):
            return
        uid = message.from_user.id
        await message.reply(
            "<b>Sᴇɴᴅ ᴀʟʟ ᴍᴇssᴀɢᴇs ᴏɴᴇ ʙʏ ᴏɴᴇ. Sᴇɴᴅ /done ᴡʜᴇɴ ꜰɪɴɪsʜᴇᴅ.</b>",
            reply_markup=CANCEL_MARKUP,
        )
        first_id = last_id = None
        while True:
            rcv = await _wait_input(uid)
            if not rcv or rcv == "CANCEL":
                await message.reply("<b><i>🆑 Cᴀɴᴄᴇʟʟᴇᴅ / Tɪᴍᴇᴅ Oᴜᴛ</i></b>")
                break
            if getattr(rcv, "text", "") == "/done":
                if not first_id:
                    await message.reply("<b>❌ Nᴏ ᴍᴇssᴀɢᴇs ᴀᴅᴅᴇᴅ.</b>")
                else:
                    encoded = await encode(
                        f"get-{first_id * abs(log_channel_id)}-{last_id * abs(log_channel_id)}"
                    )
                    me = await client.get_me()
                    link = await _process_link(encoded, uid, me.id)
                    await message.reply(
                        f"<b>✅ Cᴜsᴛᴏᴍ Bᴀᴛᴄʜ Lɪɴᴋ Gᴇɴᴇʀᴀᴛᴇᴅ:\n\n"
                        f"<blockquote><code>{link}</code></blockquote></b>",
                        reply_markup=InlineKeyboardMarkup(
                            [[InlineKeyboardButton("🔗 Oᴘᴇɴ Lɪɴᴋ", url=link)]]
                        ),
                    )
                    await send_main_log(
                        client,
                        f"<b>🔗 Lɪɴᴋ Gᴇɴᴇʀᴀᴛᴇᴅ</b>\n\n"
                        f"<b>• Bᴏᴛ:</b> @{me.username}\n"
                        f"<b>• Oᴡɴᴇʀ:</b> <code>{uid}</code>\n"
                        f"<b>• Mᴇᴛʜᴏᴅ:</b> /custom_batch\n"
                        f"<b>• Lɪɴᴋ:</b> {link}",
                    )
                break
            mid = await get_message_id(client, rcv, log_channel_id)
            if mid:
                first_id = first_id or mid
                last_id = mid
            else:
                await rcv.reply("<b>❌ Skipping — could not get ID.</b>", quote=True)

    # ── /flink (formatted multi-link) ─────────────────────────────────────────

    @app.on_message(filters.command("flink") & filters.private)
    async def handle_flink(client: Client, message: Message):
        if not await is_admin_func(message.from_user.id):
            return
        uid = message.from_user.id
        await message.reply(
            "<b>Fᴏʀᴡᴀʀᴅ ᴛʜᴇ FIRST ᴍᴇssᴀɢᴇ ꜰᴏʀ ꜰʟɪɴᴋ.</b>", reply_markup=CANCEL_MARKUP
        )
        first = await _wait_input(uid)
        if not first or first == "CANCEL":
            return await message.reply("<b><i>🆑 Cᴀɴᴄᴇʟʟᴇᴅ</i></b>")
        first_id = await get_message_id(client, first, log_channel_id)
        if not first_id:
            return await message.reply("<b>❌ Failed to get FIRST id.</b>")

        await message.reply(
            "<b>Nᴏᴡ Fᴏʀᴡᴀʀᴅ ᴛʜᴇ LAST ᴍᴇssᴀɢᴇ.</b>", reply_markup=CANCEL_MARKUP
        )
        last = await _wait_input(uid)
        if not last or last == "CANCEL":
            return await message.reply("<b><i>🆑 Cᴀɴᴄᴇʟʟᴇᴅ</i></b>")
        last_id = await get_message_id(client, last, log_channel_id)
        if not last_id:
            return await message.reply("<b>❌ Failed to get LAST id.</b>")

        me = await client.get_me()
        if first_id > last_id:
            first_id, last_id = last_id, first_id
        count = last_id - first_id + 1
        if count > 100:
            return await message.reply("<b>❌ Maximum 100 files per flink.</b>")

        wait = await message.reply(f"<b>⏳ Generating {count} links…</b>")

        import html
        from helper.caption_logic import get_file_details
        from multi.helpers import get_messages

        blocks = []
        msgs = await get_messages(client, log_channel_id, list(range(first_id, last_id + 1)))
        for msg in msgs:
            if getattr(msg, "empty", True):
                continue
            enc = await encode(f"get-{msg.id * abs(log_channel_id)}")
            # same link rules as /genlink and /batch (honours the bot's permanent-link setting)
            link = await _process_link(enc, uid, me.id)
            details = get_file_details(msg) if getattr(msg, "media", None) else {}
            name = (details.get("file_name") or "").strip()
            if not name:
                text = (msg.caption or msg.text or "").strip()
                name = text.splitlines()[0].strip()[:80] if text else ""
            name = html.escape(name or f"File {msg.id}")
            size = details.get("file_size") or ""
            size_part = f" [{html.escape(size)}]" if size and size != "Unknown Size" else ""
            blocks.append(
                f"<b>{len(blocks) + 1}. {name}</b>{size_part}\n<a href='{link}'>{link}</a>"
            )

        await wait.delete()
        if not blocks:
            return await message.reply("<b>❌ No files found in that range.</b>")

        # keep every message under Telegram's 4096-character limit
        pages, cur = [], ""
        for block in blocks:
            if cur and len(cur) + len(block) + 2 > 3800:
                pages.append(cur)
                cur = ""
            cur = f"{cur}\n\n{block}" if cur else block
        if cur:
            pages.append(cur)
        for page in pages:
            await message.reply(page, disable_web_page_preview=True)

        await send_main_log(
            client,
            f"<b>🔗 Lɪɴᴋs Gᴇɴᴇʀᴀᴛᴇᴅ</b>\n\n"
            f"<b>• Bᴏᴛ:</b> @{me.username}\n"
            f"<b>• Oᴡɴᴇʀ:</b> <code>{uid}</code>\n"
            f"<b>• Mᴇᴛʜᴏᴅ:</b> /flink\n"
            f"<b>• Fɪʟᴇs:</b> {len(blocks)}",
        )
