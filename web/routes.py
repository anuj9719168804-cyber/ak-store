import asyncio
import hmac
import re
from datetime import datetime
from urllib.parse import urlencode

import humanize
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait, InputUserDeactivated, UserIsBlocked
from quart import (
    Response, abort, current_app, redirect, render_template, request, session
)

from config import ADMIN_PANEL_PATH, ADMIN_PASSWORD, BACKEND_API_URL, LOGGER, PANEL_2FA, STREAM_PATH, TOKEN, WEB_URL
from helper import activity, file_index
from helper.stream_links import build_links, links_enabled, parse_ref, verify
from helper.utils import to_int as _to_int
from helper.streamer import MediaCache, extract_media, iter_file, make_plan
from web import data, panel, web
from web.auth import (
    check_challenge, client_key, code_cooldown_left, csrf_valid, drop_challenge, login_blocked,
    login_required, new_challenge, panel_enabled, register_failure, same_origin,
)
from web.tg_auth import verify_init_data

log = LOGGER("web", "web")
P = ADMIN_PANEL_PATH  # "" when the panel is mounted at the site root
MEDIA_CACHE = MediaCache()


def _bot():
    return current_app.config["BOT"]


async def _log(action, target="", detail=""):
    await activity.log_activity(_bot(), action, session.get("who", "panel"), target, detail)


def _flash(text, kind="ok"):
    session["flash"] = list(session.get("flash", [])) + [[kind, text]]


async def _render(template, **ctx):
    return await render_template(template, flashes=session.pop("flash", []), **ctx)


# ==========================================================
# Health / root
# ==========================================================

@web.route("/health")
async def health():
    return {"status": "ok", "bot_ready": bool(getattr(_bot(), "username", None))}


if P:
    @web.route("/")
    async def root():
        return "Bot is running!", 200


# ==========================================================
# Admin panel
# ==========================================================

@panel.route("/login", methods=["GET", "POST"])
async def login():
    if not panel_enabled():
        abort(503, "Admin panel is disabled: set ADMIN_PASSWORD.")

    if session.get("admin"):
        return redirect(f"{P}/")

    error = None
    if request.method == "POST":
        if login_blocked():
            abort(429, "Too many wrong passwords. Try again in a few minutes.")
        form = await request.form
        password = form.get("password", "")
        if not csrf_valid(form.get("csrf_token")):
            error = "This page expired. Please try again."
        elif hmac.compare_digest(password.encode(), ADMIN_PASSWORD.encode()):
            if PANEL_2FA:
                error = await _send_login_code()
                if error is None:
                    return redirect(f"{P}/login/2fa")
            else:
                session.clear()
                session["admin"] = True
                session["who"] = "password"
                session.permanent = True
                await _log("panel_login", detail=f"password, ip {client_key()}")
                return redirect(f"{P}/")
        else:
            register_failure()
            await activity.log_activity(_bot(), "panel_login_failed", "unknown", detail=f"ip {client_key()}")
            error = "Wrong password"

    return await render_template("login.html", error=error)


async def _send_login_code():
    """Password was right and 2FA is on: DM a 6-digit code to the owner. -> error text, or None if sent."""
    wait = code_cooldown_left()
    if wait:
        return f"A code was just sent to the owner on Telegram. Wait {wait}s before asking for another one."
    bot = _bot()
    cid, code = new_challenge()
    try:
        await bot.send_message(
            bot.owner,
            f"🔐 <b>Panel login code</b>\n<code>{code}</code>\n"
            f"Valid for 5 minutes. Requested from IP <code>{client_key()}</code>.\n"
            "If this wasn't you, change ADMIN_PASSWORD now.",
        )
    except Exception as e:
        drop_challenge(cid)
        log.warning("Could not send the 2FA code to the owner: %s", e)
        return "The code could not be sent to the owner on Telegram. Is the bot running and not blocked by the owner?"
    session.clear()
    session["pending_2fa"] = cid  # only an id: the code itself stays in server memory
    await activity.log_activity(bot, "panel_2fa_sent", "password", detail=f"ip {client_key()}")
    return None


@panel.route("/login/2fa", methods=["GET", "POST"])
async def login_2fa():
    if not panel_enabled():
        abort(503, "Admin panel is disabled: set ADMIN_PASSWORD.")
    if session.get("admin"):
        return redirect(f"{P}/")
    cid = session.get("pending_2fa")
    if not cid:
        return redirect(f"{P}/login")

    error = None
    if request.method == "POST":
        if not same_origin():
            abort(403)
        if login_blocked():
            abort(429, "Too many wrong attempts. Try again in a few minutes.")
        form = await request.form
        if not csrf_valid(form.get("csrf_token")):
            error = "This page expired. Reload it and try again."
        else:
            result = check_challenge(cid, form.get("code", ""))
            if result == "ok":
                session.clear()
                session["admin"] = True
                session["who"] = "password+2fa"
                session.permanent = True
                await _log("panel_login", detail=f"password + telegram code, ip {client_key()}")
                return redirect(f"{P}/")
            register_failure()
            await activity.log_activity(_bot(), "panel_2fa_failed", "unknown", detail=f"ip {client_key()}")
            if result == "gone":
                session.clear()
                return await render_template(
                    "login.html", error="That code expired or was used up. Log in again to get a new one."
                )
            error = "Wrong code"

    return await render_template("login_2fa.html", error=error)


@panel.route("/tg-login", methods=["POST"])
async def tg_login():
    """Opening the panel from the bot's Control Panel button logs the OWNER in.

    Owner only, on purpose: stock Pro keeps /addpremium for the owner, so handing
    every bot admin the same power through the panel would be a privilege jump.
    The launch data is signed by Telegram itself, so this already proves the owner's
    Telegram account: no extra 2FA code here (it would be sent to that same account).
    """
    if not panel_enabled():
        abort(503, "Admin panel is disabled: set ADMIN_PASSWORD.")
    if not same_origin():
        abort(403)
    if login_blocked():
        return {"ok": False}, 429

    payload = await request.get_json(silent=True) or {}
    user = verify_init_data(str(payload.get("init_data", "")), TOKEN)
    bot = _bot()
    if not user or user["id"] != bot.owner:
        register_failure()
        return {"ok": False}, 403

    session.clear()
    session["admin"] = True
    session["who"] = f"tg:{user['id']}"
    session.permanent = True
    await _log("panel_login", detail=f"telegram, ip {client_key()}")
    return {"ok": True}


@panel.route("/logout", methods=["POST"])
@login_required
async def logout():
    session.clear()
    return redirect(f"{P}/login")


@panel.route("/")
@login_required
async def dashboard():
    bot = _bot()
    stats = await data.counts(bot)
    started = getattr(bot, "uptime", None)
    uptime = humanize.naturaldelta(datetime.now() - started) if started else "-"
    db_rows, fsub_rows = data.channels(bot)
    from helper import stats as daily_stats
    today = (await daily_stats.series(bot.mongodb.db, 1))[0]
    from helper import support
    return await _render(
        "dashboard.html", stats=stats, uptime=uptime, today=today, support=await support.counts(bot.mongodb.db),
        db_count=len(db_rows), fsub_count=len(fsub_rows),
        web_links=links_enabled(),
    )


@panel.route("/users", methods=["GET", "POST"])
@login_required
async def users_page():
    bot = _bot()
    if request.method == "POST":
        form = await request.form
        uid = _to_int(form.get("user_id"))
        action = form.get("action")
        back = urlencode({"q": form.get("q", ""), "page": form.get("page", "1")})

        if not uid or not await bot.mongodb.present_user(uid):
            _flash("User not found.", "err")
        elif action == "ban":
            if uid in bot.admins:
                _flash("Admins can't be banned.", "err")
            else:
                await bot.mongodb.ban_user(uid)
                await _log("ban_user", uid)
                _flash(f"Banned {uid}.")
        elif action == "unban":
            await bot.mongodb.unban_user(uid)
            await _log("unban_user", uid)
            _flash(f"Unbanned {uid}.")
        return redirect(f"{P}/users?{back}")

    page = max(_to_int(request.args.get("page"), 1), 1)
    q = request.args.get("q", "")
    per_page = 50
    users, total = await data.list_users(bot, page, per_page, q)
    return await _render(
        "users.html", users=users, total=total, page=page, q=q,
        has_next=page * per_page < total,
    )


@panel.route("/premium", methods=["GET", "POST"])
@login_required
async def premium_page():
    bot = _bot()
    if request.method == "POST":
        form = await request.form
        uid = _to_int(form.get("user_id"))
        action = form.get("action")
        days_raw = (form.get("days") or "").strip()
        days = _to_int(days_raw, -1) if days_raw else 0

        if not uid:
            _flash("Enter a valid user ID.", "err")
        elif action == "add":
            if days < 0:
                _flash("Days must be a number (leave empty for permanent).", "err")
            else:
                await data.set_premium(bot, uid, days)
                await _log("add_premium", uid, f"{days} days" if days else "permanent")
                _flash(f"Premium set for {uid} ({days} days)." if days else f"Permanent premium set for {uid}.")
        elif action == "remove":
            await bot.mongodb.remove_pro(uid)
            await _log("remove_premium", uid)
            _flash(f"Premium removed from {uid}.")
        return redirect(f"{P}/premium")

    return await _render("premium.html", rows=await data.list_premium(bot))


@panel.route("/admins", methods=["GET", "POST"])
@login_required
async def admins_page():
    bot = _bot()
    if request.method == "POST":
        form = await request.form
        uid = _to_int(form.get("user_id"))
        action = form.get("action")

        if not uid:
            _flash("Enter a valid user ID.", "err")
        elif action == "add":
            await data.add_admin(bot, uid)
            await _log("add_admin", uid)
            _flash(f"{uid} is now an admin.")
        elif action == "remove":
            if await data.remove_admin(bot, uid):
                await _log("remove_admin", uid)
                _flash(f"{uid} is no longer an admin.")
            else:
                _flash("The owner can't be removed.", "err")
        return redirect(f"{P}/admins")

    return await _render("admins.html", admins=list(bot.admins), owner=bot.owner)


@panel.route("/logs")
@login_required
async def logs_page():
    page = max(_to_int(request.args.get("page"), 1), 1)
    per_page = 50
    rows, total = await activity.recent(_bot(), page, per_page)
    return await _render("logs.html", rows=rows, total=total, page=page, has_next=page * per_page < total)


@panel.route("/settings", methods=["GET", "POST"])
@login_required
async def settings_page():
    bot = _bot()
    if request.method == "POST":
        form = await request.form
        auto_del = _to_int((form.get("auto_del") or "").strip(), -1)
        if not 0 <= auto_del <= 7 * 86400:
            _flash("Auto-delete must be a whole number of seconds (0 = off, max 7 days).", "err")
        else:
            changed = await data.save_settings(
                bot,
                protect=form.get("protect") is not None,
                auto_del=auto_del,
                shortner=form.get("shortner") is not None,
                # the checkbox only exists when BACKEND_API_URL is set; otherwise leave the value alone
                permanent_link=(form.get("permanent_link") is not None) if BACKEND_API_URL else None,
            )
            from plugins import maintenance
            want_maint = form.get("maintenance") is not None
            if want_maint != await maintenance.is_on(bot):
                await maintenance.set_on(bot, want_maint)
                changed.append(f"maintenance={'on' if want_maint else 'off'}")
            from helper import linkttl
            ttl_text = (form.get("stream_ttl") or "").strip().lower()
            ttl_bad = False
            if ttl_text and ttl_text != linkttl.readable(linkttl.get()):
                if ttl_text == "reset":
                    await linkttl.save(bot.mongodb, None)
                    changed.append("stream_ttl=default")
                else:
                    seconds = linkttl.parse_duration(ttl_text)
                    if seconds is None:
                        ttl_bad = True
                    elif seconds != linkttl.get():
                        await linkttl.save(bot.mongodb, seconds)
                        changed.append(f"stream_ttl={linkttl.readable(seconds)}")
            if ttl_bad:
                _flash("Web link validity: use e.g. 1h, 30m, 2d, 0 (never) or reset.", "err")
            elif changed:
                await _log("settings_changed", "", ", ".join(changed))
                _flash("Settings saved.")
            else:
                _flash("Nothing changed.")
        return redirect(f"{P}/settings")

    from plugins import maintenance
    from helper import linkttl
    return await _render("settings.html", s=data.current_settings(bot), permanent_url=BACKEND_API_URL,
                         maintenance=await maintenance.is_on(bot),
                         stream_ttl=linkttl.readable(linkttl.get()), links_on=bool(WEB_URL))


@panel.route("/channels")
@login_required
async def channels_page():
    db_rows, fsub_rows = data.channels(_bot())
    return await _render("channels.html", db_rows=db_rows, fsub_rows=fsub_rows)


# ---------------------------------------------------------- files

async def _run_scan(app, bot, state, actor):
    await file_index.scan(bot, state)  # catches its own errors and always clears state["running"]
    await activity.log_activity(
        bot, "file_scan_finished", actor, "",
        f"checked {state['scanned']} messages, indexed {state['added']} new files"
        + (f", error: {state['error']}" if state.get("error") else ""),
    )


@panel.route("/files", methods=["GET", "POST"])
@login_required
async def files_page():
    bot = _bot()
    app = current_app._get_current_object()
    scan = app.config.setdefault("FILE_SCAN", {"running": False})

    if request.method == "POST":
        form = await request.form
        action = form.get("action")
        back = urlencode({"q": form.get("q", ""), "sort": form.get("sort", "new"), "page": form.get("page", "1")})

        if action == "delete":
            ref = (form.get("file_id") or "").strip()
            parsed = parse_ref(ref)
            if not parsed:
                _flash("Invalid file.", "err")
            else:
                ok, detail = await file_index.remove(bot, ref)
                if ok:
                    MEDIA_CACHE.discard(parsed)  # an open player must not keep serving it from cache
                    await _log("delete_file", ref, detail)
                    _flash(f"Deleted {detail}.")
                else:
                    _flash(detail, "err")
        elif action == "scan":
            if scan.get("running"):
                _flash("A scan is already running.", "err")
            else:
                scan.clear()
                scan.update(running=True, total=0, scanned=0, added=0, error=None,
                            started=datetime.now(), finished=None)
                await _log("file_scan_started")
                task = asyncio.create_task(_run_scan(app, bot, scan, session.get("who", "panel")))
                tasks = app.config.setdefault("BG_TASKS", set())  # keep a reference so it isn't GC'd
                tasks.add(task)
                task.add_done_callback(tasks.discard)
                _flash("Scan started. This page refreshes by itself while it runs.")
        return redirect(f"{P}/files?{back}")

    page = max(_to_int(request.args.get("page"), 1), 1)
    q = request.args.get("q", "")
    sort = request.args.get("sort", "new")
    per_page = 50
    rows, total = await data.list_files(bot, page, per_page, q, sort)
    return await _render(
        "files.html", rows=rows, total=total, page=page, q=q, sort=sort,
        has_next=page * per_page < total, scan=scan,
    )


# ---------------------------------------------------------- broadcast

def _wait_seconds(exc) -> int:
    return int(getattr(exc, "value", None) or getattr(exc, "x", None) or 5)


async def _run_broadcast(app, bot, text, actor):
    st = app.config["BROADCAST"]
    try:
        async for uid in data.iter_user_ids(bot):
            st["total"] += 1
            for _ in range(2):  # one retry after a FloodWait
                try:
                    await bot.send_message(uid, text, parse_mode=ParseMode.DISABLED)
                    st["sent"] += 1
                    break
                except FloodWait as e:
                    await asyncio.sleep(_wait_seconds(e) + 1)
                except (UserIsBlocked, InputUserDeactivated):
                    st["blocked"] += 1
                    break
                except Exception:
                    st["failed"] += 1
                    break
            else:
                st["failed"] += 1
            await asyncio.sleep(0.05)
    except Exception:
        log.exception("Web broadcast crashed")
    finally:
        st["running"] = False
        st["finished"] = datetime.now()
        await activity.log_activity(
            bot, "broadcast_finished", actor, "",
            f"sent {st['sent']}, blocked {st['blocked']}, failed {st['failed']} of {st['total']}",
        )


@panel.route("/broadcast", methods=["GET", "POST"])
@login_required
async def broadcast_page():
    app = current_app._get_current_object()
    state = app.config.setdefault("BROADCAST", {"running": False})

    if request.method == "POST":
        form = await request.form
        text = (form.get("message") or "").strip()

        if not text:
            _flash("Message can't be empty.", "err")
        elif state.get("running"):
            _flash("A broadcast is already running.", "err")
        else:
            state.clear()
            state.update(running=True, total=0, sent=0, blocked=0, failed=0,
                         started=datetime.now(), finished=None)
            await _log("broadcast_started", "", f"{len(text)} characters")
            task = asyncio.create_task(_run_broadcast(app, _bot(), text, session.get("who", "panel")))
            tasks = app.config.setdefault("BG_TASKS", set())  # keep a reference so it isn't GC'd
            tasks.add(task)
            task.add_done_callback(tasks.discard)
            _flash("Broadcast started.")
        return redirect(f"{P}/broadcast")

    return await _render("broadcast.html", st=state)


# --------------------------------------------------- stream link maker

_TG_LINK = re.compile(r"^https?://t\.me/c/(\d+)/(\d+)")


def _parse_source(text: str, primary: int):
    """t.me/c link, '<channel_id> <msg_id>' or just '<msg_id>' -> (chat_id, msg_id)."""
    text = (text or "").strip()
    m = _TG_LINK.match(text)
    if m:
        return int(f"-100{m.group(1)}"), int(m.group(2))
    parts = text.split()
    if len(parts) == 2 and all(p.lstrip("-").isdigit() for p in parts):
        return int(parts[0]), int(parts[1])
    if len(parts) == 1 and parts[0].isdigit():
        return primary, int(parts[0])
    return None


@panel.route("/links", methods=["GET", "POST"])
@login_required
async def links_page():
    bot = _bot()
    result = None
    source = ""

    if request.method == "POST":
        form = await request.form
        source = (form.get("source") or "").strip()
        primary = int(getattr(bot, "primary_db_channel", bot.db))
        parsed = _parse_source(source, primary)

        if not links_enabled():
            _flash("Set WEB_URL first, links can't be built without it.", "err")
        elif not parsed:
            _flash("Use a https://t.me/c/<id>/<msg> link, '<channel_id> <msg_id>' or just a message ID.", "err")
        elif parsed[0] not in data.allowed_channels(bot):
            _flash("That channel is not one of the bot's DB channels.", "err")
        else:
            try:
                info = extract_media(await bot.get_messages(*parsed))
            except Exception as e:
                info = None
                _flash(f"Could not read that message: {e}", "err")
            else:
                if info is None:
                    _flash("That message has no video, audio or document.", "err")
                else:
                    result = {"name": info.name, "links": build_links(*parsed)}
                    await _log("stream_link_created", f"{parsed[0]}/{parsed[1]}", info.name)

    return await _render("links.html", result=result, source=source)


# ==========================================================
# File streaming (real bytes from Telegram, Range/seek supported)
# ==========================================================

async def _empty_body():
    return
    yield  # pragma: no cover  (makes this an async generator)


async def _resolve(ref):
    """Verify the signature, then find the media. Aborts with a proper HTTP error."""
    if not verify(ref, request.args.get("exp"), request.args.get("sig")):
        abort(403)
    parsed = parse_ref(ref)
    if not parsed:
        abort(404)
    chat_id, msg_id = parsed

    bot = _bot()
    if not getattr(bot, "username", None):
        abort(503)  # bot is still starting
    if chat_id not in data.allowed_channels(bot):
        abort(404)

    info = MEDIA_CACHE.get((chat_id, msg_id))
    if info is None:
        try:
            message = await bot.get_messages(chat_id, msg_id)
        except Exception:
            log.exception("get_messages failed for %s", ref)
            abort(502)
        info = extract_media(message)
        if info is None:
            abort(404)
        MEDIA_CACHE.put((chat_id, msg_id), info)
    return bot, info


@web.route(f"{STREAM_PATH}/<ref>", methods=["GET", "HEAD"])
async def stream_file(ref):
    bot, info = await _resolve(ref)

    download = request.args.get("download") == "1"
    plan = make_plan(info, request.headers.get("Range"), download)

    if plan.status == 416:
        return Response(b"", status=416, headers=plan.headers)

    if request.method == "HEAD":
        resp = Response(_empty_body(), status=plan.status, headers=plan.headers)
        resp.timeout = None
        return resp

    stream = iter_file(bot, info.file_id, plan.start, plan.end)

    # Fetch the first chunk *before* sending headers, so a bad/expired file
    # becomes a proper HTTP error instead of a broken 200.
    try:
        first = await stream.__anext__()
    except StopAsyncIteration:
        first = None
    except Exception:
        log.exception("Telegram refused to serve %s", ref)
        MEDIA_CACHE.discard(parse_ref(ref))
        abort(502)

    async def body():
        try:
            if first is not None:
                yield first
            async for chunk in stream:
                yield chunk
        finally:
            await stream.aclose()

    resp = Response(body(), status=plan.status, headers=plan.headers)
    resp.timeout = None  # Quart's default response timeout would cut long videos
    return resp


@web.route("/watch/<ref>")
async def watch_file(ref):
    _, info = await _resolve(ref)

    mime = info.mime or ""
    kind = "audio" if mime.startswith("audio/") else "video" if mime.startswith("video/") else "file"
    qs = urlencode({"exp": request.args.get("exp", ""), "sig": request.args.get("sig", "")})
    return await render_template(
        "watch.html",
        ref=ref, name=info.name, mime=mime, kind=kind, qs=qs,
        size=humanize.naturalsize(info.size, binary=True) if info.size else "",
        stream_path=STREAM_PATH,
    )
