"""Single entry point: Telegram bot + admin panel + file streaming, one process.

    python main.py

Pyrogram, Motor and Quart all live in ONE event loop. That is what lets the web
routes stream files through the bot's own logged-in Telegram client.
"""
import asyncio
import signal
from datetime import datetime, timezone, timedelta

import pyrogram.utils
# Support newer large channel IDs (ported from Multi-FileStoreBot run.py)
pyrogram.utils.MIN_CHANNEL_ID = -1009147483647

from hypercorn.asyncio import serve
from hypercorn.config import Config as HypercornConfig

from config import LOGGER

log = LOGGER("main", "web")


async def _hibernation_task(main_bot):
    """Auto-hibernate worker bots idle for > HIBERNATION_HOURS (ported from Multi run.py).
    Runs every hour; skipped when HIBERNATION_HOURS is 0."""
    import logging
    _log = logging.getLogger("hibernation")
    try:
        from config import HIBERNATION_HOURS
        if not HIBERNATION_HOURS:
            return
        from multi.registry import RegistryDB
        from multi.engine import worker_engine
        db = RegistryDB()
        while True:
            await asyncio.sleep(3600)
            _log.info("Hibernation sweep…")
            now = datetime.now(timezone.utc)
            for bot in await db.get_all_active_bots():
                la = bot.get("last_active") or bot.get("created_at") or now
                if la.tzinfo is None:
                    la = la.replace(tzinfo=timezone.utc)
                if now - la > timedelta(hours=HIBERNATION_HOURS):
                    bid = bot["_id"]
                    _log.info(f"Hibernating bot {bid}")
                    await worker_engine.stop_worker(bid)
                    await db.set_bot_active(bid, False)
                    try:
                        await main_bot.send_message(
                            bot["owner_id"],
                            f"<b>💤 Bot Hibernated</b>\n\n"
                            f"<blockquote>@{bot.get('bot_username','?')} was auto-stopped after "
                            f"{HIBERNATION_HOURS}h of inactivity.\n\n"
                            f"Tap <b>🟢 Start Bot</b> in your dashboard to wake it up.</blockquote>",
                        )
                    except Exception:
                        pass
    except Exception as e:
        logging.getLogger("hibernation").error(f"Hibernation task crashed: {e}")


async def main():
    # Imported here on purpose: pyrogram/motor look up the event loop at import
    # time, so the loop must already be running.
    from config import (
        ADMINS, AUTO_DEL, API_HASH, API_ID, DB_CHANNEL, DB_NAME, DB_URI,
        DISABLE_BTN, FSUBS, HOST, MESSAGES, PORT, PROTECT, SESSION, TOKEN, WORKERS,
    )
    import pyrogram.utils
    # Newer channel ids (e.g. -1003483476894) are rejected by older limits (from Multi-FileStoreBot)
    pyrogram.utils.MIN_CHANNEL_ID = min(getattr(pyrogram.utils, "MIN_CHANNEL_ID", 0), -1009147483647)
    from bot import Bot
    from app import create_app
    from helper.activity import ensure_indexes
    from helper import file_index, scheduler

    bot = Bot(
        SESSION, WORKERS, DB_CHANNEL, FSUBS, TOKEN, ADMINS, MESSAGES,
        AUTO_DEL, DB_URI, DB_NAME, API_ID, API_HASH, PROTECT, DISABLE_BTN,
    )
    app = create_app(bot)

    hc = HypercornConfig()
    hc.bind = [f"{HOST}:{PORT}"]
    hc.accesslog = None  # one line per Range request is just noise

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows
            pass

    # Web first: Render/Heroku health checks must find the port open while the
    # bot is still connecting. Stream routes answer 503 until the bot is ready.
    server = asyncio.create_task(serve(app, hc, shutdown_trigger=stop.wait))
    waiter = asyncio.create_task(stop.wait())
    jobs = []
    try:
        await bot.start()  # exits the process itself on bad DB channel / fsub setup
        await ensure_indexes(bot)
        await file_index.ensure_indexes(bot)
        from helper import verify_web
        await verify_web.ensure_indexes(bot.mongodb.db)
        jobs = scheduler.start(bot)  # premium reminders/cleanup + auto backup

        # ── Multi-user worker engine ───────────────────────────────────────────
        # hibernation task defined below
        try:
            from multi.engine import worker_engine
            from multi.helpers import set_main_bot
            set_main_bot(bot)            # used by send_main_log to reach MAIN_LOG_CHANNEL
            await worker_engine.start_all_workers()
            log.info("Multi worker engine started (%d bots)", worker_engine.active_count)
            asyncio.create_task(_hibernation_task(bot))
            # Startup notice to owner (ported from Multi run.py)
            try:
                from config import OWNER_ID
                me = await bot.get_me()
                await bot.send_message(
                    OWNER_ID,
                    "<b>All Systems Online!</b>\n\n"
                    f"<blockquote>Main Bot: @{me.username}\n"
                    f"Active Workers: {worker_engine.active_count}</blockquote>",
                )
            except Exception as _notify_err:
                log.warning("Startup notice failed: %s", _notify_err)
        except Exception as _multi_err:
            log.error("Worker engine failed to start: %s", _multi_err)
        # ─────────────────────────────────────────────────────────────────────

        log.info("Web server on %s:%s", HOST, PORT)
        await asyncio.wait({server, waiter}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        stop.set()
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
        try:
            from multi.engine import worker_engine
            await worker_engine.stop_all_workers()
        except Exception:
            pass
        try:
            await bot.stop()
        except Exception:
            pass  # never got as far as connecting
        await asyncio.gather(server, waiter, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
