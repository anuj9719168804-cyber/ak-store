"""Grouping rules for auto-batch (pure, testable). plugins/auto_batch.py does the Telegram part."""
from dataclasses import dataclass

from . import quality


@dataclass(frozen=True)
class Upload:
    msg_id: int
    filename: str
    quality: str


def make_upload(msg_id: int, filename: str):
    """-> (group key, Upload) or None when the file name carries no quality/title to group by."""
    q = quality.extract_quality(filename)
    key = quality.group_key(filename)
    if not q or not key:
        return None
    return key, Upload(msg_id, filename, q)


def ready(uploads) -> list:
    """The uploads that should become one batch, best quality last; [] unless at least two
    DIFFERENT qualities of the title are present."""
    uniq = {}
    for u in uploads:
        uniq[u.msg_id] = u
    items = sorted(uniq.values(), key=lambda u: (quality.quality_rank(u.quality), u.msg_id))
    if len({u.quality for u in items}) < 2:
        return []
    return items


def parse_window(text: str, default: int, lo: int = 5, hi: int = 600):
    """'45' -> 45, clamped to lo..hi. None if not a whole number."""
    try:
        n = int(str(text).strip())
    except (TypeError, ValueError):
        return None
    return max(lo, min(hi, n))
