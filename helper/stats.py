"""Usage counters for the dashboard graph and the per-link click tracker.

    stats_daily   _id = "YYYY-MM-DD" (IST, same clock as /autopost), one small document per day,
                  integer counters: clicks, delivered, new_users, verified, bypass, orders, revenue
    link_stats    _id = the link payload exactly as it appears after ?start= (also "lk_<token>")
                  clicks, first, last

Everything here is bookkeeping: it must never break a file delivery, so every database
error is logged and swallowed.
"""
import logging
from datetime import datetime, timedelta, timezone

log = logging.getLogger("stats")

IST = timezone(timedelta(hours=5, minutes=30))
FIELDS = ("clicks", "delivered", "new_users", "verified", "bypass", "orders", "revenue")


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC, what Mongo stores


def day_key(now=None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.astimezone(IST).strftime("%Y-%m-%d")


async def bump(db, field: str, n: int = 1):
    """+n on today's counter. Never raises."""
    try:
        await db["stats_daily"].update_one({"_id": day_key()}, {"$inc": {field: int(n)}}, upsert=True)
    except Exception as e:
        log.warning("Could not update stats (%s): %s", field, e)


async def count_click(db, key: str):
    """+1 click for a link payload and for today. Never raises."""
    try:
        now = _now()
        await db["link_stats"].update_one(
            {"_id": key},
            {"$inc": {"clicks": 1}, "$set": {"last": now}, "$setOnInsert": {"first": now}},
            upsert=True,
        )
    except Exception as e:
        log.warning("Could not count link click: %s", e)
    await bump(db, "clicks")


async def series(db, days: int = 14) -> list:
    """Last `days` days, oldest first, missing days filled with zeros."""
    today = datetime.now(timezone.utc).astimezone(IST).date()
    keys = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days - 1, -1, -1)]
    found = {}
    try:
        async for doc in db["stats_daily"].find({"_id": {"$in": keys}}):
            found[doc["_id"]] = doc
    except Exception as e:
        log.warning("Could not read stats: %s", e)
    rows = []
    for key in keys:
        doc = found.get(key, {})
        row = {"day": key, "label": key[5:]}
        for field in FIELDS:
            row[field] = int(doc.get(field, 0) or 0)
        rows.append(row)
    return rows


async def top_links(db, limit: int = 10) -> list:
    try:
        return await db["link_stats"].find({}).sort([("clicks", -1)]).limit(limit).to_list(length=limit)
    except Exception as e:
        log.warning("Could not read link stats: %s", e)
        return []


async def link_detail(db, key: str):
    try:
        return await db["link_stats"].find_one({"_id": key})
    except Exception:
        return None
