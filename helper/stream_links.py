"""Signed watch/download links for messages stored in a DB channel.

A link points at (channel, message) and is signed with STREAM_SECRET, so it can't
be guessed or edited. Force-sub, credits and the shortener only guard the Telegram
deep links, so stream links are created only for admins (see channel_post/genlink).
"""
import hashlib
import hmac
import html
import re
import time

from config import STREAM_SECRET, STREAM_PATH, WEB_URL
from helper import linkttl
from helper.streamer import extract_media

_REF_RE = re.compile(r"^(\d+)_(\d+)$")


def links_enabled() -> bool:
    return bool(WEB_URL)


def make_ref(chat_id: int, msg_id: int) -> str:
    return f"{abs(int(chat_id))}_{int(msg_id)}"


def parse_ref(ref: str):
    """'1001234567890_42' -> (-1001234567890, 42); None if malformed."""
    m = _REF_RE.match(ref or "")
    if not m:
        return None
    return -int(m.group(1)), int(m.group(2))


def _signature(ref: str, exp: int) -> str:
    digest = hmac.new(STREAM_SECRET.encode(), f"{ref}:{exp}".encode(), hashlib.sha256)
    return digest.hexdigest()[:32]


def sign_query(ref: str, ttl: int = None) -> str:
    ttl = linkttl.get() if ttl is None else int(ttl)
    exp = 0 if ttl <= 0 else int(time.time()) + ttl
    return f"exp={exp}&sig={_signature(ref, exp)}"


def verify(ref: str, exp, sig) -> bool:
    try:
        exp = int(exp)
    except (TypeError, ValueError):
        return False
    if exp < 0 or not sig:
        return False
    if exp and int(time.time()) > exp:
        return False
    return hmac.compare_digest(_signature(ref, exp), str(sig))


def build_links(chat_id: int, msg_id: int, ttl: int = None) -> dict:
    ref = make_ref(chat_id, msg_id)
    query = sign_query(ref, ttl)
    base = WEB_URL.rstrip("/")
    direct = f"{base}{STREAM_PATH}/{ref}?{query}"
    return {
        "watch": f"{base}/watch/{ref}?{query}",
        "direct": direct,
        "download": f"{direct}&download=1",
    }


async def stream_block(client, chat_id: int, msg_id: int, message=None) -> str:
    """HTML snippet with watch/download links for a DB-channel message ('' if none)."""
    if not links_enabled():
        return ""
    try:
        if message is None:
            message = await client.get_messages(chat_id, msg_id)
        if not extract_media(message):
            return ""
        links = build_links(chat_id, msg_id)
    except Exception:
        return ""

    esc = lambda u: html.escape(u, quote=True)
    ttl = linkttl.get()
    if ttl > 0:
        note = f"\n<i>web links expire in {linkttl.readable(ttl)}</i>"
    else:
        note = ""
    return (
        "\n\n<b>Web player</b>\n"
        f"▶️ <a href=\"{esc(links['watch'])}\">Watch</a>  •  "
        f"⬇️ <a href=\"{esc(links['download'])}\">Download</a>"
        f"{note}"
    )
