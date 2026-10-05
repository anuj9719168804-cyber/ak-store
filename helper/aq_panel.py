"""Button panel for /autoquality: ON/OFF switch + one toggle per quality.

No pyrogram import here, so it can be unit-tested with a plain fake DB.  The plugin
(plugins/auto_quality.py) turns the (text, callback_data) rows into InlineKeyboardMarkup.

callback_data:  aq_toggle        flip auto-quality ON <-> OFF
                aq_q_<label>     add / remove one quality (aq_q_720p, aq_q_4K ...)
                aq_close         delete the panel message
"""
from helper import transcode

TOGGLE = "aq_toggle"
CLOSE = "aq_close"
QUALITY_PREFIX = "aq_q_"
PER_ROW = 4


def quality_data(label: str) -> str:
    return QUALITY_PREFIX + label


def build_rows(on: bool, wanted) -> list:
    """[[(text, callback_data), ...], ...] for the panel."""
    chosen = set(wanted or [])
    rows = [[(("🟢 ON  ·  tap to turn OFF" if on else "🔴 OFF  ·  tap to turn ON"), TOGGLE)]]
    row = []
    for label in transcode.ORDER:
        row.append((("✅ " if label in chosen else "▫️ ") + label, quality_data(label)))
        if len(row) == PER_ROW:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([("✖️ Close", CLOSE)])
    return rows


async def apply(db, data, on: bool, wanted: list):
    """Handle one button press.  -> (on, wanted, toast).  Writes to the bot settings only when something changed."""
    if isinstance(data, bytes):
        data = data.decode("utf-8", "ignore")
    data = str(data or "")
    wanted = list(wanted or [])
    if data == TOGGLE:
        on = not on
        await db.update_bot_setting("auto_quality", on)
        return on, wanted, f"Auto-quality {'ON ✅' if on else 'OFF ❌'}"
    if data.startswith(QUALITY_PREFIX):
        label = data[len(QUALITY_PREFIX):]
        if label not in transcode.LADDER:
            return on, wanted, "Unknown quality."
        if label in wanted:
            if len(wanted) == 1:
                # an empty list would silently fall back to the default list, so never allow it
                return on, wanted, "Keep at least one quality selected."
            wanted.remove(label)
            toast = f"{label} removed"
        else:
            wanted.append(label)
            toast = f"{label} added"
        wanted = transcode.parse_list(",".join(wanted))      # keeps low -> high order
        await db.update_bot_setting("auto_quality_list", ",".join(wanted))
        return on, wanted, toast
    return on, wanted, None
