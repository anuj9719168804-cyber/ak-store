"""/search <words>  and  @bot <words> (inline mode).

Searches the file index (see helper/search.py). Results are normal deep links, so credits,
force-sub and the shortener / web verify apply exactly as for any other link. Who may search:
SEARCH_ACCESS in config.py (all | premium | admin | off). Inline mode also has to be switched on
once in @BotFather: /setinline.
"""
import html
import secrets
import time

from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultArticle, InputTextMessageContent,
)

from config import SEARCH_ACCESS, SEARCH_PAGE_SIZE
from helper import search
from helper.utils import ban_notice
from helper.permanent_link import build_link
from helper.utils import format_bytes

_QUERIES = {}          # short id -> (query, created): callback_data is limited to 64 bytes
_QUERY_TTL = 3600
_QUERY_MAX = 2000
INLINE_PAGE = 20


def _remember(query: str) -> str:
    now = time.time()
    if len(_QUERIES) >= _QUERY_MAX:
        for key in [k for k, (_, t) in _QUERIES.items() if now - t > _QUERY_TTL] or list(_QUERIES)[:200]:
            _QUERIES.pop(key, None)
    qid = secrets.token_hex(4)
    _QUERIES[qid] = (query, now)
    return qid


def _recall(qid: str):
    item = _QUERIES.get(qid)
    return item[0] if item and time.time() - item[1] <= _QUERY_TTL else None


async def _allowed_chats(client):
    from web.data import allowed_channels
    return allowed_channels(client)


async def _link_for(client, doc) -> str:
    return build_link(client, await search.payload_for(doc))


async def _page(client, query: str, page: int):
    """-> (text, markup) for one page of results."""
    rows, total = await search.search(client.mongodb.db, query, page, SEARCH_PAGE_SIZE, await _allowed_chats(client))
    if not rows:
        return f"🔍 Nothing found for <b>{html.escape(query)}</b>.\nTry fewer or different words.", None
    pages = search.pages(total, SEARCH_PAGE_SIZE)
    buttons = []
    for doc in rows:
        label = f"📄 {search.short_title(doc, 45)} · {format_bytes(doc.get('size', 0))}"
        buttons.append([InlineKeyboardButton(label[:64], url=await _link_for(client, doc))])
    if pages > 1:
        qid = _remember(query)
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton("◀", callback_data=f"sp:{qid}:{page - 1}"))
        nav.append(InlineKeyboardButton(f"{page}/{pages}", callback_data="sp:noop:0"))
        if page < pages:
            nav.append(InlineKeyboardButton("▶", callback_data=f"sp:{qid}:{page + 1}"))
        buttons.append(nav)
    return (f"🔍 <b>{total}</b> result(s) for <b>{html.escape(query)}</b>\nTap a file to get it.",
            InlineKeyboardMarkup(buttons))


@Client.on_message(filters.command("search") & filters.private)
async def search_command(client, message):
    uid = message.from_user.id
    if SEARCH_ACCESS == "off":
        return await message.reply("Search is turned off.")
    if await client.mongodb.is_banned(uid):
        return await message.reply(await ban_notice(client.mongodb, message.from_user.id))
    if not await search.may_search(client, uid):
        return await message.reply("🔒 Search is available to " + ("premium users only. Use /buy to upgrade." if SEARCH_ACCESS == "premium" else "admins only."))
    query = " ".join(message.command[1:]).strip()
    if not search.words(query):
        return await message.reply("Usage: <code>/search avengers 1080p</code>\nAll the words must appear in the file name.")
    if not await client.mongodb.present_user(uid):
        await client.mongodb.add_user(uid)
    text, markup = await _page(client, query, 1)
    await message.reply(text, reply_markup=markup, disable_web_page_preview=True)


@Client.on_callback_query(filters.regex(r"^sp:"))
async def search_page(client, query):
    _, qid, page = query.data.split(":")
    if qid == "noop":
        return await query.answer()
    if not await search.may_search(client, query.from_user.id):
        return await query.answer("Search is not available to you.", show_alert=True)
    text_query = _recall(qid)
    if not text_query:
        return await query.answer("This list expired. Run /search again.", show_alert=True)
    try:
        page_no = max(int(page), 1)
    except ValueError:
        return await query.answer()
    text, markup = await _page(client, text_query, page_no)
    try:
        await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except Exception:
        pass
    await query.answer()


# ------------------------------------------------------------------ inline

def _note(title, description, text):
    return InlineQueryResultArticle(
        id=secrets.token_hex(6), title=title, description=description,
        input_message_content=InputTextMessageContent(text),
    )


@Client.on_inline_query()
async def inline_search(client, inline_query):
    uid = inline_query.from_user.id
    text = (inline_query.query or "").strip()
    personal = SEARCH_ACCESS in ("premium", "admin")
    if SEARCH_ACCESS == "off" or not await search.may_search(client, uid):
        return await inline_query.answer([_note("Search not available", "You can't use search here.", "Search is not available.")],
                                         cache_time=5, is_personal=True)
    if not search.words(text):
        return await inline_query.answer([_note("Type a file name", "Example: avengers 1080p", "Type part of a file name after the bot's @username.")],
                                         cache_time=5, is_personal=personal)
    try:
        offset = max(int(inline_query.offset or 0), 0)
    except ValueError:
        offset = 0
    rows, total = await search.search(client.mongodb.db, text, offset // INLINE_PAGE + 1, INLINE_PAGE, await _allowed_chats(client))
    if not rows:
        return await inline_query.answer([_note("Nothing found", f"No file matches “{text[:40]}”", f"Nothing found for: {text}")],
                                         cache_time=10, is_personal=personal)
    results = []
    for doc in rows:
        link = await _link_for(client, doc)
        title = search.short_title(doc, 64)
        results.append(InlineQueryResultArticle(
            id=doc["_id"][:64], title=title, description=f"{format_bytes(doc.get('size', 0))} · {doc.get('kind', 'file')}",
            input_message_content=InputTextMessageContent(f"📄 <b>{html.escape(title)}</b>\n{format_bytes(doc.get('size', 0))}",
                                                          disable_web_page_preview=True),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📥 ɢᴇᴛ ꜰɪʟᴇ", url=link)]]),
        ))
    next_offset = str(offset + INLINE_PAGE) if offset + INLINE_PAGE < total else ""
    await inline_query.answer(results, cache_time=30, is_personal=personal, next_offset=next_offset)
