"""Custom caption templates (ported from Multi-FileStoreBot, with fixes).

Placeholders: {file_name} {file_caption} {previouscaption} {size} {duration}
              {quality} {language} {year} {type} {username}
The template is appended under the file's own caption when files are delivered.
"""
import re

LANGUAGES = {
    "hindi": ["hindi", "hin"], "english": ["english", "eng"], "bengali": ["bengali", "ben"],
    "tamil": ["tamil", "tam"], "telugu": ["telugu", "tel"], "malayalam": ["malayalam", "mal"],
    "kannada": ["kannada", "kan"], "marathi": ["marathi", "mar"], "punjabi": ["punjabi", "pun"],
    "gujarati": ["gujarati", "guj"], "bhojpuri": ["bhojpuri"], "urdu": ["urdu", "urd"],
    "korean": ["korean", "kor"], "japanese": ["japanese", "jap"], "chinese": ["chinese", "chi"],
    "arabic": ["arabic", "ara"], "french": ["french", "fre"], "german": ["german", "ger"],
    "russian": ["russian", "rus"], "nepali": ["nepali", "nep"], "dual": ["dual"],
    "multi": ["multi", "multi audio", "multi-audio"], "dubbed": ["dubbed"], "subbed": ["subbed"],
}

PLACEHOLDERS = "{file_name} {file_caption} {previouscaption} {size} {duration} {quality} {language} {year} {type} {username}"
MAX_CAPTION = 1024


def get_size(size):
    units = ["Bytes", "KB", "MB", "GB", "TB", "PB", "EB"]
    size = float(size)
    i = 0
    while size >= 1024.0 and i < len(units) - 1:
        i += 1
        size /= 1024.0
    return "%.2f %s" % (size, units[i])


def _language_match(alias, text):
    # whole-word match, so "mal" does not hit "normal" and "eng" does not hit "engine"
    return re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", text) is not None


def get_file_details(message) -> dict:
    if not getattr(message, "media", None):
        return {}
    details = {"file_name": "", "file_caption": message.caption or "", "file_size": "",
               "duration": "", "quality": "", "language": "", "year": "", "type": ""}
    for kind in ("video", "audio", "document", "voice", "photo"):
        obj = getattr(message, kind, None)
        if not obj:
            continue
        details["type"] = kind.capitalize()
        raw_name = getattr(obj, "file_name", None) or ""
        details["file_name"] = re.sub(r"@\w+\s*", "", raw_name).replace("_", " ").replace(".", " ").strip()
        details["file_size"] = get_size(obj.file_size) if getattr(obj, "file_size", None) else "Unknown Size"
        secs = getattr(obj, "duration", None)
        if kind in ("audio", "video", "voice") and secs:
            h, m, s = int(secs // 3600), int((secs % 3600) // 60), int(secs % 60)
            details["duration"] = f"{h} Hr {m} Min {s} Sec" if h else f"{m} Min {s} Sec"
        q = re.search(r"(\d{3,4}p)", raw_name + " " + details["file_caption"])
        details["quality"] = q.group(1) if q else "Unknown Quality"
        y = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", raw_name + " " + details["file_caption"])
        details["year"] = y.group(1) if y else ""
        hay = (raw_name + " " + details["file_caption"]).lower()
        langs = [name.capitalize() for name, aliases in LANGUAGES.items()
                 if any(_language_match(a, hay) for a in aliases)]
        details["language"] = ", ".join(langs) if langs else "Unknown Audio"
        break
    return details


def format_caption(template: str, d: dict, extra: dict | None = None) -> str:
    values = {
        "{file_name}": d.get("file_name", ""), "{file_caption}": d.get("file_caption", ""),
        "{previouscaption}": d.get("file_caption", ""), "{size}": d.get("file_size", ""),
        "{duration}": d.get("duration", ""), "{quality}": d.get("quality", ""),
        "{language}": d.get("language", ""), "{year}": d.get("year", ""), "{type}": d.get("type", ""),
    }
    values.update(extra or {})
    for key, val in values.items():
        template = template.replace(key, str(val))
    return template


def apply_custom_caption(template, message, base_caption, username="", cleaner=None, mode="append"):
    """base caption + custom template. Never raises, never exceeds Telegram's limit.
    mode "append" puts the template under the file's own caption, "replace" sends only the template (use
    {file_caption} in it to keep the original text somewhere).
    `cleaner` (helper/caption_clean.py) is applied to the file's own caption text only, never to the template."""
    def _clean(text):
        if not cleaner or not text:
            return text
        try:
            return cleaner(text)
        except Exception:
            return text

    base_caption = _clean(base_caption)
    if not template or not getattr(message, "media", None):
        return base_caption
    try:
        extra = {"{username}": f"@{username}" if username else ""}
        details = get_file_details(message)
        if details:
            details["file_caption"] = _clean(details.get("file_caption", ""))
            details["file_name"] = _clean(details.get("file_name", ""))      # {file_name} gets the same cleaning
        formatted = format_caption(template, details, extra)
    except Exception:
        return base_caption
    if mode == "replace":
        return formatted if formatted.strip() and len(formatted) <= MAX_CAPTION else base_caption
    combined = f"{base_caption}\n\n{formatted}" if base_caption else formatted
    if len(combined) <= MAX_CAPTION:
        return combined
    return formatted if len(formatted) <= MAX_CAPTION else base_caption
