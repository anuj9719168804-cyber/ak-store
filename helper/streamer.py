"""Framework-independent helpers for streaming Telegram media over HTTP.

Nothing here imports Quart or Pyrogram, so it can be unit-tested on its own.

    info = extract_media(message)                     # MediaInfo | None
    plan = make_plan(info, request.headers.get("Range"), download=False)
    async for chunk in iter_file(client, info.file_id, plan.start, plan.end): ...
"""
import mimetypes
import re
import time
from dataclasses import dataclass, field
from urllib.parse import quote

# Pyrogram's stream_media() works in (at most) 1 MiB chunks.
CHUNK_SIZE = 1024 * 1024

_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")
_MEDIA_KINDS = ("video", "audio", "document", "animation", "voice", "video_note")


class RangeNotSatisfiable(Exception):
    pass


@dataclass
class MediaInfo:
    file_id: str
    size: int
    mime: str
    name: str


def extract_media(message):
    """MediaInfo for a streamable message (video/audio/document/...), else None."""
    if message is None or getattr(message, "empty", False):
        return None
    for kind in _MEDIA_KINDS:
        media = getattr(message, kind, None)
        if media is None:
            continue
        mime = getattr(media, "mime_type", None) or ""
        name = getattr(media, "file_name", None)
        if not name:
            ext = mimetypes.guess_extension(mime) or ""
            name = f"{getattr(media, 'file_unique_id', 'file')}{ext}"
        return MediaInfo(
            file_id=media.file_id,
            size=int(getattr(media, "file_size", 0) or 0),
            mime=mime,
            name=name,
        )
    return None


class MediaCache:
    """Small TTL cache so every Range request of a video doesn't re-fetch the message."""

    def __init__(self, ttl=600, max_items=512):
        self.ttl = ttl
        self.max_items = max_items
        self._data = {}

    def get(self, key):
        hit = self._data.get(key)
        if not hit:
            return None
        if hit[0] < time.monotonic():
            self._data.pop(key, None)
            return None
        return hit[1]

    def discard(self, key):
        self._data.pop(key, None)

    def put(self, key, info):
        if len(self._data) >= self.max_items:
            self._data.pop(next(iter(self._data)), None)  # oldest first
        self._data[key] = (time.monotonic() + self.ttl, info)


def parse_range(header, size):
    """Parse a single-range `Range` header.

    Returns (start, end) inclusive, or None when the header is absent, malformed
    or a multi-range request (RFC 9110 lets us ignore those and send 200).
    Raises RangeNotSatisfiable when the range lies outside the file.
    """
    if not header:
        return None
    m = _RANGE_RE.match(header.strip())
    if not m:
        return None
    first, last = m.group(1), m.group(2)
    if not first and not last:
        return None

    if not first:  # suffix range: last N bytes
        n = int(last)
        if n == 0:
            raise RangeNotSatisfiable()
        return max(size - n, 0), size - 1

    start = int(first)
    if start >= size:
        raise RangeNotSatisfiable()
    if not last:
        return start, size - 1
    end = int(last)
    if end < start:  # invalid spec -> ignore header
        return None
    return start, min(end, size - 1)


def content_type_for(info):
    if info.mime:
        return info.mime
    guessed, _ = mimetypes.guess_type(info.name or "")
    return guessed or "application/octet-stream"


def content_disposition(filename, download=False):
    filename = (filename or "file").replace("\r", "").replace("\n", "")
    ascii_name = filename.encode("ascii", "ignore").decode().replace('"', "") or "file"
    kind = "attachment" if download else "inline"
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"


@dataclass
class StreamPlan:
    status: int
    headers: dict = field(default_factory=dict)
    start: int = 0
    end: int | None = None  # inclusive; None => stream until EOF (size unknown)


def make_plan(info, range_header, download=False):
    """Decide status code, headers and byte window for a file request."""
    size = info.size or None
    headers = {
        "Content-Type": content_type_for(info),
        "Content-Disposition": content_disposition(info.name, download),
        # Signed links are private; don't let shared caches keep the bytes.
        "Cache-Control": "private, max-age=3600",
    }

    if not size:
        headers["Accept-Ranges"] = "none"
        return StreamPlan(200, headers, 0, None)

    headers["Accept-Ranges"] = "bytes"
    try:
        rng = parse_range(range_header, size)
    except RangeNotSatisfiable:
        return StreamPlan(416, {"Content-Range": f"bytes */{size}"})

    if rng is None:
        headers["Content-Length"] = str(size)
        return StreamPlan(200, headers, 0, size - 1)

    start, end = rng
    headers["Content-Length"] = str(end - start + 1)
    headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamPlan(206, headers, start, end)


async def iter_file(client, file_id, start=0, end=None):
    """Yield the bytes [start, end] (inclusive) of a Telegram file (end=None: to EOF)."""
    if end is None:
        async for chunk in client.stream_media(file_id):
            yield chunk
        return

    first_chunk = start // CHUNK_SIZE
    skip = start - first_chunk * CHUNK_SIZE
    remaining = end - start + 1
    chunk_limit = -(-(skip + remaining) // CHUNK_SIZE)  # ceil division

    async for chunk in client.stream_media(file_id, offset=first_chunk, limit=chunk_limit):
        if skip:
            chunk = chunk[skip:]
            skip = 0
        if len(chunk) > remaining:
            chunk = chunk[:remaining]
        if not chunk:
            continue
        remaining -= len(chunk)
        yield chunk
        if remaining <= 0:
            break
