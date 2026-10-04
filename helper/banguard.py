"""Short-lived cache for the global ban guard (plugins/ban_guard.py).

Idea from AK Ultra's ban_manager: one early handler blocks EVERY message and button press of a banned
user, instead of each command having to remember to check. The guard looks the user up at most once per
TTL seconds; ban_user / unban_user / unban_all_users in helper/database.py call forget() / clear(), so a
ban from this process (bot command or web panel) works at once.

Pure python on purpose: no Telegram or Mongo imports.
"""
import time

TTL = 15.0
_MAX = 20000
_cache = {}       # user id -> (expires_at, banned)


def get(user_id, now: float = None):
    """True / False when cached and fresh, else None (= ask the database)."""
    hit = _cache.get(user_id)
    now = time.monotonic() if now is None else now
    if hit and hit[0] > now:
        return hit[1]
    return None


def put(user_id, banned: bool, now: float = None):
    if len(_cache) >= _MAX:
        _cache.clear()
    now = time.monotonic() if now is None else now
    _cache[user_id] = (now + TTL, bool(banned))


def forget(user_id):
    _cache.pop(user_id, None)


def clear():
    _cache.clear()
