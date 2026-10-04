"""Add a bot admin straight in the database:  python -m scripts.create_admin [user_id]

Admins saved this way are loaded when the bot starts. The owner (OWNER_ID in
config.py) is always an admin, this is only for extra admins.
"""
import asyncio
import sys

from config import DB_NAME, DB_URI


async def main():
    from helper import MongoDB
    if not DB_URI:
        print("❌ DB_URI is empty in config.py")
        return
    try:
        raw = sys.argv[1] if len(sys.argv) > 1 else input("Enter Telegram user ID: ")
        user_id = int(raw.strip())
    except ValueError:
        print("❌ That is not a valid numeric user ID.")
        return

    added = await MongoDB(DB_URI, DB_NAME).add_admin(user_id)
    print("✅ Admin added. Restart the bot to apply." if added else "ℹ️ That user is already an admin.")


if __name__ == "__main__":
    asyncio.run(main())
