"""/animepost - build a channel post: poster + details + one download button per quality (admins only).

Flow (all in the bot's private chat):
  1. send the poster photo            (or /skip for a text-only post)
  2. send the details (copy the template the bot shows, edit it, send it back)
  3. forward / send the DB-channel post of EACH quality file; /done when finished
     (the quality is read from the file name, e.g. "... [720p].mkv"; the bot asks only if it can't tell)
  4. the bot shows the finished post, then asks for a channel id to publish it in (or /skip)

Every button is the normal single-file link (same as /genlink), so it opens the bot and delivers that file.
The bot must be an admin (can post) in the channel it publishes to.
"""
import html

from pyrogram import Client, enums, filters
from pyrogram.errors.pyromod import ListenerTimeout
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from helper import anime_post as ap
from helper.helper_func import encode, get_message_id
from helper.permanent_link import build_link
from helper.quality import extract_quality
from plugins import auto_quality as aq

WAIT = 180   # seconds the bot waits for each answer


class _Stop(Exception):
    pass


async def _ask(client, chat_id, prompt, flt):
    """Ask once. /cancel or a timeout raises _Stop."""
    try:
        reply = await client.ask(chat_id, prompt, filters=flt, timeout=WAIT)
    except ListenerTimeout:
        await client.send_message(chat_id, "<blockquote>⌛ Timed out, nothing posted.</blockquote>")
        raise _Stop
    if (reply.text or "").strip().lower() == "/cancel":
        await client.send_message(chat_id, "<blockquote>Cancelled.</blockquote>")
        raise _Stop
    return reply


def _file_name(msg) -> str:
    for media in (msg.video, msg.document, msg.audio):
        if media and getattr(media, "file_name", None):
            return media.file_name
    return msg.caption or ""


async def _more_qualities(client, chat_id, msg):
    """One video was added and /autoquality is ON: make the other qualities (waits until they are done) and
    return [(quality, link)] for ALL of them, or None (then the post just uses the file that was added)."""
    try:
        if aq.video_info(msg)[0] is None:
            return None
        # already made when the file was stored? reuse those qualities, never encode twice
        done = await client.mongodb.db["custom_batches"].find_one(
            {"chat_id": msg.chat.id, "by": "auto-quality", "ids": msg.id, "meta": {"$exists": True}})
        if done:
            return await aq.quality_links(client, msg.chat.id, done["meta"]) or None
        on, wanted = await aq._settings(client)
        if not (on and wanted):
            return None
        await client.send_message(
            chat_id, "<blockquote>🎞 Auto-quality is ON: making the other qualities first, then the post "
                     "comes here with a button for each. Please wait...</blockquote>")
        result = {}
        await aq.generate(client, msg, chat_id, uploader=chat_id, qualities=True, result=result)
        return result.get("items") or None
    except Exception as e:
        client.LOGGER(__name__, client.name).warning(f"animepost: auto-quality failed: {e}")
        return None


@Client.on_message(filters.private & filters.command("animepost"))
async def anime_post(client: Client, message):
    if message.from_user.id not in client.admins:
        return await message.reply(client.reply_text)
    chat = message.chat.id
    try:
        # 1 ── poster
        r = await _ask(client, chat,
                       "<blockquote>🖼 Send the <b>poster</b> photo.\n/skip for a text-only post · /cancel to stop</blockquote>",
                       filters.photo | filters.text)
        poster = r.photo.file_id if r.photo else None

        # 2 ── details
        tpl = ("<blockquote>✍️ Copy this, edit it and send it back (Synopsis goes last, "
               "it can be several lines). Leave out any line you don't need.</blockquote>\n"
               f"<pre>{html.escape(ap.TEMPLATE)}</pre>")
        while True:
            r = await _ask(client, chat, tpl, filters.text)
            data = ap.parse_form(r.text)
            if data.get("title"):
                break
            await client.send_message(chat, "<blockquote>✗ I need at least a <code>Title:</code> line.</blockquote>")

        # 3 ── quality files
        items, msgs = [], []
        prompt = ("<blockquote>📥 Now forward the <b>DB-channel post</b> of a quality file (or send its link).\n"
                  "One by one, any order. /done when finished.</blockquote>")
        while True:
            r = await _ask(client, chat, prompt, filters.forwarded | filters.text)
            if (r.text or "").strip().lower() == "/done":
                if items:
                    break
                await client.send_message(chat, "<blockquote>✗ Add at least one file first.</blockquote>")
                continue
            msg_id, src = await get_message_id(client, r)
            if not msg_id:
                await r.reply("<blockquote>✗ That post is not from my DB channel.</blockquote>", quote=True)
                continue
            try:
                m = await client.get_messages(src, msg_id)
                name = _file_name(m)
            except Exception:
                m, name = None, ""
            quality = extract_quality(name)
            if not quality:
                q = await _ask(client, chat,
                               f"<blockquote>I can't tell the quality of <code>{html.escape(name or str(msg_id))}</code>."
                               "\nSend it, e.g. <code>720p</code>.</blockquote>", filters.text)
                quality = q.text.strip()
            link = build_link(client, await encode(f"get-{msg_id * abs(src)}"))
            items.append((quality, link))
            msgs.append(m)
            await r.reply(f"<blockquote>✓ Added <b>{html.escape(quality)}</b> ({len(items)} so far). "
                          "Send the next one or /done.</blockquote>", quote=True)
            prompt = "<blockquote>Next file, or /done.</blockquote>"

        if len(items) == 1 and msgs[0] is not None:       # a single video: make the other qualities too
            items = await _more_qualities(client, chat, msgs[0]) or items
        items = ap.sort_qualities(items)
        caption = ap.build_caption(data, [q for q, _ in items])
        markup = InlineKeyboardMarkup([[InlineKeyboardButton(t, url=u) for t, u in row]
                                       for row in ap.build_buttons(items)])

        # 4 ── preview + publish
        async def send(to):
            if poster:
                return await client.send_photo(to, poster, caption=caption, reply_markup=markup,
                                               parse_mode=enums.ParseMode.HTML)
            return await client.send_message(to, caption, reply_markup=markup, parse_mode=enums.ParseMode.HTML,
                                             disable_web_page_preview=True)

        await send(chat)
        r = await _ask(client, chat,
                       "<blockquote>📣 Post it to a channel? Send the channel id (<code>-100…</code>) "
                       "or forward a message from it.\n/skip to keep only this preview.</blockquote>",
                       filters.forwarded | filters.text)
        target = None
        if r.forward_from_chat:
            target = r.forward_from_chat.id
        elif (r.text or "").strip().lstrip("-").isdigit():
            target = int(r.text.strip())
        if target is None:
            return await client.send_message(chat, "<blockquote>Done — preview only.</blockquote>")
        try:
            await send(target)
            await client.send_message(chat, "<blockquote>✓ Posted.</blockquote>")
        except Exception as e:
            await client.send_message(
                chat, f"<blockquote>✗ Couldn't post there: <code>{html.escape(str(e))}</code>\n"
                      "Make the bot an admin with permission to post.</blockquote>")
    except _Stop:
        return
