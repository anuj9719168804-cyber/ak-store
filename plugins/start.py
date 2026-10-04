from helper.helper_func import *
from helper.utils import ban_notice
from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
import humanize
from config import (
    MSG_EFFECT, OWNER_ID, ADMIN_PANEL_URL, ADMIN_PASSWORD,
    BYPASS_MIN_SECONDS, VERIFY_MAX_SECONDS, BYPASS_MAX_STRIKES, BYPASS_AUTO_BAN,
    VERIFY_REWARD_CREDITS, WEB_URL,
)
from helper import alerts, ledger, links, rewards, stats, verify_web as vw
from plugins.shortner import get_short_async
from helper.helper_func import get_messages, force_sub, decode, batch_auto_del_notification
from helper import custom_buttons, file_index, thumbnail
from helper.caption_clean import decorate
from helper.caption_logic import apply_custom_caption
from helper.activity import log_activity
import asyncio
import time
#===============================================================#

# What a user sees when a managed (expiring / limited) link no longer works
_LINK_MSG = {
    "missing": "<blockquote>⚠️ ᴛʜɪs ʟɪɴᴋ ᴅᴏᴇs ɴᴏᴛ ᴇxɪsᴛ.</blockquote>",
    "revoked": "<blockquote>⛔ ᴛʜɪs ʟɪɴᴋ ʜᴀs ʙᴇᴇɴ ᴅɪsᴀʙʟᴇᴅ ʙʏ ᴛʜᴇ ᴏᴡɴᴇʀ.</blockquote>",
    "expired": "<blockquote>⌛ ᴛʜɪs ʟɪɴᴋ ʜᴀs ᴇxᴘɪʀᴇᴅ.\nᴀsᴋ ꜰᴏʀ ᴀ ɴᴇᴡ ᴏɴᴇ.</blockquote>",
    "full": "<blockquote>🔒 ᴛʜɪs ʟɪɴᴋ ʜᴀs ʀᴇᴀᴄʜᴇᴅ ɪᴛs ᴅᴏᴡɴʟᴏᴀᴅ ʟɪᴍɪᴛ.\nᴀsᴋ ꜰᴏʀ ᴀ ɴᴇᴡ ᴏɴᴇ.</blockquote>",
}


async def _qualify_referral(client, user_id, event):
    """The invited user did something that can complete a referral: pay the inviter (once)."""
    try:
        inviter = await rewards.qualify(client.mongodb.db, user_id, event)
        if inviter:
            await log_activity(client, "referral", inviter, user_id, f"+{rewards.REFERRAL_CREDITS} credits ({event})")
            try:
                await client.send_message(inviter, f"<blockquote>🎉 <b>Referral completed!</b></blockquote>\n"
                                                   f"A friend you invited just used the bot: <b>+{rewards.REFERRAL_CREDITS} credits</b>.")
            except Exception:
                pass
    except Exception as e:
        client.LOGGER(__name__, client.name).warning(f"Referral qualify failed: {e}")


async def _verified_reply(client, message, unlock_payload, credits_given):
    """The 'verification successful' screen, shared by the web and the old shortener flow."""
    unlock_link = f"https://t.me/{client.username}?start={unlock_payload}"
    await client.send_photo(
        chat_id=message.chat.id,
        photo=client.messages.get("SHORT_VERIFY", ""),
        caption=(
            "<b>ⓘ Your verification is successful!</b>\n"
            f"<blockquote>✦ {credits_given} Credits Added to Your Account.</blockquote>"
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✨ ᴄʟɪᴄᴋ ʜᴇʀᴇ ✨", url=unlock_link)],
            [InlineKeyboardButton("• ʙᴜʏ ᴘʀᴇᴍɪᴜᴍ •", url="https://t.me/anujedits76")],
        ]),
    )


async def _redeem_web_verify(client, message, tid):
    """/start vt_<token>: the user is back from the web verify page."""
    user_id = message.from_user.id
    code, doc = await vw.redeem(client.mongodb.db, tid, user_id)
    if code == "ok":
        await client.mongodb.reset_bypass_strikes(user_id)
        await client.mongodb.mark_verified(user_id)
        await client.mongodb.add_credits(user_id, VERIFY_REWARD_CREDITS)
        await ledger.record(client.mongodb.db, user_id, VERIFY_REWARD_CREDITS, "verify", tid)
        await stats.bump(client.mongodb.db, "verified")
        await log_activity(client, "verified_web", user_id, tid, f"{doc.get('elapsed', 0):.0f}s")
        await _qualify_referral(client, user_id, "verify")
        return await _verified_reply(client, message, doc["payload"], VERIFY_REWARD_CREDITS)
    text = {
        "used": "<blockquote>🚫 ᴛʜɪs ᴠᴇʀɪꜰɪᴄᴀᴛɪᴏɴ ʟɪɴᴋ ʜᴀs ᴀʟʀᴇᴀᴅʏ ʙᴇᴇɴ ᴜsᴇᴅ.</blockquote>",
        "failed": "<blockquote>🚫 ᴠᴇʀɪꜰɪᴄᴀᴛɪᴏɴ ꜰᴀɪʟᴇᴅ. ᴏᴘᴇɴ ʏᴏᴜʀ ꜰɪʟᴇ ʟɪɴᴋ ᴀɢᴀɪɴ ᴀɴᴅ ᴅᴏ ɪᴛ ᴘʀᴏᴘᴇʀʟʏ.</blockquote>",
        "expired": "<blockquote>⚠️ ᴠᴇʀɪꜰɪᴄᴀᴛɪᴏɴ ᴇxᴘɪʀᴇᴅ.\nᴏᴘᴇɴ ʏᴏᴜʀ ꜰɪʟᴇ ʟɪɴᴋ ᴀɢᴀɪɴ.</blockquote>",
        "not_passed": "<blockquote>⚠️ ᴘʟᴇᴀsᴇ ꜰɪɴɪsʜ ᴛʜᴇ ᴠᴇʀɪꜰɪᴄᴀᴛɪᴏɴ ᴘᴀɢᴇ ꜰɪʀsᴛ (ᴛᴀᴘ ᴛʜᴇ ʙᴜᴛᴛᴏɴ ᴛʜᴇʀᴇ).</blockquote>",
    }.get(code, "<blockquote>⚠️ ᴠᴇʀɪꜰɪᴄᴀᴛɪᴏɴ ʟɪɴᴋ ɪs ɴᴏ ʟᴏɴɢᴇʀ ᴠᴀʟɪᴅ.</blockquote>")
    await message.reply(text)


async def _send_web_gate(client, message, payload):
    """No credits left: send the user to the web verify page (through the shortener)."""
    user_id = message.from_user.id
    doc = await vw.create(client.mongodb.db, user_id, payload)
    target = vw.verify_url(WEB_URL, doc["_id"])
    try:
        short_link = await get_short_async(target, client)
    except Exception as e:
        client.LOGGER(__name__, client.name).warning(f"Shortener failed: {e}")
        short_link = target
    if short_link == target:
        # The shortener answered nothing usable. Handing out the plain verify link would let
        # everyone skip the shortener, so say so instead (the old flow handed out the file link!).
        return await message.reply("⚠️ Couldn't generate the verification link right now. Please try again in a minute.")
    await vw.set_short(client.mongodb.db, doc["_id"], short_link)
    tutorial_link = getattr(client, 'tutorial_link', "https://t.me/ANIME_X_FLEX/19")
    await client.send_photo(
        chat_id=message.chat.id,
        photo=client.messages.get("SHORT_PIC", ""),
        caption=client.messages.get("SHORT_MSG", ""),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("• ᴏᴘᴇɴ ʟɪɴᴋ", url=vw.go_url(WEB_URL, doc["_id"]))]
            + ([InlineKeyboardButton("ᴛᴜᴛᴏʀɪᴀʟ •", url=tutorial_link)] if getattr(client, 'tutorial_enabled', True) and tutorial_link else []),
            [InlineKeyboardButton(" • ʙᴜʏ ᴘʀᴇᴍɪᴜᴍ •", url="https://t.me/Premium_Fliix/21")],
        ]),
    )


@Client.on_message(filters.command('start') & filters.private)
@force_sub
async def start_command(client: Client, message: Message):
    user_id = message.from_user.id

    # 1. Add user if not present
    present = await client.mongodb.present_user(user_id)
    if not present:
        try:
            await client.mongodb.add_user(user_id)
            await log_activity(client, "new_user", user_id, "", f"{message.from_user.first_name} @{message.from_user.username or 'N/A'}")
        except Exception as e:
            client.LOGGER(__name__, client.name).warning(f"Error adding a user:\n{e}")

    # 2. Check if banned
    is_banned = await client.mongodb.is_banned(user_id)
    if is_banned:
        return await message.reply(await ban_notice(client.mongodb, message.from_user.id))

    text = message.text
    _parts = text.split(" ", 1)
    _ref = rewards.parse_ref(_parts[1].strip()) if len(_parts) > 1 else None
    if _ref is not None:
        # /start ref_<id>: reward the inviter (once per new account), then show the normal welcome
        try:
            rewarded, _why = await rewards.register_referral(client.mongodb.db, user_id, _ref)
            if rewarded:                                   # join mode: paid right away
                await log_activity(client, "referral", _ref, user_id, f"+{rewards.REFERRAL_CREDITS} credits")
                try:
                    await client.send_message(_ref, f"<blockquote>🎉 <b>New referral!</b></blockquote>\n"
                                                    f"Someone joined with your link: <b>+{rewards.REFERRAL_CREDITS} credits</b>.")
                except Exception:
                    pass
        except Exception as e:
            client.LOGGER(__name__, client.name).warning(f"Referral failed: {e}")
        text = "/start"
    if len(text) > 7:
        try:
            original_payload = text.split(" ", 1)[1]
            base64_string = original_payload

            # ── web verify page: the user is back from WEB_URL/verify ──────────
            if base64_string.startswith(vw.PREFIX):
                return await _redeem_web_verify(client, message, base64_string[len(vw.PREFIX):])

            # ── managed link (lk_...): expiry / max uses / revoke are checked here ──
            managed_token = None
            if links.is_managed(base64_string):
                managed_token = links.token_of(base64_string)
                if user_id in client.admins:           # admins can always open their own links (no slot used)
                    ldoc = await links.get(client.mongodb.db, managed_token)
                    state = "ok" if ldoc else "missing"
                else:
                    state, ldoc = await links.check(client.mongodb.db, managed_token, user_id)
                if state != "ok":
                    return await message.reply(_LINK_MSG[state])
                await links.count_click(client.mongodb.db, managed_token)
                base64_string = ldoc["payload"]
            if not base64_string.startswith("yu3elk"):
                await stats.count_click(client.mongodb.db, original_payload)

            is_short_link = False
            if base64_string.startswith("yu3elk"):
                base64_string = base64_string[6:-1]
                is_short_link = True
                session, saved_payload, verify_time = await client.mongodb.get_verify_data(user_id)
                if not session:
                    return await message.reply(
                        "<blockquote>⚠️ ᴠᴇʀɪғɪᴄᴀᴛɪᴏɴ ᴇxᴘɪʀᴇᴅ.\nᴘʟᴇᴀsᴇ ɢᴇɴᴇʀᴀᴛᴇ ᴀ ɴᴇᴡ ʟɪɴᴋ.</blockquote>"
                    )
                # ❌ OLD LINK USED
                if saved_payload != base64_string:
                    return await message.reply(
                        "<blockquote>🚫 ᴛʜɪs ᴠᴇʀɪꜰɪᴄᴀᴛɪᴏɴ ʟɪɴᴋ ɪꜱ ɴᴏ ʟᴏɴɢᴇʀ ᴠᴀʟɪᴅ.</blockquote>"
                    )
                time_taken = int(time.time()) - verify_time
                # 🚫 BYPASS DETECTED (verified faster than BYPASS_MIN_SECONDS)
                if time_taken < BYPASS_MIN_SECONDS:
                    await client.mongodb.clear_verify_session(user_id)
                    strikes = await client.mongodb.add_bypass_strike(user_id)
                    await stats.bump(client.mongodb.db, "bypass")
                    await alerts.note_bypass(client)
                    who = f"{message.from_user.first_name} @{message.from_user.username or 'N/A'}"
                    await log_activity(
                        client, "bypass_detected", user_id, "",
                        f"{who} | {time_taken}s < {BYPASS_MIN_SECONDS}s | strike {strikes}/{BYPASS_MAX_STRIKES}",
                    )
                    if BYPASS_AUTO_BAN and strikes >= BYPASS_MAX_STRIKES:
                        await client.mongodb.ban_user(user_id)
                        await log_activity(client, "bypass_auto_ban", user_id, "", f"{who} | {strikes} strikes")
                        return await message.reply(
                            "<blockquote>🚫 ʏᴏᴜ ʜᴀᴠᴇ ʙᴇᴇɴ ʙᴀɴɴᴇᴅ ꜰᴏʀ ʀᴇᴘᴇᴀᴛᴇᴅ ʙʏᴘᴀss ᴀᴛᴛᴇᴍᴘᴛs.</blockquote>"
                        )
                    warn = f"\n⚠️ ᴡᴀʀɴɪɴɢ {strikes}/{BYPASS_MAX_STRIKES}" if BYPASS_AUTO_BAN else ""
                    return await message.reply(
                        "<blockquote>🚫 ʙʏᴘᴀss ᴅᴇᴛᴇᴄᴛᴇᴅ!\n"
                        f"⧗ ᴛɪᴍᴇ ᴛᴀᴋᴇɴ: {time_taken}s (ᴍɪɴ {BYPASS_MIN_SECONDS}s)"
                        f"{warn}\n"
                        "ᴘʟᴇᴀsᴇ ᴄᴏᴍᴘʟᴇᴛᴇ ᴛʜᴇ ᴠᴇʀɪꜰɪᴄᴀᴛɪᴏɴ ᴘʀᴏᴘᴇʀʟʏ.</blockquote>"
                    )
                # 🚫 SESSION TOO OLD
                if time_taken > VERIFY_MAX_SECONDS:
                    await client.mongodb.clear_verify_session(user_id)
                    return await message.reply(
                        "<blockquote>⚠️ ᴠᴇʀɪꜰɪᴄᴀᴛɪᴏɴ ᴛɪᴍᴇᴏᴜᴛ!\n"
                        "ᴘʟᴇᴀsᴇ ɢᴇɴᴇʀᴀᴛᴇ ᴀ ɴᴇᴡ ʟɪɴᴋ.</blockquote>"
                    )
                await client.mongodb.clear_verify_session(user_id)
                await client.mongodb.reset_bypass_strikes(user_id)
                await client.mongodb.add_credits(user_id, VERIFY_REWARD_CREDITS)
                await ledger.record(client.mongodb.db, user_id, VERIFY_REWARD_CREDITS, "verify", "shortener")
                await stats.bump(client.mongodb.db, "verified")
                await _qualify_referral(client, user_id, "verify")
                return await _verified_reply(client, message, base64_string, VERIFY_REWARD_CREDITS)
        except IndexError:
            return await message.reply("Invalid command format.")

        # 3. Check premium status
        is_user_pro = await client.mongodb.is_pro(user_id)
        # 3.5 Check credits
        user_credits = await client.mongodb.get_credits(user_id)
        # 4. Check if shortner is enabled
        shortner_enabled = getattr(client, 'shortner_enabled', True)

        # 5. If user is not premium AND shortner is enabled, send short URL and return
        if not is_user_pro and user_id != OWNER_ID and not is_short_link and shortner_enabled and user_credits <= 0:
            if vw.active():
                return await _send_web_gate(client, message, original_payload)
            await client.mongodb.set_verify_session(user_id, original_payload)
            try:
                short_link = await get_short_async(f"https://t.me/{client.username}?start=yu3elk{original_payload}7", client)
            except Exception as e:
                client.LOGGER(__name__, client.name).warning(f"Shortener failed: {e}")
                return await message.reply("Couldn't generate short link.")

            short_photo = client.messages.get("SHORT_PIC", "")
            short_caption = client.messages.get("SHORT_MSG", "")
            tutorial_link = getattr(client, 'tutorial_link', "https://t.me/ANIME_X_FLEX/19")

            await client.send_photo(
                chat_id=message.chat.id,
                photo=short_photo,
                caption=short_caption,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("• ᴏᴘᴇɴ ʟɪɴᴋ", url=short_link)]
                    + ([InlineKeyboardButton("ᴛᴜᴛᴏʀɪᴀʟ •", url=tutorial_link)] if getattr(client, 'tutorial_enabled', True) and tutorial_link else []),
                    [
                        InlineKeyboardButton(" • ʙᴜʏ ᴘʀᴇᴍɪᴜᴍ •", url="https://t.me/Premium_Fliix/21")
                    ]
                ])
            )
            return  # prevent sending actual files

        # 6. Decode and prepare file IDs
        try:
            string = await decode(base64_string)
            argument = string.split("-")
            ids = []
            source_channel_id = None

            if argument[0] == "getc" and len(argument) == 2:
                # /custom_batch link: the exact message list is stored in MongoDB
                batch_doc = await client.mongodb.db["custom_batches"].find_one({"_id": argument[1]})
                if not batch_doc:
                    raise ValueError("custom batch not found")
                source_channel_id = int(batch_doc["chat_id"])
                ids = [int(i) for i in batch_doc["ids"]]

            elif len(argument) == 3:
                # Try to determine source channel from encoded multiplier
                encoded_start = int(argument[1])
                encoded_end = int(argument[2])
                
                # Try primary channel first
                primary_multiplier = abs(client.db)
                start_primary = int(encoded_start / primary_multiplier)
                end_primary = int(encoded_end / primary_multiplier)
                
                # Check if the division results in clean integers (meaning this channel was used for encoding)
                if encoded_start % primary_multiplier == 0 and encoded_end % primary_multiplier == 0:
                    source_channel_id = client.db
                    start = start_primary
                    end = end_primary
                    client.LOGGER(__name__, client.name).info(f"Decoded batch from primary channel {source_channel_id}: {start}-{end}")
                else:
                    # Try secondary channels
                    db_channels = getattr(client, 'db_channels', {})
                    for channel_id_str in db_channels.keys():
                        channel_id = int(channel_id_str)
                        channel_multiplier = abs(channel_id)
                        start_test = int(encoded_start / channel_multiplier)
                        end_test = int(encoded_end / channel_multiplier)
                        
                        if encoded_start % channel_multiplier == 0 and encoded_end % channel_multiplier == 0:
                            source_channel_id = channel_id
                            start = start_test
                            end = end_test
                            client.LOGGER(__name__, client.name).info(f"Decoded batch from secondary channel {source_channel_id}: {start}-{end}")
                            break
                    
                    # Fallback to primary if no match found
                    if source_channel_id is None:
                        source_channel_id = client.db
                        start = start_primary
                        end = end_primary
                
                ids = range(start, end + 1) if start <= end else list(range(start, end - 1, -1))

            elif len(argument) == 2:
                # Single message
                encoded_msg = int(argument[1])
                
                # Try primary channel first
                if hasattr(client, 'db_channel') and client.db_channel:
                    primary_multiplier = abs(client.db_channel.id)
                    msg_id_primary = int(encoded_msg / primary_multiplier)
                    
                    if encoded_msg % primary_multiplier == 0:
                        source_channel_id = client.db_channel.id
                        ids = [msg_id_primary]
                    else:
                        # Try secondary channels
                        db_channels = getattr(client, 'db_channels', {})
                        for channel_id_str in db_channels.keys():
                            channel_id = int(channel_id_str)
                            channel_multiplier = abs(channel_id)
                            msg_id_test = int(encoded_msg / channel_multiplier)
                            
                            if encoded_msg % channel_multiplier == 0:
                                source_channel_id = channel_id
                                ids = [msg_id_test]
                                break
                        
                        # Fallback to primary
                        if source_channel_id is None:
                            source_channel_id = client.db_channel.id if hasattr(client, 'db_channel') else client.db
                            ids = [msg_id_primary]
                else:
                    # Fallback for legacy compatibility
                    source_channel_id = client.db
                    ids = [int(encoded_msg / abs(client.db))]

        except Exception as e:
            client.LOGGER(__name__, client.name).warning(f"Error decoding base64: {e}")
            return await message.reply("⚠️ Invalid or expired link.")

        # 6.5 managed link: take a download slot (same person again = free; admins never use slots)
        slot_taken = False
        if managed_token and user_id not in client.admins:
            got = await links.reserve(client.mongodb.db, managed_token, user_id)
            if got != "ok":
                return await message.reply(_LINK_MSG.get(got, _LINK_MSG["missing"]))
            slot_taken = True

        # 7. Get messages from the specific source channel first
        temp_msg = await message.reply("Wait A Sec..")
        messages = []

        try:
            # Try to get messages from the identified source channel first
            if source_channel_id:
                client.LOGGER(__name__, client.name).info(f"Trying to get messages from source channel: {source_channel_id}")
                try:
                    msgs = await client.get_messages(
                        chat_id=source_channel_id,
                        message_ids=list(ids)
                    )
                    # Filter out None messages (deleted/not found)
                    valid_msgs = [msg for msg in msgs if msg is not None]
                    messages.extend(valid_msgs)
                    client.LOGGER(__name__, client.name).info(f"Found {len(valid_msgs)} messages from source channel {source_channel_id}")
                    
                    # If we didn't get all messages, try the fallback system
                    if len(valid_msgs) < len(list(ids)):
                        missing_ids = [mid for mid in ids if mid not in {msg.id for msg in valid_msgs}]
                        if missing_ids:
                            client.LOGGER(__name__, client.name).info(f"Missing {len(missing_ids)} messages, trying fallback system")
                            # Use the fallback system for missing messages
                            additional_messages = await get_messages(client, missing_ids)
                            messages.extend(additional_messages)
                            client.LOGGER(__name__, client.name).info(f"Found {len(additional_messages)} additional messages from fallback")
                except Exception as e:
                    client.LOGGER(__name__, client.name).warning(f"Error getting messages from source channel {source_channel_id}: {e}")
                    # Fallback to the multi-channel system
                    messages = await get_messages(client, ids)
            else:
                client.LOGGER(__name__, client.name).info("No specific source channel identified, using multi-channel fallback")
                # Use the multi-channel fallback system
                messages = await get_messages(client, ids)
        except Exception as e:
            await temp_msg.edit_text("Something went wrong!")
            client.LOGGER(__name__, client.name).warning(f"Error getting messages: {e}")
            return

        if not messages:
            if slot_taken:
                await links.release(client.mongodb.db, managed_token, user_id)
            return await temp_msg.edit("Couldn't find the files in the database.")
        await temp_msg.delete()

        yugen_msgs = []
        delivered = []  # source messages that reached the user (for the download counter)
        for n, msg in enumerate(messages, 1):
            caption = (
                client.messages.get('CAPTION', '').format(
                    previouscaption=msg.caption.html if msg.caption else msg.document.file_name
                ) if bool(client.messages.get('CAPTION', '')) and bool(msg.document)
                else ("" if not msg.caption else msg.caption.html)
            )
            plain_caption = caption
            caption = apply_custom_caption(getattr(client, 'custom_caption', ''), msg, caption, client.username,
                                           cleaner=getattr(client, 'caption_cleaner', None),
                                           mode=getattr(client, 'caption_mode', 'append'))
            caption = decorate(caption, getattr(client, 'caption_clean', {}) or {}, n)   # numbering / bullet
            plain_markup = msg.reply_markup if not client.disable_btn else None
            reply_markup = custom_buttons.combine(plain_markup, getattr(client, 'custom_buttons', []))

            try:
                copied_msg = await thumbnail.send_safe(
                    client, msg, message.from_user.id, caption, reply_markup, client.protect, plain_caption, plain_markup
                )
                yugen_msgs.append(copied_msg)
                delivered.append(msg)
                
            except FloodWait as e:
                await asyncio.sleep(getattr(e, "value", None) or getattr(e, "x", 0))
                copied_msg = await thumbnail.send_safe(
                    client, msg, message.from_user.id, caption, reply_markup, client.protect, plain_caption, plain_markup
                )
                yugen_msgs.append(copied_msg)
                delivered.append(msg)
            except Exception as e:
                client.LOGGER(__name__, client.name).warning(f"Failed to send message: {e}")
                pass
        await file_index.count_downloads(client, delivered)  # never raises
        if delivered:
            await stats.bump(client.mongodb.db, "delivered", len(delivered))
            await _qualify_referral(client, user_id, "file")
        elif slot_taken:
            await links.release(client.mongodb.db, managed_token, user_id)   # nothing reached the user: don't burn the slot
        # Deduct 1 credit per link unlock
        if not is_user_pro and not is_short_link:
            skip = await client.mongodb.should_skip_deduct(user_id)
    
            if skip:
                await client.mongodb.clear_skip_deduct(user_id)
            else:
                await client.mongodb.deduct_credit(user_id)
                await client.mongodb.add_used_credit(user_id)
                credits_left = await client.mongodb.get_credits(user_id)

                if credits_left <= 0:
                    await client.mongodb.user_data.update_one(
                        {'_id': user_id},
                        {'$set': {'verify_session': False}}
                    )

        # 8. Auto delete timer
        if messages and client.auto_del > 0:
            # Create transfer link for getting files again (original base64_string)
            transfer_link = original_payload
            
            # Start batch auto delete notification - single notification for all files
            asyncio.create_task(batch_auto_del_notification(
                bot_username=client.username,
                messages=yugen_msgs,
                delay_time=client.auto_del,
                transfer_link=transfer_link,
                chat_id=message.from_user.id,
                client=client
            ))
        return

    # 9. Normal start message
    else:
        buttons = [
            [
                InlineKeyboardButton("•ᴀʙᴏᴜᴛ•", callback_data="about"),
                InlineKeyboardButton("•ᴄʜᴀɴɴᴇʟs•", callback_data="channels")
            ],
            [
                InlineKeyboardButton("•ᴄʟᴏsᴇ•", callback_data="close")
            ]
        ]
        if user_id in client.admins:
            buttons.insert(0, [InlineKeyboardButton("⛩️ ꜱᴇᴛᴛɪɴɢꜱ ⛩️", callback_data="settings")])
        # Web panel: owner only (the panel can grant premium, which is owner-only in this bot).
        # Telegram accepts only https URLs for Web App buttons.
        if user_id == OWNER_ID and ADMIN_PASSWORD and ADMIN_PANEL_URL.startswith("https://"):
            buttons.insert(1, [InlineKeyboardButton("🖥 ᴄᴏɴᴛʀᴏʟ ᴘᴀɴᴇʟ", web_app=WebAppInfo(url=ADMIN_PANEL_URL))])

        photo = client.messages.get("START_PHOTO", "")
        start_caption = client.messages.get('START', 'Welcome, {mention}').format(
            first=message.from_user.first_name,
            last=message.from_user.last_name,
            username=None if not message.from_user.username else '@' + message.from_user.username,
            mention=message.from_user.mention,
            id=message.from_user.id,
            bot_mention=f"@{client.username}"
        )

        if photo:
            await client.send_photo(
                chat_id=message.chat.id,
                photo=photo,
                caption=start_caption,
                message_effect_id=MSG_EFFECT,
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        else:
            await client.send_message(
                chat_id=message.chat.id,
                text=start_caption,
                message_effect_id=MSG_EFFECT,
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        return

#===============================================================#

@Client.on_message(filters.command('request') & filters.private)
async def request_command(client: Client, message: Message):
    user_id = message.from_user.id
    is_admin = user_id in client.admins  # ✅ Fix this line
    is_user_premium = await client.mongodb.is_pro(user_id)

    if is_admin or user_id == OWNER_ID:
        await message.reply_text("🔹 **You are my sensei!**\nThis command is only for users.")
        return

    if not is_user_premium: 
        BUTTON_URL = "https://t.me/anujedits76"
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("💎 Upgrade to Premium", url=BUTTON_URL)]
        ])
        await message.reply(
            "❌ **You are not a premium user.**\nUpgrade to premium to access this feature.",
            reply_markup=reply_markup
        )
        return

    if len(message.command) < 2:
        await message.reply("⚠️ **Send me your request in this format:**\n`/request Your_Request_Here`")
        return

    requested = " ".join(message.command[1:])

    owner_message = (
        f"📩 **New Request from {message.from_user.mention}**\n\n"
        f"🆔 User ID: `{user_id}`\n"
        f"📝 Request: `{requested}`"
    )

    await client.send_message(OWNER_ID, owner_message)
    await message.reply("✅ **Thanks for your request!**\nYour request will be reviewed soon. Please wait.")

#===============================================================#

@Client.on_message(filters.command('profile') & filters.private)
async def my_plan(client: Client, message: Message):
    user_id = message.from_user.id
    is_admin = user_id in client.admins  # ✅ Fix here

    if is_admin or user_id == OWNER_ID:
        await message.reply_text("🔹 You're my sensei! This command is only for users.")
        return
    
    is_user_premium = await client.mongodb.is_pro(user_id)
    credits = await client.mongodb.get_credits(user_id)

    if is_user_premium:
        await message.reply_text(
            "**👤 Profile Information:**\n\n"
            "🔸 Ads: Disabled\n"
            "🔸 Plan: Premium\n"
            "🔸 Request: Enabled\n\n"
            "🌟 You're a Premium User!"
        )
    else:
        await message.reply_text(
            "**👤 Profile Information:**\n\n"
            "🔸 Ads: Enabled\n"
            "🔸 Plan: Free\n"
            "🔸 Request: Disabled\n"
            f"💳 Credits: {credits}\n"
            "🔓 Unlock Premium to get more benefits\n"
            "Contact: @anujedits76"
        )

#===============================================================#

@Client.on_message(filters.command('credits') & filters.private)
async def credits_command(client: Client, message: Message):
    user_id = message.from_user.id
    
    credits = await client.mongodb.get_credits(user_id)
    used = await client.mongodb.get_used_credits(user_id)


    text = (
        "<blockquote>📁 <b>𝖄𝖔𝖚𝖗 𝕮𝖗𝖊𝖉𝖎𝖙𝖘 𝕴𝖓𝖋𝖔𝖗𝖒𝖆𝖙𝖎𝖔𝖓</b></blockquote>\n\n"
        f"▪️ <b>Remaining Credits:</b> <code>{credits}</code>\n"
        f"▪️ <b>Total Used Credits:</b> <code>{used}</code>\n"
        "▪️ <b>Credits Per Verification:</b> <code>5</code>\n\n"
        "<i>Use /cplan to earn more credits!</i>"
    )

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 ᴄʀᴇᴅɪᴛ ᴘʟᴀɴꜱ", callback_data="show_cplan")],
        [InlineKeyboardButton("• ᴄʟᴏꜱᴇ •", callback_data="close")]
    ])

    await message.reply_text(text, reply_markup=buttons)

#===============================================================#

@Client.on_message(filters.command('cplan') & filters.private)
async def credit_plan(client: Client, message: Message):

    from config import CREDIT_PLANS
    from helper import payments
    from plugins.autopay import credit_plan_rows
    text = (
        "<blockquote>✦ <b>𝗖𝗥𝗘𝗗𝗜𝗧 𝗕𝗔𝗦𝗘𝗗 𝗣𝗟𝗔𝗡𝗦</b></blockquote>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "<blockquote>\n"
        + "\n".join(f"» {p['label']} : ₹{p['inr']:g}" for p in CREDIT_PLANS.values()) +
        "</blockquote>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        + ("<blockquote>✦ Tap a plan below to pay online. It is added automatically.</blockquote>" if payments.methods()
           else "<blockquote>✦ Contact @anujedits76 to Buy Credits</blockquote>")
    )

    buttons = InlineKeyboardMarkup(credit_plan_rows() + [
        [InlineKeyboardButton("• ᴄʟᴏꜱᴇ •", callback_data="close")]
    ])

    await message.reply_text(text, reply_markup=buttons)

#===============================================================#

@Client.on_message(filters.command("add_credit") & filters.private)
async def add_credit_command(client: Client, message: Message):

    if message.from_user.id not in client.admins:
        return await message.reply_text("❌ You are not allowed to use this command.")

    if len(message.command) != 3:
        return await message.reply_text(
            "<blockquote>⚠️ Usage:\n/add_credit user_id amount</blockquote>"
        )

    try:
        user_id = int(message.command[1])
        amount = int(message.command[2])
    except:
        return await message.reply_text("⚠️ Invalid User ID or Amount.")

    # Check if user exists
    if not await client.mongodb.present_user(user_id):
        await client.mongodb.add_user(user_id)

    await client.mongodb.add_credits(user_id, amount)
    await ledger.record(client.mongodb.db, user_id, amount, "admin", str(message.from_user.id))

    await message.reply_text(
        f"<blockquote>✅ Credits Added Successfully</blockquote>\n\n"
        f"👤 User ID: <code>{user_id}</code>\n"
        f"💳 Added Credits: <code>{amount}</code>"
    )

    try:
        await client.send_message(
            chat_id=user_id,
            text=(
                f"<blockquote>🎉 Credits Added to Your Account</blockquote>\n\n"
                f"💳 Amount: <code>{amount}</code>\n"
                f"Use /credits to check your balance."
            )
        )
    except:
        pass

#===============================================================#

@Client.on_message(filters.command('buy') & filters.private)
async def buy_command(client, message):

    photo = client.messages.get("PREMIUM_PLANS_PIC", "")

    text = (
        "<blockquote>✦ <b>𝗣𝗥𝗘𝗠𝗜𝗨𝗠 𝗣𝗟𝗔𝗡𝗦</b></blockquote>\n"
        "<blockquote expandable>◍ 𝟷 ᴍᴏɴᴛʜ: ₹𝟷𝟿𝟿\n"
        "◍ 𝟹 ᴍᴏɴᴛʜs: ₹𝟹𝟿𝟿 (ʙᴇsᴛ ᴠᴀʟᴜᴇ)\n"
        "◍ 𝟼 ᴍᴏɴᴛʜs: ₹𝟻𝟿𝟿 (ᴍᴏsᴛ ᴘᴏᴘᴜʟᴀʀ)\n"
        "◍ 𝟷𝟸 ᴍᴏɴᴛʜs: ₹𝟷,𝟷𝟿𝟿 (ᴛᴏᴘ ᴄʜᴏɪᴄᴇ)</blockquote>\n"
        "<blockquote>≡ ʟɪғᴇᴛɪᴍᴇ: ₹𝟸,𝟿𝟿𝟿 (ᴘᴀʏ ᴏɴᴄᴇ, ᴜsᴇ ғᴏʀᴇᴠᴇʀ)</blockquote>\n"
        "<blockquote>⧗ ᴘᴀʏᴍᴇɴᴛ ᴍᴇᴛʜᴏᴅs: ᴘᴀʏᴛᴍ, ɢᴘᴀʏ, ᴘʜᴏɴᴇᴘᴇ, ᴜᴘɪ & ǫʀ ᴄᴏᴅᴇ</blockquote>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "<blockquote expandable>◍ ᴘʀᴇᴍɪᴜᴍ ᴀᴅᴅᴇᴅ ᴀᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ ᴀғᴛᴇʀ ᴘᴀʏᴍᴇɴᴛ!\n◍ ᴀғᴛᴇʀ ᴘᴀʏᴍᴇɴᴛ ᴘʟᴇᴀsᴇ sᴇɴᴅ ᴜs sᴄʀᴇᴀɴsʜᴏᴛ ᴜsɪɴɢ /bought (ʀᴇᴘʟʏ ᴛᴏ sᴄʀᴇᴀɴsʜᴏᴛ)</blockquote>"
    )

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("Buy Premium", callback_data="premium_select")],
        [InlineKeyboardButton("• Close •", callback_data="close")]
    ])

    await message.reply_photo(photo=photo, caption=text, reply_markup=buttons)

#===============================================================#

@Client.on_message(filters.command('bought') & filters.private)
async def bought_command(client, message):

    user = message.from_user

    # ❌ if not replying
    if not message.reply_to_message:
        return await message.reply(
            "<blockquote>ᴜꜱᴇ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ ᴛᴏ ʀᴇᴘʟʏ ᴛᴏ ʏᴏᴜʀ ᴘᴀʏᴍᴇɴᴛ ꜱᴄʀᴇᴇɴꜱʜᴏᴛ</blockquote>"
        )

    replied = message.reply_to_message

    # ❌ if not photo
    if not replied.photo:
        return await message.reply(
            "<blockquote>ʀᴇᴘʟʏ ᴏɴʟʏ ᴛᴏ ᴘᴀʏᴍᴇɴᴛ ꜱᴄʀᴇᴇɴꜱʜᴏᴛ</blockquote>"
        )

    caption = (
        f"📥 <b>New Premium Purchase Request</b>\n"
        f"👤 User: {user.mention}\n"
        f"🆔 ID: <code>{user.id}</code>\n\n"
        f"Check Screenshot"
    )

    for admin in client.admins:
        try:
            await replied.copy(
                chat_id=admin,
                caption=caption
            )
        except:
            pass

    await message.reply(
        "<blockquote>✅ Screenshot Sent to Admin.\n"
        "Please wait for activation.</blockquote>"
    )
