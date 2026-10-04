"""In-memory per-key cooldown (used by plugins/rate_limit.py).

Only the first *allowed* hit starts a window; hits inside the window are refused
and do NOT extend it, so a spammer can't lock themselves out forever.
"""
import time

_PRUNE_AT = 5000  # start dropping stale entries once the table gets this big


class RateLimiter:
    def __init__(self):
        self._last = {}       # key -> time of the last allowed hit
        self._warned = set()  # keys already told to slow down in this window

    def check(self, key, seconds: float):
        """Return (allowed, seconds_left, first_refusal_in_window)."""
        now = time.monotonic()
        last = self._last.get(key)
        if last is not None and now - last < seconds:
            first = key not in self._warned
            self._warned.add(key)
            return False, seconds - (now - last), first
        self._last[key] = now
        self._warned.discard(key)
        if len(self._last) > _PRUNE_AT:
            self._prune(now, seconds)
        return True, 0.0, False

    def _prune(self, now, seconds):
        for key in [k for k, t in self._last.items() if now - t >= seconds]:
            del self._last[key]
            self._warned.discard(key)


limiter = RateLimiter()
