"""Quality / episode parsing from file names (ported from the src bot's Akbots/quality_detector.py).

Pure functions, no Telegram or Mongo. Used by plugins/auto_batch.py to decide which uploads are
quality variants of the same title.
"""
import re
from typing import Optional

# name -> (regex, rank). Lower rank = lower quality. Longest/most specific first so '2160p' is not read as '160p'.
QUALITIES = {
    "4K": (r"(?<![0-9a-z])(?:4k|2160p)(?![0-9a-z])", 7),
    "1440p": (r"(?<![0-9a-z])(?:1440p|2k)(?![0-9a-z])", 5.5),
    "1080p": (r"(?<![0-9])1080p", 5),
    "720p": (r"(?<![0-9])720p", 4),
    "480p": (r"(?<![0-9])480p", 3),
    "360p": (r"(?<![0-9])360p", 2),
    "240p": (r"(?<![0-9])240p", 1),
    "144p": (r"(?<![0-9])144p", 0),
    "HDRip": (r"hd[\s._-]?rip", 6),
}

_EPISODE = re.compile(r"\bS\d{1,3}[\s._-]?E\d{1,4}\b|\bE(?:p(?:isode)?)?[\s._-]?\d{1,4}\b", re.IGNORECASE)
_NOISE = (
    r"\bS\d+[\s._-]?E\d+\b", r"\bS\d+\b", r"\bSeason\s*\d+\b", r"\bEpisode\s*\d+\b", r"\bEp?\s?\d{1,4}\b",
    r"\b(?:19|20)\d{2}\b", r"\bBlu[\s]?Ray\b", r"\bBR[\s]?Rip\b", r"\bWEB[\s]?Rip\b", r"\bWEB[\s]?DL\b", r"\bHDTV\b", r"\bH[\s.]?26[45]\b", r"\b10[\s]?bit\b", r"\bx26[45]\b",
    r"\bHEVC\b", r"\bDual\b", r"\bAudio\b", r"\bMulti\b", r"\b(?:mkv|mp4|avi|webm)\b", r"\[.*?\]", r"\(.*?\)",
)


def extract_quality(filename: str) -> Optional[str]:
    """'Show.S01E01.720p.mkv' -> '720p'; None when no quality tag is present."""
    for name, (pattern, _) in QUALITIES.items():
        if re.search(pattern, filename or "", re.IGNORECASE):
            return name
    return None


def quality_rank(quality: str) -> int:
    return QUALITIES.get(quality, (None, 99))[1]


def _clean(filename: str) -> str:
    name = filename.rsplit(".", 1)[0] if "." in filename else filename
    name = re.sub(r"\[.*?\]|\(.*?\)", " ", name)          # drop [group] / (year) tags before separators go
    name = re.sub(r"[.\-_/;:,\\]+", " ", name)
    for pattern, _ in QUALITIES.values():
        name = re.sub(pattern, " ", name, flags=re.IGNORECASE)
    for pattern in _NOISE:
        name = re.sub(pattern, " ", name, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", name).strip().lower()


def episode_marker(filename: str) -> str:
    """'S01E02' / 'E07' as found in the name, upper-cased with separators removed; '' if none."""
    m = _EPISODE.search(re.sub(r"[.\-_]+", " ", filename or ""))
    return re.sub(r"[\s]+", "", m.group(0)).upper() if m else ""


def group_key(filename: str) -> str:
    """Two uploads share a key when they are the same title AND the same episode (so only the
    quality differs). '' when the name has nothing left to group by."""
    base = _clean(filename or "")
    if not base:
        return ""
    return f"{base}|{episode_marker(filename)}"


def display_title(filename: str) -> str:
    base = _clean(filename or "").title()
    ep = episode_marker(filename)
    return f"{base} {ep}".strip()
