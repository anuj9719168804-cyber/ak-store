"""Buttons under every delivered file (idea taken from AK Manager's "Buttons" setting).

The admin sends, one button per line (add `:same` at the end of the url to put it on the previous button's row):

    [Join Channel][buttonurl:https://t.me/mychannel]
    [Backup][buttonurl:https://t.me/backup:same]
    [How to download][buttonurl:https://t.me/howto]

Buttons are added under the file's own buttons (unless "disable button" is on, which only drops the original ones).
"""
import re

from helper.caption_clean import valid_link

MAX_BUTTONS = 8
MAX_TEXT = 32
_BTN = re.compile(r"\[([^\[\]]+?)\]\[buttonurl:/{0,2}(.+?)(:same)?\]")


def parse(text: str) -> list:
    """-> rows [[{"text","url"}, ...], ...]; invalid urls and anything past MAX_BUTTONS are skipped."""
    rows, count = [], 0
    for m in _BTN.finditer(text or ""):
        label, url = m.group(1).strip()[:MAX_TEXT], valid_link(m.group(2).replace(" ", ""))
        if not label or not url:
            continue
        if count >= MAX_BUTTONS:
            break
        if m.group(3) and rows and len(rows[-1]) < 3:
            rows[-1].append({"text": label, "url": url})
        else:
            rows.append([{"text": label, "url": url}])
        count += 1
    return rows


def normalize(rows) -> list:
    """Defensive copy of rows loaded from the database."""
    out, count = [], 0
    for row in rows if isinstance(rows, list) else []:
        clean_row = []
        for b in row if isinstance(row, list) else []:
            if isinstance(b, dict) and b.get("text") and valid_link(b.get("url")) and count < MAX_BUTTONS:
                clean_row.append({"text": str(b["text"])[:MAX_TEXT], "url": valid_link(b["url"])})
                count += 1
        if clean_row:
            out.append(clean_row)
    return out


def describe(rows) -> str:
    return "\n".join(" | ".join(f"{b['text']} -> {b['url']}" for b in row) for row in rows) or "None"


def combine(base, rows):
    """The file's own markup (or None) with the custom rows under it -> InlineKeyboardMarkup / base / None."""
    if not rows:
        return base
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    try:
        keyboard = [list(r) for r in (base.inline_keyboard if base else [])]
        keyboard += [[InlineKeyboardButton(b["text"], url=b["url"]) for b in row] for row in rows]
        return InlineKeyboardMarkup(keyboard)
    except Exception:
        return base
