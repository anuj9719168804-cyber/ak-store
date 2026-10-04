from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors.pyromod import ListenerTimeout
from config import FSUBS
from helper.helper_func import is_bot_admin

#===============================================================#

async def fsub(client, query):
    # Create a formatted list of channels with names and IDs
    if client.fsub_dict:
        channel_list = []
        for channel_id, channel_data in client.fsub_dict.items():
            channel_name = channel_data[0] if channel_data and len(channel_data) > 0 else "Unknown"
            request_status = "Request: ✅" if channel_data[2] else "Request: ❌"
            timer_status = f"Timer: {channel_data[3]}m" if channel_data[3] > 0 else "Timer: ∞"
            channel_list.append(f"• `{channel_name}` (`{channel_id}`) - {request_status}, {timer_status}")
        
        channels_display = "\n".join(channel_list)
    else:
        channels_display = "_No force subscription channels configured_"
    
    msg = f"""<blockquote>**Force Subscription Settings:**</blockquote>
**Configured Channels:**
{channels_display}

__Use the appropriate button below to add or remove a force subscription channel based on your needs!__
"""
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton('ᴀᴅᴅ ᴄʜᴀɴɴᴇʟ', 'add_fsub'), InlineKeyboardButton('ʀᴇᴍᴏᴠᴇ ᴄʜᴀɴɴᴇʟ', 'rm_fsub')],
        [InlineKeyboardButton('ᴛᴏɢɢʟᴇ ʀᴇǫᴜᴇsᴛ / ᴊᴏɪɴ ᴍᴏᴅᴇ', 'toggle_fsub_mode')],
        [InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'settings')]]
    )
    await query.message.edit_text(msg, reply_markup=reply_markup)
    return

#===============================================================#

@Client.on_callback_query(filters.regex('^add_fsub$'))
async def add_fsub(client: Client, query: CallbackQuery):
    await query.answer()
    ask_channel_info = await client.ask(query.from_user.id, "Send channel id(negative integer value), request boolean(yes/no/true/false), timers(integer without decimal)(to enable it keep it greator than 0 otherwise the invite link will not have any timer to invalidate it) seperated by a space in the next 60 seconds!\n<blockquote expandable>Eg: `-10089479289 yes 5`\n\n__It means `-10089479289` is the force sub channel id, `yes` means to enable request it means the link will be request link and only after user sends request to the channel bot will work for that user even if you do not accept his request or user is not a member, `5` means timer in minutes aftetr 5 minutes the invite link will be expired.__</blockquote>", filters=filters.text, timeout=60)
    try:
        channel_info = ask_channel_info.text.split()
        channel_id, request, timer = channel_info
        channel_id = int(channel_id)
        if channel_id in client.fsub_dict.keys():
            return await ask_channel_info.reply("**This channel id already exists in force sub list, remove it to change it's configuration!!**")
        val, res = await is_bot_admin(client, channel_id)
        if not val:
            return await ask_channel_info.reply(f"**Error:** `{res}`")
        if request.lower() in ('true', 'on', 'yes'):
            request = True
        elif request.lower() in ('false', 'off', 'no'):
            request = False
        else:
            raise Exception("Invalid request value or type.")
        if timer.isdigit():
            timer = int(timer)
        else:
            raise Exception("Timer is not a valid integer.")
        chat = await client.get_chat(channel_id)
        name = chat.title
        if timer > 0:
            client.fsub_dict[channel_id] = [name, None, request, timer]
        else:
            chat_link = await client.create_chat_invite_link(channel_id, creates_join_request=request)
            link = chat_link.invite_link
            client.fsub_dict[channel_id] = [name, link, request, timer]
        
        # Update req_channels list if request is enabled
        if request and channel_id not in client.req_channels:
            client.req_channels.append(channel_id)
            await client.mongodb.set_channels(client.req_channels)
        
        # Save to database for persistence across bot restarts
        await client.mongodb.add_fsub_channel(channel_id, client.fsub_dict[channel_id])
        
        await fsub(client, query)
        return await ask_channel_info.reply(f"__Channel with name: `{name.strip()}` is added as a force sub channel!!__")
    except Exception as e:
        return await ask_channel_info.reply(f"**Error:** `{e}`")
    
#===============================================================#

@Client.on_callback_query(filters.regex('^rm_fsub$'))
async def rm_fsub(client: Client, query: CallbackQuery):
    await query.answer()
    ask_channel_info = await client.ask(query.from_user.id, "Send channel id(negative integer value) in the next 60 seconds!", filters=filters.text, timeout=60)
    try:
        channel_id = int(ask_channel_info.text)
        if channel_id not in client.fsub_dict.keys():
            return await ask_channel_info.reply("**This channel id is not in force sub list!**")
        
        # Check if it was a request channel and remove from req_channels
        if channel_id in client.req_channels:
            client.req_channels.remove(channel_id)
            await client.mongodb.set_channels(client.req_channels)
        
        client.fsub_dict.pop(channel_id)
        
        # Remove from database for persistence across bot restarts
        await client.mongodb.remove_fsub_channel(channel_id)
        
        await fsub(client, query)
        return await ask_channel_info.reply(f"__Channel with id: `{channel_id}` has been removed as a force sub channel!!__")
    except Exception as e:
        return await ask_channel_info.reply(f"**Error:** `{e}`")


#===============================================================#

@Client.on_callback_query(filters.regex('^toggle_fsub_mode$'))
async def toggle_fsub_mode(client: Client, query: CallbackQuery):
    """Flip a force-sub channel between 'join request' and normal join (ported from Multi-FileStoreBot)."""
    if query.from_user.id not in client.admins:
        return await query.answer("Admins only.", show_alert=True)
    await query.answer()
    try:
        ask = await client.ask(query.from_user.id, "Send the channel id (negative integer) to switch between Request and Join mode, within 60 seconds.", filters=filters.text, timeout=60)
    except ListenerTimeout:
        return await query.message.reply("**Timeout, try again!**")
    try:
        channel_id = int(ask.text.strip())
        data = client.fsub_dict.get(channel_id)
        if not data:
            return await ask.reply("**This channel id is not in the force sub list!**")
        name, link, was_request, timer = data
        now_request = not was_request
        if timer == 0:  # fixed invite link: it has to be recreated with the new mode
            link = (await client.create_chat_invite_link(channel_id, creates_join_request=now_request)).invite_link
        client.fsub_dict[channel_id] = [name, link, now_request, timer]
        if now_request and channel_id not in client.req_channels:
            client.req_channels.append(channel_id)
        elif not now_request and channel_id in client.req_channels:
            client.req_channels.remove(channel_id)
        await client.mongodb.set_channels(client.req_channels)
        await client.mongodb.add_fsub_channel(channel_id, client.fsub_dict[channel_id])
        await fsub(client, query)
        note = "\n__This channel is also set in config.py FSUBS, which wins after a restart. Change it there too.__" if any(c[0] == channel_id for c in FSUBS) else ""
        return await ask.reply(f"__`{name.strip()}` is now in **{'Request' if now_request else 'Join'}** mode.__{note}")
    except Exception as e:
        return await ask.reply(f"**Error:** `{e}`")
