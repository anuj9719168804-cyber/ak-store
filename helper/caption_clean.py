"""Caption cleaner (idea taken from AK Manager's Remover / Link Remover / Username remover / Replacer).

Runs on the HTML caption of every delivered file, before the custom caption template is added, so the
admin's own template (links, @channel) is never touched.  Settings (/settings -> page 2 -> Caption Cleaner):

    links      "off" | "remove" (hyperlinks keep their text, plain URLs go) | "replace" (every link becomes `link_value`)
    usernames  "off" | "remove" | "replace" (every @name becomes `username_value`)
    remove     words / phrases to delete
    replace    [{"old": ..., "new": ...}] word replacements (applied last, so a replacement may contain @name or a link)

Also here (idea from AK Manager's Auto Numbering / Bullets): `numbering` and `bullet` put "1. " / an emoji in front of
the final caption (see decorate()).  Everything works on the text between HTML tags, so tags stay balanced and links keep working: a bad
cleaner can never make Telegram reject a delivery.  Any error returns the caption unchanged.
"""
import html
import re

MAX_ITEMS = 30
MAX_LEN = 100
MODES = ("off", "remove", "replace")
NUM_STYLES = ("off", "dot", "bracket", "emoji", "asterisk", "dash")
BULLETS = ("off", "🚀", "🔥", "📌", "⭐", "💫", "✨")
MAX_CAPTION = 1024

DEFAULTS = {"links": "off", "link_value": "", "usernames": "off", "username_value": "", "remove": [], "replace": [],
            "numbering": "off", "bullet": "off"}

_TAG = re.compile(r"(<[^>]*>)")
_TAG_ONLY = re.compile(r"<[^>]*>")
_ANCHOR = re.compile(r"<a\s[^>]*>(.*?)</a>", re.I | re.S)
_URL = re.compile(r"(?:https?://|www\.|t\.me/|telegram\.me/)[^\s<>\"']+", re.I)
_USER = re.compile(r"(?<![A-Za-z0-9_.])@[A-Za-z0-9_]{5,32}")
_EMPTY = re.compile(r"<(b|i|u|s|em|strong|del|ins|code|pre|blockquote|tg-spoiler|spoiler)(?:\s[^>]*)?>\s*</\1>", re.I)
_EMPTY_A = re.compile(r"<a\s[^>]*>\s*</a>", re.I)


def _balanced(s: str) -> bool:
    stack = []
    for m in re.finditer(r"<(/?)([A-Za-z][\w-]*)[^>]*>", s):
        if m.group(1):
            if not stack or stack.pop() != m.group(2).lower():
                return False
        else:
            stack.append(m.group(2).lower())
    return not stack


def _safe_new(new: str) -> str:
    """Replacement text: kept as HTML only when it holds complete, balanced tags; otherwise escaped,
    so a stray "<" typed by the admin can never make Telegram reject the caption."""
    if re.search(r"<[A-Za-z/][^<>]*>", new) and _balanced(new):
        return new
    return html.escape(new, quote=False)


def valid_link(url) -> str:
    """-> a safe https/tg link, or "" (no spaces, quotes or angle brackets: it goes inside an HTML attribute)."""
    url = str(url or "").strip()
    if re.fullmatch(r"(?:https?://|tg://)[^\s<>\"']{3,200}", url, re.I):
        return url
    if re.fullmatch(r"(?:t\.me|telegram\.me)/[^\s<>\"']{2,200}", url, re.I):
        return "https://" + url
    return ""


def next_mode(current, options):
    return options[(options.index(current) + 1) % len(options)] if current in options else options[0]


def normalize(cfg) -> dict:
    out = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULTS.items()}
    if isinstance(cfg, dict):
        links = cfg.get("links")
        out["links"] = "remove" if links is True else (links if links in MODES else "off")
        out["link_value"] = valid_link(cfg.get("link_value"))
        out["numbering"] = cfg.get("numbering") if cfg.get("numbering") in NUM_STYLES else "off"
        out["bullet"] = cfg.get("bullet") if cfg.get("bullet") in BULLETS else "off"
        out["usernames"] = cfg.get("usernames") if cfg.get("usernames") in MODES else "off"
        out["username_value"] = str(cfg.get("username_value") or "").lstrip("@")[:32]
        out["remove"] = [str(x) for x in (cfg.get("remove") or []) if str(x).strip()][:MAX_ITEMS]
        out["replace"] = [{"old": str(p["old"]), "new": str(p.get("new", ""))}
                          for p in (cfg.get("replace") or []) if isinstance(p, dict) and str(p.get("old", "")).strip()][:MAX_ITEMS]
    return out


def is_active(cfg: dict) -> bool:
    return bool(cfg["links"] == "remove" or (cfg["links"] == "replace" and cfg["link_value"])
                or cfg["remove"] or cfg["replace"]
                or cfg["usernames"] == "remove" or (cfg["usernames"] == "replace" and cfg["username_value"]))


def _map_text(s: str, fn) -> str:
    """Apply fn to the text parts of an HTML string only (never to tags or attributes)."""
    parts = _TAG.split(s)
    for i in range(0, len(parts), 2):
        parts[i] = fn(parts[i])
    return "".join(parts)


def _remove_phrase(s: str, phrase: str) -> str:
    """Delete `phrase` even when it spans formatting tags; the tags inside the match are kept."""
    chars = [re.escape(c) for c in html.escape(phrase.strip(), quote=False)]
    if not chars:
        return s
    pattern = r"(?![^<]*>)" + r"(?:<[^>]*>)*".join(chars)      # the lookahead keeps us out of tag attributes
    return re.sub(pattern, lambda m: "".join(_TAG_ONLY.findall(m.group(0))), s, flags=re.I)


def _tidy(s: str) -> str:
    for _ in range(3):
        s = _EMPTY_A.sub("", _EMPTY.sub("", s))
    s = _map_text(s, lambda t: re.sub(r"[ \t]{2,}", " ", t))
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n[ \t]*(?:\n[ \t]*){2,}", "\n\n", s)
    return s.strip()


def clean(caption: str, cfg: dict) -> str:
    if not caption or not is_active(cfg):
        return caption
    s = caption
    for phrase in cfg["remove"]:
        s = _remove_phrase(s, phrase)
    if cfg["links"] == "remove":
        s = _ANCHOR.sub(r"\1", s)
        s = _map_text(s, lambda t: _URL.sub("", t))
    elif cfg["links"] == "replace":
        own = html.escape(cfg["link_value"], quote=True)
        s = re.sub(r'(<a\s[^>]*?href=")[^"]*(")', lambda m: m.group(1) + own + m.group(2), s, flags=re.I)
        s = _map_text(s, lambda t: _URL.sub(lambda m: own, t))
    if cfg["usernames"] == "remove":
        s = _map_text(s, lambda t: _USER.sub("", t))
    elif cfg["usernames"] == "replace" and cfg["username_value"]:
        own = "@" + cfg["username_value"]
        s = _map_text(s, lambda t: _USER.sub(lambda m: own, t))
    for pair in cfg["replace"]:
        old = html.escape(pair["old"].strip(), quote=False)
        new = _safe_new(pair["new"])
        s = _map_text(s, lambda t, o=old, n=new: re.sub(re.escape(o), lambda m: n, t, flags=re.I))
    s = _tidy(s)
    if _balanced(caption) and not _balanced(s):      # never hand Telegram broken markup
        return caption
    return s


def build_cleaner(cfg):
    """-> a text->text function, or None when nothing is switched on. The function never raises."""
    cfg = normalize(cfg)
    if not is_active(cfg):
        return None

    def cleaner(text):
        try:
            return clean(text, cfg)
        except Exception:
            return text
    return cleaner


def parse_words(text: str) -> list:
    return [ln.strip()[:MAX_LEN] for ln in (text or "").splitlines() if ln.strip()]


def parse_pairs(text: str) -> list:
    """One `old => new` per line (a line without `=>` removes nothing, so it is skipped)."""
    pairs = []
    for ln in (text or "").splitlines():
        if "=>" in ln:
            old, new = ln.split("=>", 1)
            if old.strip():
                pairs.append({"old": old.strip()[:MAX_LEN], "new": new.strip()[:MAX_LEN]})
    return pairs


_KEYCAPS = {str(i): f"{i}\ufe0f\u20e3" for i in range(10)}


def number_prefix(n: int, style: str) -> str:
    if style == "bracket":
        return f"{n}) "
    if style == "emoji":
        return "".join(_KEYCAPS[d] for d in str(n)) + " "
    if style == "asterisk":
        return f"* {n} "
    if style == "dash":
        return f"- {n} "
    return f"{n}. "


def decorate(caption: str, cfg: dict, index=None) -> str:
    """Number / bullet in front of the final caption ("1. 🚀 caption"). Only a caption that has text gets one,
    and it is left alone when the result would pass Telegram's limit."""
    try:
        if not caption or not caption.strip():
            return caption
        prefix = ""
        if cfg.get("numbering", "off") != "off" and index:
            prefix += number_prefix(int(index), cfg["numbering"])
        if cfg.get("bullet", "off") != "off":
            prefix += cfg["bullet"] + " "
        return prefix + caption if prefix and len(prefix) + len(caption) <= MAX_CAPTION else caption
    except Exception:
        return caption
