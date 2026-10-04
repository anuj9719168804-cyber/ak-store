"""Owner alerts: tell the owner right away when something important breaks.

  * a DB channel or force-sub channel can no longer be reached (bot removed / lost rights)
  * a worker bot's token stops working (revoked in @BotFather)
  * bypass attempts spike (BYPASS_SPIKE_COUNT hits within BYPASS_SPIKE_MINUTES)
  * a scheduled backup failed (see helper/scheduler.py)

An alert for the same problem is sent once, then again only after COOLDOWN (6 h) if it is still
there; when it recovers the owner gets one "recovered" message. State lives in memory: after a
restart a problem that is still present is reported once more, which is the safe direction.
Every function swallows its own errors: alerting must never break the bot.
"""
import asyncio
import html
import time

from config import (
    ALERTS_ENABLED, ALERT_CHECK_MINUTES, BYPASS_SPIKE_COUNT, BYPASS_SPIKE_MINUTES, LOGGER,
    WORKER_CHECK_MINUTES,
)

log = LOGGER("alerts", "bot")

COOLDOWN = 6 * 3600
_active = {}        # key -> time the alert was last sent
_bypass_hits = []   # timestamps of recent bypass detections
_last_spike = None   # monotonic time of the last spike alert


async def send(bot, text: str):
    if not ALERTS_ENABLED:
        return False
    try:
        await bot.send_message(bot.owner, text, disable_web_page_preview=True)
        return True
    except Exception as e:
        log.warning("Could not send alert to owner: %s", e)
        return False


async def raise_alert(bot, key: str, text: str):
    """Send `text` unless the same `key` was already reported recently."""
    now = time.monotonic()
    last = _active.get(key)
    if last is not None and now - last < COOLDOWN:
        return False
    if await send(bot, text):
        _active[key] = now
        return True
    return False


async def clear_alert(bot, key: str, text: str):
    """The problem is gone: say so once (only if we had reported it)."""
    if _active.pop(key, None) is not None:
        await send(bot, text)


# ---------------------------------------------------------------- channels

async def _can_post_or_read(bot, chat_id: int):
    """None if fine, else a short reason."""
    try:
        member = await bot.get_chat_member(chat_id, "me")
    except Exception as e:
        return f"{type(e).__name__}: {str(e)[:120]}"
    status = getattr(member.status, "name", str(member.status)).upper()
    if status in ("BANNED", "LEFT", "RESTRICTED"):
        return f"bot status is {status.lower()}"
    return None


async def check_channels(bot):
    """DB channels (need read/post) and force-sub channels (need admin to check members)."""
    from web.data import allowed_channels
    problems = []
    for cid in sorted(allowed_channels(bot)):
        key = f"db:{cid}"
        reason = await _can_post_or_read(bot, cid)
        if reason:
            problems.append(key)
            await raise_alert(bot, key,
                              f"🚨 <b>DB channel lost</b>\n<code>{cid}</code>\n{html.escape(reason)}\n"
                              "File links from this channel will fail until the bot has access again.")
        else:
            await clear_alert(bot, key, f"✅ DB channel <code>{cid}</code> is reachable again.")
        await asyncio.sleep(0.3)
    for cid in list(getattr(bot, "fsub_dict", {}).keys()):
        key = f"fsub:{cid}"
        reason = await _can_post_or_read(bot, cid)
        if reason:
            problems.append(key)
            name = html.escape(str(bot.fsub_dict.get(cid, ["?"])[0]))
            await raise_alert(bot, key,
                              f"⚠️ <b>Force-sub channel problem</b>\n{name} (<code>{cid}</code>)\n{html.escape(reason)}\n"
                              "Users may be blocked or let through until this is fixed.")
        else:
            await clear_alert(bot, key, f"✅ Force-sub channel <code>{cid}</code> is fine again.")
        await asyncio.sleep(0.3)
    return problems


# ----------------------------------------------------------------- workers

async def check_workers(bot):
    """Is every active worker's token still accepted by Telegram? A revoked token makes the
    worker fail on start; a running worker whose token was revoked later raises on get_me()."""
    try:
        from multi.engine import worker_engine
        from multi.registry import RegistryDB
    except Exception as e:
        log.warning("Worker check unavailable: %s", e)
        return []
    registry = RegistryDB()
    bad = []
    for doc in await registry.get_all_active_bots():
        bot_id = doc["_id"]
        key = f"worker:{bot_id}"
        app = worker_engine.get_worker(bot_id)
        uname = html.escape(str(doc.get("bot_username", bot_id)))
        if app is None:
            problem = "not running"
        else:
            try:
                await asyncio.wait_for(app.get_me(), timeout=15)
                problem = None
            except Exception as e:
                name = type(e).__name__
                problem = ("token revoked or invalid" if "Unauthorized" in name or "AuthKey" in name
                           or "ACCESS_TOKEN" in str(e).upper() else f"{name}")
        if problem:
            bad.append(bot_id)
            await raise_alert(bot, key,
                              f"⚠️ <b>Worker bot problem</b>\n@{uname} (<code>{bot_id}</code>)\n{html.escape(problem)}\n"
                              f"Its owner: <code>{doc.get('owner_id', '?')}</code>")
        else:
            await clear_alert(bot, key, f"✅ Worker @{uname} is healthy again.")
        await asyncio.sleep(0.5)
    return bad


# ------------------------------------------------------------ bypass spike

async def note_bypass(bot):
    """Call on every bypass detection; alerts when too many land in a short window."""
    global _last_spike
    if BYPASS_SPIKE_COUNT <= 0:
        return
    now = time.monotonic()
    window = BYPASS_SPIKE_MINUTES * 60
    _bypass_hits.append(now)
    while _bypass_hits and now - _bypass_hits[0] > window:
        _bypass_hits.pop(0)
    if len(_bypass_hits) >= BYPASS_SPIKE_COUNT and (_last_spike is None or now - _last_spike > window):
        _last_spike = now
        await send(bot, f"🚨 <b>Bypass spike</b>\n{len(_bypass_hits)} bypass attempts in the last "
                        f"{BYPASS_SPIKE_MINUTES} min.\nSomeone may be running a bypass tool against your links. "
                        "Check the Logs page.")


# ------------------------------------------------------------------ runner

async def channels_job(bot):
    if ALERTS_ENABLED:
        await check_channels(bot)


async def workers_job(bot):
    if ALERTS_ENABLED:
        await check_workers(bot)


def start(bot):
    """Background tasks for main.py's scheduler list."""
    from helper.scheduler import _forever
    if not ALERTS_ENABLED:
        return []
    return [
        asyncio.create_task(_forever("alerts-channels", ALERT_CHECK_MINUTES * 60, channels_job, bot, 90)),
        asyncio.create_task(_forever("alerts-workers", WORKER_CHECK_MINUTES * 60, workers_job, bot, 240)),
    ]
