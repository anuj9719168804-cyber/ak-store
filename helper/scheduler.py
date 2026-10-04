"""Background jobs that run inside the bot process (started from main.py).

  premium job  every PREMIUM_CHECK_HOURS
      * ONE reminder to each premium user who has PREMIUM_REMINDER_DAYS (or less) left
      * removes expired premium users (and tells the ones that expired recently)
      * once a day: the bot's own database maintenance (old fsub / join-request records)
        -> replaces running `python -m scripts.cleanup_expired` by hand

  backup job   checked hourly, runs when AUTO_BACKUP_HOURS have passed
      * dumps MongoDB and sends the .tar.gz to the owner on Telegram
      * the time of the last backup is stored in MongoDB, so a restart does not
        trigger an extra backup (or skip one)

Every job catches its own errors: a failing job is logged and retried at the next
interval, it never takes the bot down.
"""
import asyncio
import os
import time
from datetime import datetime, timedelta

from pyrogram.errors import FloodWait, InputUserDeactivated, PeerIdInvalid, UserIsBlocked
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import AUTO_BACKUP_HOURS, DB_NAME, LOGGER, PREMIUM_CHECK_HOURS, PREMIUM_REMINDER_DAYS, RENEW_URL
from helper.utils import format_bytes

log = LOGGER("scheduler", "bot")

EXPIRED_NOTICE_DAYS = 3            # only tell users whose premium ended within this many days
_MAX_SEND_BYTES = 1900 * 1024 * 1024  # stay below Telegram's 2 GB upload limit
_DAY = 86400
_last_db_cleanup = 0.0             # monotonic time of the last daily maintenance run

DEFAULT_REMINDER = (
    "<b>⏰ Your premium is about to expire</b>\n"
    "<blockquote>Expires on: {expiry} ({left} left)</blockquote>\n"
    "Renew now to keep unlimited access without token verification."
)
DEFAULT_EXPIRED = (
    "<b>⌛ Your premium has expired</b>\n"
    "You are back on the free plan (credits + verification). Renew any time to get premium again."
)


# ------------------------------------------------------------------ helpers

def _wait_seconds(exc) -> int:
    return int(getattr(exc, "value", None) or getattr(exc, "x", None) or 5)


def time_left_text(delta: timedelta) -> str:
    hours = max(int(delta.total_seconds() // 3600), 1)
    return f"{hours // 24}d {hours % 24}h" if hours >= 24 else f"{hours}h"


def _render(bot, key, default, **values) -> str:
    """Message from config MESSAGES (editable there), falling back to the built-in text."""
    template = (getattr(bot, "messages", None) or {}).get(key) or default
    try:
        return template.format(**values)
    except (KeyError, IndexError, ValueError):
        return default.format(**values)


def _renew_markup():
    return InlineKeyboardMarkup([[InlineKeyboardButton("💎 Renew premium", url=RENEW_URL)]])


async def _notify(bot, user_id, text, markup=None):
    """True = delivered, False = user can't be reached (don't retry), None = try again later."""
    for _ in range(2):
        try:
            await bot.send_message(user_id, text, reply_markup=markup, disable_web_page_preview=True)
            return True
        except FloodWait as e:
            await asyncio.sleep(_wait_seconds(e) + 1)
        except (UserIsBlocked, InputUserDeactivated, PeerIdInvalid):
            return False
        except Exception as e:
            log.warning(f"Could not message {user_id}: {e}")
            return None
    return None


async def _get_state(bot, key, default=None):
    doc = await bot.mongodb.user_data.find_one({"_id": "job_state"})
    return (doc or {}).get(key, default)


async def _set_state(bot, **values):
    await bot.mongodb.user_data.update_one({"_id": "job_state"}, {"$set": values}, upsert=True)


# ------------------------------------------------------------ premium expiry

async def premium_maintenance(bot, now=None) -> dict:
    """Send due reminders, remove expired premium users. Returns what it did."""
    now = now or datetime.now()  # Pro stores naive local datetimes
    col = bot.mongodb.premium_users
    done = {"reminded": 0, "expired_notified": 0, "removed": 0}

    if PREMIUM_REMINDER_DAYS > 0:
        window = now + timedelta(days=PREMIUM_REMINDER_DAYS)
        due = await col.find({"expiry_date": {"$gt": now, "$lte": window}}).to_list(length=5000)
        for doc in due:
            expiry = doc["expiry_date"]
            # `reminded_for` holds the expiry date we already warned about. Renewing gives a
            # new expiry date, so the next period automatically gets its own reminder.
            if doc.get("reminded_for") == expiry:
                continue
            text = _render(bot, "PREMIUM_REMINDER", DEFAULT_REMINDER,
                           expiry=expiry.strftime("%Y-%m-%d %H:%M"), left=time_left_text(expiry - now))
            result = await _notify(bot, doc["_id"], text, _renew_markup())
            if result is not None:
                await col.update_one({"_id": doc["_id"]}, {"$set": {"reminded_for": expiry}})
            if result:
                done["reminded"] += 1
            await asyncio.sleep(0.05)

    # expiry_date None / missing (permanent) never matches $lt, so those are never touched
    expired = await col.find({"expiry_date": {"$lt": now}}).to_list(length=5000)
    recent_from = now - timedelta(days=EXPIRED_NOTICE_DAYS)
    for doc in expired:
        if doc["expiry_date"] >= recent_from:
            text = _render(bot, "PREMIUM_EXPIRED", DEFAULT_EXPIRED)
            if await _notify(bot, doc["_id"], text, _renew_markup()):
                done["expired_notified"] += 1
            await asyncio.sleep(0.05)
    if expired:
        result = await col.delete_many({"_id": {"$in": [d["_id"] for d in expired]}})
        done["removed"] = result.deleted_count
    return done


async def premium_job(bot):
    global _last_db_cleanup
    done = await premium_maintenance(bot)
    if any(done.values()):
        log.info("Premium check: %s", done)
    if _last_db_cleanup == 0.0 or time.monotonic() - _last_db_cleanup >= _DAY:
        ok = await bot.mongodb.cleanup_database()
        _last_db_cleanup = time.monotonic()
        log.info("Daily database maintenance: %s", "done" if ok else "finished with errors")


# ------------------------------------------------------------------- backups

async def _tell_owner(bot, text):
    try:
        await bot.send_message(bot.owner, text, disable_web_page_preview=True)
    except Exception as e:
        log.warning(f"Could not message the owner: {e}")


async def run_backup(bot, reason="scheduled"):
    """Dump the database and send it to the owner -> (ok, summary text)."""
    from scripts import backup_db  # imported late: only needed when a backup actually runs

    await _set_state(bot, last_backup=time.time())  # set first: a crash must not cause a backup storm
    try:
        path, method = await asyncio.to_thread(backup_db.make_backup, True)
    except backup_db.BackupError as e:
        message = f"❌ Database backup failed: {e}"
    except Exception as e:
        log.exception("Backup crashed")
        message = f"❌ Database backup failed: {type(e).__name__}"
    else:
        size = os.path.getsize(path)
        if size > _MAX_SEND_BYTES:
            message = (f"⚠️ Backup created but it is {format_bytes(size)}, too big to send on Telegram. "
                       f"It is stored on the server: {path}")
        else:
            caption = (f"🗄 <b>Database backup</b> ({reason})\n"
                       f"<code>{DB_NAME}</code> · {format_bytes(size)} · {method}\n"
                       f"{datetime.now().strftime('%Y-%m-%d %H:%M')}")
            try:
                await bot.send_document(bot.owner, path, caption=caption)
                log.info("Backup sent to the owner (%s, %s)", format_bytes(size), method)
                return True, f"Backup sent ({format_bytes(size)})."
            except Exception as e:
                log.warning(f"Could not send the backup: {e}")
                message = f"⚠️ Backup created ({path}) but sending it failed: {type(e).__name__}"
    await _tell_owner(bot, message)
    return False, message


async def backup_job(bot):
    if AUTO_BACKUP_HOURS <= 0:
        return
    last = await _get_state(bot, "last_backup", 0)
    if time.time() - last < AUTO_BACKUP_HOURS * 3600 - 120:  # checked hourly; small tolerance
        return
    await run_backup(bot, "scheduled")


# -------------------------------------------------------------------- runner

async def _forever(name, interval, job, bot, first_delay):
    await asyncio.sleep(first_delay)  # let the bot settle after a (re)start
    while True:
        try:
            await job(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Background job '%s' failed, will retry in %ss", name, interval)
        await asyncio.sleep(interval)


def start(bot):
    """Start the background jobs, returns the tasks so main.py can cancel them on shutdown."""
    tasks = [asyncio.create_task(_forever("premium", PREMIUM_CHECK_HOURS * 3600, premium_job, bot, 60))]
    if AUTO_BACKUP_HOURS > 0:
        tasks.append(asyncio.create_task(_forever("backup", 3600, backup_job, bot, 120)))
    from helper.autopost import autopost_job  # scheduled posts to promo channels (/autopost)
    tasks.append(asyncio.create_task(_forever("autopost", 20, autopost_job, bot, 30)))
    from helper import alerts  # owner alerts: lost channels, dead worker tokens
    tasks.extend(alerts.start(bot))
    return tasks
