from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors.pyromod import ListenerTimeout
import html as _html
import os, shutil, tempfile
from config import OWNER_ID
import humanize

#===============================================================#

@Client.on_callback_query(filters.regex("^settings$"))
async def settings(client, query):
    # Count active force subscription channels by type
    total_fsub = len(client.fsub_dict)
    request_enabled = sum(1 for data in client.fsub_dict.values() if data[2])
    timer_enabled = sum(1 for data in client.fsub_dict.values() if data[3] > 0)
    
    # Count DB channels
    total_db_channels = len(getattr(client, 'db_channels', {}))
    primary_db = getattr(client, 'primary_db_channel', client.db)
    
    msg = f"""<blockquote>✦ sᴇᴛᴛɪɴɢs ᴏғ @{client.username}</blockquote>
›› **ꜰꜱᴜʙ ᴄʜᴀɴɴᴇʟs:** `{total_fsub}` (ʀᴇǫᴜᴇsᴛ: {request_enabled}, ᴛɪᴍᴇʀ: {timer_enabled})
›› **ᴅʙ ᴄʜᴀɴɴᴇʟs:** `{total_db_channels}` (ᴘʀɪᴍᴀʀʏ: `{primary_db}`)
›› **ᴀᴜᴛᴏ ᴅᴇʟᴇᴛᴇ ᴛɪᴍᴇʀ:** `{client.auto_del}`
›› **ᴘʀᴏᴛᴇᴄᴛ ᴄᴏɴᴛᴇɴᴛ:** `{"✓ ᴛʀᴜᴇ" if client.protect else "✗ ꜰᴀʟsᴇ"}`
›› **ᴘᴇʀᴍᴀɴᴇɴᴛ ʟɪɴᴋ:** `{"✓ ᴏɴ" if getattr(client, "permanent_link", False) else "✗ ᴏꜰꜰ"}`
›› **ᴅɪsᴀʙʟᴇ ʙᴜᴛᴛᴏɴ:** `{"✓ ᴛʀᴜᴇ" if client.disable_btn else "✗ ꜰᴀʟsᴇ"}`
›› **ʀᴇᴘʟʏ ᴛᴇxᴛ:** `{client.reply_text if client.reply_text else 'ɴᴏɴᴇ'}`
›› **ᴀᴅᴍɪɴs:** `{len(client.admins)}`
›› **sʜᴏʀᴛɴᴇʀ ᴜʀʟ:** `{getattr(client, 'short_url', 'ɴᴏᴛ sᴇᴛ')}`
›› **ᴛᴜᴛᴏʀɪᴀʟ ʟɪɴᴋ:** `{getattr(client, 'tutorial_link', 'ɴᴏᴛ sᴇᴛ')}`
›› **sᴛᴀʀᴛ ᴍᴇssᴀɢᴇ:**
<pre>{client.messages.get('START', 'ᴇᴍᴘᴛʏ')}</pre>
›› **sᴛᴀʀᴛ ɪᴍᴀɢᴇ:** `{bool(client.messages.get('START_PHOTO', ''))}`
›› **ꜰᴏʀᴄᴇ sᴜʙ ᴍᴇssᴀɢᴇ:**
<pre>{client.messages.get('FSUB', 'ᴇᴍᴘᴛʏ')}</pre>
›› **ꜰᴏʀᴄᴇ sᴜʙ ɪᴍᴀɢᴇ:** `{bool(client.messages.get('FSUB_PHOTO', ''))}`
›› **ᴀʙᴏᴜᴛ ᴍᴇssᴀɢᴇ:**
<pre>{client.messages.get('ABOUT', 'ᴇᴍᴘᴛʏ')}</pre>
›› **ʀᴇᴘʟʏ ᴍᴇssᴀɢᴇ:**
<pre>{client.reply_text}</pre>
    """
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton('ꜰꜱᴜʙ ᴄʜᴀɴɴᴇʟꜱ', 'fsub'), InlineKeyboardButton('ᴅʙ ᴄʜᴀɴɴᴇʟꜱ', 'db_channels')],
        [InlineKeyboardButton('ᴀᴅᴍɪɴꜱ', 'admins'), InlineKeyboardButton('ᴀᴜᴛᴏ ᴅᴇʟᴇᴛᴇ', 'auto_del')],
        [InlineKeyboardButton('ʜᴏᴍᴇ', 'home'), InlineKeyboardButton('›› ɴᴇxᴛ', 'settings_page_2')]
    ])
    await query.message.edit_text(msg, reply_markup=reply_markup)
    return

#===============================================================#

@Client.on_callback_query(filters.regex("^settings_page_2$"))
async def settings_page_2(client, query):
    # Count active force subscription channels by type
    total_fsub = len(client.fsub_dict)
    request_enabled = sum(1 for data in client.fsub_dict.values() if data[2])
    timer_enabled = sum(1 for data in client.fsub_dict.values() if data[3] > 0)
    
    # Count DB channels
    total_db_channels = len(getattr(client, 'db_channels', {}))
    primary_db = getattr(client, 'primary_db_channel', client.db)
    
    msg = f"""<blockquote>✦ sᴇᴛᴛɪɴɢs ᴏғ @{client.username}</blockquote>
›› **ꜰsᴜʙ ᴄʜᴀɴɴᴇʟs:** `{total_fsub}` (ʀᴇǫᴜᴇsᴛ: {request_enabled}, ᴛɪᴍᴇʀ: {timer_enabled})
›› **ᴅʙ ᴄʜᴀɴɴᴇʟs:** `{total_db_channels}` (ᴘʀɪᴍᴀʀʏ: `{primary_db}`)
›› **ᴀᴜᴛᴏ ᴅᴇʟᴇᴛᴇ ᴛɪᴍᴇʀ:** `{client.auto_del}`
›› **ᴘʀᴏᴛᴇᴄᴛ ᴄᴏɴᴛᴇɴᴛ:** `{"✓ ᴛʀᴜᴇ" if client.protect else "✗ ꜰᴀʟsᴇ"}`
›› **ᴘᴇʀᴍᴀɴᴇɴᴛ ʟɪɴᴋ:** `{"✓ ᴏɴ" if getattr(client, "permanent_link", False) else "✗ ᴏꜰꜰ"}`
›› **ᴅɪsᴀʙʟᴇ ʙᴜᴛᴛᴏɴ:** `{"✓ ᴛʀᴜᴇ" if client.disable_btn else "✗ ꜰᴀʟsᴇ"}`
›› **ʀᴇᴘʟʏ ᴛᴇxᴛ:** `{client.reply_text if client.reply_text else 'ɴᴏɴᴇ'}`
›› **ᴀᴅᴍɪɴs:** `{len(client.admins)}`
›› **sʜᴏʀᴛɴᴇʀ ᴜʀʟ:** `{getattr(client, 'short_url', 'ɴᴏᴛ sᴇᴛ')}`
›› **ᴛᴜᴛᴏʀɪᴀʟ ʟɪɴᴋ:** `{getattr(client, 'tutorial_link', 'ɴᴏᴛ sᴇᴛ')}`
›› **sᴛᴀʀᴛ ᴍᴇssᴀɢᴇ:**
<pre>{client.messages.get('START', 'ᴇᴍᴘᴛʏ')}</pre>
›› **sᴛᴀʀᴛ ɪᴍᴀɢᴇ:** `{bool(client.messages.get('START_PHOTO', ''))}`
›› **ꜰᴏʀᴄᴇ sᴜʙ ᴍᴇssᴀɢᴇ:**
<pre>{client.messages.get('FSUB', 'ᴇᴍᴘᴛʏ')}</pre>
›› **ꜰᴏʀᴄᴇ sᴜʙ ɪᴍᴀɢᴇ:** `{bool(client.messages.get('FSUB_PHOTO', ''))}`
›› **ᴀʙᴏᴜᴛ ᴍᴇssᴀɢᴇ:**
<pre>{client.messages.get('ABOUT', 'ᴇᴍᴘᴛʏ')}</pre>
›› **ʀᴇᴘʟʏ ᴍᴇssᴀɢᴇ:**
<pre>{client.reply_text}</pre>
    """
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton('ᴘʀᴏᴛᴇᴄᴛ ᴄᴏɴᴛᴇɴᴛ', 'protect'), InlineKeyboardButton('ᴘʜᴏᴛᴏs', 'photos')],
        [InlineKeyboardButton('ᴛᴇxᴛs', 'texts'), InlineKeyboardButton('sʜᴏʀᴛɴᴇʀ', 'shortner')],
        [InlineKeyboardButton('ᴄᴀᴘᴛɪᴏɴ', 'caption_cfg'), InlineKeyboardButton('ᴘᴇʀᴍᴀɴᴇɴᴛ ʟɪɴᴋ', 'permanent_link')],
        [InlineKeyboardButton('ᴛʜᴜᴍʙɴᴀɪʟ', 'thumb_cfg'), InlineKeyboardButton('ᴄᴀᴘᴛɪᴏɴ ᴄʟᴇᴀɴᴇʀ', 'cclean_cfg')],
        [InlineKeyboardButton('ꜰɪʟᴇ ʙᴜᴛᴛᴏɴs', 'cbtn_cfg')],
        [InlineKeyboardButton('‹ ᴘʀᴇᴠ', 'settings'), InlineKeyboardButton('ʜᴏᴍᴇ', 'home')]
    ])
    await query.message.edit_text(msg, reply_markup=reply_markup)
    return

#===============================================================#

@Client.on_callback_query(filters.regex("^fsub$"))
async def fsub(client, query):
    # Create a formatted list of channels with names and IDs
    if client.fsub_dict:
        channel_list = []
        for channel_id, channel_data in client.fsub_dict.items():
            channel_name = channel_data[0] if channel_data and len(channel_data) > 0 else "Unknown"
            request_status = "✓ ʀᴇѦᴜᴇsᴛ" if channel_data[2] else "✗ ʀᴇѦᴜᴇsᴛ"
            timer_status = f"ᴛɪᴍᴇʀ: {channel_data[3]}ᴍ" if channel_data[3] > 0 else "ᴛɪᴍᴇʀ: ∞"
            channel_list.append(f"• `{channel_name}` (`{channel_id}`) - {request_status}, {timer_status}")
        
        channels_display = "\n".join(channel_list)
    else:
        channels_display = "_ɴᴏ ꜰᴏʀᴄᴇ sᴜʙsᴄʀɪᴘᴛɪᴏɴ ᴄʜᴀɴɴᴇʟs ᴄᴏɴғɪɢᴜʀᴇᴅ_"
    
    msg = f"""<blockquote>✦ ꜰᴏʀᴄᴇ sᴜʙsᴄʀɪᴘᴛɪᴏɴ sᴇᴛᴛɪɴɢs</blockquote>
›› **ᴄᴏɴғɪɢᴜʀᴇᴅ ᴄʜᴀɴɴᴇʟs:**
{channels_display}

__ᴜsᴇ ᴛʜᴇ ᴀᴘᴘʀᴏᴘʀɪᴀᴛᴇ ʙᴜᴛᴛᴏɴ ʙᴇʟᴏᴡ ᴛᴏ ᴀᴅᴅ ᴏʀ ʀᴇᴍᴏᴠᴇ ᴀ ꜰᴏʀᴄᴇ sᴜʙsᴄʀɪᴘᴛɪᴏɴ ᴄʜᴀɴɴᴇʟ ʙᴀsᴇᴅ ᴏɴ ʏᴏᴜʀ ɴᴇᴇᴅs!__
"""
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton('›› ᴀᴅᴅ ᴄʜᴀɴɴᴇʟ', 'add_fsub'), InlineKeyboardButton('›› ʀᴇᴍᴏᴠᴇ ᴄʜᴀɴɴᴇʟ', 'rm_fsub')],
        [InlineKeyboardButton('›› ᴛᴏɢɢʟᴇ ʀᴇǫᴜᴇsᴛ / ᴊᴏɪɴ ᴍᴏᴅᴇ', 'toggle_fsub_mode')],
        [InlineKeyboardButton('‹ ʙᴀᴄᴋ', 'settings')]]
    )
    await query.message.edit_text(msg, reply_markup=reply_markup)
    return

#===============================================================#

@Client.on_callback_query(filters.regex("^db_channels$"))
async def db_channels(client, query):
    if not query.from_user.id in client.admins:
        return await query.answer('✗ ᴏɴʟʏ ᴀᴅᴍɪɴs ᴄᴀɴ ᴜsᴇ ᴛʜɪs!', show_alert=True)
    
    # Create a formatted list of DB channels
    db_channels = getattr(client, 'db_channels', {})
    if db_channels:
        channel_list = []
        for channel_id_str, channel_data in db_channels.items():
            channel_name = channel_data.get('name', 'Unknown')
            is_primary = "✓ ᴘʀɪᴍᴀʀʏ" if channel_data.get('is_primary', False) else "• sᴇᴄᴏɴᴅᴀʀʏ"
            is_active = "✓ ᴀᴄᴛɪᴠᴇ" if channel_data.get('is_active', True) else "✗ ɪɴᴀᴄᴛɪᴠᴇ"
            channel_list.append(f"• `{channel_name}` (`{channel_id_str}`)\n  {is_primary} | {is_active}")
        
        channels_display = "\n\n".join(channel_list)
    else:
        channels_display = "_ɴᴏ ᴅᴀᴛᴀʙᴀsᴇ ᴄʜᴀɴɴᴇʟs ᴄᴏɴғɪɢᴜʀᴇᴅ_"
    
    # Show current primary DB channel
    primary_db = getattr(client, 'primary_db_channel', client.db)
    
    msg = f"""<blockquote>✦ ᴅᴀᴛᴀʙᴀsᴇ ᴄʜᴀɴɴᴇʟs sᴇᴛᴛɪɴɢs</blockquote>
›› **ᴄᴜʀʀᴇɴᴛ ᴘʀɪᴍᴀʀʏ ᴅʙ:** `{primary_db}`
›› **ᴛᴏᴛᴀʟ ᴅʙ ᴄʜᴀɴɴᴇʟs:** `{len(db_channels)}`

**ᴄᴏɴғɪɢᴜʀᴇᴅ ᴄʜᴀɴɴᴇʟs:**
{channels_display}

__ᴜsᴇ ᴛʜᴇ ᴀᴘᴘʀᴏᴘʀɪᴀᴛᴇ ʙᴜᴛᴛᴏɴ ʙᴇʟᴏᴡ ᴛᴏ ᴍᴀɴᴀɢᴇ ʏᴏᴜʀ ᴅᴀᴛᴀʙᴀsᴇ ᴄʜᴀɴɴᴇʟs!__
"""
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton('›› ᴀᴅᴅ ᴅʙ ᴄʜᴀɴɴᴇʟ', 'add_db_channel'), InlineKeyboardButton('›› ʀᴇᴍᴏᴠᴇ ᴅʙ ᴄʜᴀɴɴᴇʟ', 'rm_db_channel')],
        [InlineKeyboardButton('›› sᴇᴛ ᴘʀɪᴍᴀʀʏ', 'set_primary_db'), InlineKeyboardButton('›› sᴛᴀᴛᴜs', 'toggle_db_status')],
        [InlineKeyboardButton('‹ ʙᴀᴄᴋ', 'settings')]
    ])
    await query.message.edit_text(msg, reply_markup=reply_markup)
    return

#===============================================================#

@Client.on_callback_query(filters.regex("^add_db_channel$"))
async def add_db_channel(client, query):
    if not query.from_user.id in client.admins:
        return await query.answer('✗ ᴏɴʟʏ ᴀᴅᴍɪɴs ᴄᴀɴ ᴜsᴇ ᴛʜɪs!', show_alert=True)
    
    await query.answer()
    msg = f"""<blockquote>✦ ᴀᴅᴅ ɴᴇᴡ ᴅᴀᴛᴀʙᴀsᴇ ᴄʜᴀɴɴᴇʟ</blockquote>
›› **ᴄᴜʀʀᴇɴᴛ ᴅʙ ᴄʜᴀɴɴᴇʟs:** `{len(getattr(client, 'db_channels', {}))}`

__sᴇɴᴅ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ ɪᴅ (ɴᴇɢᴀᴛɪᴠᴇ ɪɴᴛᴇɢᴇʀ ᴠᴀʟᴜᴇ) ᴏғ ᴛʜᴇ ᴅᴀᴛᴀʙᴀsᴇ ᴄʜᴀɴɴᴇʟ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴀᴅᴅ ɪɴ ᴛʜᴇ ɴᴇxᴛ 60 sᴇᴄᴏɴᴅs!__

**ᴇxᴀᴍᴘʟᴇ:** `-1001234567675`
**ɴᴏᴛᴇ:** ᴍᴀᴋᴇ sᴜʀᴇ ᴛʜᴇ ʙᴏᴛ ɪs ᴀᴅᴍɪɴ ɪɴ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ!"""
    
    await query.message.edit_text(msg)
    try:
        res = await client.listen(user_id=query.from_user.id, filters=filters.text, timeout=60)
        channel_id_text = res.text.strip()
        
        if not channel_id_text.lstrip('-').isdigit():
            return await query.message.edit_text("**✗ ɪɴᴠᴀʟɪᴅ ᴄʜᴀɴɴᴇʟ ɪᴅ! ᴘʟᴇᴀsᴇ sᴇɴᴅ ᴀ ᴠᴀʟɪᴅ ɴᴇɢᴀᴛɪᴠᴇ ɪɴᴛᴇɢᴇʀ.**", 
                                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ ʙᴀᴄᴋ', 'db_channels')]]))
        
        channel_id = int(channel_id_text)
        
        # Check if channel already exists
        db_channels = getattr(client, 'db_channels', {})
        if str(channel_id) in db_channels:
            return await query.message.edit_text(f"**✗ ᴄʜᴀɴɴᴇʟ `{channel_id}` ɪs ᴀʟʀᴇᴀᴅʏ ᴀᴅᴅᴇᴅ ᴀs ᴀ ᴅʙ ᴄʜᴀɴɴᴇʟ!**", 
                                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ ʙᴀᴄᴋ', 'db_channels')]]))
        
        # Verify bot can access the channel
        try:
            chat = await client.get_chat(channel_id)
            test_msg = await client.send_message(chat_id=channel_id, text="ᴛᴇsᴛɪɴɢ ᴅʙ ᴄʜᴀɴɴᴇʟ ᴀᴄᴄᴇss - @Okabe_xRintarou")
            await test_msg.delete()
            
            # Add channel to database
            channel_data = {
                'name': chat.title,
                'is_primary': len(db_channels) == 0,  # First channel becomes primary
                'is_active': True,
                'added_by': query.from_user.id
            }
            
            await client.mongodb.add_db_channel(channel_id, channel_data)
            
            # Update client attributes
            if not hasattr(client, 'db_channels'):
                client.db_channels = {}
            client.db_channels[str(channel_id)] = channel_data
            
            # Set as primary if it's the first channel
            if channel_data['is_primary']:
                client.primary_db_channel = channel_id
                await client.mongodb.set_primary_db_channel(channel_id)
            
            await query.message.edit_text(f"""**✓ ᴅᴀᴛᴀʙᴀsᴇ ᴄʜᴀɴɴᴇʟ ᴀᴅᴅᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!**

›› **ᴄʜᴀɴɴᴇʟ:** `{chat.title}`
›› **ɪᴅ:** `{channel_id}`
›› **sᴛᴀᴛᴜs:** {'ᴘʀɪᴍᴀʀʏ' if channel_data['is_primary'] else 'sᴇᴄᴏɴᴅᴀʀʏ'}""", 
                                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ ʙᴀᴄᴋ', 'db_channels')]]))
        
        except Exception as e:
            await query.message.edit_text(f"""**✗ ᴇʀʀᴏʀ ᴀᴄᴄᴇssɪɴɢ ᴄʜᴀɴɴᴇʟ!**

›› **ᴇʀʀᴏʀ:** `{str(e)}`

**ᴘʟᴇᴀsᴇ ᴍᴀᴋᴇ sᴜʀᴇ:**
• ʙᴏᴛ ɪs ᴀᴅᴍɪɴ ɪɴ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ
• ᴄʜᴀɴɴᴇʟ ɪᴅ ɪs ᴄᴏʀʀᴇᴄᴛ
• ᴄʜᴀɴɴᴇʟ ᴇxɪsᴛs""", 
                                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ ʙᴀᴄᴋ', 'db_channels')]]))
    
    except Exception as e:
        await query.message.edit_text(f"""**✗ ᴛɪᴍᴇᴏᴜᴛ ᴏʀ ᴇʀʀᴏʀ ᴏᴄᴄᴜʀʀᴇᴅ!**

›› **ᴇʀʀᴏʀ:** `{str(e)}`""", 
                                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('‹ ʙᴀᴄᴋ', 'db_channels')]]))

#===============================================================#

@Client.on_callback_query(filters.regex("^rm_db_channel$"))
async def rm_db_channel(client, query):
    if not query.from_user.id in client.admins:
        return await query.answer('❌ ᴏɴʟʏ ᴀᴅᴍɪɴs ᴄᴀɴ ᴜsᴇ ᴛʜɪs!', show_alert=True)
    
    await query.answer()
    db_channels = getattr(client, 'db_channels', {})
    
    if not db_channels:
        return await query.message.edit_text("**❌ No database channels to remove!**", 
                                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'db_channels')]]))
    
    msg = f"""<blockquote>**Remove Database Channel:**</blockquote>
**Available Channels:**
"""
    
    for channel_id_str, channel_data in db_channels.items():
        channel_name = channel_data.get('name', 'Unknown')
        is_primary = " (Primary)" if channel_data.get('is_primary', False) else ""
        msg += f"• `{channel_name}` - `{channel_id_str}`{is_primary}\n"
    
    msg += "\n__Send the channel ID you want to remove in the next 60 seconds!__"
    
    await query.message.edit_text(msg)
    try:
        res = await client.listen(user_id=query.from_user.id, filters=filters.text, timeout=60)
        channel_id_text = res.text.strip()
        
        if not channel_id_text.lstrip('-').isdigit():
            return await query.message.edit_text("**❌ Invalid channel ID!**", 
                                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'db_channels')]]))
        
        channel_id = int(channel_id_text)
        
        if str(channel_id) not in db_channels:
            return await query.message.edit_text(f"**❌ Channel `{channel_id}` is not in the DB channels list!**", 
                                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'db_channels')]]))
        
        # Check if trying to remove primary channel
        if db_channels[str(channel_id)].get('is_primary', False) and len(db_channels) > 1:
            return await query.message.edit_text("**❌ Cannot remove primary channel!**\n\n__Please set another channel as primary first.__", 
                                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'db_channels')]]))
        
        # Remove from database and client
        channel_name = db_channels[str(channel_id)].get('name', 'Unknown')
        await client.mongodb.remove_db_channel(channel_id)
        del client.db_channels[str(channel_id)]
        
        await query.message.edit_text(f"**✅ Database channel removed successfully!**\n\n**Removed:** `{channel_name}` (`{channel_id}`)", 
                                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'db_channels')]]))
    
    except Exception as e:
        await query.message.edit_text(f"**❌ Timeout or error occurred!**\n\n**Error:** `{str(e)}`", 
                                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'db_channels')]]))

#===============================================================#

@Client.on_callback_query(filters.regex("^set_primary_db$"))
async def set_primary_db(client, query):
    if not query.from_user.id in client.admins:
        return await query.answer('❌ ᴏɴʟʏ ᴀᴅᴍɪɴs ᴄᴀɴ ᴜsᴇ ᴛʜɪs!', show_alert=True)
    
    await query.answer()
    db_channels = getattr(client, 'db_channels', {})
    
    if not db_channels:
        return await query.message.edit_text("**❌ No database channels available!**", 
                                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'db_channels')]]))
    
    msg = f"""<blockquote>**Set Primary Database Channel:**</blockquote>
**Available Channels:**
"""
    
    for channel_id_str, channel_data in db_channels.items():
        channel_name = channel_data.get('name', 'Unknown')
        is_primary = " (Current Primary)" if channel_data.get('is_primary', False) else ""
        msg += f"• `{channel_name}` - `{channel_id_str}`{is_primary}\n"
    
    msg += "\n__Send the channel ID you want to set as primary in the next 60 seconds!__"
    
    await query.message.edit_text(msg)
    try:
        res = await client.listen(user_id=query.from_user.id, filters=filters.text, timeout=60)
        channel_id_text = res.text.strip()
        
        if not channel_id_text.lstrip('-').isdigit():
            return await query.message.edit_text("**❌ Invalid channel ID!**", 
                                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'db_channels')]]))
        
        channel_id = int(channel_id_text)
        
        if str(channel_id) not in db_channels:
            return await query.message.edit_text(f"**❌ Channel `{channel_id}` is not in the DB channels list!**", 
                                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'db_channels')]]))
        
        # Set as primary
        await client.mongodb.set_primary_db_channel(channel_id)
        
        # Update client attributes
        for ch_id, ch_data in client.db_channels.items():
            ch_data['is_primary'] = (int(ch_id) == channel_id)
        
        client.primary_db_channel = channel_id
        client.db = channel_id  # Update current db reference
        
        channel_name = db_channels[str(channel_id)].get('name', 'Unknown')
        await query.message.edit_text(f"**✅ Primary database channel updated!**\n\n**New Primary:** `{channel_name}` (`{channel_id}`)", 
                                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'db_channels')]]))
    
    except Exception as e:
        await query.message.edit_text(f"**❌ Timeout or error occurred!**\n\n**Error:** `{str(e)}`", 
                                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'db_channels')]]))

#===============================================================#

@Client.on_callback_query(filters.regex("^toggle_db_status$"))
async def toggle_db_status(client, query):
    if not query.from_user.id in client.admins:
        return await query.answer('❌ ᴏɴʟʏ ᴀᴅᴍɪɴs ᴄᴀɴ ᴜsᴇ ᴛʜɪs!', show_alert=True)
    
    await query.answer()
    db_channels = getattr(client, 'db_channels', {})
    
    if not db_channels:
        return await query.message.edit_text("**❌ No database channels available!**", 
                                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'db_channels')]]))
    
    msg = f"""<blockquote>**Toggle Channel Status:**</blockquote>
**Available Channels:**
"""
    
    for channel_id_str, channel_data in db_channels.items():
        channel_name = channel_data.get('name', 'Unknown')
        status = "🟢 ᴀᴄᴛɪᴠᴇ" if channel_data.get('is_active', True) else "🔴 ɪɴᴀᴄᴛɪᴠᴇ"
        msg += f"• `{channel_name}` - `{channel_id_str}` ({status})\n"
    
    msg += "\n__Send the channel ID you want to ᴀᴄᴛɪᴠᴇ/ɪɴᴀᴄᴛɪᴠᴇ status for in the next 60 seconds!__"
    
    await query.message.edit_text(msg)
    try:
        res = await client.listen(user_id=query.from_user.id, filters=filters.text, timeout=60)
        channel_id_text = res.text.strip()
        
        if not channel_id_text.lstrip('-').isdigit():
            return await query.message.edit_text("**❌ Invalid channel ID!**", 
                                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'db_channels')]]))
        
        channel_id = int(channel_id_text)
        
        if str(channel_id) not in db_channels:
            return await query.message.edit_text(f"**❌ Channel `{channel_id}` is not in the DB channels list!**", 
                                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'db_channels')]]))
        
        # Toggle status
        new_status = await client.mongodb.toggle_db_channel_status(channel_id)
        
        if new_status is not None:
            # Update client attributes
            client.db_channels[str(channel_id)]['is_active'] = new_status
            
            channel_name = db_channels[str(channel_id)].get('name', 'Unknown')
            status_text = "🟢 Active" if new_status else "🔴 Inactive"
            await query.message.edit_text(f"**✅ Channel status updated!**\n\n**Channel:** `{channel_name}` (`{channel_id}`)\n**New Status:** {status_text}", 
                                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'db_channels')]]))
        else:
            await query.message.edit_text("**❌ Failed to toggle channel status!**", 
                                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'db_channels')]]))
    
    except Exception as e:
        await query.message.edit_text(f"**❌ Timeout or error occurred!**\n\n**Error:** `{str(e)}`", 
                                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'db_channels')]]))

#===============================================================#

@Client.on_callback_query(filters.regex("^admins$"))
async def admins(client, query):
    if not (query.from_user.id==OWNER_ID):
        return await query.answer('This can only be used by owner.')
    msg = f"""<blockquote>**Admin Settings:**</blockquote>
**Admin User IDs:** {", ".join(f"`{a}`" for a in client.admins)}

__Use the appropriate button below to add or remove an admin based on your needs!__
"""
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton('ᴀᴅᴅ ᴀᴅᴍɪɴ', 'add_admin'), InlineKeyboardButton('ʀᴇᴍᴏᴠᴇ ᴀᴅᴍɪɴ', 'rm_admin')],
        [InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'settings')]]
    )
    await query.message.edit_text(msg, reply_markup=reply_markup)
    return

#===============================================================#

@Client.on_callback_query(filters.regex("^photos$"))
async def photos(client, query):
    msg = f"""<blockquote>**Force Subscription Settings:**</blockquote>
**Start Photo:** `{client.messages.get("START_PHOTO", "None")}`
**Force Sub Photo:** `{client.messages.get('FSUB_PHOTO', 'None')}`

__Use the appropriate button below to add or remove any admin based on your needs!__
"""
    reply_markup = InlineKeyboardMarkup([
    [
        InlineKeyboardButton(
            ('ꜱᴇᴛ' if client.messages.get("START_PHOTO", "") == "" else 'ᴄʜᴀɴɢᴇ') + '\nꜱᴛᴀʀᴛ ᴘʜᴏᴛᴏ', 
            callback_data='add_start_photo'
        ),
        InlineKeyboardButton(
            ('ꜱᴇᴛ' if client.messages.get("FSUB_PHOTO", "") == "" else 'ᴄʜᴀɴɢᴇ') + '\nꜰꜱᴜʙ ᴘʜᴏᴛᴏ', 
            callback_data='add_fsub_photo'
        )
    ],
    [
        InlineKeyboardButton('ʀᴇᴍᴏᴠᴇ\nꜱᴛᴀʀᴛ ᴘʜᴏᴛᴏ', callback_data='rm_start_photo'),
        InlineKeyboardButton('ʀᴇᴍᴏᴠᴇ\nꜰꜱᴜʙ ᴘʜᴏᴛᴏ', callback_data='rm_fsub_photo')
    ],
    [InlineKeyboardButton('◂ ʙᴀᴄᴋ', callback_data='settings')]

    ])
    await query.message.edit_text(msg, reply_markup=reply_markup)
    return

#===============================================================#

@Client.on_callback_query(filters.regex("^protect$"))
async def protect(client, query):
    client.protect = False if client.protect else True
    try:
        await client.mongodb.update_bot_setting("protect", client.protect)
    except Exception as e:
        client.LOGGER(__name__, client.name).warning(f"Could not save protect setting: {e}")
    return await settings(client, query)

#===============================================================#

@Client.on_callback_query(filters.regex("^permanent_link$"))
async def permanent_link_toggle(client, query):
    """Switch generated links between t.me/<bot>?start=... and the Cloudflare Worker URL."""
    from config import BACKEND_API_URL
    if query.from_user.id not in client.admins:
        return await query.answer("Admins only.", show_alert=True)
    if not BACKEND_API_URL:
        return await query.answer(
            "Set BACKEND_API_URL (your Cloudflare Worker URL, see backend/README.md) and restart first.",
            show_alert=True)
    client.permanent_link = not getattr(client, "permanent_link", False)
    try:
        await client.mongodb.update_bot_setting("permanent_link", client.permanent_link)
    except Exception as e:
        client.LOGGER(__name__, client.name).warning(f"Could not save permanent link setting: {e}")
    await query.answer("Permanent link: " + ("ON" if client.permanent_link else "OFF"))
    return await settings_page_2(client, query)

#===============================================================#

@Client.on_callback_query(filters.regex("^auto_del$"))
async def auto_del(client, query):
    msg = f"""<blockquote>**Change Auto Delete Time:**</blockquote>
**Current Timer:** `{client.auto_del}`

__Enter new integer value of auto delete timer, keep 0 to disable auto delete and -1 to as it was, or wait for 60 second timeout to be comoleted!__
"""
    await query.answer()
    await query.message.edit_text(msg)
    try:
        res = await client.listen(user_id=query.from_user.id, filters=filters.text, timeout=60)
        timer = res.text.strip()
        if timer.isdigit() or (timer.startswith('+' or '-') and timer[1:].isdigit()):
            timer = int(timer)
            if timer >= 0:
                client.auto_del = timer
                try:
                    await client.mongodb.update_bot_setting("auto_del", timer)
                except Exception as e:
                    client.LOGGER(__name__, client.name).warning(f"Could not save auto delete setting: {e}")
                return await query.message.edit_text(f'**Auto Delete timer vakue changed to {timer} seconds!**', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'settings')]]))
            else:
                return await query.message.edit_text("**There is no change done in auto delete timer!**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'settings')]]))
        else:
            return await query.message.edit_text("**This is not an integer value!!**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'settings')]]))
    except ListenerTimeout:
        return await query.message.edit_text("**Timeout, try again!**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'settings')]]))

#===============================================================#

@Client.on_callback_query(filters.regex("^texts$"))
async def texts(client, query):
    msg = f"""<blockquote>**Text Configuration:**</blockquote>
**Start Message:**
<pre>{client.messages.get('START', 'Empty')}</pre>
**Force Sub Message:**
<pre>{client.messages.get('FSUB', 'Empty')}</pre>
**About Message:**
<pre>{client.messages.get('ABOUT', 'Empty')}</pre>
**Reply Message:**
<pre>{client.messages.get('CHANNELS', 'Empty')}</pre>
**Reply Message:**
<pre>{client.reply_text}</pre>
    """
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(f'ꜱᴛᴀʀᴛ ᴛᴇxᴛ', 'start_txt'), InlineKeyboardButton(f'ꜰꜱᴜʙ ᴛᴇxᴛ', 'fsub_txt')],
        [InlineKeyboardButton('ʀᴇᴘʟʏ ᴛᴇxᴛ', 'reply_txt'), InlineKeyboardButton('ᴀʙᴏᴜᴛ ᴛᴇxᴛ', 'about_txt')],
        [InlineKeyboardButton('ᴄʜᴀɴɴᴇʟ ᴛᴇxᴛ', 'channels_txt')],
        [InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'settings')]]
    )
    await query.message.edit_text(msg, reply_markup=reply_markup)
    return

#===============================================================#

@Client.on_callback_query(filters.regex('^rm_start_photo$'))
async def rm_start_photo(client, query):
    client.messages['START_PHOTO'] = ''
    await client.mongodb.update_message_setting('START_PHOTO', '')
    await query.answer()
    await photos(client, query)

#===============================================================#

@Client.on_callback_query(filters.regex('^rm_fsub_photo$'))
async def rm_fsub_photo(client, query):
    client.messages['FSUB_PHOTO'] = ''
    await client.mongodb.update_message_setting('FSUB_PHOTO', '')
    await query.answer()
    await photos(client, query)

#===============================================================#

@Client.on_callback_query(filters.regex("^add_start_photo$"))
async def add_start_photo(client, query):
    msg = f"""<blockquote>**Change Start Image:**</blockquote>
**Current Start Image:** `{client.messages.get('START_PHOTO', '')}`

__Enter new link of start image or send the photo, or wait for 60 second timeout to be comoleted!__
"""
    await query.answer()
    await query.message.edit_text(msg)
    try:
        res = await client.listen(user_id=query.from_user.id, filters=(filters.text|filters.photo), timeout=60)
        if res.text and res.text.startswith(('https://', 'http://')):
            client.messages['START_PHOTO'] = res.text
            await client.mongodb.update_message_setting('START_PHOTO', res.text)
            return await query.message.edit_text("**This link has been set at the place of start photo!!**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'photos')]]))
        elif res.photo:
            client.messages['START_PHOTO'] = res.photo.file_id
            await client.mongodb.update_message_setting('START_PHOTO', res.photo.file_id)
            return await query.message.edit_text("**This image has been set as the starting image!!**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'photos')]]))
        else:
            return await query.message.edit_text("**Invalid Photo or Link format!!**\n__If you're sending the link of any image it must starts with either 'http' or 'https'!__", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'photos')]]))
    except ListenerTimeout:
        return await query.message.edit_text("**Timeout, try again!**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'photos')]]))

#===============================================================#

@Client.on_callback_query(filters.regex("^add_fsub_photo$"))
async def add_fsub_photo(client, query):
    msg = f"""<blockquote>**Change Force Sub Image:**</blockquote>
**Current Force Sub Image:** `{client.messages.get('FSUB_PHOTO', '')}`

__Enter new link of fsub image or send the photo, or wait for 60 second timeout to be comoleted!__
"""
    await query.answer()
    await query.message.edit_text(msg)
    try:
        res = await client.listen(user_id=query.from_user.id, filters=(filters.text|filters.photo), timeout=60)
        if res.text and res.text.startswith(('https://', 'http://')):
            client.messages['FSUB_PHOTO'] = res.text
            await client.mongodb.update_message_setting('FSUB_PHOTO', res.text)
            return await query.message.edit_text("**This link has been set at the place of fsub photo!!**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'photos')]]))
        elif res.photo:
            client.messages['FSUB_PHOTO'] = res.photo.file_id
            await client.mongodb.update_message_setting('FSUB_PHOTO', res.photo.file_id)
            return await query.message.edit_text("**This image has been set as the force sub image!!**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'photos')]]))
        else:
            return await query.message.edit_text("**Invalid Photo or Link format!!**\n__If you're sending the link of any image it must starts with either 'http' or 'https'!__", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'photos')]]))
    except ListenerTimeout:
        return await query.message.edit_text("**Timeout, try again!**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'photos')]]))

#===============================================================#

@Client.on_callback_query(filters.regex("^show_cplan$"))
async def show_cplan_callback(client, query):
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

    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(credit_plan_rows() + [
            [InlineKeyboardButton("• ᴄʟᴏꜱᴇ •", callback_data="close")]
        ])
    )

#===============================================================#
# Custom caption (ported from Multi-FileStoreBot)

@Client.on_callback_query(filters.regex("^caption_cfg$"))
async def caption_cfg(client, query):
    if query.from_user.id not in client.admins:
        return await query.answer("Admins only.", show_alert=True)
    from helper.caption_logic import PLACEHOLDERS
    current = getattr(client, "custom_caption", "")
    msg = f"""<blockquote>**Custom Caption:**</blockquote>
**Current:**
<pre>{current or 'Not set'}</pre>

**Mode:** `{getattr(client, "caption_mode", "append").upper()}`
__APPEND: added under the file's own caption. REPLACE: sent instead of it (put `{{file_caption}}` in the template to keep the original text).__
**Placeholders:** `{PLACEHOLDERS}`
"""
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton('sᴇᴛ / ᴄʜᴀɴɢᴇ', 'set_caption'), InlineKeyboardButton('ʀᴇᴍᴏᴠᴇ', 'rm_caption')],
        [InlineKeyboardButton(f"ᴍᴏᴅᴇ: {getattr(client, 'caption_mode', 'append')}", 'caption_mode')],
        [InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'settings_page_2')]
    ])
    await query.message.edit_text(msg, reply_markup=markup)


@Client.on_callback_query(filters.regex("^caption_mode$"))
async def caption_mode(client, query):
    if query.from_user.id not in client.admins:
        return await query.answer("Admins only.", show_alert=True)
    client.caption_mode = "replace" if getattr(client, "caption_mode", "append") == "append" else "append"
    await client.mongodb.update_bot_setting("caption_mode", client.caption_mode)
    await query.answer(f"Caption mode: {client.caption_mode}")
    return await caption_cfg(client, query)


@Client.on_callback_query(filters.regex("^set_caption$"))
async def set_caption(client, query):
    if query.from_user.id not in client.admins:
        return await query.answer("Admins only.", show_alert=True)
    back = InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'caption_cfg')]])
    await query.answer()
    await query.message.edit_text("**Send the new caption template (HTML allowed), or wait 60s to cancel.**\n\n"
                                  "Example: `<b>{file_name}</b>\\nSize: {size} | {quality} | {language}`")
    try:
        res = await client.listen(user_id=query.from_user.id, filters=filters.text, timeout=60)
    except ListenerTimeout:
        return await query.message.edit_text("**Timeout, try again!**", reply_markup=back)
    text = (res.text.html if res.text else "").strip()
    if not text or text.startswith("/"):
        return await query.message.edit_text("**Cancelled.**", reply_markup=back)
    if len(text) > 800:
        return await query.message.edit_text("**Too long (max 800 characters).**", reply_markup=back)
    client.custom_caption = text
    await client.mongodb.update_bot_setting("custom_caption", text)
    await query.message.edit_text("**Custom caption saved.**", reply_markup=back)


@Client.on_callback_query(filters.regex("^rm_caption$"))
async def rm_caption(client, query):
    if query.from_user.id not in client.admins:
        return await query.answer("Admins only.", show_alert=True)
    client.custom_caption = ""
    await client.mongodb.update_bot_setting("custom_caption", "")
    await query.answer("Custom caption removed.")
    return await caption_cfg(client, query)


#===============================================================#
# Custom thumbnail (helper/thumbnail.py)

def _thumb_markup(has_thumb, enabled=True):
    rows = [[InlineKeyboardButton('sᴇᴛ / ᴄʜᴀɴɢᴇ', 'set_thumb')]]
    if has_thumb:
        rows[0].append(InlineKeyboardButton('ʀᴇᴍᴏᴠᴇ', 'rm_thumb'))
        rows.append([InlineKeyboardButton(f"sᴡɪᴛᴄʜ: {'ᴏɴ' if enabled else 'ᴏꜰꜰ'}", 'toggle_thumb'),
                     InlineKeyboardButton('ᴠɪᴇᴡ', 'view_thumb')])
    rows.append([InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'settings_page_2')])
    return InlineKeyboardMarkup(rows)


@Client.on_callback_query(filters.regex("^thumb_cfg$"))
async def thumb_cfg(client, query):
    if query.from_user.id not in client.admins:
        return await query.answer("Admins only.", show_alert=True)
    from helper import thumbnail
    has = bool(thumbnail.exists(client))
    on = getattr(client, "thumb_enabled", True)
    msg = f"""<blockquote>**Custom Thumbnail:**</blockquote>
**Image:** `{'Set' if has else 'Not set'}`  ›› **Switch:** `{'ON' if on else 'OFF'}`

__Put on every video / document the bot delivers. Files are uploaded again with it, so big files are slower
(over {thumbnail.MAX_FILE // (1024 * 1024)} MB they are sent without it). OFF keeps the image but stops using it.__
"""
    await query.message.edit_text(msg, reply_markup=_thumb_markup(has, on))


@Client.on_callback_query(filters.regex("^toggle_thumb$"))
async def toggle_thumb(client, query):
    if query.from_user.id not in client.admins:
        return await query.answer("Admins only.", show_alert=True)
    client.thumb_enabled = not getattr(client, "thumb_enabled", True)
    await client.mongodb.update_bot_setting("thumb_enabled", client.thumb_enabled)
    await query.answer(f"Thumbnail {'ON' if client.thumb_enabled else 'OFF'}")
    return await thumb_cfg(client, query)


@Client.on_callback_query(filters.regex("^set_thumb$"))
async def set_thumb(client, query):
    if query.from_user.id not in client.admins:
        return await query.answer("Admins only.", show_alert=True)
    from helper import thumbnail
    back = InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'thumb_cfg')]])
    await query.answer()
    await query.message.edit_text("**Send the new thumbnail as a photo (not as a file), or wait 60s to cancel.**")
    try:
        res = await client.listen(user_id=query.from_user.id, filters=filters.photo, timeout=60)
    except ListenerTimeout:
        return await query.message.edit_text("**Timeout, try again!**", reply_markup=back)
    tmp = tempfile.mkdtemp(prefix="fsp_thumb_")
    try:
        src = await client.download_media(res, file_name=tmp + os.sep)
        ok = bool(src) and await thumbnail.save(client, src)
    except Exception as e:
        client.LOGGER(__name__, client.name).warning(f"set thumbnail: {e}")
        ok = False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if ok and not getattr(client, "thumb_enabled", True):
        client.thumb_enabled = True
        await client.mongodb.update_bot_setting("thumb_enabled", True)
    await query.message.edit_text("**Thumbnail saved.**" if ok else "**Could not use that image, try another one.**",
                                  reply_markup=back)


@Client.on_callback_query(filters.regex("^rm_thumb$"))
async def rm_thumb(client, query):
    if query.from_user.id not in client.admins:
        return await query.answer("Admins only.", show_alert=True)
    from helper import thumbnail
    await thumbnail.remove(client)
    await query.answer("Thumbnail removed.")
    return await thumb_cfg(client, query)


@Client.on_callback_query(filters.regex("^view_thumb$"))
async def view_thumb(client, query):
    if query.from_user.id not in client.admins:
        return await query.answer("Admins only.", show_alert=True)
    from helper import thumbnail
    path = thumbnail.exists(client)
    if not path:
        return await query.answer("No thumbnail set.", show_alert=True)
    await query.answer()
    await query.message.reply_photo(path, caption="**Current thumbnail**",
                                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("• ᴄʟᴏꜱᴇ •", callback_data="close")]]))


#===============================================================#
# Caption cleaner (helper/caption_clean.py)

async def _cclean_save(client, cfg):
    from helper import caption_clean
    cfg = caption_clean.normalize(cfg)
    client.caption_clean = cfg
    client.caption_cleaner = caption_clean.build_cleaner(cfg)
    await client.mongodb.update_bot_setting("caption_clean", cfg)


def _cclean_list(items, pairs=False):
    if not items:
        return "<pre>None</pre>"
    rows = [f"{p['old']} => {p['new']}" if pairs else p for p in items]
    return "<pre>" + _html.escape("\n".join(rows)) + "</pre>"


@Client.on_callback_query(filters.regex("^cclean_cfg$"))
async def cclean_cfg(client, query):
    if query.from_user.id not in client.admins:
        return await query.answer("Admins only.", show_alert=True)
    from helper import caption_clean
    cfg = caption_clean.normalize(getattr(client, "caption_clean", {}))
    mode, links = cfg["usernames"], cfg["links"]
    uname = f"@{cfg['username_value']}" if cfg["username_value"] else "not set"
    lval = cfg["link_value"] or "not set"
    notes = ""
    if mode == "replace" and not cfg["username_value"]:
        notes += "\n⚠️ __Usernames REPLACE needs your @username, tap **Set @username**.__"
    if links == "replace" and not cfg["link_value"]:
        notes += "\n⚠️ __Links REPLACE needs your link, tap **Set link**.__"
    msg = f"""<blockquote>**Caption Cleaner:**</blockquote>
__Cleans the file's own caption and {{file_name}} before delivery. Your Custom Caption is never touched.__

›› **Links:** `{links.upper()}` (own: `{lval}`)
›› **@usernames:** `{mode.upper()}` (own: `{uname}`)
›› **Remove words:** `{len(cfg['remove'])}`
›› **Replace words:** `{len(cfg['replace'])}`
›› **Numbering:** `{cfg['numbering'].upper()}`  ›› **Bullet:** `{cfg['bullet'].upper()}`{notes}
"""
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"ʟɪɴᴋs: {links}", 'cclean_links'),
         InlineKeyboardButton(f"@ᴜsᴇʀɴᴀᴍᴇs: {mode}", 'cclean_user')],
        [InlineKeyboardButton('sᴇᴛ ʟɪɴᴋ', 'cclean_setlink'), InlineKeyboardButton('sᴇᴛ @ᴜsᴇʀɴᴀᴍᴇ', 'cclean_setuser')],
        [InlineKeyboardButton(f"ʀᴇᴍᴏᴠᴇ ᴡᴏʀᴅs ({len(cfg['remove'])})", 'cclean_rm'),
         InlineKeyboardButton(f"ʀᴇᴘʟᴀᴄᴇ ᴡᴏʀᴅs ({len(cfg['replace'])})", 'cclean_rp')],
        [InlineKeyboardButton(f"ɴᴜᴍʙᴇʀɪɴɢ: {cfg['numbering']}", 'cclean_num'),
         InlineKeyboardButton(f"ʙᴜʟʟᴇᴛ: {cfg['bullet']}", 'cclean_bul')],
        [InlineKeyboardButton('⚡ ᴄʟᴇᴀɴ ᴀʟʟ (ʟɪɴᴋs + @ ʀᴇᴍᴏᴠᴇ)', 'cclean_all')],
        [InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'settings_page_2')],
    ])
    await query.message.edit_text(msg, reply_markup=markup)


@Client.on_callback_query(filters.regex("^cclean_(links|user|num|bul|all)$"))
async def cclean_toggle(client, query):
    if query.from_user.id not in client.admins:
        return await query.answer("Admins only.", show_alert=True)
    from helper import caption_clean as cc
    cfg = cc.normalize(getattr(client, "caption_clean", {}))
    what = query.data[7:]
    if what == "links":
        cfg["links"] = cc.next_mode(cfg["links"], cc.MODES)
    elif what == "user":
        cfg["usernames"] = cc.next_mode(cfg["usernames"], cc.MODES)
    elif what == "num":
        cfg["numbering"] = cc.next_mode(cfg["numbering"], cc.NUM_STYLES)
    elif what == "bul":
        cfg["bullet"] = cc.next_mode(cfg["bullet"], cc.BULLETS)
    else:   # one-tap preset (AK Manager's "Course Sellers"): no links, no @usernames in the caption
        cfg["links"], cfg["usernames"] = "remove", "remove"
    await _cclean_save(client, cfg)
    await query.answer("Saved.")
    return await cclean_cfg(client, query)


@Client.on_callback_query(filters.regex("^cclean_setlink$"))
async def cclean_setlink(client, query):
    if query.from_user.id not in client.admins:
        return await query.answer("Admins only.", show_alert=True)
    from helper import caption_clean as cc
    back = InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'cclean_cfg')]])
    await query.answer()
    await query.message.edit_text("**Send your link (used when Links is on REPLACE), e.g. `https://t.me/mychannel`. Wait 60s to cancel.**")
    try:
        res = await client.listen(user_id=query.from_user.id, filters=filters.text, timeout=60)
    except ListenerTimeout:
        return await query.message.edit_text("**Timeout, try again!**", reply_markup=back)
    link = cc.valid_link((res.text or "").strip())
    if not link:
        return await query.message.edit_text("**Not a valid link (use https://... or t.me/...).**", reply_markup=back)
    cfg = cc.normalize(getattr(client, "caption_clean", {}))
    cfg["link_value"] = link
    await _cclean_save(client, cfg)
    await query.message.edit_text(f"**Saved:** `{link}`", reply_markup=back)


@Client.on_callback_query(filters.regex("^cclean_setuser$"))
async def cclean_setuser(client, query):
    if query.from_user.id not in client.admins:
        return await query.answer("Admins only.", show_alert=True)
    from helper import caption_clean
    back = InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'cclean_cfg')]])
    await query.answer()
    await query.message.edit_text("**Send your @username (used when @usernames is on REPLACE), or wait 60s to cancel.**")
    try:
        res = await client.listen(user_id=query.from_user.id, filters=filters.text, timeout=60)
    except ListenerTimeout:
        return await query.message.edit_text("**Timeout, try again!**", reply_markup=back)
    name = (res.text or "").strip().lstrip("@")
    if not name or name.startswith("/") or not name.replace("_", "").isalnum() or len(name) < 5 or len(name) > 32:
        return await query.message.edit_text("**Not a valid username (5-32 letters, digits or _).**", reply_markup=back)
    cfg = caption_clean.normalize(getattr(client, "caption_clean", {}))
    cfg["username_value"] = name
    await _cclean_save(client, cfg)
    await query.message.edit_text(f"**Saved:** `@{name}`", reply_markup=back)


@Client.on_callback_query(filters.regex("^cclean_(rm|rp)(_add|_clear)?$"))
async def cclean_words(client, query):
    if query.from_user.id not in client.admins:
        return await query.answer("Admins only.", show_alert=True)
    from helper import caption_clean
    kind, action = query.data[7:9], query.data[9:]
    key, pairs = ("remove", False) if kind == "rm" else ("replace", True)
    cfg = caption_clean.normalize(getattr(client, "caption_clean", {}))
    back = InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', f'cclean_{kind}')]])
    if action == "_clear":
        cfg[key] = []
        await _cclean_save(client, cfg)
        await query.answer("Cleared.")
        action = ""
    if action == "_add":
        if len(cfg[key]) >= caption_clean.MAX_ITEMS:
            return await query.answer(f"Limit reached ({caption_clean.MAX_ITEMS}). Clear the list first.", show_alert=True)
        await query.answer()
        hint = ("Send one **old => new** per line.\nExample: `OldChannel => My Channel`" if pairs
                else "Send one word or phrase per line.")
        await query.message.edit_text(f"**{hint}**\n\n__Wait 60s to cancel.__")
        try:
            res = await client.listen(user_id=query.from_user.id, filters=filters.text, timeout=60)
        except ListenerTimeout:
            return await query.message.edit_text("**Timeout, try again!**", reply_markup=back)
        text = res.text or ""
        new = caption_clean.parse_pairs(text) if pairs else caption_clean.parse_words(text)
        if not new or text.strip().startswith("/"):
            return await query.message.edit_text("**Nothing added.**" + (" Use the `old => new` format." if pairs else ""),
                                                 reply_markup=back)
        cfg[key] = (cfg[key] + new)[:caption_clean.MAX_ITEMS]
        await _cclean_save(client, cfg)
        return await query.message.edit_text(f"**Added {len(new)}.** Total: `{len(cfg[key])}`", reply_markup=back)
    title = "Replace words" if pairs else "Remove words"
    msg = (f"<blockquote>**{title}:**</blockquote>\n{_cclean_list(cfg[key], pairs)}\n"
           f"__Case-insensitive, max {caption_clean.MAX_ITEMS} entries.__")
    await query.message.edit_text(msg, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton('ᴀᴅᴅ', f'cclean_{kind}_add'), InlineKeyboardButton('ᴄʟᴇᴀʀ ᴀʟʟ', f'cclean_{kind}_clear')],
        [InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'cclean_cfg')],
    ]))


#===============================================================#
# File buttons (helper/custom_buttons.py)

@Client.on_callback_query(filters.regex("^cbtn_cfg$"))
async def cbtn_cfg(client, query):
    if query.from_user.id not in client.admins:
        return await query.answer("Admins only.", show_alert=True)
    from helper import custom_buttons as cb
    rows = getattr(client, "custom_buttons", [])
    msg = f"""<blockquote>**File Buttons:**</blockquote>
__Url buttons shown under every file the bot delivers (below the file's own buttons).__

**Current:**
<pre>{_html.escape(cb.describe(rows))}</pre>
"""
    await query.message.edit_text(msg, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton('sᴇᴛ / ᴄʜᴀɴɢᴇ', 'cbtn_set'), InlineKeyboardButton('ʀᴇᴍᴏᴠᴇ', 'cbtn_rm')],
        [InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'settings_page_2')],
    ]))


@Client.on_callback_query(filters.regex("^cbtn_set$"))
async def cbtn_set(client, query):
    if query.from_user.id not in client.admins:
        return await query.answer("Admins only.", show_alert=True)
    from helper import custom_buttons as cb
    back = InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'cbtn_cfg')]])
    await query.answer()
    await query.message.edit_text(
        "**Send the buttons, one per line (this replaces the current ones):**\n\n"
        "`[Join Channel][buttonurl:https://t.me/mychannel]`\n"
        "`[Backup][buttonurl:https://t.me/backup:same]`\n\n"
        f"__`:same` at the end puts the button on the previous button's row. Max {cb.MAX_BUTTONS} buttons. Wait 60s to cancel.__")
    try:
        res = await client.listen(user_id=query.from_user.id, filters=filters.text, timeout=60)
    except ListenerTimeout:
        return await query.message.edit_text("**Timeout, try again!**", reply_markup=back)
    rows = cb.parse(res.text or "")
    if not rows:
        return await query.message.edit_text("**No valid button found.** Use `[Text][buttonurl:https://...]`.", reply_markup=back)
    client.custom_buttons = rows
    await client.mongodb.update_bot_setting("custom_buttons", rows)
    await query.message.edit_text(f"**Saved {sum(len(r) for r in rows)} button(s).**", reply_markup=back)


@Client.on_callback_query(filters.regex("^cbtn_rm$"))
async def cbtn_rm(client, query):
    if query.from_user.id not in client.admins:
        return await query.answer("Admins only.", show_alert=True)
    client.custom_buttons = []
    await client.mongodb.update_bot_setting("custom_buttons", [])
    await query.answer("Buttons removed.")
    return await cbtn_cfg(client, query)
