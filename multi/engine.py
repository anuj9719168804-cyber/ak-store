"""Worker engine: manages multiple Pyrogram Bot clients concurrently.

Ported from Multi-FileStoreBot worker_bot/engine.py.
Each user-created bot runs as an isolated Pyrogram Client with
dynamically registered handlers — all inside the same process and event loop
as the Pro controller bot.
"""
import asyncio
import logging

from pyrogram import Client, filters, ContinuePropagation
from pyrogram.enums import ParseMode, ChatMemberStatus
from pyrogram.errors.exceptions.bad_request_400 import UserNotParticipant
from pyrogram.handlers import CallbackQueryHandler, MessageHandler
from pyrogram.types import (
    BotCommand, ChatJoinRequest, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from config import (
    API_ID, API_HASH, OWNER_ID,
    BYPASS_MIN_SECONDS, VERIFY_MAX_SECONDS, BYPASS_MAX_STRIKES, BYPASS_AUTO_BAN,
)
from multi.helpers import decode, get_exp_time, get_messages, send_main_log
from multi.registry import RegistryDB, WorkerDB
from multi.security import decrypt_token

log = logging.getLogger(__name__)
_registry = RegistryDB()


class WorkerEngine:
    """Singleton that holds and manages all running worker Pyrogram clients."""

    def __init__(self):
        self.workers: dict[int, Client] = {}
        self._lock = asyncio.Lock()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start_all_workers(self):
        bots = await _registry.get_all_active_bots()
        log.info(f"Starting {len(bots)} worker bots…")
        BATCH = 50
        for i in range(0, len(bots), BATCH):
            await asyncio.gather(*[self._safe_start(d) for d in bots[i:i + BATCH]])
            if i + BATCH < len(bots):
                log.info(f"  {min(i + BATCH, len(bots))}/{len(bots)} started…")
        log.info(f"Worker engine: {len(self.workers)} bots running")

    async def _safe_start(self, bot_doc: dict):
        try:
            await self.start_worker(bot_doc)
        except Exception as e:
            log.error(f"Failed to start worker {bot_doc.get('_id', '?')}: {e}")

    async def start_worker(self, bot_doc: dict):
        bot_id = bot_doc["_id"]
        async with self._lock:
            if bot_id in self.workers:
                return

        try:
            token = decrypt_token(bot_doc["bot_token_encrypted"])
        except Exception as e:
            log.error(f"Cannot decrypt token for {bot_id}: {e}")
            return

        log_channel_id = bot_doc["log_channel_id"]
        owner_id = bot_doc["owner_id"]
        worker_db = WorkerDB(bot_id)

        app = Client(
            name=f"worker_{bot_id}",
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=token,
            in_memory=True,
            workers=4,
        )

        # Activity tracker (group -1 fires before all real handlers)
        async def _activity(client, update):
            asyncio.create_task(_registry.update_last_active(bot_id))
            raise ContinuePropagation

        app.add_handler(MessageHandler(_activity), group=-1)
        app.add_handler(CallbackQueryHandler(_activity), group=-1)

        # Helpers (closures capturing bot_doc, worker_db, etc.)
        async def is_admin(uid: int) -> bool:
            return uid in (owner_id, OWNER_ID) or await worker_db.admin_exist(uid)

        async def check_force_sub(client: Client, uid: int) -> bool:
            if uid in (owner_id, OWNER_ID):
                return True
            channel_ids = await worker_db.show_channels()
            if not channel_ids:
                return True
            for cid in channel_ids:
                try:
                    member = await client.get_chat_member(cid, uid)
                    if member.status not in {
                        ChatMemberStatus.OWNER,
                        ChatMemberStatus.ADMINISTRATOR,
                        ChatMemberStatus.MEMBER,
                    }:
                        return False
                except UserNotParticipant:
                    mode = await worker_db.get_channel_mode(cid)
                    if mode != "on" or not await worker_db.req_user_exist(cid, uid):
                        return False
                except Exception as e:
                    log.error(f"force_sub check {cid}: {e}")
                    return False
            return True

        async def build_fsub_markup(client: Client, uid: int, start_param: str = None):
            buttons = []
            for cid in await worker_db.show_channels():
                try:
                    mode = await worker_db.get_channel_mode(cid)
                    name = "📢 Join Channel"
                    link = None
                    try:
                        chat = await client.get_chat(cid)
                        name = f"📢 {chat.title or str(cid)}"
                        if chat.username and mode != "on":
                            link = f"https://t.me/{chat.username}"
                    except Exception:
                        pass
                    if not link:
                        inv = await client.create_chat_invite_link(
                            cid, creates_join_request=(mode == "on")
                        )
                        link = inv.invite_link
                    if link:
                        buttons.append([InlineKeyboardButton(name, url=link)])
                except Exception as e:
                    log.error(f"build_fsub_markup {cid}: {e}")
            if start_param:
                me = await client.get_me()
                buttons.append([
                    InlineKeyboardButton(
                        "♻️ Reload",
                        url=f"https://t.me/{me.username}?start={start_param}",
                    )
                ])
            return InlineKeyboardMarkup(buttons) if buttons else None

        # ── /start ────────────────────────────────────────────────────────────

        @app.on_message(filters.command("start") & filters.private)
        async def worker_start(client: Client, message: Message):
            uid = message.from_user.id
            cur = await _registry.get_bot(bot_id) or bot_doc

            # Track user
            if not await worker_db.present_user(uid):
                await worker_db.add_user(uid)
                if log_channel_id:
                    try:
                        await client.send_message(
                            log_channel_id,
                            f"<b>#NewUser</b>\n\n"
                            f"<b>Iᴅ</b> - <code>{uid}</code>\n"
                            f"<b>Nᴀᴍᴇ</b> - {message.from_user.first_name}\n"
                            f"<b>Username</b> - @{message.from_user.username or 'N/A'}",
                        )
                    except Exception:
                        pass

            # Ban check
            if await worker_db.ban_user_exist(uid):
                await message.reply(
                    "<b>━━━━━━━━━━━━━━━━━━━━━\n"
                    "⛔ 𝗔𝗖𝗖𝗘𝗦𝗦 𝗗𝗘𝗡𝗜𝗘𝗗\n"
                    "━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
                    "<blockquote>ʏᴏᴜ ᴀʀᴇ ʙᴀɴɴᴇᴅ ꜰʀᴏᴍ ᴜsɪɴɢ ᴛʜɪs ʙᴏᴛ.</blockquote>"
                )
                return

            # Force-sub check
            if not await check_force_sub(client, uid):
                param = message.command[1] if len(message.command) > 1 else None
                markup = await build_fsub_markup(client, uid, param)
                settings = cur.get("settings", {})
                txt = (
                    "<b>━━━━━━━━━━━━━━━━━━━━━\n"
                    "🔒 𝗔𝗖𝗖𝗘𝗦𝗦 𝗥𝗘𝗦𝗧𝗥𝗜𝗖𝗧𝗘𝗗\n"
                    "━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
                    f"<blockquote>ʜᴇʏ {message.from_user.mention},\n\n"
                    "ᴊᴏɪɴ ᴛʜᴇ ᴄʜᴀɴɴᴇʟs ʙᴇʟᴏᴡ ᴀɴᴅ ᴛᴀᴘ <b>♻️ Rᴇʟᴏᴀᴅ</b>.</blockquote>"
                )
                fp = settings.get("force_pic", "")
                if fp and fp.lower() not in ("none", "ɴᴏɴᴇ", "0"):
                    await message.reply_photo(fp, caption=txt, reply_markup=markup)
                else:
                    await message.reply(txt, reply_markup=markup)
                return

            # Shortener verify deep link
            _arg = message.command[1] if len(message.command) > 1 else ""
            if len(_arg) == 15 and _arg.startswith("vf_"):
                status, secs = await worker_db.check_verify(
                    uid, _arg[3:], BYPASS_MIN_SECONDS, VERIFY_MAX_SECONDS
                )
                if status in ("none", "invalid"):
                    return await message.reply(
                        "<blockquote>⚠️ ᴠᴇʀɪꜰɪᴄᴀᴛɪᴏɴ ʟɪɴᴋ ɪs ɪɴᴠᴀʟɪᴅ ᴏʀ ᴇxᴘɪʀᴇᴅ.\n"
                        "ᴏᴘᴇɴ ʏᴏᴜʀ ꜰɪʟᴇ ʟɪɴᴋ ᴀɢᴀɪɴ ᴛᴏ ɢᴇᴛ ᴀ ɴᴇᴡ ᴏɴᴇ.</blockquote>"
                    )
                if status == "expired":
                    return await message.reply(
                        "<blockquote>⚠️ ᴠᴇʀɪꜰɪᴄᴀᴛɪᴏɴ ᴛɪᴍᴇᴏᴜᴛ!\n"
                        "ᴏᴘᴇɴ ʏᴏᴜʀ ꜰɪʟᴇ ʟɪɴᴋ ᴀɢᴀɪɴ ᴛᴏ ɢᴇᴛ ᴀ ɴᴇᴡ ᴏɴᴇ.</blockquote>"
                    )
                if status == "too_fast":
                    strikes = await worker_db.add_bypass_strike(uid)
                    who = f"{message.from_user.first_name} @{message.from_user.username or 'N/A'}"
                    await send_main_log(
                        client,
                        f"<b>🚫 Bypass detected</b>\nbot: @{(await client.get_me()).username}\n"
                        f"user: <code>{uid}</code> ({who})\n"
                        f"{secs}s &lt; {BYPASS_MIN_SECONDS}s | strike {strikes}/{BYPASS_MAX_STRIKES}",
                    )
                    if BYPASS_AUTO_BAN and strikes >= BYPASS_MAX_STRIKES:
                        await worker_db.add_ban_user(uid)
                        return await message.reply(
                            "<blockquote>🚫 ʏᴏᴜ ʜᴀᴠᴇ ʙᴇᴇɴ ʙᴀɴɴᴇᴅ ꜰᴏʀ ʀᴇᴘᴇᴀᴛᴇᴅ ʙʏᴘᴀss ᴀᴛᴛᴇᴍᴘᴛs.</blockquote>"
                        )
                    warn = f"\n⚠️ ᴡᴀʀɴɪɴɢ {strikes}/{BYPASS_MAX_STRIKES}" if BYPASS_AUTO_BAN else ""
                    return await message.reply(
                        "<blockquote>🚫 ʙʏᴘᴀss ᴅᴇᴛᴇᴄᴛᴇᴅ!\n"
                        f"⧗ ᴛɪᴍᴇ ᴛᴀᴋᴇɴ: {secs}s (ᴍɪɴ {BYPASS_MIN_SECONDS}s){warn}\n"
                        "ᴏᴘᴇɴ ʏᴏᴜʀ ꜰɪʟᴇ ʟɪɴᴋ ᴀɢᴀɪɴ ᴀɴᴅ ᴄᴏᴍᴘʟᴇᴛᴇ ᴛʜᴇ ʟɪɴᴋ ᴘʀᴏᴘᴇʀʟʏ.</blockquote>"
                    )
                await worker_db.reset_bypass_strikes(uid)
                await worker_db.set_verified(uid)
                await message.reply(
                    "<b>━━━━━━━━━━━━━━━━━━━━━\n✅ 𝗩𝗘𝗥𝗜𝗙𝗜𝗘𝗗\n━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
                    "<blockquote>ʏᴏᴜ ᴀʀᴇ ɴᴏᴡ ᴠᴇʀɪꜰɪᴇᴅ! ᴛᴀᴘ ʏᴏᴜʀ ᴏʀɪɢɪɴᴀʟ ʟɪɴᴋ ᴀɢᴀɪɴ.</blockquote>"
                )
                return

            # File deep link
            text = message.text or ""
            if len(text) > 7:
                try:
                    b64 = text.split(" ", 1)[1]
                except IndexError:
                    return
                string = await decode(b64)
                parts = string.split("-")
                ids = []
                if len(parts) == 3:
                    try:
                        s = int(int(parts[1]) / abs(log_channel_id))
                        e = int(int(parts[2]) / abs(log_channel_id))
                        ids = list(range(s, e + 1)) if s <= e else list(range(s, e - 1, -1))
                    except Exception:
                        return
                elif len(parts) == 2:
                    try:
                        ids = [int(int(parts[1]) / abs(log_channel_id))]
                    except Exception:
                        return
                if not ids:
                    return

                # Shortener gate
                cur = await _registry.get_bot(bot_id) or cur
                short_cfg = cur.get("shortener", {})
                if (
                    short_cfg.get("enabled")
                    and short_cfg.get("domain")
                    and short_cfg.get("api_key_encrypted")
                    and not await is_admin(uid)
                    and not await _registry.is_premium(uid)  # premium = no verification
                ):
                    expire = short_cfg.get("verify_expire", 86400)
                    if not await worker_db.is_verified(uid, expire):
                        me = await client.get_me()
                        _tok = await worker_db.start_verify(uid)
                        verify_url = f"https://t.me/{me.username}?start=vf_{_tok}"
                        try:
                            from helper.shortener import shorten_url as get_short_link
                            # key is stored Fernet-encrypted when ENCRYPTION_KEY is set
                            shortened = await get_short_link(
                                verify_url,
                                decrypt_token(short_cfg["api_key_encrypted"]),
                                short_cfg["domain"],
                            )
                        except Exception:
                            shortened = verify_url
                        expire_hrs = expire // 3600
                        btns = [[InlineKeyboardButton("🔗 ᴠᴇʀɪꜰʏ", url=shortened)]]
                        if short_cfg.get("tutorial_enabled") and short_cfg.get("tutorial_link"):
                            btns.append([InlineKeyboardButton("📹 ᴛᴜᴛᴏʀɪᴀʟ", url=short_cfg["tutorial_link"])])
                        btns.append([InlineKeyboardButton(
                            "✅ ɪ ʜᴀᴠᴇ ᴠᴇʀɪꜰɪᴇᴅ",
                            url=f"https://t.me/{me.username}?start={b64}",
                        )])
                        await message.reply(
                            "<b>━━━━━━━━━━━━━━━━━━━━━\n"
                            "🔗 𝗩𝗘𝗥𝗜𝗙𝗜𝗖𝗔𝗧𝗜𝗢𝗡 𝗥𝗘𝗤𝗨𝗜𝗥𝗘𝗗\n"
                            "━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
                            f"<blockquote>ʜᴇʏ {message.from_user.mention},\n\n"
                            "ᴛᴀᴘ <b>🔗 ᴠᴇʀɪꜰʏ</b>, ᴄᴏᴍᴘʟᴇᴛᴇ ᴛʜᴇ sʜᴏʀᴛ ʟɪɴᴋ,\n"
                            "ᴛʜᴇɴ ᴛᴀᴘ <b>✅ ɪ ʜᴀᴠᴇ ᴠᴇʀɪꜰɪᴇᴅ</b>.\n\n"
                            f"◈ ᴠᴀʟɪᴅ ꜰᴏʀ: <b>{expire_hrs}h</b></blockquote>",
                            reply_markup=InlineKeyboardMarkup(btns),
                        )
                        return

                # Fetch and send files
                tmp = await message.reply("<b>⏳ ʟᴏᴀᴅɪɴɢ…</b>") if len(ids) > 5 else None
                try:
                    msgs = await get_messages(client, log_channel_id, ids)
                except Exception as e:
                    await message.reply("<b>❌ Error fetching files.</b>")
                    log.error(f"get_messages: {e}")
                    return
                finally:
                    if tmp:
                        try:
                            await tmp.delete()
                        except Exception:
                            pass

                settings = cur.get("settings", {})
                protect = settings.get("protect_content", False)
                custom_cap = settings.get("custom_caption", "")

                from helper.caption_logic import apply_custom_caption
                _me = getattr(client, "me", None)
                _uname = getattr(_me, "username", "") or ""

                sent = []
                for msg in msgs:
                    if getattr(msg, "empty", True):
                        continue
                    orig_cap = msg.caption.html if msg.caption else ""
                    # Fills {file_name} {size} {duration} {quality} {language} {username} etc.
                    cap = apply_custom_caption(custom_cap, msg, orig_cap, _uname)
                    try:
                        cp = await msg.copy(
                            chat_id=uid,
                            caption=cap or None,
                            parse_mode=ParseMode.HTML,
                            protect_content=protect,
                        )
                        sent.append(cp)
                        await asyncio.sleep(0)
                    except Exception as e:
                        log.error(f"copy msg: {e}")

                # Auto-delete
                del_t = await worker_db.get_del_timer()
                if del_t > 0 and sent:
                    note = await message.reply(
                        f"<b>⏱ Files auto-delete in {get_exp_time(del_t)}. Save before deletion!</b>"
                    )
                    me = await client.get_me()
                    reload = (
                        f"https://t.me/{me.username}?start={message.command[1]}"
                        if len(message.command) > 1 else None
                    )
                    asyncio.create_task(_auto_delete(sent, note, del_t, reload))

            else:
                # Plain /start — welcome message
                cur = await _registry.get_bot(bot_id) or cur
                settings = cur.get("settings", {})
                sp = settings.get("start_pic", "")
                sm = settings.get("start_message", "")
                if not sm:
                    sm = (
                        f"<blockquote>ᴡᴇʟᴄᴏᴍᴇ {message.from_user.mention}!\n\n"
                        "ɪ ᴄᴀɴ sᴛᴏʀᴇ ꜰɪʟᴇs ᴀɴᴅ sʜᴀʀᴇ ᴛʜᴇᴍ ᴠɪᴀ sᴘᴇᴄɪᴀʟ ʟɪɴᴋs.\n\n"
                        "ᴘᴏᴡᴇʀᴇᴅ ʙʏ <b>File-Store-Pro</b></blockquote>"
                    )
                else:
                    try:
                        me = await client.get_me()
                        sm = sm.format(
                            mention=message.from_user.mention,
                            first=message.from_user.first_name,
                            last=message.from_user.last_name or "",
                            id=uid,
                            bot_mention=f"@{me.username}",
                            username=message.from_user.username or "",
                        )
                    except Exception:
                        pass
                if sp and sp.lower() not in ("none", "ɴᴏɴᴇ", "0"):
                    await message.reply_photo(sp, caption=sm)
                else:
                    await message.reply(sm)

        # ── Chat join request ─────────────────────────────────────────────────

        @app.on_chat_join_request()
        async def _join_req(client: Client, request: ChatJoinRequest):
            cid = request.chat.id
            uid = request.from_user.id
            if cid in await worker_db.show_channels():
                if await worker_db.get_channel_mode(cid) == "on":
                    await worker_db.req_user(cid, uid)

        # ── /ban /unban (admin) ───────────────────────────────────────────────

        @app.on_message(filters.command("ban") & filters.private)
        async def _ban(client: Client, message: Message):
            if not await is_admin(message.from_user.id):
                return
            if len(message.command) < 2:
                return await message.reply("<b>Usage:</b> <code>/ban [user_id]</code>")
            try:
                tid = int(message.command[1])
                await worker_db.add_ban_user(tid)
                await message.reply(f"<b>✅ User {tid} banned.</b>")
            except ValueError:
                await message.reply("<b>❌ Invalid ID.</b>")

        @app.on_message(filters.command("unban") & filters.private)
        async def _unban(client: Client, message: Message):
            if not await is_admin(message.from_user.id):
                return
            if len(message.command) < 2:
                return await message.reply("<b>Usage:</b> <code>/unban [user_id]</code>")
            try:
                tid = int(message.command[1])
                await worker_db.del_ban_user(tid)
                await message.reply(f"<b>✅ User {tid} unbanned.</b>")
            except ValueError:
                await message.reply("<b>❌ Invalid ID.</b>")

        # ── /broadcast (admin) ────────────────────────────────────────────────

        @app.on_message(filters.command("broadcast") & filters.private)
        async def _broadcast(client: Client, message: Message):
            if not await is_admin(message.from_user.id):
                return
            if not message.reply_to_message:
                return await message.reply("<b>❌ Reply to a message.</b>")
            b = await message.reply("<b>⏳ Broadcasting…</b>")
            users = await worker_db.full_userbase()
            ok = fail = 0
            for uid in users:
                try:
                    await message.reply_to_message.copy(uid)
                    ok += 1
                    await asyncio.sleep(0.1)
                except Exception:
                    fail += 1
            await b.edit(
                f"<b>✅ Broadcast Done</b>\n\n"
                f"<b>Total:</b> {len(users)}\n"
                f"<b>Success:</b> {ok}  <b>Failed:</b> {fail}"
            )

        # ── link_gen (genlink, batch, custom_batch, flink) ────────────────────

        from multi.link_gen import setup_link_gen
        setup_link_gen(app, log_channel_id, is_admin)

        # ── Start the client ──────────────────────────────────────────────────

        try:
            await app.start()
            app.set_parse_mode(ParseMode.HTML)
            await app.set_bot_commands([
                BotCommand("start",        "Start / retrieve files"),
                BotCommand("genlink",      "Generate single link"),
                BotCommand("batch",        "Batch link (range)"),
                BotCommand("custom_batch", "Custom batch link"),
                BotCommand("flink",        "Formatted link list"),
                BotCommand("broadcast",    "Broadcast (admin)"),
            ])
            me = await app.get_me()
            log.info(f"Worker started: @{me.username} ({bot_id})")
            async with self._lock:
                self.workers[bot_id] = app
        except Exception as e:
            log.error(f"start_worker {bot_id}: {e}")
            raise

    async def stop_worker(self, bot_id: int):
        async with self._lock:
            app = self.workers.pop(bot_id, None)
        if app:
            try:
                await asyncio.wait_for(app.stop(block=False), timeout=5.0)
                log.info(f"Worker stopped: {bot_id}")
            except Exception as e:
                log.error(f"stop_worker {bot_id}: {e}")

    async def stop_all_workers(self):
        async with self._lock:
            ids = list(self.workers.keys())
        for bid in ids:
            await self.stop_worker(bid)
        log.info("All workers stopped")

    def get_worker(self, bot_id: int) -> Client | None:
        return self.workers.get(bot_id)

    @property
    def active_count(self) -> int:
        return len(self.workers)


# ── Auto-delete helper ────────────────────────────────────────────────────────

async def _auto_delete(messages, notification, delay: int, reload_url: str | None):
    await asyncio.sleep(delay)
    for msg in messages:
        try:
            await msg.delete()
        except Exception:
            pass
    try:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📥 Get Again", url=reload_url)]]) if reload_url else None
        await notification.edit(
            "<b>🗑 Files auto-deleted.</b>\n<blockquote>Click below to get again.</blockquote>",
            reply_markup=kb,
        )
    except Exception:
        pass


# ── Global singleton ──────────────────────────────────────────────────────────

worker_engine = WorkerEngine()
