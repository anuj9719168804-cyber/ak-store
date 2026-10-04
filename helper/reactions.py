"""Emoji reactions that can never break a command (ported from AK Ultra utils/reactions.py).

Telegram only lets bots use its standard reaction set; any other emoji raises REACTION_INVALID.
AK Ultra's list also held emoji outside that set (💎 👑 💰 ...) which could never work, so this
list keeps only the standard, friendly ones.
"""
import logging
import random

log = logging.getLogger("reactions")

REACTION_EMOJIS = (
    "👍", "❤", "🔥", "🥰", "👏", "😁", "🎉", "🤩", "🙏", "👌", "😍", "💯",
    "⚡", "🏆", "😎", "🫡", "🤝", "🦄", "😘", "👀", "🐳", "🤗", "😇", "🆒",
)


def pick() -> str:
    return random.choice(REACTION_EMOJIS)


async def safe_react(client, chat_id: int, message_id: int, emoji: str | None = None) -> bool:
    """React to a message. Returns False (never raises) if Telegram refuses."""
    try:
        await client.send_reaction(chat_id=chat_id, message_id=message_id, emoji=emoji or pick())
        return True
    except Exception as e:  # message too old, reactions off, FloodWait ... — a reaction is only decoration
        log.debug("reaction skipped on %s/%s: %s", chat_id, message_id, e)
        return False
