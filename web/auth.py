import hashlib
import hmac
import math
import secrets
import time
from functools import wraps
from urllib.parse import urlparse

from quart import abort, redirect, request, session

from config import ADMIN_PANEL_PATH, ADMIN_PASSWORD, PANEL_SECRET, WEB_URL

_FAIL_WINDOW = 600      # seconds
_FAIL_LIMIT = 5         # wrong passwords per client per window
_GLOBAL_LIMIT = 40      # ... and across all clients (X-Forwarded-For can be spoofed)
_fails = {}             # key -> [timestamps]
_all_fails = []


def _prune(now):
    global _all_fails
    _all_fails = [t for t in _all_fails if now - t < _FAIL_WINDOW]
    for key in list(_fails):
        _fails[key] = [t for t in _fails[key] if now - t < _FAIL_WINDOW]
        if not _fails[key]:
            del _fails[key]


def client_key() -> str:
    fwd = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    return fwd or request.remote_addr or "?"


def login_blocked() -> bool:
    now = time.time()
    _prune(now)
    return len(_fails.get(client_key(), [])) >= _FAIL_LIMIT or len(_all_fails) >= _GLOBAL_LIMIT


def register_failure():
    now = time.time()
    _fails.setdefault(client_key(), []).append(now)
    _all_fails.append(now)


def panel_enabled() -> bool:
    return bool(ADMIN_PASSWORD)


def same_origin() -> bool:
    """POSTs from another site are rejected (Lax cookies already block most of them)."""
    origin = request.headers.get("Origin")
    if not origin or origin == "null":
        return True
    allowed = {request.host}
    if WEB_URL:
        allowed.add(urlparse(WEB_URL).netloc)
    return urlparse(origin).netloc in allowed


# ----------------------------------------------------------------- CSRF

def csrf_token() -> str:
    """Per-session token. Every POST form in the panel carries it as <input name="csrf_token">."""
    token = session.get("csrf")
    if not token:
        token = session["csrf"] = secrets.token_urlsafe(32)
    return token


def csrf_valid(supplied) -> bool:
    expected = session.get("csrf")
    if not expected or not supplied:
        return False
    return hmac.compare_digest(str(expected), str(supplied))


# ------------------------------------------------- two-step login (2FA)
# After the right password, a 6-digit code is sent to the owner on Telegram.
# The code lives ONLY here in server memory. The session cookie is signed but
# readable by the client, so a hash of the code stored there could be brute-forced offline.

CODE_TTL = 300        # seconds a code stays valid
CODE_TRIES = 5        # wrong guesses before the code is burned
CODE_COOLDOWN = 20    # min seconds between codes: a password thief must not be able to spam the owner
_MAX_PENDING = 20
_challenges = {}      # challenge id -> {"hash", "exp", "tries"}
_last_code_at = None  # monotonic time the last code was issued


def _code_hash(cid: str, code: str) -> str:
    return hmac.new(PANEL_SECRET.encode(), f"{cid}:{code}".encode(), hashlib.sha256).hexdigest()


def _prune_challenges(now):
    for cid in [c for c, v in _challenges.items() if v["exp"] <= now]:
        del _challenges[cid]
    while len(_challenges) >= _MAX_PENDING:
        del _challenges[next(iter(_challenges))]  # oldest first


def code_cooldown_left() -> int:
    if _last_code_at is None:
        return 0
    remaining = CODE_COOLDOWN - (time.monotonic() - _last_code_at)
    return math.ceil(remaining) if remaining > 0 else 0


def new_challenge():
    """-> (challenge id for the session, 6-digit code to send to the owner)"""
    global _last_code_at
    now = time.time()
    _prune_challenges(now)
    cid = secrets.token_urlsafe(16)
    code = f"{secrets.randbelow(1_000_000):06d}"
    _challenges[cid] = {"hash": _code_hash(cid, code), "exp": now + CODE_TTL, "tries": 0}
    _last_code_at = time.monotonic()
    return cid, code


def drop_challenge(cid):
    _challenges.pop(cid, None)


def check_challenge(cid, code) -> str:
    """'ok' | 'bad' (wrong code, may retry) | 'gone' (expired, used up or unknown)"""
    entry = _challenges.get(cid)
    if not entry or entry["exp"] <= time.time():
        _challenges.pop(cid, None)
        return "gone"
    entry["tries"] += 1
    if hmac.compare_digest(entry["hash"], _code_hash(cid, str(code or "").strip())):
        del _challenges[cid]  # one use only
        return "ok"
    if entry["tries"] >= CODE_TRIES:
        del _challenges[cid]
        return "gone"
    return "bad"


# ------------------------------------------------------------- decorator

def login_required(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        if not panel_enabled():
            abort(503, "Admin panel is disabled: set ADMIN_PASSWORD.")
        if not session.get("admin"):
            return redirect(f"{ADMIN_PANEL_PATH}/login")
        if request.method == "POST":
            if not same_origin():
                abort(403)
            form = await request.form  # cached by Quart, the route can read it again
            supplied = form.get("csrf_token") or request.headers.get("X-CSRF-Token")
            if not csrf_valid(supplied):
                abort(403, "Security token missing or expired. Go back, reload the page and try again.")
        return await func(*args, **kwargs)
    return wrapper
