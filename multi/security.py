"""Token encryption / masking for worker bot tokens at rest.

Uses Fernet (cryptography library) when ENCRYPTION_KEY is configured;
falls back to plain-text storage so the system still works without it.
Set ENCRYPTION_KEY to a Fernet key generated with:
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
import logging

log = logging.getLogger(__name__)

_fernet = None
_fernet_ready = False


def _get_fernet():
    global _fernet, _fernet_ready
    if _fernet_ready:
        return _fernet
    _fernet_ready = True
    try:
        from config import ENCRYPTION_KEY
        if not ENCRYPTION_KEY:
            return None
        from cryptography.fernet import Fernet
        key = ENCRYPTION_KEY.encode() if isinstance(ENCRYPTION_KEY, str) else ENCRYPTION_KEY
        _fernet = Fernet(key)
    except ImportError:
        log.warning("cryptography not installed — tokens stored as plain text. "
                    "Add cryptography to requirements.txt and set ENCRYPTION_KEY to enable encryption.")
    except Exception as e:
        log.warning(f"Fernet init failed ({e}) — tokens stored as plain text.")
    return _fernet


def encrypt_token(token: str) -> str:
    """Encrypt a bot token for storage. Returns plain text if encryption is not configured."""
    f = _get_fernet()
    if f:
        try:
            return f.encrypt(token.encode()).decode()
        except Exception as e:
            log.error(f"encrypt_token failed: {e}")
    return token


def decrypt_token(stored: str) -> str:
    """Decrypt a stored bot token. Returns stored value as-is if not encrypted."""
    f = _get_fernet()
    if f:
        try:
            return f.decrypt(stored.encode()).decode()
        except Exception:
            pass  # stored plain-text (no key at time of storage, or key rotated)
    return stored


def mask_token(token: str) -> str:
    """Return a display-safe masked version of a bot token."""
    if not token or ":" not in token:
        return "****"
    bot_id, secret = token.split(":", 1)
    return f"{bot_id}:****...{secret[-4:]}" if len(secret) > 4 else f"{bot_id}:****"


def mask_api_key(key: str) -> str:
    """Return a display-safe masked version of a shortener API key."""
    if not key:
        return "ɴᴏᴛ sᴇᴛ"
    return f"****{key[-4:]}" if len(key) > 4 else "****"
