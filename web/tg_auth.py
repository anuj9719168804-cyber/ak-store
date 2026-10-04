"""Verify Telegram Web App `initData` (https://core.telegram.org/bots/webapps#validating-data)."""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


def verify_init_data(init_data: str, bot_token: str, max_age: int = 600):
    """Return the Telegram user dict if `init_data` is genuine and fresh, else None."""
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
        received = pairs.pop("hash")
        check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
        secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, received):
            return None
        age = time.time() - int(pairs["auth_date"])
        if age > max_age or age < -60:
            return None
        user = json.loads(pairs["user"])
        return user if isinstance(user, dict) and isinstance(user.get("id"), int) else None
    except Exception:
        return None
