import os
import hashlib
import logging
from logging.handlers import RotatingFileHandler

# Optional: read a local .env file (see .env.example). Real environment variables win.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# Every value below can come from an environment variable / .env file;
# if the variable is not set, the value written in this file is used.
def _get(name, default):
    raw = os.getenv(name)
    return raw.strip() if raw and raw.strip() else default


def _get_int(name, default):
    raw = os.getenv(name)
    if not raw or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        raise ValueError(f"{name} must be a whole number, got {raw!r}")


def _get_bool(name, default):
    raw = os.getenv(name)
    if not raw or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _get_int_list(name, default):
    raw = os.getenv(name)
    if not raw or not raw.strip():
        return default
    return [int(x) for x in raw.replace(",", " ").split()]


def _get_api_id(default):
    raw = _get("API_ID", None)
    if raw is None:
        return default
    return int(raw) if raw.isdigit() else raw


# Bot Configuration
LOG_FILE_NAME = "bot.log"
PORT = int(os.environ.get("PORT", 5010))  # Render/Heroku inject PORT
OWNER_ID = _get_int("OWNER_ID", 8729304171)

MSG_EFFECT = 5046509860389126442

SHORT_URL = _get("SHORT_URL", "shrinkme.io") # shortner url 
SHORT_API = _get("SHORT_API", "05e572390d5a204da2ae17f59ff2fadfe2aaa23a") # shortner API
SHORT_TUT = _get("SHORT_TUT", "https://t.me/+s7xUnZN3_hgxNjNl") # shortner tutorial link

# Bot Configuration
SESSION = _get("SESSION", "filestore_bot")
TOKEN = _get("TOKEN", "8815294227:AAHrGIgha2w2oKLEFlir7l038Yo8JYyHy6o") # Bot token
API_ID = _get_api_id("20432885") # API ID
API_HASH = _get("API_HASH", "4fdcfab1c7f5e24ae69f3ce6bb234dec") # API HASH
WORKERS = _get_int("WORKERS", 5)

DB_URI = _get("DB_URI", "mongodb+srv://Anujedit:Anujedit@cluster0.7cs2nhd.mongodb.net/?appName=Cluster0") # MongoDB URI
DB_NAME = _get("DB_NAME", "BotifyX-Filestore")

FSUBS = [[-1004396123873, True, 10]] # Force Subscription Channels [channel_id, request_enabled, timer_in_minutes]
# Database Channel (Primary)
DB_CHANNEL = _get_int("DB_CHANNEL", -1003873749415)  # just put channel id dont add ""
# Multiple Database Channels (can be set via bot settings)
# DB_CHANNELS = {
#     "-1002595092736": {"name": "Primary DB", "is_primary": True, "is_active": True},
#     "-1001234567890": {"name": "Secondary DB", "is_primary": False, "is_active": True}
# }
# Auto Delete Timer (seconds)
AUTO_DEL = _get_int("AUTO_DEL", 300)
# Admin IDs
ADMINS = _get_int_list("ADMINS", [8729304171])
# Bot Settings
DISABLE_BTN = _get_bool("DISABLE_BTN", True)
PROTECT = _get_bool("PROTECT", True) # For content protection stops message forwarding and copying from the bot and same goes for the screenshot

# Messages Configuration
MESSAGES = {
    "START": "╭━━━〔 ✦ 𝐅𝐈𝐋𝐄 𝐌𝐀𝐍𝐀𝐆𝐄𝐌𝐄𝐍𝐓 𝐀𝐒𝐒𝐈𝐒𝐓𝐀𝐍𝐓 ✦ 〕━━━╮\n\n👋 𝗪ᴇʟᴄᴏᴍᴇ ᴛᴏ ʏᴏᴜʀ 𝗔ʟʟ-𝗜ɴ-𝗢ɴᴇ\n𝗙ɪʟᴇ 𝗠ᴀɴᴀɢᴇᴍᴇɴᴛ 𝗔ssɪsᴛᴀɴᴛ ⚡\n\n🚀 𝗠ᴀɴᴀɢᴇ • 𝗢ʀɢᴀɴɪᴢᴇ • 𝗦ʜᴀʀᴇ\n\n✨ Effortlessly manage your files with a\nfast, clean &amp; reliable experience.\n\n📁 𝗦ᴍᴀʀᴛ 𝗙ɪʟᴇ 𝗠ᴀɴᴀɢᴇᴍᴇɴᴛ\n⚡ 𝗙ᴀsᴛ &amp; 𝗥ᴇʟɪᴀʙʟᴇ 𝗣ᴇʀғᴏʀᴍᴀɴᴄᴇ\n🔗 𝗘ᴀsʏ 𝗦ʜᴀʀɪɴɢ &amp; 𝗔ᴄᴄᴇss\n🧹 𝗖ʟᴇᴀɴ &amp; 𝗢ʀɢᴀɴɪᴢᴇᴅ 𝗙ɪʟᴇs\n\n💎 𝗣ʀᴇᴍɪᴜᴍ • 𝗦ᴍᴀʀᴛ • 𝗣ʀᴏғᴇssɪᴏɴᴀʟ\n\n━━━━━━━━━━━━━━━━━━━━\n\n❤️ 𝗠ᴀɪɴᴛᴀɪɴᴇᴅ ʙʏ\n彡 ᴀɴᴜᴊ ᴋᴜᴍᴀʀ 彡 ⭐️\n\n╰━━━━━━━━━━━━━━━━━━━━╯",
    "FSUB": "<blockquote>›› ʜᴇʏ {mention}× sᴇɴᴘᴀɪ 🎊</blockquote>\n<blockquote><b>ʏᴏᴜʀ ғɪʟᴇ ɪs ʀᴇᴀᴅʏ ‼️ ʟᴏᴏᴋs ʟɪᴋᴇ ʏᴏᴜ ʜᴀᴠᴇɴ'ᴛ sᴜʙsᴄʀɪʙᴇᴅ ᴛᴏ ᴏᴜʀ ᴄʜᴀɴɴᴇʟs ʏᴇᴛ, sᴜʙsᴄʀɪʙᴇ ɴᴏᴡ ᴛᴏ ɢᴇᴛ ʏᴏᴜʀ ғɪʟᴇs</b></blockquote>",
    "ABOUT": "<b>›› ғᴏʀ ᴍᴏʀᴇ: <a href='https://t.me/ANIME_X_FLEX'>Cʟɪᴄᴋ ʜᴇʀᴇ</a>\n<blockquote expandable>›› ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ: <a href='https://t.me/BotifyX_Pro_Botz'>ʙᴏᴛɪғʏx_ᴏғғɪᴄɪᴀʟ</a> \n›› ᴏᴡɴᴇʀ: @ITSANIMEN\n›› ʟᴀɴɢᴜᴀɢᴇ: <a href='https://docs.python.org/3/'>Pʏᴛʜᴏɴ 3</a> \n›› ʟɪʙʀᴀʀʏ: <a href='https://docs.pyrogram.org/'>Pʏʀᴏɢʀᴀᴍ ᴠ2</a> \n›› ᴅᴀᴛᴀʙᴀsᴇ: <a href='https://www.mongodb.com/docs/'>Mᴏɴɢᴏ ᴅʙ</a> \n›› ᴅᴇᴠᴇʟᴏᴘᴇʀ: @ITS_shun_x</b></blockquote>",
    "CHANNELS":"<b>›› ᴀɴɪᴍᴇ ᴄʜᴀɴɴᴇʟ: <a href='https://t.me/Anime_z_Flex'>ᴏᴛᴀᴋᴜ_ɴᴀᴛɪᴏɴx</a>\n<blockquote expandable>›› ᴍᴏᴠɪᴇs: <a href='https://t.me/OTAKU_Mania'>ᴀɴɪ_ᴍᴏᴠɪᴇ's ᴍᴀɴɪᴀ</a>\n›› ᴀɴɪᴍᴇ ᴇᴅɪᴛᴢ: <a href='https://t.me/Animez_Edits'>ᴀɴɪᴍᴇ'ᴢ ᴇᴅɪᴛ'ᴢ</a>\n›› ᴀᴅᴜʟᴛ ᴄʜᴀɴɴᴇʟs: <a href='https://t.me/Hamine_flix'>𝖧𝖺𝗇𝗂𝗆𝖾 𝖥𝗅𝗂𝗑</a>\n›› ᴍᴀɴʜᴡᴀ ᴄʜᴀɴɴᴇʟ: <a href='https://t.me/pornwhaa_flix'>ᴘᴏʀɴʜᴡᴀ ғʟɪx</a>\n›› ᴄᴏᴍᴍᴜɴɪᴛʏ: <a href='https://t.me/ANIME_X_FLEX'>ᴏᴛᴀᴋᴜғʟɪx</a>\n›› ᴅᴇᴠᴇʟᴏᴘᴇʀ: @ITSANIMEN</b></blockquote>",
    "REPLY": "<b>ғᴜᴄᴋ ᴏғғ ʙɪᴛᴄʜ !!!</b>",
    "SHORT_MSG": "<blockquote><b>✧ TOKEN EXPIRED</b></blockquote>\n<blockquote>›› ᴘʟᴇᴀsᴇ ᴠᴇʀɪғʏ ᴛᴏ ʀᴇɢᴀɪɴ ᴀᴄᴄᴇss ᴛᴏ ᴛʜᴇ ғɪʟᴇs\n›› ᴠᴀʟɪᴅ ᴄʀᴇᴅɪᴛs: 5 ᴄʀᴇᴅɪᴛs</blockquote>\n────────────────────────\n<blockquote>›› ᴡʜᴀᴛ ɪs ᴀ ᴛᴏᴋᴇɴ?</blockquote>\n<blockquote>≡  ᴇᴀᴄʜ ᴀᴅ ʙʏᴘᴀss ʀᴇᴡᴀʀᴅ ʏᴏᴜ ᴡɪᴛʜ 5 ᴄʀᴇᴅɪᴛs.ᴏɴᴇ ᴄʀᴇᴅɪᴛ ɪs ᴄᴏɴsᴜᴍᴇᴅ ᴘᴇʀ ғɪʟᴇ/ʟɪɴᴋ ᴀᴄᴄᴇss.</blockquote>",
    "START_PHOTO": "https://ibb.co/ch6kvnMf",
    "FSUB_PHOTO": "https://ibb.co/C5q41g1C",
    "SHORT_PIC": "https://ibb.co/XxMhdhDs",
    "SHORT": "https://ibb.co/mC9H5kmF",
    "SHORT_VERIFY": "https://ibb.co/rGg6R2q6",
    "PREMIUM_PLANS_PIC": "https://ibb.co/8Dzq5n9G",
    "QR_PAYMENT_PIC": "https://ibb.co/kVPDT5cP",
    # Premium reminder / expiry notices. Placeholders: {expiry} date, {left} time left.
    "PREMIUM_REMINDER": "<b>⏰ Your premium is about to expire</b>\n<blockquote>Expires on: {expiry} ({left} left)</blockquote>\nRenew now to keep unlimited access without token verification.",
    "PREMIUM_EXPIRED": "<b>⌛ Your premium has expired</b>\nYou are back on the free plan (credits + verification). Renew any time to get premium again."
}

def LOGGER(name: str, client_name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    formatter = logging.Formatter(
        f"[%(asctime)s - %(levelname)s] - {client_name} - %(name)s - %(message)s",
        datefmt='%d-%b-%y %H:%M:%S'
    )
    file_handler = RotatingFileHandler(LOG_FILE_NAME, maxBytes=50_000_000, backupCount=10)
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    return logger


# ==========================================================
# Web panel + streaming (one server, same process as the bot)
# Everything below can be set as an environment variable.
# ==========================================================

def _env_int(name, default):
    raw = (os.getenv(name) or "").strip()
    return int(raw) if raw else default


def _path(value, default, allow_root=False):
    """Normalise a URL path: leading slash, no trailing slash ("" = site root)."""
    if value is None or not value.strip():
        return default
    inner = value.strip().strip("/")
    if not inner:
        return "" if allow_root else default
    return "/" + inner


def _derived(label):
    # Stable per-bot secret, so nothing has to be configured to get started.
    # Set the env var explicitly if you want to rotate it independently of TOKEN.
    return hashlib.sha256(f"{label}:{TOKEN}".encode()).hexdigest()


HOST = os.getenv("HOST") or "0.0.0.0"

# Public https URL of this deployment, used to build watch/download links.
# Empty -> the bot sends no web links (panel + server still run).
WEB_URL = (os.getenv("WEB_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")

# Admin panel password. Empty -> the panel is disabled (no default password).
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
ADMIN_PANEL_PATH = _path(os.getenv("ADMIN_PANEL_PATH"), "/admin", allow_root=True)

# Files are streamed from <STREAM_PATH>/<ref> (keep in sync with your nginx location)
STREAM_PATH = _path(os.getenv("STREAM_PATH"), "/file")
# Stream links are always signed. 0 = the link never expires.
STREAM_LINK_TTL = _env_int("STREAM_LINK_TTL", 86400)
# Parallel Telegram transfers (players open several Range requests at once)
STREAM_CONCURRENCY = _env_int("STREAM_CONCURRENCY", 8)

STREAM_SECRET = os.getenv("STREAM_SECRET") or _derived("stream")   # signs stream links
PANEL_SECRET = os.getenv("PANEL_SECRET") or _derived("panel")      # signs the panel session cookie

# Who may store files by sending them to the bot: admin | premium | all
#   admin   -> owner + admins only (Pro's original behaviour, default)
#   premium -> admins + premium users (media only)
#   all     -> everyone (media only). Fills your DB channel, use with care.
UPLOAD_ACCESS = (os.getenv("UPLOAD_ACCESS") or "admin").strip().lower()
if UPLOAD_ACCESS not in ("admin", "premium", "all"):
    LOGGER("config", "config").warning(f"UPLOAD_ACCESS={UPLOAD_ACCESS!r} is invalid, using 'admin'")
    UPLOAD_ACCESS = "admin"

# Flood protection: a non-admin may send one command per this many seconds (0 = off).
# Button presses are limited to one per second. Owner and admins are never limited.
RATE_LIMIT_SECONDS = _env_int("RATE_LIMIT_SECONDS", 5)

# Optional: panel/upload activity is also posted to this channel (bot must be admin there). 0 = off
LOG_CHANNEL_ID = _env_int("LOG_CHANNEL_ID", -1003873749415)

# Optional "Permanent Link" (ported from Multi-FileStoreBot): public URL of the Cloudflare Worker
# in backend/. When this is set AND the Permanent Link toggle is on (/settings -> page 2, or the web
# panel), generated links look like https://<worker>/?url=<payload> and redirect to the bot, so they
# keep working if the bot username ever changes. Empty = off.
BACKEND_API_URL = _get("BACKEND_API_URL", "").rstrip("/")
# Activity log entries older than this are deleted automatically (MongoDB TTL index)
ACTIVITY_KEEP_DAYS = _env_int("ACTIVITY_KEEP_DAYS", 90)

# Where the "Control Panel" button in /start opens (needs https)
ADMIN_PANEL_URL = f"{WEB_URL}{ADMIN_PANEL_PATH}/login" if WEB_URL else ""


# ==========================================================
# Files, duplicates, background jobs, panel security
# ==========================================================

# Same file sent again -> the bot replies with the old link instead of storing a copy.
# Matching uses Telegram's file_unique_id, then (file name + size).
DEDUPE_UPLOADS = _get_bool("DEDUPE_UPLOADS", True)

# Premium users get ONE reminder when this many days (or fewer) are left. 0 = off.
PREMIUM_REMINDER_DAYS = _env_int("PREMIUM_REMINDER_DAYS", 2)
# How often (hours) the bot checks for reminders and removes expired premium users.
PREMIUM_CHECK_HOURS = max(_env_int("PREMIUM_CHECK_HOURS", 6), 1)
# Button under the reminder / expiry message
RENEW_URL = _get("RENEW_URL", "https://t.me/anujedits76")

# A MongoDB backup is sent to the owner on Telegram every N hours (0 = off).
AUTO_BACKUP_HOURS = _env_int("AUTO_BACKUP_HOURS", 24)

# Two-step panel login: after the password, a 6-digit code is sent to the OWNER on Telegram.
# Env-only on purpose, so nobody inside the panel can switch it off.
PANEL_2FA = _get_bool("PANEL_2FA", False)

# ── From AK Ultra: free trial, support inbox, ban notices ────────────────────
# /trial gives every user ONE free premium trial of this many days (0 = off, the default).
TRIAL_DAYS = _env_int("TRIAL_DAYS", 0)
# /contact <message> opens a support thread the admins answer in the panel (Support) or with /reply.
# Seconds a user must wait between two /contact messages, 0 = no limit.
SUPPORT_COOLDOWN = _env_int("SUPPORT_COOLDOWN", 30)
# Tell a user in the bot when an admin bans / unbans them from the panel (the ban reason is included).
NOTIFY_ON_BAN = _get_bool("NOTIFY_ON_BAN", True)

# Keep the console readable: these libraries log every request at INFO (from Multi-FileStoreBot)
for _noisy in ("pyrogram", "pymongo", "motor", "hypercorn"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

# ==========================================================
# ── Multi-User Bot Creation System ─────────────────────────
# (ported from Multi-FileStoreBot)
# ==========================================================

# Fernet key for encrypting worker bot tokens at rest.
# Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
ENCRYPTION_KEY = _get("ENCRYPTION_KEY", "")

# Maximum worker bots a single user can create
MAX_BOTS_PER_USER = _get_int("MAX_BOTS_PER_USER", 1)

# Seconds a user must wait between creating bots
BOT_CREATION_COOLDOWN = _get_int("BOT_CREATION_COOLDOWN", 30)

# Shortener bypass detection (main bot + worker bots)
BYPASS_MIN_SECONDS = _get_int("BYPASS_MIN_SECONDS", 45)      # faster than this = bypass
VERIFY_MAX_SECONDS = _get_int("VERIFY_MAX_SECONDS", 240)     # slower than this = expired
BYPASS_MAX_STRIKES = _get_int("BYPASS_MAX_STRIKES", 3)       # strikes before auto-ban
BYPASS_AUTO_BAN = _get_bool("BYPASS_AUTO_BAN", True)         # ban after max strikes

# After this many hours of inactivity a worker bot is auto-hibernated (0 = off)
HIBERNATION_HOURS = _get_int("HIBERNATION_HOURS", 48)

# Channel where link-generation and bot-creation events are logged.
# Defaults to the Pro bot's LOG_CHANNEL_ID if not set separately.
MAIN_LOG_CHANNEL = _get_int("MAIN_LOG_CHANNEL", LOG_CHANNEL_ID)

# Shared secret sent in Authorization: Bearer header to the Cloudflare backend
BACKEND_API_SECRET = _get("BACKEND_API_SECRET", "")

# ==========================================================
# Auto-post (/autopost): scheduled posts to your promo channels
# ==========================================================
# Text in the footer line of every auto-post, e.g. @YourChannel (empty = plain footer)
AUTOPOST_BRAND = _get("AUTOPOST_BRAND", "")
# Optional button under every auto-post (both needed, empty = no button)
AUTOPOST_BUTTON_TEXT = _get("AUTOPOST_BUTTON_TEXT", "")
AUTOPOST_BUTTON_URL = _get("AUTOPOST_BUTTON_URL", "")


# ==========================================================
# v9 additions
# ==========================================================

# ── Expiring / limited links (/explink) ──────────────────────────────────────
# Nothing to configure: links made with /explink carry their own expiry and max uses.

# ── Web verify page (strong anti-bypass) ─────────────────────────────────────
# The shortener sends the user to YOUR page (WEB_URL/verify/<token>) instead of straight to Telegram.
# The page checks the browser (proof-of-work, real tap, same-browser cookie, timing) and only then
# opens the bot. Needs WEB_URL. When off (or WEB_URL empty) the old time-only check is used.
VERIFY_WEB = _get_bool("VERIFY_WEB", True)
VERIFY_WEB_ACTIVE = bool(VERIFY_WEB and WEB_URL)
# Fastest believable shortener run, measured from the browser check on /go to the /verify page.
VERIFY_MIN_SECONDS = _get_int("VERIFY_MIN_SECONDS", BYPASS_MIN_SECONDS)
# Proof-of-work size in bits (16 = ~65k hashes, well under a second on a phone; 0 = off)
VERIFY_POW_BITS = _get_int("VERIFY_POW_BITS", 16)
# Also require the shortener's domain in the Referer header (off by default: privacy browsers strip it)
VERIFY_REQUIRE_REFERRER = _get_bool("VERIFY_REQUIRE_REFERRER", False)
# If the same-browser cookie is missing, accept the same device (same User-Agent + same IP block)
VERIFY_COOKIE_FALLBACK = _get_bool("VERIFY_COOKIE_FALLBACK", True)
# Reject when the IP changed between the two steps (off by default: mobile networks switch IPs)
VERIFY_IP_STRICT = _get_bool("VERIFY_IP_STRICT", False)
# Credits given for one completed verification (the old flow always gave 5)
VERIFY_REWARD_CREDITS = _get_int("VERIFY_REWARD_CREDITS", 5)

# ── Auto payments (Razorpay = UPI/cards/netbanking, NOWPayments = crypto) ────
# Needs WEB_URL (public https). Webhook URLs to put in the gateway dashboards:
#   Razorpay     -> {WEB_URL}/webhook/razorpay      (event: payment_link.paid)
#   NOWPayments  -> set automatically per invoice   ({WEB_URL}/webhook/nowpayments)
RAZORPAY_KEY_ID = _get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = _get("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = _get("RAZORPAY_WEBHOOK_SECRET", "")
NOWPAYMENTS_API_KEY = _get("NOWPAYMENTS_API_KEY", "")
NOWPAYMENTS_IPN_SECRET = _get("NOWPAYMENTS_IPN_SECRET", "")
NOWPAYMENTS_API_URL = _get("NOWPAYMENTS_API_URL", "https://api.nowpayments.io/v1").rstrip("/")  # sandbox: https://api-sandbox.nowpayments.io/v1
PAYMENT_LINK_EXPIRE_MIN = max(_get_int("PAYMENT_LINK_EXPIRE_MIN", 60), 16)  # Razorpay needs at least 15 minutes

# Plans. EDIT THESE: prices (inr = rupees, usd = crypto price) and what each plan gives.
#   days 0 = permanent (lifetime). Keys are used in buttons, keep them short and unique.
PREMIUM_PLANS = {
    "1m":   {"label": "1 Month",   "days": 30,  "inr": 199,  "usd": 2.5},
    "3m":   {"label": "3 Months",  "days": 90,  "inr": 399,  "usd": 5.0},
    "6m":   {"label": "6 Months",  "days": 180, "inr": 599,  "usd": 7.5},
    "12m":  {"label": "12 Months", "days": 365, "inr": 999,  "usd": 12.0},
    "life": {"label": "Lifetime",  "days": 0,   "inr": 2999, "usd": 35.0},
}
CREDIT_PLANS = {
    "c30":  {"label": "30 credits",  "credits": 30,  "inr": 50,  "usd": 0.6},
    "c60":  {"label": "60 credits",  "credits": 60,  "inr": 110, "usd": 1.3},
    "c120": {"label": "120 credits", "credits": 120, "inr": 220, "usd": 2.6},
    "c240": {"label": "240 credits", "credits": 240, "inr": 480, "usd": 5.6},
}

# ── Referral + daily bonus ───────────────────────────────────────────────────
DAILY_BONUS_CREDITS = _get_int("DAILY_BONUS_CREDITS", 2)       # /daily, once per 24h (0 = off)
REFERRAL_CREDITS = _get_int("REFERRAL_CREDITS", 3)             # to the inviter, per new user (0 = off)
REFERRAL_NEW_USER_CREDITS = _get_int("REFERRAL_NEW_USER_CREDITS", 0)  # extra for the invited user
REFERRAL_MAX_PER_USER = _get_int("REFERRAL_MAX_PER_USER", 50)  # rewarded invites per inviter (0 = unlimited)
REFERRAL_WINDOW_HOURS = _get_int("REFERRAL_WINDOW_HOURS", 24)  # an invite only counts for accounts this new

# ── File search + inline mode ────────────────────────────────────────────────
# Who may use /search and @bot inline: all | premium | admin | off.  (Inline also needs /setinline in @BotFather.)
SEARCH_ACCESS = (_get("SEARCH_ACCESS", "all") or "all").lower()
if SEARCH_ACCESS not in ("all", "premium", "admin", "off"):
    SEARCH_ACCESS = "all"
SEARCH_PAGE_SIZE = max(min(_get_int("SEARCH_PAGE_SIZE", 8), 10), 3)

# ── Auto reactions (from AK Ultra) ───────────────────────────────────────────
# React with a random emoji to every command a user sends in private chat.
AUTO_REACT = _get_bool("AUTO_REACT", True)

# ── Auto-batch (from the src bot) ────────────────────────────────────────────
# Seconds to wait after the last upload of a title before its qualities are grouped. Switch on with /autobatch on.
AUTO_BATCH_WINDOW = max(min(_get_int("AUTO_BATCH_WINDOW", 30), 600), 5)

# ── Auto-quality: 144p ... 4K versions of every stored video (from the src bot) ──
# When a video is stored, the bot re-encodes it with ffmpeg into every smaller quality in the list,
# uploads each one to the same DB channel and sends ONE batch link with all qualities.
# Switch on with /autoquality on (this is only the default). Needs ffmpeg (the Dockerfile installs it).
AUTO_QUALITY = _get_bool("AUTO_QUALITY", False)
AUTO_QUALITY_LIST = _get("AUTO_QUALITY_LIST", "144p,240p,360p,480p,720p,1080p,1440p")   # 4K is never made (no upscaling)
AUTO_QUALITY_PRESET = _get("AUTO_QUALITY_PRESET", "veryfast")   # ultrafast ... veryslow: slower = smaller files
AUTO_QUALITY_THREADS = max(_get_int("AUTO_QUALITY_THREADS", 0), 0)        # ffmpeg threads, 0 = all cores
AUTO_QUALITY_PARALLEL = max(_get_int("AUTO_QUALITY_PARALLEL", 1), 1)      # videos encoded at the same time
AUTO_QUALITY_UPSCALE = _get("AUTO_QUALITY_UPSCALE", "")                    # e.g. "1080p,1440p,4K" = also upscale small videos to these; empty = off
AUTO_QUALITY_UPSCALE_MAX_FACTOR = max(_get_int("AUTO_QUALITY_UPSCALE_MAX_FACTOR", 4), 2)   # never enlarge more than this many times
AUTO_QUALITY_MAX_MB = max(_get_int("AUTO_QUALITY_MAX_MB", 4000), 1)       # never download a source bigger than this (disk / time guard; 4000 = Telegram Premium limit)

# ── Auto-split: files over 2 GB are cut into parts that fit Telegram ─────────
# Videos are cut with ffmpeg stream-copy (no re-encode, every part plays on its own); any other file
# is cut into raw bytes name.ext.001, .002 ... (join them with 7-Zip, or `cat name.ext.* > name.ext`).
# The parts go to the DB channel and ONE batch link delivers them all. Switch with /autosplit on|off.
# Optional: a Telegram PREMIUM user account (pyrogram string session) that does the uploading of big files.
# Bots can only upload 2 GB; a Premium account can upload ~4 GB, so with this set a 3 GB video / 4K copy
# is stored as ONE file instead of parts. The account must be an admin of the DB channel. Use a separate
# account, keep this value secret (anyone with it controls that account). Empty = bot only (2 GB + auto-split).
PREMIUM_SESSION = _get("PREMIUM_SESSION", "")
PREMIUM_MAX_MB = min(max(_get_int("PREMIUM_MAX_MB", 3900), 2100), 3990)     # biggest single file the Premium account uploads
AUTO_SPLIT = _get_bool("AUTO_SPLIT", True)
AUTO_SPLIT_MB = min(max(_get_int("AUTO_SPLIT_MB", 1900), 50), 1990)       # biggest part (a file above 2000 MB gets split)

# ── Same file posted by hand in the DB channel ───────────────────────────────
# warn = tell the owner | skip = also delete the new copy from the channel | off
DUPLICATE_DB_POST = (_get("DUPLICATE_DB_POST", "warn") or "warn").lower()
if DUPLICATE_DB_POST not in ("warn", "skip", "off"):
    DUPLICATE_DB_POST = "warn"

# ── Owner alerts ─────────────────────────────────────────────────────────────
ALERTS_ENABLED = _get_bool("ALERTS_ENABLED", True)
ALERT_CHECK_MINUTES = max(_get_int("ALERT_CHECK_MINUTES", 10), 1)     # DB / force-sub channel access check
WORKER_CHECK_MINUTES = max(_get_int("WORKER_CHECK_MINUTES", 60), 5)   # worker bot token check
BYPASS_SPIKE_COUNT = _get_int("BYPASS_SPIKE_COUNT", 10)               # this many bypass hits ...
BYPASS_SPIKE_MINUTES = max(_get_int("BYPASS_SPIKE_MINUTES", 10), 1)   # ... within this window = alert (0 count = off)


# ── Risk scoring on top of the web verify checks ─────────────────────────────
# Every verification gets a 0-100 risk score (too fast for this shortener's normal users, no
# shortener referrer, cookie missing, IP changed, many passes from one network). Learned from
# your own real traffic, so it adapts to whichever shortener you use.
VERIFY_RISK_FLAG = _get_int("VERIFY_RISK_FLAG", 40)      # score >= this: passes but is marked "suspicious" in the panel
VERIFY_RISK_BLOCK = _get_int("VERIFY_RISK_BLOCK", 70)    # score >= this: handled per VERIFY_RISK_ACTION (0 = never)
VERIFY_RISK_ACTION = (_get("VERIFY_RISK_ACTION", "block") or "block").lower()   # block | flag
if VERIFY_RISK_ACTION not in ("block", "flag"):
    VERIFY_RISK_ACTION = "block"


# ── Referral: when does the inviter get paid? ────────────────────────────────
#   file   = after the invited person receives their first file (hardest to farm)  [default]
#   verify = after the invited person completes a verification
#   join   = immediately when they join (old behaviour, easiest to farm)
REFERRAL_QUALIFY = (_get("REFERRAL_QUALIFY", "file") or "file").lower()
if REFERRAL_QUALIFY not in ("file", "verify", "join"):
    REFERRAL_QUALIFY = "file"


# ── Cloudflare Turnstile on the verify pages (free; dash.cloudflare.com -> Turnstile) ──
# A real bot/automation challenge that runs on /go and /verify. Scripts and bypass services cannot
# pass it on their own; the token is checked server side (single use, expires after 5 minutes).
# Create a widget for your WEB_URL domain, put both keys here. Empty = off.
TURNSTILE_SITE_KEY = _get("TURNSTILE_SITE_KEY", "")
TURNSTILE_SECRET_KEY = _get("TURNSTILE_SECRET_KEY", "")
TURNSTILE_ON = bool(TURNSTILE_SITE_KEY and TURNSTILE_SECRET_KEY)
