"""Housekeeping:  python -m scripts.cleanup_expired

  * removes premium users whose subscription has expired
  * runs the bot's own maintenance (old force-sub statuses / join requests, orphaned records)
Safe to run any time, e.g. daily from cron.
"""
import asyncio
from datetime import datetime

from config import DB_NAME, DB_URI


async def run(mongodb):
    # Only real dates below "now". Permanent premium (expiry None / missing) is never matched.
    result = await mongodb.premium_users.delete_many({"expiry_date": {"$lt": datetime.now()}})
    print(f"🗑  Expired premium removed: {result.deleted_count}")

    ok = await mongodb.cleanup_database()
    print("🧹 Bot database maintenance:", "done" if ok else "finished with errors (see above)")
    return result.deleted_count


async def main():
    from helper import MongoDB
    if not DB_URI:
        print("❌ DB_URI is empty in config.py")
        return
    print("🔄 Cleaning expired data...")
    await run(MongoDB(DB_URI, DB_NAME))
    print("✅ Cleanup complete.")


if __name__ == "__main__":
    asyncio.run(main())
