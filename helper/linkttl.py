"""How long NEW web (watch / download) links stay valid, changeable while the bot runs.

Idea from the src bot's /set_expiry. The env value STREAM_LINK_TTL is the default; an admin override is
saved in the bot settings (key `stream_ttl`) and survives restarts. Links already handed out keep the
expiry they were signed with.
"""
import re

from config import STREAM_LINK_TTL

MAX_SECONDS = 365 * 86400
_override = None          # None = use the env default


def get() -> int:
    return STREAM_LINK_TTL if _override is None else _override


def is_override() -> bool:
    return _override is not None


def apply(value):
    """Set in memory only. None = back to the default."""
    global _override
    _override = None if value is None else int(value)


async def load(mongo):
    """Call once at start-up. Never raises."""
    try:
        saved = await mongo.get_bot_setting("stream_ttl", None)
        apply(saved if isinstance(saved, int) and 0 <= saved <= MAX_SECONDS else None)
    except Exception:
        pass


async def save(mongo, value):
    """value None = reset to default. Applies at once and persists."""
    apply(value)
    await mongo.update_bot_setting("stream_ttl", value)


_PART = re.compile(r"(\d+)\s*([dhms]?)")


def parse_duration(text):
    """'1h30m' -> 5400, '45m' -> 2700, '3600' -> 3600, '0'/'off'/'never' -> 0. Bad input or > 1 year -> None."""
    t = (text or "").strip().lower().replace(" ", "")
    if t in ("0", "off", "never", "none"):
        return 0
    if not t or not re.fullmatch(r"(?:\d+[dhms]?)+", t):
        return None
    units = {"d": 86400, "h": 3600, "m": 60, "s": 1, "": 1}
    total = sum(int(n) * units[u] for n, u in _PART.findall(t))
    return total if 0 < total <= MAX_SECONDS else None


def readable(seconds: int) -> str:
    if seconds <= 0:
        return "never (links do not expire)"
    out = []
    for name, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        n, seconds = divmod(seconds, size)
        if n:
            out.append(f"{n}{name}")
    return " ".join(out)
