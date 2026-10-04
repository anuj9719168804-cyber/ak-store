"""Web verify page: the server-side half of the anti-bypass check.

Flow (see plugins/start.py for the bot side and web/verify_routes.py for the HTTP side):

  1. A user with no credits opens a file link. The bot creates a token (create()), shortens
     WEB_URL/verify/<token> and sends the user a button to WEB_URL/go/<token>  (NOT the shortener).
  2. /go: the browser solves a small proof-of-work and the server hands out the shortener link
     only then (begin_go). That also drops a same-browser cookie and starts the clock.
  3. The user goes through the shortener, which sends them to /verify/<token>.
  4. /verify: needs the cookie from step 2, at least VERIFY_MIN_SECONDS since step 2, a second
     proof-of-work, and a real tap (finish). The page then opens t.me/<bot>?start=vt_<token>.
  5. The bot redeems the token (redeem): it must belong to that user and be single use.

Why this beats a pure time check: a bypass tool that resolves the shortener elsewhere and opens
the final link never ran step 2 in the same browser (no cookie, no clock, no shortener link),
plain HTTP clients cannot run the JavaScript, and "wait 45 s then open the link" no longer works
because the link itself is only valid for a browser that did step 2.
It is a strong filter, not magic: a person driving a real browser through the whole flow is
indistinguishable from a real user, which is exactly the point of the shortener.

    verify_tokens   _id = token, user_id, payload (what to unlock afterwards), state
                    created -> go -> passed -> used  (or failed), ch1/ch2 (challenges),
                    short_url, go_at (epoch), go_ua, go_ip, expires_at (naive UTC)
"""
import hashlib
import hmac
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from config import (
    PANEL_SECRET, VERIFY_COOKIE_FALLBACK, VERIFY_IP_STRICT, VERIFY_MAX_SECONDS, VERIFY_MIN_SECONDS,
    VERIFY_POW_BITS, VERIFY_REQUIRE_REFERRER, VERIFY_RISK_ACTION, VERIFY_RISK_BLOCK, VERIFY_RISK_FLAG,
    VERIFY_WEB_ACTIVE,
)

PREFIX = "vt_"
TOKEN_LEN = 16
TOKEN_TTL = 3600           # token must be used within an hour of being issued
AFTER_PASS_TTL = 600       # ... and within 10 minutes of the page confirming it
MIN_PAGE_MS = 1500         # the page must have been open this long before the tap
_NONCE_RE = re.compile(r"^\d{1,12}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9]{%d}$" % TOKEN_LEN)

# knobs the tests (and nothing else) change
MIN_SECONDS = VERIFY_MIN_SECONDS
MAX_SECONDS = VERIFY_MAX_SECONDS
POW_BITS = VERIFY_POW_BITS
RISK_FLAG = VERIFY_RISK_FLAG
RISK_BLOCK = VERIFY_RISK_BLOCK
RISK_ACTION = VERIFY_RISK_ACTION
BASELINE_SAMPLES = 20      # need this many earlier passes before "faster than normal" is judged
VELOCITY_WINDOW = 600      # seconds: passes from one network block are counted over this window


def active() -> bool:
    return VERIFY_WEB_ACTIVE


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------- small helpers

def valid_token_format(tid: str) -> bool:
    return bool(tid) and bool(_TOKEN_RE.match(tid))


def new_id() -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(secrets.choice(alphabet) for _ in range(TOKEN_LEN))


def make_challenge() -> str:
    return secrets.token_hex(16)


def ua_hash(ua: str) -> str:
    return hashlib.sha256((ua or "").encode("utf-8", "ignore")).hexdigest()[:16]


def ip_block(ip: str) -> str:
    """The network part of an address, so a phone hopping inside one carrier block still matches."""
    ip = (ip or "").strip()
    if ":" in ip:                                   # IPv6: first 4 groups
        return ":".join(ip.split(":")[:4])
    parts = ip.split(".")
    return ".".join(parts[:3]) if len(parts) == 4 else ip


def cookie_name(tid: str) -> str:
    return f"fsv_{tid}"


def cookie_value(tid: str, uah: str) -> str:
    return hmac.new(PANEL_SECRET.encode(), f"cookie:{tid}:{uah}".encode(), hashlib.sha256).hexdigest()[:32]


def cookie_ok(tid: str, uah: str, supplied) -> bool:
    return bool(supplied) and hmac.compare_digest(cookie_value(tid, uah), str(supplied))


def pow_ok(challenge: str, nonce, bits: int = None) -> bool:
    """sha256("<challenge>:<nonce>") must start with `bits` zero bits."""
    bits = POW_BITS if bits is None else bits
    if bits <= 0:
        return True
    nonce = str(nonce)
    if not _NONCE_RE.match(nonce) or not challenge:
        return False
    digest = hashlib.sha256(f"{challenge}:{nonce}".encode()).digest()
    return (int.from_bytes(digest, "big") >> (256 - bits)) == 0


def ua_ok(ua: str) -> bool:
    ua = (ua or "").strip()
    if len(ua) < 10:
        return False
    low = ua.lower()
    return not any(bad in low for bad in ("headless", "phantomjs", "python-requests", "curl/", "aiohttp", "httpx", "go-http"))


def signals_ok(sig, step: str) -> bool:
    """What the page reports about itself. Spoofable by someone who reads this file, but it
    stops stock headless browsers and scripts, which is who actually uses bypass services."""
    if not isinstance(sig, dict):
        return False
    if sig.get("wd"):                                # navigator.webdriver === true
        return False
    if step == "verify":
        if not sig.get("trusted"):                   # the tap must be a real (isTrusted) event
            return False
        try:
            if int(sig.get("ptr", 0)) < 1:           # at least one real pointer/touch event on the page
                return False
            if int(sig.get("ms", 0)) < MIN_PAGE_MS:  # page open long enough to have been read
                return False
        except (TypeError, ValueError):
            return False
    return True


def referrer_state(referer: str, short_domain: str):
    """True = comes from the shortener's domain, False = comes from elsewhere, None = no referrer."""
    if not referer:
        return None
    host = (urlparse(referer).hostname or "").lower()
    domain = (short_domain or "").lower().lstrip(".")
    if not host or not domain:
        return None
    return host == domain or host.endswith("." + domain) or domain.endswith("." + host)


# ------------------------------------------------------------------ risk score

def score_risk(*, elapsed, baseline, ref, cookie_ok, ip_changed, velocity):
    """Pure scoring. -> (score 0-100, [reasons]). No single weak signal reaches the default block
    level (70) alone: it takes a bypass-looking combination."""
    score, why = 0, []
    if baseline:
        if elapsed < baseline * 0.5:
            score += 50; why.append(f"much faster than normal ({elapsed:.0f}s vs ~{baseline:.0f}s)")
        elif elapsed < baseline * 0.7:
            score += 25; why.append(f"faster than normal ({elapsed:.0f}s vs ~{baseline:.0f}s)")
    if ref is False:
        score += 35; why.append("did not come from the shortener")
    elif ref is None:
        score += 10; why.append("no referrer")
    if not cookie_ok:
        score += 20; why.append("cookie missing")
    if ip_changed:
        score += 15; why.append("network changed")
    if velocity >= 10:
        score += 50; why.append(f"{velocity} passes from one network in 10 min")
    elif velocity >= 5:
        score += 30; why.append(f"{velocity} passes from one network in 10 min")
    return min(score, 100), why


async def baseline_seconds(db, exclude_id=None):
    """Median time real users took (recent passed verifications), or None while there is too little data."""
    docs = await db["verify_tokens"].find({"state": {"$in": ["passed", "used"]}, "risk": {"$lt": RISK_FLAG}}) \
        .sort([("pass_at", -1)]).limit(200).to_list(length=200)
    values = sorted(float(d["elapsed"]) for d in docs if d.get("elapsed") and d["_id"] != exclude_id)
    if len(values) < BASELINE_SAMPLES:
        return None
    return values[len(values) // 2]


async def assess(db, doc, *, elapsed, ip, ref, cookie_ok, now_ts):
    block = ip_block(ip)
    velocity = await db["verify_tokens"].count_documents(
        {"pass_block": block, "pass_at": {"$gt": now_ts - VELOCITY_WINDOW}, "_id": {"$ne": doc["_id"]}})
    return score_risk(
        elapsed=elapsed, baseline=await baseline_seconds(db, doc["_id"]), ref=ref, cookie_ok=cookie_ok,
        ip_changed=ip_block(doc.get("go_ip", "")) != block, velocity=velocity + 1)


# ------------------------------------------------------------------ persistence

async def ensure_indexes(db):
    try:
        # keep a token an hour past its expiry so the page can still say "expired" instead of "unknown"
        await db["verify_tokens"].create_index("expires_at", expireAfterSeconds=3600)
        await db["verify_tokens"].create_index("user_id")
    except Exception:
        pass


async def create(db, user_id: int, payload: str) -> dict:
    """New token for `user_id` who wants to unlock `payload` (the link payload as the user opened it)."""
    now = _now()
    doc = {
        "_id": new_id(), "user_id": int(user_id), "payload": payload, "state": "created",
        "ch1": make_challenge(), "ch2": make_challenge(), "short_url": "",
        "created": now, "expires_at": now + timedelta(seconds=TOKEN_TTL),
    }
    await db["verify_tokens"].insert_one(doc)
    return doc


async def set_short(db, tid: str, short_url: str):
    await db["verify_tokens"].update_one({"_id": tid}, {"$set": {"short_url": short_url}})


async def get(db, tid: str):
    if not valid_token_format(tid):
        return None
    return await db["verify_tokens"].find_one({"_id": tid})


def _expired(doc, now=None) -> bool:
    return doc["expires_at"] <= (now or _now())


def same_browser(doc, ua: str, ip: str, cookie) -> bool:
    """Is this request from the browser that ran step 2? Cookie first; optionally same UA + same IP block."""
    uah = ua_hash(ua)
    if uah != doc.get("go_ua"):
        return False
    if cookie_ok(doc["_id"], uah, cookie):
        return True
    return bool(VERIFY_COOKIE_FALLBACK and ip_block(ip) == ip_block(doc.get("go_ip", "")))


# ------------------------------------------------------------ step 2: /go

async def begin_go(db, tid: str, *, ua: str, ip: str, nonce, signals, now_ts: float = None):
    """Browser check before the shortener link is released. -> (code, doc)
    code: ok | missing | expired | bad_state | browser"""
    doc = await get(db, tid)
    if not doc:
        return "missing", None
    if _expired(doc):
        return "expired", doc
    if doc["state"] not in ("created", "go"):
        return "bad_state", doc
    if not ua_ok(ua) or not signals_ok(signals, "go") or not pow_ok(doc["ch1"], nonce):
        return "browser", doc
    if not doc.get("short_url"):
        return "bad_state", doc
    if doc["state"] == "created":
        await db["verify_tokens"].update_one(
            {"_id": tid, "state": "created"},
            {"$set": {"state": "go", "go_at": now_ts if now_ts is not None else time.time(),
                      "go_ua": ua_hash(ua), "go_ip": ip}},
        )
        doc = await get(db, tid)
    return "ok", doc


# --------------------------------------------------------------- step 4: /verify

async def finish(db, tid: str, *, ua: str, ip: str, cookie, nonce, signals, referer: str = "",
                 short_domain: str = "", now_ts: float = None):
    """Browser check after the shortener. -> (code, doc, extra)
    code: ok | missing | expired | bad_state | ua | cookie | too_fast | risky | browser | referrer | ip
    extra: elapsed seconds for too_fast/ok"""
    now_ts = time.time() if now_ts is None else now_ts
    doc = await get(db, tid)
    if not doc:
        return "missing", None, None
    if _expired(doc):
        return "expired", doc, None
    if doc["state"] not in ("go", "passed") or not doc.get("go_at"):
        return "bad_state", doc, None

    # same browser as step 2? (also required to re-open an already passed page)
    uah = ua_hash(ua)
    if uah != doc.get("go_ua"):
        return "ua", doc, None
    if not same_browser(doc, ua, ip, cookie):
        return "cookie", doc, None
    if doc["state"] == "passed":
        return "ok", doc, doc.get("elapsed")            # page reloaded / tapped twice: same answer

    elapsed = now_ts - float(doc["go_at"])
    if elapsed < MIN_SECONDS:
        await db["verify_tokens"].update_one({"_id": tid, "state": "go"}, {"$set": {"state": "failed", "elapsed": elapsed}})
        return "too_fast", doc, elapsed
    if elapsed > MAX_SECONDS:
        await db["verify_tokens"].update_one({"_id": tid, "state": "go"}, {"$set": {"state": "failed", "elapsed": elapsed}})
        return "expired", doc, elapsed

    if not ua_ok(ua) or not signals_ok(signals, "verify") or not pow_ok(doc["ch2"], nonce):
        return "browser", doc, elapsed
    ref = referrer_state(referer, short_domain)
    if VERIFY_REQUIRE_REFERRER and ref is not True:
        return "referrer", doc, elapsed
    if VERIFY_IP_STRICT and ip_block(ip) != ip_block(doc.get("go_ip", "")):
        return "ip", doc, elapsed

    has_cookie = cookie_ok(tid, uah, cookie)
    risk, reasons = await assess(db, doc, elapsed=elapsed, ip=ip, ref=ref, cookie_ok=has_cookie, now_ts=now_ts)
    if RISK_BLOCK and risk >= RISK_BLOCK and RISK_ACTION == "block":
        await db["verify_tokens"].update_one(
            {"_id": tid, "state": "go"},
            {"$set": {"state": "failed", "elapsed": elapsed, "risk": risk, "reasons": reasons, "ref_ok": ref,
                      "cookie_ok": has_cookie, "pass_ip": ip, "blocked_by_risk": True}})
        return "risky", await get(db, tid), elapsed

    now = _now()
    await db["verify_tokens"].update_one(
        {"_id": tid, "state": "go"},
        {"$set": {"state": "passed", "pass_at": now_ts, "pass_ip": ip, "pass_block": ip_block(ip), "elapsed": elapsed,
                  "ref_ok": ref, "cookie_ok": has_cookie, "risk": risk, "reasons": reasons,
                  "flagged": bool(RISK_FLAG and risk >= RISK_FLAG),
                  "expires_at": now + timedelta(seconds=AFTER_PASS_TTL)}},
    )
    return "ok", await get(db, tid), elapsed


# ------------------------------------------------------------------ bot side

async def redeem(db, tid: str, user_id: int):
    """Called when the bot gets /start vt_<token>. -> (code, doc)
    code: ok | missing | wrong_user | not_passed | used | expired | failed"""
    doc = await get(db, tid)
    if not doc:
        return "missing", None
    if doc["user_id"] != int(user_id):
        return "wrong_user", None                       # someone else's token: reveal nothing
    if doc["state"] == "used":
        return "used", doc
    if doc["state"] == "failed":
        return "failed", doc
    if _expired(doc):
        return "expired", doc
    if doc["state"] != "passed":
        return "not_passed", doc
    taken = await db["verify_tokens"].find_one_and_update(
        {"_id": tid, "user_id": int(user_id), "state": "passed"},
        {"$set": {"state": "used", "used_at": _now()}},
        return_document=True,
    )
    if not taken:
        return "used", doc                               # lost a race with ourselves
    return "ok", taken


async def penalize(bot, doc, elapsed: float):
    """Same consequences the old time check had: strike, log, owner-spike counter, auto-ban, DM.
    -> (strikes, banned)"""
    from config import BYPASS_AUTO_BAN, BYPASS_MAX_STRIKES
    from helper import alerts, stats
    from helper.activity import log_activity

    uid = doc["user_id"]
    strikes = await bot.mongodb.add_bypass_strike(uid)
    await log_activity(bot, "bypass_detected", uid, "",
                       f"web verify | {elapsed:.0f}s < {MIN_SECONDS}s | strike {strikes}/{BYPASS_MAX_STRIKES}")
    await stats.bump(bot.mongodb.db, "bypass")
    await alerts.note_bypass(bot)
    banned = False
    if BYPASS_AUTO_BAN and strikes >= BYPASS_MAX_STRIKES:
        await bot.mongodb.ban_user(uid)
        await log_activity(bot, "bypass_auto_ban", uid, "", f"web verify | {strikes} strikes")
        banned = True
    try:
        if banned:
            text = "<blockquote>🚫 ʏᴏᴜ ʜᴀᴠᴇ ʙᴇᴇɴ ʙᴀɴɴᴇᴅ ꜰᴏʀ ʀᴇᴘᴇᴀᴛᴇᴅ ʙʏᴘᴀss ᴀᴛᴛᴇᴍᴘᴛs.</blockquote>"
        else:
            warn = f"\n⚠️ ᴡᴀʀɴɪɴɢ {strikes}/{BYPASS_MAX_STRIKES}" if BYPASS_AUTO_BAN else ""
            text = ("<blockquote>🚫 ʙʏᴘᴀss ᴅᴇᴛᴇᴄᴛᴇᴅ!\n"
                    f"⧗ ᴛɪᴍᴇ ᴛᴀᴋᴇɴ: {int(elapsed)}s (ᴍɪɴ {MIN_SECONDS}s){warn}\n"
                    "ᴏᴘᴇɴ ʏᴏᴜʀ ꜰɪʟᴇ ʟɪɴᴋ ᴀɢᴀɪɴ ᴀɴᴅ ᴄᴏᴍᴘʟᴇᴛᴇ ᴛʜᴇ ᴠᴇʀɪꜰɪᴄᴀᴛɪᴏɴ ᴘʀᴏᴘᴇʀʟʏ.</blockquote>")
        await bot.send_message(uid, text)
    except Exception:
        pass
    return strikes, banned


def go_url(base: str, tid: str) -> str:
    return f"{base.rstrip('/')}/go/{tid}"


def verify_url(base: str, tid: str) -> str:
    return f"{base.rstrip('/')}/verify/{tid}"
