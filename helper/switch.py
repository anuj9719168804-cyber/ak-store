"""A boolean read from storage, cached for a few seconds so a busy bot does not hit Mongo on every update."""
import time


class CachedFlag:
    def __init__(self, loader, ttl: float = 15.0, clock=time.monotonic):
        self._loader, self._ttl, self._clock = loader, ttl, clock
        self._value, self._at = False, None

    async def get(self) -> bool:
        now = self._clock()
        if self._at is None or now - self._at > self._ttl:
            try:
                self._value = bool(await self._loader())
            except Exception:
                pass          # keep the last known value if storage hiccups
            self._at = now
        return self._value

    def set(self, value: bool):
        """Call right after saving, so this process sees the change immediately."""
        self._value, self._at = bool(value), self._clock()
