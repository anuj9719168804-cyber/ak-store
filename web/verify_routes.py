"""Public pages of the web verify flow: /go/<token> and /verify/<token>.

All the decisions live in helper/verify_web.py (and are unit-tested there); this file only turns
HTTP requests into calls to it and its answers into pages / JSON. See that module for the flow.
"""
import time

from quart import current_app, jsonify, make_response, render_template, request

from config import LOGGER, VERIFY_POW_BITS, VERIFY_REQUIRE_REFERRER, WEB_URL
from helper import turnstile, verify_web as vw
from web import web
from web.auth import client_key

log = LOGGER("verify", "web")

_hits = {}  # ip -> [timestamps]  (tiny in-memory limiter: these pages are public)
_LIMIT, _WINDOW = 60, 60


def _bot():
    return current_app.config["BOT"]


def _db():
    return _bot().mongodb.db


def _too_many() -> bool:
    now = time.time()
    ip = client_key()
    stamps = [t for t in _hits.get(ip, []) if now - t < _WINDOW]
    stamps.append(now)
    _hits[ip] = stamps
    if len(_hits) > 5000:  # keep memory bounded
        for key in [k for k, v in _hits.items() if not v or now - v[-1] >= _WINDOW]:
            _hits.pop(key, None)
    return len(stamps) > _LIMIT


async def _page(template, status=200, **ctx):
    resp = await make_response(await render_template(template, **ctx), status)
    resp.headers["Cache-Control"] = "no-store"
    return resp


async def _message(title, text, status=200):
    return await _page("verify_msg.html", status, title=title, text=text)


_RESTART = "Open your file link in Telegram again to get a fresh verification link."

# what the page says for each failure code (the JS shows `msg` as is)
_MSG = {
    "missing": "This verification link was not found. " + _RESTART,
    "expired": "This verification link has expired. " + _RESTART,
    "bad_state": "This step is not available right now. " + _RESTART,
    "browser": "The browser check failed. Use your normal browser (not a script or private tool) and try again.",
    "ua": "Open the verification in the same browser you started it in.",
    "cookie": "Open the verification in the same browser you started it in (cookies must be on).",
    "referrer": "Complete the shortener link first, then you will land here.",
    "ip": "Your network changed during verification. " + _RESTART,
    "too_fast": "That was too fast: the shortener step was skipped. " + _RESTART,
    "captcha": "The security check did not pass. Reload this page and try again.",
    "risky": "We could not confirm that you completed the shortener properly. " + _RESTART,
}


def _fail(code, status=400):
    return jsonify({"ok": False, "code": code, "msg": _MSG.get(code, "Verification failed. " + _RESTART)}), status


# ==========================================================
# Step 2: browser check, then the shortener link is released
# ==========================================================

@web.route("/go/<tid>")
async def go_page(tid):
    if _too_many():
        return await _message("Slow down", "Too many requests. Wait a minute and try again.", 429)
    doc = await vw.get(_db(), tid)
    if not doc:
        return await _message("Link not found", _MSG["missing"], 404)
    if doc["expires_at"] <= vw._now():
        return await _message("Link expired", _MSG["expired"], 410)
    if doc["state"] not in ("created", "go"):
        return await _message("Not available", _MSG["bad_state"], 410)
    return await _page("verify_go.html", tid=tid, challenge=doc["ch1"], bits=VERIFY_POW_BITS, ts_key=turnstile.site_key())


@web.route("/go/<tid>/start", methods=["POST"])
async def go_start(tid):
    if _too_many():
        return jsonify({"ok": False, "msg": "Too many requests. Wait a minute."}), 429
    body = await request.get_json(silent=True) or {}
    ua = request.headers.get("User-Agent", "")
    if not await turnstile.check(body.get("ts"), client_key()):
        return _fail("captcha")
    code, doc = await vw.begin_go(_db(), tid, ua=ua, ip=client_key(), nonce=body.get("nonce"), signals=body.get("sig"))
    if code != "ok":
        return _fail(code)
    resp = await make_response(jsonify({"ok": True, "url": doc["short_url"]}))
    resp.set_cookie(
        vw.cookie_name(tid), vw.cookie_value(tid, vw.ua_hash(ua)), max_age=vw.TOKEN_TTL,
        httponly=True, samesite="Lax", secure=WEB_URL.startswith("https://"), path="/",
    )
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ==========================================================
# Step 4: where the shortener sends the user
# ==========================================================

@web.route("/verify/<tid>")
async def verify_page(tid):
    if _too_many():
        return await _message("Slow down", "Too many requests. Wait a minute and try again.", 429)
    db = _db()
    doc = await vw.get(db, tid)
    if not doc:
        return await _message("Link not found", _MSG["missing"], 404)
    if doc["expires_at"] <= vw._now():
        return await _message("Link expired", _MSG["expired"], 410)
    if doc["state"] == "created":
        # They reached the final page without ever running the browser check: the shortener
        # was skipped or resolved elsewhere. No strike (cannot be proven), just no access.
        from helper.activity import log_activity
        await log_activity(_bot(), "verify_skipped_go", doc["user_id"], tid, f"ip {client_key()}")
        return await _message("Start from Telegram", "Open your file link in Telegram and use the button there. " + _RESTART, 403)
    if doc["state"] not in ("go", "passed"):
        return await _message("Not available", _MSG["bad_state"], 410)
    ua = request.headers.get("User-Agent", "")
    if not vw.same_browser(doc, ua, client_key(), request.cookies.get(vw.cookie_name(tid))):
        return await _message("Wrong browser", _MSG["cookie"], 403)
    # the Referer of THIS navigation is the only place the shortener shows up: remember it
    referer = (request.headers.get("Referer") or "")[:300]
    if referer and not doc.get("first_ref"):
        await db["verify_tokens"].update_one({"_id": tid, "first_ref": {"$exists": False}}, {"$set": {"first_ref": referer}})
    return await _page("verify_check.html", tid=tid, challenge=doc["ch2"], bits=VERIFY_POW_BITS,
                       bot=_bot().username, min_seconds=vw.MIN_SECONDS, ts_key=turnstile.site_key())


@web.route("/verify/<tid>/done", methods=["POST"])
async def verify_done(tid):
    if _too_many():
        return jsonify({"ok": False, "msg": "Too many requests. Wait a minute."}), 429
    bot = _bot()
    db = bot.mongodb.db
    body = await request.get_json(silent=True) or {}
    ua = request.headers.get("User-Agent", "")
    if not await turnstile.check(body.get("ts"), client_key()):
        return _fail("captcha")
    pre = await vw.get(db, tid)
    code, doc, extra = await vw.finish(
        db, tid, ua=ua, ip=client_key(), cookie=request.cookies.get(vw.cookie_name(tid)),
        nonce=body.get("nonce"), signals=body.get("sig"),
        referer=(pre or {}).get("first_ref", ""), short_domain=getattr(bot, "short_url", "") or "",
    )
    if code == "too_fast":
        await vw.penalize(bot, doc, extra)
        return _fail("too_fast")
    if code == "risky":
        from helper import alerts, stats
        from helper.activity import log_activity
        await stats.bump(db, "bypass")
        await alerts.note_bypass(bot)
        await log_activity(bot, "bypass_risk_blocked", doc["user_id"], tid, f"risk {doc.get('risk')}: {'; '.join(doc.get('reasons', []))}")
        return _fail("risky")
    if code != "ok":
        return _fail(code)
    if doc.get("flagged"):
        from helper.activity import log_activity
        await log_activity(bot, "verify_flagged", doc["user_id"], tid, f"risk {doc.get('risk')}: {'; '.join(doc.get('reasons', []))}")
    return jsonify({"ok": True, "url": f"https://t.me/{bot.username}?start={vw.PREFIX}{tid}"})
