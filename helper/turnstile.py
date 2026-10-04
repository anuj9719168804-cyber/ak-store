"""Cloudflare Turnstile: server-side check of the token the widget gives the browser.

POST https://challenges.cloudflare.com/turnstile/v0/siteverify  (form: secret, response, remoteip)
-> {"success": bool, "error-codes": [...], "hostname": ..., ...}
A token works once and expires after 5 minutes, so a replayed or stolen token is refused by Cloudflare
("timeout-or-duplicate"). If Cloudflare cannot be reached the check FAILS (closed): letting everyone
through while it is down would be an open door for bypass tools.
"""
import aiohttp

from config import LOGGER, TURNSTILE_ON, TURNSTILE_SECRET_KEY, TURNSTILE_SITE_KEY

log = LOGGER("turnstile", "web")
SITEVERIFY = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
MAX_TOKEN = 4096
ENABLED = TURNSTILE_ON          # tests switch this


def enabled() -> bool:
    return ENABLED


def site_key() -> str:
    return TURNSTILE_SITE_KEY if ENABLED else ""


async def _post(data: dict) -> dict:
    timeout = aiohttp.ClientTimeout(total=8)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.post(SITEVERIFY, data=data) as r:
            return await r.json(content_type=None)


async def check(token, ip: str = "") -> bool:
    """True only when Cloudflare says this token is valid (and unused)."""
    if not ENABLED:
        return True
    if not isinstance(token, str) or not token or len(token) > MAX_TOKEN:
        return False
    data = {"secret": TURNSTILE_SECRET_KEY, "response": token}
    if ip:
        data["remoteip"] = ip
    try:
        result = await _post(data)
    except Exception as e:
        log.warning("Turnstile siteverify failed (%s): %s", type(e).__name__, e)
        return False
    ok = bool(isinstance(result, dict) and result.get("success") is True)
    if not ok:
        log.info("Turnstile refused a token: %s", (result or {}).get("error-codes") if isinstance(result, dict) else result)
    return ok
