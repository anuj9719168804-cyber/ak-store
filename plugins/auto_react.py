"""React with a random emoji to every command a user sends the bot in private chat.

Ported from AK Ultra plugins/auto_react.py. One handler covers all commands, so no command needs
editing. Switch off with AUTO_REACT=false (config.py / .env).

It runs in group -10 (before everything else) because create_bot.py calls stop_propagation(),
which would otherwise skip a later group. The reaction is sent in the background, so it never
slows the command down.
"""
import asyncio

from pyrogram import Client, filters

from config import AUTO_REACT
from helper.reactions import safe_react

_tasks: set = set()   # keeps background tasks alive until they finish


def _looks_like_command(_, __, message) -> bool:
    return bool(message.text and message.text.startswith("/"))


is_command = filters.create(_looks_like_command)


@Client.on_message(filters.private & is_command, group=-10)
async def auto_react(client: Client, message):
    if not AUTO_REACT:
        return
    task = asyncio.create_task(safe_react(client, message.chat.id, message.id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
