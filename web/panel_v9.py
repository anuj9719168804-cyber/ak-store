"""Panel pages added in v9: Analytics (graphs, top files/links, orders) and Limited links."""
from urllib.parse import urlencode

from quart import redirect, request

from config import ADMIN_PANEL_PATH
from helper import links, stats
from helper.helper_func import decode, encode
from helper.permanent_link import build_link
from web import data, panel
from web.auth import login_required
from web.charts import bar_chart
from web.routes import _bot, _flash, _log, _parse_source, _render

P = ADMIN_PANEL_PATH


# ==========================================================
# Analytics
# ==========================================================

@panel.route("/analytics")
@login_required
async def analytics_page():
    bot = _bot()
    db = bot.mongodb.db
    try:
        days = min(max(int(request.args.get("days", 14)), 7), 60)
    except ValueError:
        days = 14
    rows = await stats.series(db, days)
    totals = {k: sum(r[k] for r in rows) for k in stats.FIELDS}

    top_files = await bot.mongodb.files.find({"downloads": {"$gt": 0}}).sort([("downloads", -1)]).limit(10).to_list(length=10)
    top_links = []
    for doc in await stats.top_links(db, 10):
        key = doc["_id"]
        label = key
        if links.is_managed(key):
            ldoc = await links.get(db, key)
            label = f"{key}" + (f" · {ldoc['note']}" if ldoc and ldoc.get("note") else "")
        top_links.append({"key": key, "label": label, "clicks": doc.get("clicks", 0), "last": doc.get("last"),
                          "link": build_link(bot, key) if getattr(bot, "username", None) else ""})
    orders = await db["orders"].find({}).sort([("created", -1)]).limit(20).to_list(length=20)

    traffic = bar_chart(rows, [("clicks", "Link clicks"), ("delivered", "Files sent"), ("new_users", "New users")], title="Traffic")
    guard = bar_chart(rows, [("verified", "Verified"), ("bypass", "Bypass caught")], title="Verification")
    return await _render("analytics.html", rows=rows, totals=totals, days=days, top_files=top_files, top_links=top_links,
                         orders=orders, traffic=traffic, guard=guard)


# ==========================================================
# Limited (expiring / max-uses) links
# ==========================================================

async def _payload_from_form(bot, text: str):
    """A t.me/c post link / '<channel> <msg>' / message id (single file), or any link the bot made before."""
    parsed = _parse_source(text, int(getattr(bot, "primary_db_channel", bot.db)))
    if parsed:
        chat_id, msg_id = parsed
        if chat_id not in data.allowed_channels(bot):
            return None, "That channel is not one of the bot's DB channels."
        return await encode(f"get-{msg_id * abs(chat_id)}"), None
    payload = links.extract_payload(text)
    if not payload or links.is_managed(payload) or payload.startswith(("yu3elk", "vt_", "ref_")):
        return None, "Paste a post link, a message ID, or a link made by /genlink or /batch."
    try:
        parts = (await decode(payload)).split("-")
    except Exception:
        return None, "That is not a link made by this bot."
    if parts[0] not in ("get", "getc") or not 2 <= len(parts) <= 3:
        return None, "That is not a link made by this bot."
    return payload, None


@panel.route("/managed", methods=["GET", "POST"])
@login_required
async def managed_page():
    bot = _bot()
    db = bot.mongodb.db
    if request.method == "POST":
        form = await request.form
        action = form.get("action")
        if action == "revoke":
            token = (form.get("token") or "").strip()
            if await links.revoke(db, token):
                await _log("explink_revoked", links.PREFIX + links.token_of(token))
                _flash("Link revoked. It stops working immediately.")
            else:
                _flash("Link not found.", "err")
        elif action == "create":
            ttl = links.parse_duration(form.get("ttl") or "0")
            try:
                max_uses = int((form.get("max_uses") or "0").strip() or 0)
            except ValueError:
                max_uses = -1
            payload, error = await _payload_from_form(bot, (form.get("source") or "").strip())
            if ttl is None or max_uses < 0:
                _flash("Time like 24h / 7d / 0 and a whole number of people (0 = unlimited).", "err")
            elif ttl == 0 and max_uses == 0:
                _flash("Set a time limit, a user limit, or both. Otherwise it is just a normal link.", "err")
            elif error:
                _flash(error, "err")
            else:
                doc = await links.create(db, payload, "panel", ttl, max_uses, (form.get("note") or "").strip())
                await _log("explink_created", links.PREFIX + doc["_id"],
                           f"ttl={links.describe_seconds(ttl) if ttl else 'none'} max_uses={max_uses or 'none'}")
                _flash("Created: " + build_link(bot, links.PREFIX + doc["_id"]))
        return redirect(f"{P}/managed")

    rows = []
    for doc in await links.recent(db, 50):
        rows.append({"token": doc["_id"], "state": links.state_of(doc), "uses": doc.get("uses", 0), "max_uses": doc.get("max_uses", 0),
                     "clicks": doc.get("clicks", 0), "expires_at": doc.get("expires_at"), "note": doc.get("note", ""),
                     "created": doc.get("created"),
                     "link": build_link(bot, links.PREFIX + doc["_id"]) if getattr(bot, "username", None) else ""})
    return await _render("managed.html", rows=rows)


# ==========================================================
# Verification quality (how real users behave, who looks like a bypass)
# ==========================================================

@panel.route("/verification")
@login_required
async def verification_page():
    from helper import verify_web as vw
    db = _bot().mongodb.db
    docs = await db["verify_tokens"].find({"state": {"$in": ["passed", "used", "failed"]}, "elapsed": {"$exists": True}}) \
        .sort([("created", -1)]).limit(150).to_list(length=150)
    good = sorted(float(d["elapsed"]) for d in docs if d["state"] in ("passed", "used") and not d.get("flagged"))
    pct = lambda p: good[min(int(len(good) * p), len(good) - 1)] if good else None
    summary = {
        "total": len(docs), "passed": sum(d["state"] in ("passed", "used") for d in docs),
        "flagged": sum(bool(d.get("flagged")) for d in docs),
        "blocked": sum(bool(d.get("blocked_by_risk")) for d in docs),
        "too_fast": sum(d["state"] == "failed" and not d.get("blocked_by_risk") for d in docs),
        "median": pct(0.5), "p10": pct(0.1), "samples": len(good),
        "suggest_min": int(pct(0.1) * 0.6) if pct(0.1) else None,
        "min_now": vw.MIN_SECONDS, "ref_ok": sum(d.get("ref_ok") is True for d in docs),
        "no_cookie": sum(d.get("cookie_ok") is False for d in docs),
    }
    return await _render("verification.html", docs=docs[:60], s=summary, flag=vw.RISK_FLAG, block=vw.RISK_BLOCK, action=vw.RISK_ACTION)
