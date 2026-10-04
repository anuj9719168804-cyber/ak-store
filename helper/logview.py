"""Read the end of the bot's log file for /logs, with secrets blanked out first.

Idea from the src bot's /logs. The extra step is the redaction: log lines can contain a shortener URL
with its API key, a MongoDB URI or a bot token inside an error text, and a log file gets forwarded around.
Pure python (no Telegram / Mongo imports).
"""
import os
import re

TAIL_BYTES = 150_000          # ~1500 lines; plenty to see a recent crash, small enough for one message
MIN_SECRET_LEN = 6            # shorter values would blank out ordinary words

_PATTERNS = (
    (re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b"), "<bot-token>"),                       # Telegram bot token
    (re.compile(r"mongodb(?:\+srv)?://[^\s'\"<>]+", re.I), "mongodb://<hidden>"),           # MongoDB URI incl. password
    (re.compile(r"(?i)\b(api[_-]?key|api[_-]?hash|api|key|token|secret|password|sig)=([^&\s'\"]+)"), r"\1=<hidden>"),
)


def redact(text: str, secrets=()) -> str:
    """Blank known secret values (config) and anything shaped like a token, URI or key=value."""
    for value in sorted({str(s) for s in secrets if s and len(str(s)) >= MIN_SECRET_LEN}, key=len, reverse=True):
        text = text.replace(value, "<hidden>")
    for rx, repl in _PATTERNS:
        text = rx.sub(repl, text)
    return text


def tail(path: str, max_bytes: int = TAIL_BYTES) -> str:
    """Last `max_bytes` of a text file, starting at a line boundary. '' when missing / unreadable."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
                fh.readline()                       # drop the half line we landed in
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
