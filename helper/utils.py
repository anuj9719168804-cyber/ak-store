"""Small pure-python helpers (no Telegram/Mongo imports, safe to use anywhere)."""
import secrets
import string


def format_bytes(size) -> str:
    """1536 -> '1.5 KB'. Bad or negative input -> '0 B'."""
    try:
        size = float(size)
    except (TypeError, ValueError):
        return "0 B"
    if size < 0:
        return "0 B"
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    n = 0
    while size >= 1024 and n < len(units) - 1:
        size /= 1024
        n += 1
    return f"{int(size)} B" if n == 0 else f"{round(size, 2)} {units[n]}"


def generate_token(length: int = 32) -> str:
    """Random URL-safe token (letters + digits), from the `secrets` module."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(max(int(length), 1)))


def to_int(value, default: int = 0) -> int:
    """int(value) that never raises: ' 42 ' -> 42, 'abc'/None -> default."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def mask_api_key(key) -> str:
    """'abcdef123456' -> '****3456'. Empty -> 'Not set'. Used so API keys are never shown in full."""
    key = str(key or "")
    if not key:
        return "Not set"
    return "****" if len(key) <= 4 else f"****{key[-4:]}"


BANNED_TEXT = "**You have been banned from using this bot!**"


async def ban_notice(mongo, user_id) -> str:
    """The text a banned user sees. Includes the reason when the ban was made with one (panel / `/ban id reason`)."""
    try:
        reason = await mongo.get_ban_reason(user_id)
    except Exception:
        reason = ""
    if not reason:
        return BANNED_TEXT
    return f"{BANNED_TEXT}\n\n**Reason:** {reason}"


def split_ban_args(words) -> tuple:
    """['123', '456', 'spam', 'bot'] -> ([123, 456], 'spam bot'). Ids first, the rest is the reason (max 200)."""
    words = list(words)
    ids = []
    while words and words[0].lstrip("-").isdigit():
        ids.append(int(words.pop(0)))
    return ids, " ".join(words)[:200]
