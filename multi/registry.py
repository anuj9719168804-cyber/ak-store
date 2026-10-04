"""Bot registry and per-worker database layer.

All collections live in the SAME MongoDB database as File-Store-Pro (DB_URI + DB_NAME)
but are prefixed so they never clash with Pro's own collections:

  multi_bots       – registered worker bot docs
  multi_users      – users of the controller (Pro) bot in multi-mode
  multi_cooldowns  – bot-creation cooldown timestamps

Per-worker collections (namespaced by Telegram bot ID):
  mw_{bot_id}_users    – users who started the worker bot
  mw_{bot_id}_admins   – additional admins of the worker bot
  mw_{bot_id}_banned   – banned users
  mw_{bot_id}_channels – force-sub channels
  mw_{bot_id}_req_fsub – join-request tracking (request-mode fsub)
  mw_{bot_id}_del_timer – auto-delete timer setting
  mw_{bot_id}_verify   – shortener-verification timestamps
"""
from datetime import datetime, timezone
import motor.motor_asyncio
import logging

log = logging.getLogger(__name__)

_client = None
_db_obj = None


def _get_db():
    global _client, _db_obj
    if _db_obj is None:
        from config import DB_URI, DB_NAME
        _client = motor.motor_asyncio.AsyncIOMotorClient(DB_URI)
        _db_obj = _client[DB_NAME]
    return _db_obj


# ─────────────────────────────────────────────────────────────────────────────
# RegistryDB — main controller bot's data
# ─────────────────────────────────────────────────────────────────────────────

class RegistryDB:
    """Bot registry and main-controller user management."""

    def __init__(self):
        db = _get_db()
        self.bots = db["multi_bots"]
        self.users = db["multi_users"]
        self.cooldowns = db["multi_cooldowns"]

    # ── Premium (shared with the main bot's `pros` collection) ───────────────

    async def is_premium(self, user_id: int) -> bool:
        """Same rules as MongoDB.is_pro in helper/database.py (expiry-aware)."""
        doc = await _get_db()["pros"].find_one({"_id": user_id})
        if not doc:
            return False
        expiry = doc.get("expiry_date")
        if "expiry_date" not in doc or expiry is None:
            return True  # legacy / permanent premium
        return expiry > datetime.now()

    # ── User management ───────────────────────────────────────────────────────

    async def add_user(self, user_id: int) -> bool:
        if await self.users.find_one({"_id": user_id}):
            return False
        await self.users.insert_one({"_id": user_id, "created_at": datetime.now(timezone.utc)})
        return True

    async def user_exists(self, user_id: int) -> bool:
        return bool(await self.users.find_one({"_id": user_id}))

    async def get_all_users(self) -> list:
        return [d["_id"] async for d in self.users.find()]

    async def total_users(self) -> int:
        return await self.users.count_documents({})

    async def ban_user_exist(self, user_id: int) -> bool:
        doc = await self.users.find_one({"_id": user_id})
        return doc.get("banned", False) if doc else False

    async def add_ban_user(self, user_id: int):
        await self.users.update_one({"_id": user_id}, {"$set": {"banned": True}}, upsert=True)

    async def del_ban_user(self, user_id: int):
        await self.users.update_one({"_id": user_id}, {"$unset": {"banned": ""}})

    # ── Bot registry ──────────────────────────────────────────────────────────

    async def add_bot(self, bot_id: int, owner_id: int, token_enc: str,
                      bot_username: str, log_channel_id: int) -> dict:
        doc = {
            "_id": bot_id,
            "owner_id": owner_id,
            "bot_token_encrypted": token_enc,
            "bot_username": bot_username,
            "log_channel_id": log_channel_id,
            "is_active": True,
            "created_at": datetime.now(timezone.utc),
            "settings": {
                "auto_delete_time": 0,
                "protect_content": False,
                "custom_caption": "",
                "start_pic": "",
                "start_message": "",
                "force_pic": "",
                "permanent_link": False,
            },
            "shortener": {
                "enabled": False,
                "api_key_encrypted": "",
                "domain": "",
                "verify_expire": 86400,
                "tutorial_link": "",
                "tutorial_enabled": False,
            },
        }
        await self.bots.replace_one({"_id": bot_id}, doc, upsert=True)
        log.info(f"Bot @{bot_username} ({bot_id}) registered by {owner_id}")
        return doc

    async def get_bot(self, bot_id: int):
        return await self.bots.find_one({"_id": bot_id})

    async def get_bot_by_token(self, token_encrypted: str):
        return await self.bots.find_one({"bot_token_encrypted": token_encrypted})

    async def get_user_bots(self, owner_id: int) -> list:
        return await self.bots.find(
            {"owner_id": owner_id, "is_deleted": {"$ne": True}}
        ).to_list(None)

    async def count_user_bots(self, owner_id: int) -> int:
        return await self.bots.count_documents(
            {"owner_id": owner_id, "is_deleted": {"$ne": True}}
        )

    async def get_deleted_user_bots(self, owner_id: int) -> list:
        return await self.bots.find(
            {"owner_id": owner_id, "is_deleted": True}
        ).to_list(None)

    async def get_all_active_bots(self) -> list:
        return await self.bots.find({"is_active": True}).to_list(None)

    async def delete_bot(self, bot_id: int) -> bool:
        r = await self.bots.update_one(
            {"_id": bot_id},
            {"$set": {"is_deleted": True, "is_active": False}},
        )
        return r.modified_count > 0

    async def purge_bot(self, bot_id: int) -> bool:
        r = await self.bots.delete_one({"_id": bot_id})
        return r.deleted_count > 0

    async def set_bot_active(self, bot_id: int, active: bool):
        await self.bots.update_one({"_id": bot_id}, {"$set": {"is_active": active}})

    async def update_log_channel(self, bot_id: int, channel_id: int):
        await self.bots.update_one({"_id": bot_id}, {"$set": {"log_channel_id": channel_id}})

    async def update_last_active(self, bot_id: int):
        await self.bots.update_one(
            {"_id": bot_id}, {"$set": {"last_active": datetime.now(timezone.utc)}}
        )

    async def update_setting(self, bot_id: int, key: str, value):
        await self.bots.update_one({"_id": bot_id}, {"$set": {f"settings.{key}": value}})

    async def get_settings(self, bot_id: int) -> dict:
        doc = await self.get_bot(bot_id)
        return doc.get("settings", {}) if doc else {}

    async def update_shortener(self, bot_id: int, key: str, value):
        await self.bots.update_one({"_id": bot_id}, {"$set": {f"shortener.{key}": value}})

    async def get_shortener(self, bot_id: int) -> dict:
        doc = await self.get_bot(bot_id)
        return doc.get("shortener", {}) if doc else {}

    async def set_cooldown(self, user_id: int):
        await self.cooldowns.replace_one(
            {"_id": user_id},
            {"_id": user_id, "timestamp": datetime.now(timezone.utc)},
            upsert=True,
        )

    async def get_cooldown(self, user_id: int):
        doc = await self.cooldowns.find_one({"_id": user_id})
        return doc["timestamp"] if doc else None


# ─────────────────────────────────────────────────────────────────────────────
# WorkerDB — isolated per-worker state
# ─────────────────────────────────────────────────────────────────────────────

class WorkerDB:
    """Database collections scoped to one worker bot (prefix mw_{bot_id}_)."""

    def __init__(self, bot_id: int):
        self.bot_id = bot_id
        db = _get_db()
        p = f"mw_{bot_id}"
        self.users     = db[f"{p}_users"]
        self.admins    = db[f"{p}_admins"]
        self.channels  = db[f"{p}_channels"]
        self.banned    = db[f"{p}_banned"]
        self.req_fsub  = db[f"{p}_req_fsub"]
        self.del_timer = db[f"{p}_del_timer"]
        self.verify    = db[f"{p}_verify"]

    # ── Users ─────────────────────────────────────────────────────────────────

    async def present_user(self, user_id: int) -> bool:
        return bool(await self.users.find_one({"_id": user_id}))

    async def add_user(self, user_id: int):
        if not await self.present_user(user_id):
            await self.users.insert_one({"_id": user_id})

    async def full_userbase(self) -> list:
        return [d["_id"] async for d in self.users.find()]

    async def del_user(self, user_id: int):
        await self.users.delete_one({"_id": user_id})

    async def total_users(self) -> int:
        return await self.users.count_documents({})

    # ── Admins ────────────────────────────────────────────────────────────────

    async def admin_exist(self, admin_id: int) -> bool:
        return bool(await self.admins.find_one({"_id": admin_id}))

    async def add_admin(self, admin_id: int):
        if not await self.admin_exist(admin_id):
            await self.admins.insert_one({"_id": admin_id})

    async def del_admin(self, admin_id: int):
        await self.admins.delete_one({"_id": admin_id})

    async def get_all_admins(self) -> list:
        return [d["_id"] async for d in self.admins.find()]

    # ── Ban ───────────────────────────────────────────────────────────────────

    async def ban_user_exist(self, user_id: int) -> bool:
        return bool(await self.banned.find_one({"_id": user_id}))

    async def add_ban_user(self, user_id: int):
        if not await self.ban_user_exist(user_id):
            await self.banned.insert_one({"_id": user_id})

    async def del_ban_user(self, user_id: int):
        await self.banned.delete_one({"_id": user_id})

    async def get_ban_users(self) -> list:
        return [d["_id"] async for d in self.banned.find()]

    # ── Auto-delete timer ─────────────────────────────────────────────────────

    async def set_del_timer(self, value: int):
        if await self.del_timer.find_one({}):
            await self.del_timer.update_one({}, {"$set": {"value": value}})
        else:
            await self.del_timer.insert_one({"value": value})

    async def get_del_timer(self) -> int:
        doc = await self.del_timer.find_one({})
        return doc.get("value", 0) if doc else 0

    # ── Force-sub channels ────────────────────────────────────────────────────

    async def channel_exist(self, channel_id: int) -> bool:
        return bool(await self.channels.find_one({"_id": channel_id}))

    async def add_channel(self, channel_id: int, mode: str = "off"):
        if not await self.channel_exist(channel_id):
            await self.channels.insert_one({"_id": channel_id, "mode": mode})

    async def rem_channel(self, channel_id: int):
        await self.channels.delete_one({"_id": channel_id})
        await self.req_fsub.delete_one({"_id": channel_id})

    async def show_channels(self) -> list:
        return [d["_id"] async for d in self.channels.find()]

    async def get_channel_mode(self, channel_id: int) -> str:
        doc = await self.channels.find_one({"_id": channel_id})
        return doc.get("mode", "off") if doc else "off"

    async def set_channel_mode(self, channel_id: int, mode: str):
        await self.channels.update_one(
            {"_id": channel_id}, {"$set": {"mode": mode}}, upsert=True
        )

    # ── Request-based fsub ────────────────────────────────────────────────────

    async def req_user(self, channel_id: int, user_id: int):
        try:
            await self.req_fsub.update_one(
                {"_id": int(channel_id)},
                {"$addToSet": {"user_ids": int(user_id)}},
                upsert=True,
            )
        except Exception as e:
            log.error(f"req_user: {e}")

    async def del_req_user(self, channel_id: int, user_id: int):
        try:
            await self.req_fsub.update_one(
                {"_id": int(channel_id)},
                {"$pull": {"user_ids": int(user_id)}},
            )
        except Exception as e:
            log.error(f"del_req_user: {e}")

    async def req_user_exist(self, channel_id: int, user_id: int) -> bool:
        try:
            return bool(await self.req_fsub.find_one(
                {"_id": int(channel_id), "user_ids": int(user_id)}
            ))
        except Exception:
            return False

    # ── Shortener verification ────────────────────────────────────────────────

    async def start_verify(self, user_id: int) -> str:
        """Create a one-time token; the shortener must redirect to start=vf_<token>."""
        import secrets
        token = secrets.token_hex(6)  # 12 hex chars
        await self.verify.update_one(
            {"_id": user_id},
            {"$set": {"pending_token": token, "pending_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
        return token

    async def check_verify(self, user_id: int, token: str, min_s: int, max_s: int):
        """Returns (status, seconds): ok | none | invalid | too_fast | expired.
        The token is burned on every outcome except 'none'/'invalid' (stale link)."""
        doc = await self.verify.find_one({"_id": user_id})
        if not doc or not doc.get("pending_token"):
            return "none", 0
        if doc["pending_token"] != token:
            return "invalid", 0
        pending_at = doc["pending_at"]
        if pending_at.tzinfo is None:
            pending_at = pending_at.replace(tzinfo=timezone.utc)
        secs = int((datetime.now(timezone.utc) - pending_at).total_seconds())
        await self.verify.update_one({"_id": user_id}, {"$unset": {"pending_token": "", "pending_at": ""}})
        if secs < min_s:
            return "too_fast", secs
        if secs > max_s:
            return "expired", secs
        return "ok", secs

    async def add_bypass_strike(self, user_id: int) -> int:
        doc = await self.verify.find_one_and_update(
            {"_id": user_id}, {"$inc": {"bypass_strikes": 1}}, upsert=True, return_document=True,
        )
        return int(doc.get("bypass_strikes", 1))

    async def reset_bypass_strikes(self, user_id: int):
        await self.verify.update_one({"_id": user_id}, {"$set": {"bypass_strikes": 0}})

    async def set_verified(self, user_id: int):
        await self.verify.update_one(
            {"_id": user_id},
            {"$set": {"verified_at": datetime.now(timezone.utc)}},
            upsert=True,
        )

    async def is_verified(self, user_id: int, expire_seconds: int) -> bool:
        doc = await self.verify.find_one({"_id": user_id})
        if not doc or not doc.get("verified_at"):
            return False
        elapsed = (datetime.now(timezone.utc) - doc["verified_at"]).total_seconds()
        return elapsed < expire_seconds

    # ── Data transfer ─────────────────────────────────────────────────────────

    async def copy_data_from(self, source_bot_id: int) -> dict:
        """Copy all mw_{source}_* collections into mw_{self.bot_id}_*."""
        db = _get_db()
        src_prefix = f"mw_{source_bot_id}"
        dst_prefix = f"mw_{self.bot_id}"
        stats = {}
        for col_name in await db.list_collection_names():
            if not col_name.startswith(src_prefix):
                continue
            suffix = col_name[len(src_prefix):]
            docs = await db[col_name].find().to_list(None)
            if docs:
                await db[f"{dst_prefix}{suffix}"].delete_many({})
                await db[f"{dst_prefix}{suffix}"].insert_many(docs)
            stats[suffix.strip("_")] = len(docs)
        return stats

    async def drop_all_collections(self):
        db = _get_db()
        prefix = f"mw_{self.bot_id}"
        for col_name in await db.list_collection_names():
            if col_name.startswith(prefix):
                await db.drop_collection(col_name)
                log.info(f"Dropped {col_name}")
