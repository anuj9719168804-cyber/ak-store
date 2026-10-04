"""Auto-quality + auto-split: store ONE video (e.g. a 4K file) and get 144p ... 1440p copies too; files over
2 GB are cut into parts that fit Telegram.

Ported from the src bot's Akbots/filestore.py (`generate_missing_qualities` + `/autogenerate`).
How it works for File Store:
  * when an admin/uploader stores a video, channel_post.py hands it to `maybe_start()`;
  * the video is downloaded from the DB channel, every quality in the list that is clearly smaller than
    the source is encoded with ffmpeg (helper/transcode.py), uploaded to the SAME DB channel and indexed;
  * all of them (+ the original) go into one `custom_batches` entry, so the usual `getc-` batch link
    delivers every quality; that link is sent to the uploader when the last one is done.
The normal single-file link is still sent immediately - nothing waits for the encoding.

Auto-split (/autosplit on|off, on by default): a stored file above 2000 MB is cut into <= AUTO_SPLIT_MB parts
(videos with ffmpeg stream copy = every part plays; other files as raw .001 .002 ...), uploaded to the same DB
channel and delivered by one batch link. A quality copy that is itself over 2 GB is split the same way.

Auto-quality is off by default.  /autoquality on | off | set 144p,480p,720p     /genquality  /gensplit
"""
import asyncio
import os
import shutil
import tempfile
import time

from pyrogram import Client, enums, filters
from pyrogram.errors import FloodWait
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import (AUTO_QUALITY, AUTO_QUALITY_LIST, AUTO_QUALITY_MAX_MB, AUTO_QUALITY_PARALLEL,
                    AUTO_QUALITY_PRESET, AUTO_QUALITY_THREADS, AUTO_QUALITY_UPSCALE,
                    AUTO_QUALITY_UPSCALE_MAX_FACTOR, AUTO_SPLIT, AUTO_SPLIT_MB, PREMIUM_MAX_MB,
                    PREMIUM_SESSION, API_HASH, API_ID)
from helper import file_index, thumbnail, transcode
from helper.activity import log_activity
from helper.helper_func import encode, get_message_id
from helper.permanent_link import build_link
from helper.quality import extract_quality, quality_rank
from helper.utils import generate_token

_tasks = set()                 # keeps background tasks alive until they finish
_sem = None                    # asyncio.Semaphore, created on first use (needs the running loop)
_busy = set()                  # (chat_id, msg_id) currently queued/encoding, so one post is never done twice


def _semaphore():
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(AUTO_QUALITY_PARALLEL)
    return _sem


async def _settings(client):
    on = bool(await client.mongodb.get_bot_setting("auto_quality", AUTO_QUALITY))
    raw = await client.mongodb.get_bot_setting("auto_quality_list", AUTO_QUALITY_LIST)
    wanted = transcode.parse_list(raw, transcode.parse_list(AUTO_QUALITY_LIST))
    return on, wanted


async def _upscale_list(client):
    raw = await client.mongodb.get_bot_setting("auto_quality_upscale", AUTO_QUALITY_UPSCALE)
    return transcode.parse_list(raw)


async def _split_on(client):
    return bool(await client.mongodb.get_bot_setting("auto_split", AUTO_SPLIT))


_premium = {"client": None, "failed_at": 0.0}


async def get_premium(client):
    """The Premium uploader account (started once, kept running), or None. A failed start is retried after 10 min."""
    if not PREMIUM_SESSION:
        return None
    if _premium["client"] is not None:
        return _premium["client"]
    if time.monotonic() - _premium["failed_at"] < 600 and _premium["failed_at"]:
        return None
    log = client.LOGGER(__name__, client.name)
    acc = None
    try:
        acc = Client("aq_premium", api_id=API_ID, api_hash=API_HASH, session_string=PREMIUM_SESSION,
                     in_memory=True, no_updates=True, max_concurrent_transmissions=4)
        await acc.start()
        me = await acc.get_me()
        if not getattr(me, "is_premium", False):
            raise RuntimeError("that account does not have Telegram Premium (needed for files over 2 GB)")
        async for _ in acc.get_dialogs(limit=300):   # fills the peer cache so it can post in the DB channel
            pass
        _premium["client"] = acc
        log.info(f"auto-quality: Premium uploader ready ({me.first_name})")
        return acc
    except Exception as e:
        _premium["failed_at"] = time.monotonic() or 1.0
        log.warning(f"auto-quality: PREMIUM_SESSION not usable ({e}); the bot uploads and splits at 2 GB")
        if acc is not None:
            try:
                await acc.stop()
            except Exception:
                pass
        return None


async def _limits(client):
    """-> (uploading client, biggest single file, size of a split part). Premium account = ~4 GB, bot = 2 GB."""
    acc = await get_premium(client)
    if acc is not None:
        single = PREMIUM_MAX_MB * 1024 * 1024
        return acc, single, int(single * 0.97)
    return client, transcode.TELEGRAM_MAX_BYTES, AUTO_SPLIT_MB * 1024 * 1024


def media_info(message):
    """(media, file_name) for any video / document / audio post, else (None, '')."""
    if message is None or getattr(message, "empty", False):
        return None, ""
    media, name = video_info(message)
    if media is not None:
        return media, name
    for kind in ("document", "audio"):
        m = getattr(message, kind, None)
        if m is not None:
            return m, getattr(m, "file_name", None) or f"{kind}_{message.id}"
    return None, ""


def video_info(message):
    """(media, file_name) when `message` carries a video / video document, else (None, '')."""
    if message is None or getattr(message, "empty", False):
        return None, ""
    media = getattr(message, "video", None)
    if media is not None:
        return media, getattr(media, "file_name", None) or f"video_{message.id}.mp4"
    doc = getattr(message, "document", None)
    if doc is not None and transcode.looks_like_video(getattr(doc, "file_name", "") or "", getattr(doc, "mime_type", "") or ""):
        return doc, getattr(doc, "file_name", None) or f"video_{message.id}.mkv"
    return None, ""


class _Status:
    """A status message that is edited at most every few seconds (Telegram flood limits)."""

    def __init__(self, msg, gap=6.0):
        self.msg, self.gap, self._last, self._text = msg, gap, 0.0, ""

    async def set(self, text, force=False):
        if text == self._text or not self.msg:
            return
        now = time.monotonic()
        if not force and now - self._last < self.gap:
            return
        self._last, self._text = now, text
        try:
            await self.msg.edit_text(text)
        except FloodWait as e:
            self._last = now + (getattr(e, "value", None) or getattr(e, "x", 10))
        except Exception:
            pass


async def _send_with_retry(client, chat_id, path, name, probe, thumb):
    caption = f"<blockquote>{name}</blockquote>"
    for attempt in (1, 2):
        try:
            return await client.send_video(
                chat_id, path, caption=caption, parse_mode=enums.ParseMode.HTML, file_name=name,
                duration=int(probe.get("duration") or 0), width=probe.get("width") or 0,
                height=probe.get("height") or 0, thumb=thumb, supports_streaming=True, disable_notification=True)
        except FloodWait as e:
            await asyncio.sleep((getattr(e, "value", None) or getattr(e, "x", 10)) + 1)
        except Exception as e:
            client.LOGGER(__name__, client.name).warning(f"auto-quality: send_video failed ({e}), trying as document")
            break
    return await client.send_document(chat_id, path, caption=caption, parse_mode=enums.ParseMode.HTML,
                                      file_name=name, thumb=thumb, force_document=False, disable_notification=True)


async def _send_plain(client, chat_id, path, name, label=""):
    """Upload one raw (non-video) part as a document."""
    for _ in (1, 2):
        try:
            return await client.send_document(chat_id, path, file_name=name, force_document=True,
                                              caption=f"<blockquote>{name}</blockquote>",
                                              parse_mode=enums.ParseMode.HTML, disable_notification=True)
        except FloodWait as e:
            await asyncio.sleep((getattr(e, "value", None) or getattr(e, "x", 10)) + 1)
    raise RuntimeError("upload failed (flood wait)")


async def generate(client: Client, src: Message, notify_chat_id: int, uploader=None, wanted=None, upscale_to=None,
                   qualities: bool = True, split=None):
    """Process the post `src` (already in a DB channel): split it when it is over 2 GB and make the missing
    qualities when it is a video. One batch link with everything is sent to `notify_chat_id`.
    Returns the link or None. Never raises for ordinary failures: the user gets a message instead."""
    log = client.LOGGER(__name__, client.name)
    media, src_name = media_info(src)
    if media is None:
        return None
    is_video = video_info(src)[0] is not None
    if wanted is None:
        wanted = (await _settings(client))[1]
    if upscale_to is None:
        upscale_to = await _upscale_list(client)
    if split is None:
        split = await _split_on(client)
    up_client, max_single, part_limit = await _limits(client)
    size = getattr(media, "file_size", 0) or 0
    oversize = bool(split and size > max_single)
    want_q = bool(qualities and is_video and (wanted or upscale_to))
    if not (oversize or want_q):
        return None
    key = (src.chat.id, src.id)
    if key in _busy:
        await client.send_message(notify_chat_id, "⏳ This file is already being processed.")
        return None
    _busy.add(key)

    chat_id = src.chat.id
    index_as = uploader if uploader is not None else "auto-quality"
    status = _Status(await client.send_message(notify_chat_id, f"⏳ <b>{src_name}</b>\nWaiting in queue..."))
    tmp = tempfile.mkdtemp(prefix="aq_")
    try:
        if size > AUTO_QUALITY_MAX_MB * 1024 * 1024:
            await status.set(f"⚠️ <b>{src_name}</b> is {transcode.human_size(size)}: bigger than AUTO_QUALITY_MAX_MB "
                             f"({AUTO_QUALITY_MAX_MB} MB), skipped.", force=True)
            return None
        need = size * (2.2 if oversize else 1.3)
        free = shutil.disk_usage(tmp).free
        if free < need:
            await status.set(f"⚠️ <b>{src_name}</b>: not enough free disk ({transcode.human_size(free)} free, about "
                             f"{transcode.human_size(need)} needed), skipped.", force=True)
            return None

        entries = []     # dicts: rank, seq, mid, label, size, up, part
        failed, ups_done = [], set()

        async def upload_video_file(path, name, label, rank, dur, head, up=False):
            """Upload one finished video file, cutting it into playable parts first when it is over 2 GB."""
            fsize = os.path.getsize(path)
            if fsize <= max_single:
                files = [(path, name)]
            elif split:
                await status.set(f"{head}\n✂️ Splitting {transcode.human_size(fsize)} into parts...", force=True)
                parts = await transcode.split_video(path, os.path.join(tmp, f"split_{label}"), dur, part_limit, hard_limit=max_single)
                files = [(pp, transcode.part_name(name, n)) for n, pp in enumerate(parts, 1)]
            else:
                raise RuntimeError(f"{label} is {transcode.human_size(fsize)}: over the Telegram limit and /autosplit is off")
            out = []
            for n, (pp, pname) in enumerate(files, 1):
                tag = f" part {n}/{len(files)}" if len(files) > 1 else ""
                await status.set(f"{head}\n⬆️ Uploading{tag} {transcode.human_size(os.path.getsize(pp))}...", force=True)
                pinfo = await transcode.probe(pp)
                custom = thumbnail.active(client)      # the /settings thumbnail wins over a generated frame
                thumb = custom or os.path.join(tmp, f"thumb_{label}_{n}.jpg")
                if not custom and not await transcode.make_thumbnail(pp, thumb, min(max(pinfo["duration"] * 0.1, 0.5), 30)):
                    thumb = None
                try:
                    sent = await _send_with_retry(up_client, chat_id, pp, pname, pinfo, thumb)
                finally:
                    if thumb and not custom and os.path.exists(thumb):
                        os.remove(thumb)
                await file_index.record(client, sent, uploader=index_as)
                out.append({"rank": rank, "seq": n, "mid": sent.id, "label": label, "up": up,
                            "size": os.path.getsize(pp), "part": (n, len(files)) if len(files) > 1 else None})
                if pp != path:
                    os.remove(pp)
            return out

        async with _semaphore():
            ext = os.path.splitext(src_name)[1] or (".mkv" if is_video else ".bin")
            in_path = os.path.join(tmp, "source" + ext)

            async def dl_progress(cur, total):
                pct = int(cur * 100 / total) if total else 0
                await status.set(f"⬇️ <b>{src_name}</b>\nDownloading source... {pct}% "
                                 f"({transcode.human_size(cur)} / {transcode.human_size(total)})")

            await status.set(f"⬇️ <b>{src_name}</b>\nDownloading source...", force=True)
            await client.download_media(src, file_name=in_path, progress=dl_progress)
            if not os.path.exists(in_path):
                raise RuntimeError("download failed")

            w = h = 0
            dur = 0.0
            src_q = None
            if is_video:
                info = await transcode.probe(in_path)
                w, h, dur = info["width"], info["height"], info["duration"]
                if not w or not h:
                    if not oversize:
                        await status.set(f"❌ <b>{src_name}</b>: ffprobe could not read this video, nothing made.", force=True)
                        return None
                    want_q = False
                else:
                    src_q = transcode.source_label(w, h)
            orig_label = src_q or extract_quality(src_name) or "Original"
            orig_rank = quality_rank(orig_label) if orig_label in transcode.LADDER else 99

            # 1) the original itself, when it is too big to hand out
            if oversize:
                head = f"✂️ <b>{src_name}</b>"
                if is_video and dur > 0:
                    entries += await upload_video_file(in_path, src_name, orig_label, orig_rank, dur, head)
                else:
                    await status.set(f"{head}\nSplitting {transcode.human_size(size)} into parts...", force=True)
                    parts = await asyncio.to_thread(transcode.split_raw, in_path, os.path.join(tmp, "raw"), part_limit, src_name)
                    for n, pp in enumerate(parts, 1):
                        await status.set(f"{head}\n⬆️ Uploading part {n}/{len(parts)} "
                                         f"{transcode.human_size(os.path.getsize(pp))}...", force=True)
                        sent = await _send_plain(up_client, chat_id, pp, os.path.basename(pp))
                        await file_index.record(client, sent, uploader=index_as)
                        entries.append({"rank": orig_rank, "seq": n, "mid": sent.id, "label": orig_label, "up": False,
                                        "size": os.path.getsize(pp), "part": (n, len(parts))})
                        os.remove(pp)
            else:
                entries.append({"rank": orig_rank, "seq": 0, "mid": src.id, "label": orig_label, "up": False,
                                "size": size, "part": None, "original": True})

            # 2) smaller / upscaled qualities
            plan = []
            if want_q and w and h:
                portrait = h > w
                have = {src_q} if src_q else set()
                if extract_quality(src_name) in transcode.LADDER:
                    have.add(extract_quality(src_name))
                plan = [(l, False) for l in transcode.pick_targets(w, h, wanted, have)]
                plan += [(l, True) for l in transcode.pick_upscale_targets(w, h, upscale_to, have, AUTO_QUALITY_UPSCALE_MAX_FACTOR)]
            if not plan and not oversize:
                await status.set(f"ℹ️ <b>{src_name}</b> ({w}x{h}) is already at or below every wanted quality, "
                                 f"nothing to generate.", force=True)
                return None

            for i, (label, upscaled) in enumerate(plan, 1):
                out_name = transcode.output_name(src_name, label, "Upscaled" if upscaled else "")
                out_path = os.path.join(tmp, f"out_{label}.mp4")
                head = f"🎞 <b>{src_name}</b>\nQuality {i}/{len(plan)}: <b>{label}</b>" + (" (upscaling)" if upscaled else "")

                async def enc_progress(frac, head=head):
                    await status.set(f"{head}\nEncoding... {int(frac * 100)}%")

                await status.set(f"{head}\nEncoding... 0%", force=True)
                build = transcode.build_upscale_cmd if upscaled else transcode.build_ffmpeg_cmd
                cmd = build(in_path, out_path, label, portrait, AUTO_QUALITY_PRESET, AUTO_QUALITY_THREADS)
                rc, err = await transcode.run_ffmpeg(cmd, dur, enc_progress)
                if rc != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
                    log.warning(f"auto-quality: ffmpeg failed for {label}: {err}")
                    failed.append(label)
                    continue
                try:
                    got = await upload_video_file(out_path, out_name, label, quality_rank(label), dur, head, upscaled)
                except Exception as e:
                    log.warning(f"auto-quality: {label} failed: {e}")
                    failed.append(label)
                    continue
                finally:
                    shutil.rmtree(os.path.join(tmp, f"split_{label}"), ignore_errors=True)
                    if os.path.exists(out_path):
                        os.remove(out_path)
                entries += got
                if upscaled:
                    ups_done.add(label)

        if not any(not e.get("original") for e in entries):
            await status.set(f"❌ <b>{src_name}</b>: no quality could be generated "
                             f"({', '.join(failed) or 'unknown error'}). Is ffmpeg installed?", force=True)
            return None

        entries.sort(key=lambda e: (e["rank"], e["seq"]))
        ids = [e["mid"] for e in entries]
        token = generate_token(8)
        await client.mongodb.db["custom_batches"].insert_one(
            {"_id": token, "chat_id": chat_id, "ids": ids, "by": "auto-quality"})
        link = build_link(client, await encode(f"getc-{token}"))
        await log_activity(client, "link_generated", uploader or "auto-quality", link, f"auto-quality {len(ids)} files")

        grouped = {}
        for e in entries:
            g = grouped.setdefault((e["rank"], e["label"]), {"n": 0, "size": 0, "up": e["up"], "orig": e.get("original", False)})
            g["n"] += 1
            g["size"] += e["size"]
        lines = []
        for (_r, lab), g in grouped.items():
            if g["orig"]:
                lines.append(f"• {lab} (original)")
                continue
            txt = f"• {lab} ({transcode.human_size(g['size'])}"
            txt += f", {g['n']} parts)" if g["n"] > 1 else ")"
            if g["up"]:
                txt += " ⬆️ upscaled"
            lines.append(txt)
        title = "All qualities ready" if plan else "File split into parts"
        text = (f"<blockquote>{'🎞' if plan else '✂️'} <b>{title}</b></blockquote>\n<b>{src_name}</b>\n"
                + "\n".join(lines) + f"\n\n<code>{link}</code>")
        if not is_video and oversize:
            text += "\n\nℹ️ Not a video: parts are raw. Join them with 7-Zip (open the .001) or <code>cat name.* > name</code>."
        if failed:
            text += f"\n\n⚠️ Skipped (failed): {', '.join(failed)}"
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔁 Share URL", url=f"https://telegram.me/share/url?url={link}")]])
        try:
            await status.msg.delete()
        except Exception:
            pass
        await client.send_message(notify_chat_id, text, reply_markup=markup, disable_web_page_preview=True)
        return link
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.error(f"auto-quality failed for {src_name}: {e}", exc_info=True)
        await status.set(f"❌ <b>{src_name}</b>: failed ({e}).", force=True)
        return None
    finally:
        _busy.discard(key)
        shutil.rmtree(tmp, ignore_errors=True)


def _spawn(coro):
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def maybe_start(client: Client, user_message: Message, post_message: Message):
    """Called by channel_post after a file was stored. Starts a background job when the file is over 2 GB
    (and /autosplit is on) and/or it is a video (and /autoquality is on). -> True when a job was started."""
    try:
        media, _ = media_info(post_message)
        if media is None:
            return False
        on, wanted = await _settings(client)
        ups = await _upscale_list(client)
        is_video = video_info(post_message)[0] is not None
        max_single = (await _limits(client))[1]
        need_split = await _split_on(client) and (getattr(media, "file_size", 0) or 0) > max_single
        need_q = bool(on and is_video and (wanted or ups))
        if not (need_split or need_q):
            return False
        _spawn(generate(client, post_message, user_message.chat.id, uploader=user_message.from_user.id,
                        wanted=wanted, upscale_to=ups, qualities=need_q))
        return True
    except Exception as e:
        client.LOGGER(__name__, client.name).warning(f"auto-quality: could not start: {e}")
        return False


@Client.on_message(filters.private & filters.command("autoquality"))
async def autoquality_command(client: Client, message: Message):
    if message.from_user.id not in client.admins:
        return await message.reply(client.reply_text)
    on, wanted = await _settings(client)
    args = [a for a in message.command[1:]]
    if args and args[0].lower() in ("on", "off"):
        on = args[0].lower() == "on"
        await client.mongodb.update_bot_setting("auto_quality", on)
    elif args and args[0].lower() == "upscale":
        if len(args) < 2:
            return await message.reply("Usage: <code>/autoquality upscale 1080p,1440p,4K</code> or <code>/autoquality upscale off</code>")
        if args[1].lower() == "off":
            await client.mongodb.update_bot_setting("auto_quality_upscale", "")
        else:
            ups = transcode.parse_list(" ".join(args[1:]))
            if not ups:
                return await message.reply("Allowed: " + ", ".join(transcode.ORDER))
            await client.mongodb.update_bot_setting("auto_quality_upscale", ",".join(ups))
    elif args and args[0].lower() == "set":
        new = transcode.parse_list(" ".join(args[1:]))
        if not new:
            return await message.reply("Usage: <code>/autoquality set 144p,360p,720p</code>\n"
                                       "Allowed: " + ", ".join(transcode.ORDER))
        wanted = new
        await client.mongodb.update_bot_setting("auto_quality_list", ",".join(wanted))
    elif args:
        return await message.reply("Usage: <code>/autoquality on</code> · <code>off</code> · <code>set 144p,480p,720p</code>")
    await message.reply(
        f"<blockquote>🎞 <b>Auto-quality</b></blockquote>\nStatus: <b>{'ON' if on else 'OFF'}</b>\n"
        f"Qualities: <b>{', '.join(wanted)}</b>\n"
        f"Upscale to: <b>{', '.join(await _upscale_list(client)) or 'off'}</b>\n"
        f"Uploader: <b>{'Premium account' if await get_premium(client) else 'bot'}</b>\n\n"
        "When ON, every video you store also gets the smaller qualities above (never upscaled, so a 720p "
        "upload only gets 144p-480p). One batch link with all of them is sent when encoding is done.\n"
        "<code>/autoquality on|off</code> · <code>/autoquality set 144p,360p,720p</code> · "
        "<code>/autoquality upscale 1080p,4K</code> also enlarges SMALL videos (Lanczos + denoise + sharpen, "
        "not AI: bigger and cleaner, but no real new detail). "
        "<code>/genquality</code> for a video that is already stored.")


@Client.on_message(filters.private & filters.command("genquality"))
async def genquality_command(client: Client, message: Message):
    """Make the qualities for a video that is already in a DB channel (works even when /autoquality is off)."""
    if message.from_user.id not in client.admins:
        return await message.reply(client.reply_text)
    try:
        ask = await client.ask(
            text="<blockquote>Forward the video from the DB channel (with quotes), or send its post link.</blockquote>",
            chat_id=message.from_user.id, filters=(filters.forwarded | (filters.text & ~filters.forwarded)), timeout=60)
    except Exception:
        return
    msg_id, channel_id = await get_message_id(client, ask)
    if not msg_id:
        return await ask.reply("✗ That post is not from my DB channel.", quote=True)
    try:
        src = await client.get_messages(channel_id, msg_id)
    except Exception as e:
        return await ask.reply(f"✗ Could not read that post: {e}", quote=True)
    if video_info(src)[0] is None:
        return await ask.reply("✗ That post is not a video.", quote=True)
    wanted = (await _settings(client))[1]
    _spawn(generate(client, src, message.from_user.id, uploader=message.from_user.id, wanted=wanted, qualities=True))
    await ask.reply("🎞 Started. I will send one batch link with all qualities when it is done.", quote=True)


@Client.on_message(filters.private & filters.command("autosplit"))
async def autosplit_command(client: Client, message: Message):
    if message.from_user.id not in client.admins:
        return await message.reply(client.reply_text)
    on = await _split_on(client)
    arg = message.command[1].lower() if len(message.command) > 1 else ""
    if arg in ("on", "off"):
        on = arg == "on"
        await client.mongodb.update_bot_setting("auto_split", on)
    elif arg:
        return await message.reply("Usage: <code>/autosplit on</code> or <code>/autosplit off</code>")
    await message.reply(
        f"<blockquote>✂️ <b>Auto-split</b></blockquote>\nStatus: <b>{'ON' if on else 'OFF'}</b>\n"
        f"Uploader: <b>{'Premium account (files up to ' + str(PREMIUM_MAX_MB) + ' MB stay in one piece)' if await get_premium(client) else 'bot (2000 MB limit)'}</b>\n"
        f"Parts are at most <b>{(await _limits(client))[2] // (1024 * 1024)} MB</b>\n\n"
        "A stored file above the uploader limit (2000 MB bot / Premium account if PREMIUM_SESSION is set) is cut into parts and one batch link delivers them all. Videos are cut "
        "without re-encoding (every part plays); other files are raw <code>.001 .002</code> parts to join with 7-Zip.\n"
        "<code>/autosplit on|off</code> · <code>/gensplit</code> for a file that is already stored.")


@Client.on_message(filters.private & filters.command("gensplit"))
async def gensplit_command(client: Client, message: Message):
    """Split a file that is already in a DB channel and is over 2 GB (works even when /autosplit is off)."""
    if message.from_user.id not in client.admins:
        return await message.reply(client.reply_text)
    try:
        ask = await client.ask(
            text="<blockquote>Forward the big file from the DB channel (with quotes), or send its post link.</blockquote>",
            chat_id=message.from_user.id, filters=(filters.forwarded | (filters.text & ~filters.forwarded)), timeout=60)
    except Exception:
        return
    msg_id, channel_id = await get_message_id(client, ask)
    if not msg_id:
        return await ask.reply("✗ That post is not from my DB channel.", quote=True)
    try:
        src = await client.get_messages(channel_id, msg_id)
    except Exception as e:
        return await ask.reply(f"✗ Could not read that post: {e}", quote=True)
    media, _ = media_info(src)
    if media is None:
        return await ask.reply("✗ That post has no file.", quote=True)
    max_single = (await _limits(client))[1]
    if (getattr(media, "file_size", 0) or 0) <= max_single:
        return await ask.reply(f"✗ That file is not over {max_single // (1024 * 1024)} MB, nothing to split.", quote=True)
    _spawn(generate(client, src, message.from_user.id, uploader=message.from_user.id, qualities=False, split=True))
    await ask.reply("✂️ Started. I will send one batch link with all parts when it is done.", quote=True)
