from quart import Blueprint

from config import ADMIN_PANEL_PATH

# Public routes: health, file streaming, player page, static files
web = Blueprint("web", __name__, static_folder="static")

# Admin panel, mounted under ADMIN_PANEL_PATH ("" = site root)
panel = Blueprint("panel", __name__, url_prefix=ADMIN_PANEL_PATH or None)
