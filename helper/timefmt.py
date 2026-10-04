"""Show stored times in IST (UTC+5:30) in the web panel. Everything is STORED as naive UTC; this is display only.

Not used for premium expiry: Pro stores that as naive server-local time, so it is shown as saved.
"""
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def ist(value, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """naive-UTC datetime -> text in IST. None / not a datetime -> '-'."""
    if not isinstance(value, datetime):
        return "-"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(IST).strftime(fmt)
