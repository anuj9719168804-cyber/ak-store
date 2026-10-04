from datetime import timedelta

from quart import Quart

from config import ADMIN_PANEL_PATH, PANEL_SECRET, STREAM_PATH, WEB_URL
# Imported under new names on purpose: the next line (`import web.routes`) rebinds
# the name `web` to the *package*, so register_blueprint(web) would get a module.
from web import web as public_bp, panel as panel_bp
import web.routes  # noqa: F401  (registers the routes on the blueprints)
import web.verify_routes  # noqa: F401  (/go and /verify: web anti-bypass check)
import web.pay_routes  # noqa: F401  (/webhook/razorpay, /webhook/nowpayments)
import web.panel_v9  # noqa: F401  (panel pages: analytics, limited links)
import web.panel_v10  # noqa: F401  (panel pages: user detail, bans, referrals, codes, support, restart)
from web.auth import csrf_token
from helper.timefmt import ist


def create_app(bot) -> Quart:
    """Web app that shares the running Pyrogram client (same process, same event loop)."""
    if ADMIN_PANEL_PATH and (
        ADMIN_PANEL_PATH == STREAM_PATH
        or ADMIN_PANEL_PATH.startswith(STREAM_PATH + "/")
        or STREAM_PATH.startswith(ADMIN_PANEL_PATH + "/")
    ):
        raise ValueError("ADMIN_PANEL_PATH and STREAM_PATH must not overlap")

    app = Quart(__name__, static_folder=None)  # static files are served by the blueprint
    app.secret_key = PANEL_SECRET
    app.config["BOT"] = bot

    # Every panel POST needs the session's CSRF token (web/auth.py). Lax cookies and
    # the Origin check stay on as extra layers.
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SECURE"] = WEB_URL.startswith("https://")
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=12)

    @app.context_processor
    def inject_panel_path():
        return {"panel": ADMIN_PANEL_PATH, "csrf_token": csrf_token, "ist": ist}

    app.register_blueprint(public_bp)
    app.register_blueprint(panel_bp)
    return app
