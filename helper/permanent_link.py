"""One place that builds the deep links the bot hands out.

Normal link:     https://t.me/<bot>?start=<payload>
Permanent link:  <BACKEND_API_URL>/?url=<payload>   (Cloudflare Worker in backend/, redirects to the bot)

The permanent form is used only when BACKEND_API_URL is configured AND the toggle is on
(bot.permanent_link, saved in the bot settings). Anything else falls back to the t.me link,
so turning the feature off never breaks a working setup.
"""
from config import BACKEND_API_URL


def build_link(bot, payload: str) -> str:
    if BACKEND_API_URL and getattr(bot, "permanent_link", False):
        return f"{BACKEND_API_URL}/?url={payload}"
    return f"https://t.me/{bot.username}?start={payload}"
