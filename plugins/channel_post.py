import asyncio
from pyrogram import filters, Client
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait
from helper.helper_func import encode
from helper.stream_links import stream_block
from helper.upload_access import can_upload
from helper.activity import log_activity
from helper.permanent_link import build_link
from helper import file_index
from config import DUPLICATE_DB_POST
from plugins import auto_quality

#===============================================================#

async def send_duplicate_reply(client, message, reply_text, dup):
    """Tell the uploader the file already exists and hand back the existing link."""
    link = await file_index.start_link(client, dup["chat_id"], dup["msg_id"])
    stream = await stream_block(client, dup["chat_id"], dup["msg_id"])
    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔁 Share URL", url=f'https://telegram.me/share/url?url={link}')]])
    await reply_text.edit(
        f"<b>♻️ This file is already stored, nothing was uploaded again.</b>\n<b>Existing link:</b>\n\n{link}{stream}",
        reply_markup=reply_markup, disable_web_page_preview=True,
    )
    await log_activity(client, "duplicate_upload", message.from_user.id, dup["_id"], dup.get("name", ""))

#===============================================================#

@Client.on_message(filters.private & ~filters.command(['start', 'shortner','users','broadcast','batch','genlink','stats', 'pbroadcast', 'db', 'adddb', 'add_db', 'removedb', 'rm_db',  'ban', 'unban', 'unbanall', 'autopost', 'scheduled', 'cancelpost', 'addpostch', 'rmpostch', 'postchs', 'addpremium', 'delpremium', 'premiumusers', 'request', 'profile', 'credits', 'cplan', 'add_credit', 'buy', 'bought', 'addadmin', 'removeadmin', 'nbatch', 'custom_batch', 'flink', 'done', 'backup', 'explink', 'links', 'revoke', 'daily', 'refer', 'invite', 'search', 'redeem', 'gencode', 'codes', 'delcode', 'ledger', 'help', 'commands', 'info', 'autobatch', 'autoquality', 'genquality', 'autosplit', 'gensplit', 'maintenance', 'contact', 'reply', 'trial', 'set_expiry', 'logs', 'restart']))
async def channel_post(client: Client, message: Message):
    if not await can_upload(client, message):  # admins always; others per UPLOAD_ACCESS (config.py)
        return await message.reply(client.reply_text)
    reply_text = await message.reply_text("Please Wait...!", quote = True)

    # Same file twice? Answer with the old link instead of filling the DB channel.
    # The guard makes two identical uploads that arrive together run one after the other.
    async with file_index.upload_guard(message):
        dup = await file_index.find_duplicate(client, message)
        if dup:
            await send_duplicate_reply(client, message, reply_text, dup)
            return
        try:
            post_message = await message.copy(chat_id = client.db, disable_notification=True)
        except FloodWait as e:
            await asyncio.sleep(e.x)
            post_message = await message.copy(chat_id = client.db, disable_notification=True)
        except Exception as e:
            print(e)
            await reply_text.edit_text("Something went Wrong..!")
            return
        await file_index.record(client, post_message, uploader=message.from_user.id)
    await log_activity(client, "file_upload", message.from_user.id, f"{client.db}/{post_message.id}",
                       message.media.value if message.media else "text")
    converted_id = post_message.id * abs(client.db)
    string = f"get-{converted_id}"
    base64_string = await encode(string)
    link = build_link(client, base64_string)

    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔁 Share URL", url=f'https://telegram.me/share/url?url={link}')]])

    stream = await stream_block(client, client.db, post_message.id, post_message)  # web player links (media only)
    await reply_text.edit(f"<b>Here is your link</b>\n\n{link}{stream}", reply_markup=reply_markup, disable_web_page_preview = True)

    if not client.disable_btn:
        await post_message.edit_reply_markup(reply_markup)

    # Videos: make 144p ... 1080p copies in the background (needs /autoquality on); a batch link follows.
    await auto_quality.maybe_start(client, message, post_message)

#===============================================================#

async def _handle_hand_posted_duplicate(client, message) -> bool:
    """A file posted by hand in the DB channel that is already stored: warn the owner (and, with
    DUPLICATE_DB_POST=skip, remove the new copy). -> True when the message was removed."""
    try:
        meta = file_index.describe(message)
        if not meta:
            return False
        dup = await file_index.find_duplicate(client, message, exclude_id=meta["_id"])
        if not dup:
            return False
        link = await file_index.start_link(client, dup["chat_id"], dup["msg_id"])
        removed = False
        if DUPLICATE_DB_POST == "skip":
            try:
                await message.delete()
                removed = True
            except Exception as e:
                client.LOGGER(__name__, client.name).warning(f"Could not delete the duplicate post: {e}")
        note = ("🗑 The new copy was <b>removed</b>." if removed else
                "The new copy was kept. Delete it yourself, or set <code>DUPLICATE_DB_POST=skip</code> to have me remove duplicates.")
        await client.send_message(
            client.owner,
            f"♻️ <b>Duplicate file in the DB channel</b>\n<code>{meta['name']}</code>\n"
            f"Already stored as message <code>{dup['msg_id']}</code>.\n<b>Existing link:</b> {link}\n\n{note}",
            disable_web_page_preview=True)
        await log_activity(client, "duplicate_db_post", "channel", dup["_id"], meta["name"])
        return removed
    except Exception as e:
        client.LOGGER(__name__, client.name).warning(f"Duplicate check for a hand-posted file failed: {e}")
        return False


@Client.on_message(filters.channel & filters.incoming)
async def new_post(client: Client, message: Message):
    if message.chat.id != client.db:
        return
    if DUPLICATE_DB_POST != "off" and await _handle_hand_posted_duplicate(client, message):
        return
    await file_index.record(client, message, uploader="channel")  # posted by hand in the DB channel
    if client.disable_btn:
        return

    converted_id = message.id * abs(client.db)
    string = f"get-{converted_id}"
    base64_string = await encode(string)
    link = build_link(client, base64_string)
    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔁 Share URL", url=f'https://telegram.me/share/url?url={link}')]])
    try:
        await message.edit_reply_markup(reply_markup)
    except Exception as e:
        print(e)

        pass





