"""Panel pages added in v10, ideas taken from the AK Ultra admin panel:

  /users/<id>   one page per user: credits, premium, ban (with reason), referrals, ledger, orders, message
  /bans         banned users with their reason; ban by ID; unban / unban all
  /referrals    top inviters and payout summary
  /codes        make, switch on/off and delete gift codes (same codes as /gencode in the bot)
  /support      inbox for /contact messages; /support/<id> is one conversation
  /restart      restart the bot process from the panel
  /api/stats    JSON for the dashboard's auto-refresh
  /logs/clear   empty the activity log

Same rules as the other panel pages: login_required (CSRF + origin check on every POST), every
action is written to the activity log, nothing here trusts form input without checking it.
"""
import asyncio
import html
import os
import sys

from quart import current_app, redirect, request

from config import ADMIN_PANEL_PATH, NOTIFY_ON_BAN
from helper import codes, support
from helper.utils import to_int as _to_int
from web import data10, panel
from web.auth import login_required
from web.routes import _bot, _flash, _log, _render

P = ADMIN_PANEL_PATH
MAX_PREMIUM_DAYS = 36500          # 100 years; "empty" means lifetime
MAX_CREDIT_STEP = 10_000_000


async def _tell(bot, user_id: int, text: str) -> bool:
    """Send a notice to a user. Never raises (blocked the bot, never started it, ...)."""
    try:
        await bot.send_message(int(user_id), text)
        return True
    except Exception:
        return False


async def _ban(bot, uid: int, reason: str) -> str:
    """Ban from the panel. -> '' on success, else the error text."""
    if uid in bot.admins:
        return "Admins can't be banned."
    m = bot.mongodb
    if not await m.present_user(uid):
        await m.add_user(uid, True)       # same as the /ban command: unknown ids are pre-banned
    await m.ban_user(uid, reason)
    await _log("ban_user", uid, reason)
    if NOTIFY_ON_BAN:
        await _tell(bot, uid, "🚫 <b>You have been banned from this bot.</b>"
                    + (f"\n\n<b>Reason:</b> {html.escape(reason)}" if reason else ""))
    return ""


async def _unban(bot, uid: int):
    await bot.mongodb.unban_user(uid)
    await _log("unban_user", uid)
    if NOTIFY_ON_BAN:
        await _tell(bot, uid, "✅ <b>You have been unbanned.</b> You can use the bot again.")


# ==========================================================
# One user
# ==========================================================

@panel.route("/users/<int:uid>", methods=["GET", "POST"])
@login_required
async def user_page(uid):
    bot = _bot()
    m = bot.mongodb
    if request.method == "POST":
        form = await request.form
        action = form.get("action")
        if not await m.present_user(uid):
            _flash("User not found.", "err")
            return redirect(f"{P}/users")

        if action == "ban":
            err = await _ban(bot, uid, (form.get("reason") or "").strip()[:200])
            _flash(err or f"Banned {uid}.", "err" if err else "ok")
        elif action == "unban":
            await _unban(bot, uid)
            _flash(f"Unbanned {uid}.")
        elif action == "credits":
            mode = form.get("mode")
            amount = _to_int(form.get("amount"), -1)
            if not 0 <= amount <= MAX_CREDIT_STEP:
                _flash("Enter a whole number of credits.", "err")
            else:
                try:
                    old, new = await data10.adjust_credits(m, uid, mode, amount, who="panel")
                except ValueError as e:
                    _flash(str(e).capitalize() + ".", "err")
                else:
                    await _log("credits_changed", uid, f"{mode} {amount}: {old} -> {new}")
                    _flash(f"Credits: {old} → {new}.")
        elif action == "premium_add":
            raw = (form.get("days") or "").strip()
            days = _to_int(raw, -1) if raw else 0
            if not 0 <= days <= MAX_PREMIUM_DAYS:
                _flash("Days must be a whole number (empty = lifetime).", "err")
            else:
                result = await data10.give_premium(m, uid, days)
                await _log("add_premium", uid, result)
                _flash(f"Premium: {result}.")
        elif action == "premium_remove":
            await m.remove_pro(uid)
            await _log("remove_premium", uid)
            _flash(f"Premium removed from {uid}.")
        elif action == "message":
            text = (form.get("text") or "").strip()[:1000]
            if not text:
                _flash("Message can't be empty.", "err")
            elif await _tell(bot, uid, f"📩 <b>Message from the admins</b>\n\n{html.escape(text)}"):
                await _log("message_user", uid, f"{len(text)} characters")
                _flash("Message sent.")
            else:
                _flash("Telegram did not deliver it (the user blocked the bot or never started it).", "err")
        else:
            _flash("Unknown action.", "err")
        return redirect(f"{P}/users/{uid}")

    detail = await data10.user_detail(m, uid)
    if not detail:
        _flash("User not found.", "err")
        return redirect(f"{P}/users")
    return await _render("user_detail.html", u=detail, is_admin=uid in bot.admins)


# ==========================================================
# Bans
# ==========================================================

@panel.route("/bans", methods=["GET", "POST"])
@login_required
async def bans_page():
    bot = _bot()
    if request.method == "POST":
        form = await request.form
        action = form.get("action")
        uid = _to_int(form.get("user_id"))
        if action == "ban":
            if uid <= 1:
                _flash("Enter a valid user ID.", "err")
            else:
                err = await _ban(bot, uid, (form.get("reason") or "").strip()[:200])
                _flash(err or f"Banned {uid}.", "err" if err else "ok")
        elif action == "unban":
            if uid <= 1:
                _flash("Enter a valid user ID.", "err")
            else:
                await _unban(bot, uid)
                _flash(f"Unbanned {uid}.")
        elif action == "unban_all":
            count = await bot.mongodb.unban_all_users()
            await _log("unban_all", "", f"{count} users")
            _flash(f"Unbanned {count} users.")
        return redirect(f"{P}/bans")

    rows, total = await data10.banned_users(bot.mongodb)
    return await _render("bans.html", rows=rows, total=total)


# ==========================================================
# Referrals
# ==========================================================

@panel.route("/referrals")
@login_required
async def referrals_page():
    page = max(_to_int(request.args.get("page"), 1), 1)
    per_page = 25
    rows, total, summary = await data10.referral_board(_bot().mongodb, page, per_page)
    return await _render("referrals.html", rows=rows, total=total, summary=summary, page=page,
                         has_next=page * per_page < total, first_rank=(page - 1) * per_page + 1)


# ==========================================================
# Gift codes
# ==========================================================

@panel.route("/codes", methods=["GET", "POST"])
@login_required
async def codes_page():
    bot = _bot()
    db = bot.mongodb.db
    if request.method == "POST":
        form = await request.form
        action = form.get("action")
        code = (form.get("code") or "").strip()
        if action == "create":
            kind = form.get("kind")
            amount = _to_int(form.get("amount"), -1)
            people = _to_int(form.get("max_uses"), 0)
            valid_days = _to_int(form.get("valid_days"), 0) if (form.get("valid_days") or "").strip() else 0
            if valid_days < 0 or valid_days > 3650:
                _flash("Valid days: 0 (never expires) up to 3650.", "err")
            else:
                try:
                    doc = await codes.create(db, kind, amount, people, "panel", valid_days * 86400, code,
                                             (form.get("note") or "").strip())
                except ValueError as e:
                    _flash(str(e)[:1].upper() + str(e)[1:] + ".", "err")
                else:
                    await _log("code_created", doc["_id"], f"{kind} {amount} x{people}")
                    _flash(f"Code created: {doc['_id']}")
        elif action in ("off", "on"):
            if await codes.set_active(db, code, action == "on"):
                await _log("code_switched", code, action)
                _flash(f"{code} is now {action}.")
            else:
                _flash("Code not found.", "err")
        elif action == "delete":
            if await codes.remove(db, code):
                await _log("code_deleted", code)
                _flash(f"{code} deleted.")
            else:
                _flash("Code not found.", "err")
        return redirect(f"{P}/codes")

    rows = data10.code_rows(await codes.recent(db, 200))
    return await _render("codes.html", rows=rows)


# ==========================================================
# Support inbox
# ==========================================================

@panel.route("/support")
@login_required
async def support_page():
    show_all = request.args.get("all") == "1"
    db = _bot().mongodb.db
    rows = await support.threads(db, only_open=not show_all)
    return await _render("support.html", rows=rows, show_all=show_all, counts=await support.counts(db))


@panel.route("/support/<int:uid>", methods=["GET", "POST"])
@login_required
async def support_thread(uid):
    bot = _bot()
    db = bot.mongodb.db
    if not await support.get_thread(db, uid):
        _flash("No such conversation.", "err")
        return redirect(f"{P}/support")

    if request.method == "POST":
        form = await request.form
        action = form.get("action")
        if action == "reply":
            try:
                delivered, note = await support.send_reply(bot, uid, form.get("text") or "", "panel")
            except ValueError:
                _flash("Write an answer first.", "err")
            else:
                await _log("support_reply", uid)
                _flash("Sent." if delivered else f"Saved, but Telegram would not deliver it ({note}).",
                       "ok" if delivered else "err")
        elif action in ("close", "reopen"):
            await support.set_open(db, uid, action == "reopen")
            await _log(f"support_{action}", uid)
            _flash("Conversation closed." if action == "close" else "Conversation reopened.")
        return redirect(f"{P}/support/{uid}")

    await support.mark_read(db, uid)
    return await _render("support_thread.html", t=await support.get_thread(db, uid),
                         msgs=await support.messages(db, uid))


# ==========================================================
# Restart, live stats, clear logs
# ==========================================================

async def _restart_soon():
    await asyncio.sleep(1.5)                       # let the "restarting" page reach the browser first
    os.execv(sys.executable, [sys.executable] + sys.argv)


@panel.route("/restart", methods=["GET", "POST"])
@login_required
async def restart_page():
    if request.method == "POST":
        await _log("panel_restart")
        app = current_app._get_current_object()
        task = asyncio.create_task(_restart_soon())
        tasks = app.config.setdefault("BG_TASKS", set())
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return await _render("restart.html", restarting=True)
    return await _render("restart.html", restarting=False)


@panel.route("/api/stats")
@login_required
async def api_stats():
    return await data10.live_stats(_bot())


@panel.route("/logs/clear", methods=["POST"])
@login_required
async def logs_clear():
    res = await _bot().mongodb.db["activity"].delete_many({})
    await _log("logs_cleared", "", f"{getattr(res, 'deleted_count', 0)} entries")   # first entry of the new log
    _flash("Activity log cleared.")
    return redirect(f"{P}/logs")
