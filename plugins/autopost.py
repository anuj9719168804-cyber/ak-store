"""/autopost - schedule one post to many promo channels (admins only).

  /autopost            build a post step by step (title, preview link, download link, time, channels)
  /scheduled           list the posts waiting to go out
  /cancelpost <id>     cancel a waiting post
  /addpostch           add a channel the posts go to (forward a message from it, or send its id / link)
  /rmpostch <id>       remove a channel          /postchs   list the channels

Ported from ng-auto-post2.0. The bot must be an admin (can post) in each channel.
The sending itself runs in helper.autopost.autopost_job, started by helper.scheduler.
"""
import html
from datetime import timedelta

from pyrogram import Client, filters
from pyrogram.errors.pyromod import ListenerTimeout

from helper import autopost as ap

WAIT = 120  # seconds the bot waits for each answer


async def _is_admin(client, message) -> bool:
    if message.from_user and message.from_user.id in client.admins:
        return True
    await message.reply(client.reply_text)
    return False


async def _ask(client, message, prompt: str):
    """Ask one question; returns the answer text, or None on /cancel or timeout."""
    try:
        reply = await client.ask(message.chat.id, prompt, filters=filters.text, timeout=WAIT)
    except ListenerTimeout:
        await message.reply("<blockquote>⌛ Timed out, nothing saved.</blockquote>")
        return None
    text = (reply.text or "").strip()
    if text.lower() == "/cancel":
        await message.reply("<blockquote>Cancelled.</blockquote>")
        return None
    return text


# ───────────────────────────── channels ─────────────────────────────

@Client.on_message(filters.private & filters.command("addpostch"))
async def add_post_channel(client, message):
    if not await _is_admin(client, message):
        return
    try:
        reply = await client.ask(
            message.chat.id,
            "<blockquote>Forward any message from the channel, or send its id (<code>-100…</code>) or t.me link.\n"
            "The bot must be an admin there. /cancel to stop.</blockquote>",
            timeout=WAIT,
        )
    except ListenerTimeout:
        return await message.reply("<blockquote>⌛ Timed out.</blockquote>")
    if (reply.text or "").strip().lower() == "/cancel":
        return await message.reply("<blockquote>Cancelled.</blockquote>")

    chat = None
    try:
        if reply.forward_from_chat:
            chat = await client.get_chat(reply.forward_from_chat.id)
        elif reply.text and "t.me/" in reply.text:
            chat = await client.get_chat(reply.text.strip())
        elif reply.text:
            chat = await client.get_chat(int(reply.text.strip()))
    except Exception as e:
        return await message.reply(f"<blockquote>❌ Could not open that channel: <code>{html.escape(str(e))}</code></blockquote>")
    if not chat:
        return await message.reply("<blockquote>❌ Could not read a channel from that.</blockquote>")

    title = chat.title or str(chat.id)
    if await ap.add_channel(client, chat.id, title):
        await message.reply(f"<blockquote>✅ Added <b>{html.escape(title)}</b> (<code>{chat.id}</code>)</blockquote>")
    else:
        await message.reply("<blockquote>⚠️ That channel is already in the list.</blockquote>")


@Client.on_message(filters.private & filters.command("rmpostch"))
async def remove_post_channel(client, message):
    if not await _is_admin(client, message):
        return
    try:
        cid = int(message.command[1])
    except (IndexError, ValueError):
        return await message.reply("<blockquote>Usage: <code>/rmpostch -100123456789</code> (see /postchs)</blockquote>")
    ok = await ap.remove_channel(client, cid)
    await message.reply("<blockquote>✅ Removed.</blockquote>" if ok else "<blockquote>❌ Not in the list.</blockquote>")


@Client.on_message(filters.private & filters.command("postchs"))
async def list_post_channels(client, message):
    if not await _is_admin(client, message):
        return
    chans = await ap.list_channels(client)
    if not chans:
        return await message.reply("<blockquote>No channels yet. Use /addpostch.</blockquote>")
    lines = [f"{i}. <b>{html.escape(c['title'])}</b> <code>{c['_id']}</code>" for i, c in enumerate(chans, 1)]
    await message.reply("<b>📢 Post channels</b>\n\n" + "\n".join(lines))


# ───────────────────────────── posts ─────────────────────────────

@Client.on_message(filters.private & filters.command("autopost"))
async def autopost_cmd(client, message):
    if not await _is_admin(client, message):
        return
    chans = await ap.list_channels(client)
    if not chans:
        return await message.reply("<blockquote>Add at least one channel first with /addpostch.</blockquote>")

    title = await _ask(client, message, "<b>🎬 Send the post title</b>\n<i>/cancel to stop</i>")
    if not title:
        return
    title = title[:200]

    preview = await _ask(client, message, "<b>👀 Send the preview link</b> (or /skip)")
    if preview is None:
        return
    if preview.lower() == "/skip":
        preview = None
    elif not ap.valid_url(preview):
        return await message.reply("<blockquote>❌ That is not a link (it must start with http:// or https://).</blockquote>")

    link = await _ask(client, message, "<b>📥 Send the download link</b>")
    if link is None:
        return
    if not ap.valid_url(link):
        return await message.reply("<blockquote>❌ That is not a link (it must start with http:// or https://).</blockquote>")

    when = None
    while when is None:
        text = await _ask(
            client, message,
            "<b>🕒 When?</b>\n<code>now</code>, <code>30m</code>, <code>2h</code> or <code>DD-MM HH:MM</code> (IST), e.g. <code>25-07 21:00</code>",
        )
        if text is None:
            return
        when = ap.parse_when(text)
        if when is None:
            await message.reply("<blockquote>❌ I could not read that time, try again.</blockquote>")
        elif when < ap.parse_when("now") - timedelta(minutes=1):
            await message.reply("<blockquote>⚠️ That time is in the past, try again.</blockquote>")
            when = None

    listing = "\n".join(f"{i}. {html.escape(c['title'])} <code>{c['_id']}</code>" for i, c in enumerate(chans, 1))
    which = await _ask(
        client, message,
        f"<b>📢 Which channels?</b>\n\n{listing}\n\nSend <code>all</code> (new channels added later are included automatically) "
        "or the numbers, e.g. <code>1 3</code>",
    )
    if which is None:
        return
    if which.lower() == "all":
        mode, ids = "all", []
    else:
        try:
            picks = sorted({int(x) for x in which.replace(",", " ").split()})
            if not picks or picks[0] < 1 or picks[-1] > len(chans):
                raise ValueError
        except ValueError:
            return await message.reply("<blockquote>❌ Invalid choice, start again with /autopost.</blockquote>")
        mode, ids = "select", [chans[i - 1]["_id"] for i in picks]

    count = len(chans) if mode == "all" else len(ids)
    summary = (f"<b>📋 Confirm</b>\n\n🎬 {html.escape(title)}\n🕒 {ap.fmt_ist(when)}\n📢 {count} channel(s)"
               f"{' (all, live)' if mode == 'all' else ''}\n\nSend <code>yes</code> to schedule, anything else cancels.")
    answer = await _ask(client, message, summary)
    if not answer or answer.lower() not in ("yes", "y"):
        if answer is not None:
            await message.reply("<blockquote>Cancelled.</blockquote>")
        return

    post_id = await ap.save_post(client, {
        "title": title, "main_link": link, "preview": preview,
        "channels_mode": mode, "channels": ids, "schedule_time": when,
        "created_by": message.from_user.id,
    })
    await message.reply(f"<blockquote>✅ Scheduled for {ap.fmt_ist(when)}\nID: <code>{post_id}</code></blockquote>")


@Client.on_message(filters.private & filters.command("scheduled"))
async def scheduled_cmd(client, message):
    if not await _is_admin(client, message):
        return
    posts = await ap.pending_posts(client)
    if not posts:
        return await message.reply("<blockquote>No posts are waiting.</blockquote>")
    lines = [f"• <b>{html.escape(p['title'])}</b>\n  🕒 {ap.fmt_ist(p['schedule_time'])}\n  <code>{p['_id']}</code>" for p in posts[:20]]
    await message.reply("<b>📅 Scheduled posts</b>\n\n" + "\n\n".join(lines) + "\n\nCancel one: <code>/cancelpost &lt;id&gt;</code>")


@Client.on_message(filters.private & filters.command("cancelpost"))
async def cancel_post_cmd(client, message):
    if not await _is_admin(client, message):
        return
    if len(message.command) < 2:
        return await message.reply("<blockquote>Usage: <code>/cancelpost &lt;id&gt;</code> (ids are in /scheduled)</blockquote>")
    ok = await ap.cancel_post(client, message.command[1])
    await message.reply("<blockquote>✅ Cancelled.</blockquote>" if ok else "<blockquote>❌ No waiting post with that id.</blockquote>")
