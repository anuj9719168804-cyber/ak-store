import asyncio
import requests
import random
import string
from config import SHORT_URL, SHORT_API, MESSAGES
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputMediaPhoto
from pyrogram.errors.pyromod import ListenerTimeout
from helper.helper_func import force_sub
from helper.utils import mask_api_key

# ✅ In-memory cache
shortened_urls_cache = {}

def generate_random_alphanumeric():
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for _ in range(8))

def get_short(url, client):
    """Shorten `url` with the configured shortener. Blocking: call get_short_async from async code.

    Always returns something usable: the original url if the shortener fails.
    """
    # Check if shortner is enabled
    shortner_enabled = getattr(client, 'shortner_enabled', True)
    if not shortner_enabled:
        return url  # Return original URL if shortner is disabled

    short_url = getattr(client, 'short_url', SHORT_URL)
    short_api = getattr(client, 'short_api', SHORT_API)

    # Cache per shortener, so links made with an old domain/key are not reused after a change
    cache_key = (short_url, url)
    if cache_key in shortened_urls_cache:
        return shortened_urls_cache[cache_key]

    try:
        response = requests.get(
            f"https://{short_url}/api",
            params={"api": short_api, "url": url, "alias": generate_random_alphanumeric()},
            timeout=10,
        )
        result = None
        try:
            rjson = response.json()
            if rjson.get("status") == "success" and response.status_code == 200:
                result = rjson.get("shortenedUrl")
        except ValueError:
            # Some shorteners answer with the short link as plain text
            text = (response.text or "").strip()
            if response.status_code == 200 and text.startswith("http") and " " not in text:
                result = text
        if result:
            if len(shortened_urls_cache) >= 1000:  # keep memory bounded
                shortened_urls_cache.clear()
            shortened_urls_cache[cache_key] = result
            return result
    except Exception as e:
        print(f"[Shortener Error] {e}")

    return url  # fallback


def probe_api(short_url, short_api, timeout=8):
    """Really try the shortener once. -> (ok, short_link_or_error_text).

    A shortener with a wrong API key answers HTTP 200 with {"status": "error", ...}, so the HTTP code alone
    proves nothing: only a real short link counts as working. A random alias is used every time
    (a fixed one is refused by the shortener from the second test on).
    """
    try:
        r = requests.get(f"https://{short_url}/api",
                         params={"api": short_api, "url": "https://google.com", "alias": generate_random_alphanumeric()},
                         timeout=timeout)
        try:
            data = r.json()
        except ValueError:
            data = None
        if r.status_code == 200 and isinstance(data, dict):
            if data.get("status") == "success" and data.get("shortenedUrl"):
                return True, data["shortenedUrl"]
            return False, str(data.get("message") or data.get("status") or "Unknown error")
        text = (r.text or "").strip()
        if r.status_code == 200 and data is None and text.startswith("http") and " " not in text:
            return True, text
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, str(e)


async def get_short_async(url, client):
    """get_short without freezing the bot: the HTTP call runs in a worker thread."""
    return await asyncio.to_thread(get_short, url, client)

#===============================================================#

@Client.on_message(filters.command('shortner') & filters.private)
async def shortner_command(client: Client, message: Message):
    await shortner_panel(client, message)

#===============================================================#

async def shortner_panel(client, query_or_message):
    # Get current shortner settings
    short_url = getattr(client, 'short_url', SHORT_URL)
    short_api = getattr(client, 'short_api', SHORT_API)
    tutorial_link = getattr(client, 'tutorial_link', "https://t.me/ANIME_X_FLEX/19")
    shortner_enabled = getattr(client, 'shortner_enabled', True)
    
    # Check if shortner is working (only if enabled)
    if shortner_enabled:
        ok, _ = await asyncio.to_thread(probe_api, short_url, short_api, 5)
        status = "✓ ᴡᴏʀᴋɪɴɢ" if ok else "✗ ɴᴏᴛ ᴡᴏʀᴋɪɴɢ"
    else:
        status = "✗ ᴅɪsᴀʙʟᴇᴅ"
    
    enabled_text = "✓ ᴇɴᴀʙʟᴇᴅ" if shortner_enabled else "✗ ᴅɪsᴀʙʟᴇᴅ"
    toggle_text = "✗ ᴏғғ" if shortner_enabled else "✓ ᴏɴ"
    
    msg = f"""<blockquote>✦ 𝗦𝗛𝗢𝗥𝗧𝗡𝗘𝗥 𝗦𝗘𝗧𝗧𝗜𝗡𝗚𝗦</blockquote>
**<u>ᴄᴜʀʀᴇɴᴛ ꜱᴇᴛᴛɪɴɢꜱ:</u>**
<blockquote>›› **ꜱʜᴏʀᴛɴᴇʀ ꜱᴛᴀᴛᴜꜱ:** {enabled_text}
›› **ꜱʜᴏʀᴛɴᴇʀ ᴜʀʟ:** `{short_url}`
›› **ꜱʜᴏʀᴛɴᴇʀ ᴀᴘɪ:** `{mask_api_key(short_api)}`</blockquote> 
<blockquote>›› **ᴛᴜᴛᴏʀɪᴀʟ ʟɪɴᴋ:** `{tutorial_link}`
›› **ᴀᴘɪ ꜱᴛᴀᴛᴜꜱ:** {status}</blockquote>

<blockquote>**≡ ᴜꜱᴇ ᴛʜᴇ ʙᴜᴛᴛᴏɴꜱ ʙᴇʟᴏᴡ ᴛᴏ ᴄᴏɴꜰɪɢᴜʀᴇ ʏᴏᴜʀ ꜱʜᴏʀᴛɴᴇʀ ꜱᴇᴛᴛɪɴɢꜱ!**</blockquote>"""
    
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(f'• {toggle_text} ꜱʜᴏʀᴛɴᴇʀ •', 'toggle_shortner'), InlineKeyboardButton('• ᴀᴅᴅ ꜱʜᴏʀᴛɴᴇʀ •', 'add_shortner')],
        [InlineKeyboardButton('• ꜱᴇᴛ ᴛᴜᴛᴏʀɪᴀʟ ʟɪɴᴋ •', 'set_tutorial_link')],
        [InlineKeyboardButton('• ᴛᴜᴛᴏʀɪᴀʟ ʙᴜᴛᴛᴏɴ: ' + ('✓ ᴏɴ' if getattr(client, 'tutorial_enabled', True) else '✗ ᴏғғ') + ' •', 'toggle_tutorial')],
        [InlineKeyboardButton('• ᴛᴇꜱᴛ ꜱʜᴏʀᴛɴᴇʀ •', 'test_shortner')],
        [InlineKeyboardButton('◂ ʙᴀᴄᴋ ᴛᴏ ꜱᴇᴛᴛɪɴɢꜱ', 'settings')] if hasattr(query_or_message, 'message') else []
    ])
    
    image_url = MESSAGES.get("SHORT", "")
    
    if hasattr(query_or_message, 'message'):
        await query_or_message.message.edit_media(
            media=InputMediaPhoto(media=image_url, caption=msg),
            reply_markup=reply_markup
        )
    else:
        await query_or_message.reply_photo(photo=image_url, caption=msg, reply_markup=reply_markup)


#===============================================================#

@Client.on_callback_query(filters.regex("^shortner$"))
async def shortner_callback(client, query):
    if not query.from_user.id in client.admins:
        return await query.answer('❌ ᴏɴʟʏ ᴀᴅᴍɪɴꜱ ᴄᴀɴ ᴜꜱᴇ ᴛʜɪꜱ!', show_alert=True)
    await query.answer()
    await shortner_panel(client, query)

#===============================================================#

@Client.on_callback_query(filters.regex("^toggle_shortner$"))
async def toggle_shortner(client: Client, query: CallbackQuery):
    if not query.from_user.id in client.admins:
        return await query.answer('❌ ᴏɴʟʏ ᴀᴅᴍɪɴꜱ ᴄᴀɴ ᴜꜱᴇ ᴛʜɪꜱ!', show_alert=True)
    # Toggle the shortner status
    current_status = getattr(client, 'shortner_enabled', True)
    new_status = not current_status
    client.shortner_enabled = new_status
    
    # Save to database
    await client.mongodb.set_shortner_status(new_status)
    
    status_text = "ᴇɴᴀʙʟᴇᴅ" if new_status else "ᴅɪsᴀʙʟᴇᴅ"
    await query.answer(f"✓ ꜱʜᴏʀᴛɴᴇʀ {status_text}!")
    
    # Refresh the panel
    await shortner_panel(client, query)

#===============================================================#

@Client.on_callback_query(filters.regex("^add_shortner$"))
async def add_shortner(client: Client, query: CallbackQuery):
    if not query.from_user.id in client.admins:
        return await query.answer('❌ ᴏɴʟʏ ᴀᴅᴍɪɴꜱ ᴄᴀɴ ᴜꜱᴇ ᴛʜɪꜱ!', show_alert=True)
    
    await query.answer()
        
    current_url = getattr(client, 'short_url', SHORT_URL)
    current_api = getattr(client, 'short_api', SHORT_API)
    
    msg = f"""<blockquote>**ꜱᴇᴛ ꜱʜᴏʀᴛɴᴇʀ ꜱᴇᴛᴛɪɴɢꜱ:**</blockquote>
**ᴄᴜʀʀᴇɴᴛ ꜱᴇᴛᴛɪɴɢꜱ:**
• **ᴜʀʟ:** `{current_url}`
• **ᴀᴘɪ:** `{mask_api_key(current_api)}`

__<blockquote>**≡ ꜱᴇɴᴅ ɴᴇᴡ ꜱʜᴏʀᴛɴᴇʀ ᴜʀʟ ᴀɴᴅ ᴀᴘɪ ɪɴ ᴛʜɪꜱ ꜰᴏʀᴍᴀᴛ ɪɴ ᴛʜᴇ ɴᴇxᴛ 60 ꜱᴇᴄᴏɴᴅꜱ!**</blockquote>__

**ꜰᴏʀᴍᴀᴛ:** `ᴜʀʟ ᴀᴘɪ`
**ᴇxᴀᴍᴘʟᴇ:** `inshorturl.com 9435894656863495834957348`"""
    
    await query.message.edit_text(msg)
    try:
        res = await client.listen(user_id=query.from_user.id, filters=filters.text, timeout=60)
        response_text = res.text.strip()
        try:
            await res.delete()  # do not leave the API key sitting in the chat
        except Exception:
            pass
        
        # Parse the response: url api
        parts = response_text.split()
        if len(parts) >= 2:
            new_url = parts[0].replace('https://', '').replace('http://', '').replace('/', '')
            new_api = ' '.join(parts[1:])  # Join remaining parts as API key
            
            if new_url and '.' in new_url and new_api and len(new_api) > 10:
                # Update both settings
                client.short_url = new_url
                client.short_api = new_api
                
                # Save to database
                await client.mongodb.update_shortner_setting('short_url', new_url)
                await client.mongodb.update_shortner_setting('short_api', new_api)
                
                await query.message.edit_text(f"**✓ ꜱʜᴏʀᴛɴᴇʀ ꜱᴇᴛᴛɪɴɢꜱ ᴜᴘᴅᴀᴛᴇᴅ ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ!**\n\n**ɴᴇᴡ ᴜʀʟ:** `{new_url}`\n**ɴᴇᴡ ᴀᴘɪ:** `{new_api[:20]}...`", 
                                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'shortner')]]))
            else:
                await query.message.edit_text("**✗ ɪɴᴠᴀʟɪᴅ ꜰᴏʀᴍᴀᴛ! ᴘʟᴇᴀꜱᴇ ᴄʜᴇᴄᴋ ᴜʀʟ ᴀɴᴅ ᴀᴘɪ ᴋᴇʏ.**", 
                                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'shortner')]]))
        else:
            await query.message.edit_text("**✗ ɪɴᴠᴀʟɪᴅ ꜰᴏʀᴍᴀᴛ! ᴘʟᴇᴀꜱᴇ ᴜꜱᴇ: `ᴜʀʟ ᴀᴘɪ`**", 
                                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'shortner')]]))
    except ListenerTimeout:
        await query.message.edit_text("**⏰ ᴛɪᴍᴇᴏᴜᴛ! ᴛʀʏ ᴀɢᴀɪɴ.**", 
                                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'shortner')]]))

#===============================================================#

@Client.on_callback_query(filters.regex("^set_tutorial_link$"))
async def set_tutorial_link(client: Client, query: CallbackQuery):
    if not query.from_user.id in client.admins:
        return await query.answer('❌ ᴏɴʟʏ ᴀᴅᴍɪɴꜱ ᴄᴀɴ ᴜꜱᴇ ᴛʜɪꜱ!', show_alert=True)
    
    await query.answer()
        
    current_tutorial = getattr(client, 'tutorial_link', "https://t.me/ANIME_X_FLEX/19")
    msg = f"""<blockquote>**ꜱᴇᴛ ᴛᴜᴛᴏʀɪᴀʟ ʟɪɴᴋ:**</blockquote>
**ᴄᴜʀʀᴇɴᴛ ᴛᴜᴛᴏʀɪᴀʟ:** `{current_tutorial}`

__ꜱᴇɴᴅ ᴛʜᴇ ɴᴇᴡ ᴛᴜᴛᴏʀɪᴀʟ ʟɪɴᴋ ɪɴ ᴛʜᴇ ɴᴇxᴛ 60 ꜱᴇᴄᴏɴᴅꜱ!__
**ᴇxᴀᴍᴘʟᴇ:** `https://t.me/ANIME_X_FLEX/19`"""
    
    await query.message.edit_text(msg)
    try:
        res = await client.listen(user_id=query.from_user.id, filters=filters.text, timeout=60)
        new_tutorial = res.text.strip()
        
        if new_tutorial and (new_tutorial.startswith('https://') or new_tutorial.startswith('http://')):
            client.tutorial_link = new_tutorial
            # Save to database
            await client.mongodb.update_shortner_setting('tutorial_link', new_tutorial)
            await query.message.edit_text(f"**✓ ᴛᴜᴛᴏʀɪᴀʟ ʟɪɴᴋ ᴜᴘᴅᴀᴛᴇᴅ ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ!**", 
                                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'shortner')]]))
        else:
            await query.message.edit_text("**✗ ɪɴᴠᴀʟɪᴅ ʟɪɴᴋ ꜰᴏʀᴍᴀᴛ! ᴍᴜꜱᴛ ꜱᴛᴀʀᴛ ᴡɪᴛʜ https:// ᴏʀ http://**", 
                                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'shortner')]]))
    except ListenerTimeout:
        await query.message.edit_text("**⏰ ᴛɪᴍᴇᴏᴜᴛ! ᴛʀʏ ᴀɢᴀɪɴ.**", 
                                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'shortner')]]))

#===============================================================#

@Client.on_callback_query(filters.regex("^test_shortner$"))
async def test_shortner(client: Client, query: CallbackQuery):
    if not query.from_user.id in client.admins:
        return await query.answer('❌ ᴏɴʟʏ ᴀᴅᴍɪɴꜱ ᴄᴀɴ ᴜꜱᴇ ᴛʜɪꜱ!', show_alert=True)
    
    await query.answer()
        
    await query.message.edit_text("**🔄 ᴛᴇꜱᴛɪɴɢ ꜱʜᴏʀᴛɴᴇʀ...**")
    
    short_url = getattr(client, 'short_url', SHORT_URL)
    short_api = getattr(client, 'short_api', SHORT_API)
    
    test_url = "https://google.com"
    ok, result = await asyncio.to_thread(probe_api, short_url, short_api, 10)
    if ok:
        msg = f"""**✅ ꜱʜᴏʀᴛɴᴇʀ ᴛᴇꜱᴛ ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟ!**

**ᴛᴇꜱᴛ ᴜʀʟ:** `{test_url}`
**ꜱʜᴏʀᴛ ᴜʀʟ:** `{result}`"""
    else:
        msg = f"""**❌ ꜱʜᴏʀᴛɴᴇʀ ᴛᴇꜱᴛ ꜰᴀɪʟᴇᴅ!**

**ᴇʀʀᴏʀ:** `{result}`"""

    await query.message.edit_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('◂ ʙᴀᴄᴋ', 'shortner')]]))


#===============================================================#

@Client.on_callback_query(filters.regex("^toggle_tutorial$"))
async def toggle_tutorial(client: Client, query: CallbackQuery):
    if not query.from_user.id in client.admins:
        return await query.answer('❌ ᴏɴʟʏ ᴀᴅᴍɪɴꜱ ᴄᴀɴ ᴜꜱᴇ ᴛʜɪꜱ!', show_alert=True)
    client.tutorial_enabled = not getattr(client, 'tutorial_enabled', True)
    await client.mongodb.update_shortner_setting('tutorial_enabled', client.tutorial_enabled)
    await query.answer("✓ ᴛᴜᴛᴏʀɪᴀʟ ʙᴜᴛᴛᴏɴ ᴏɴ" if client.tutorial_enabled else "✓ ᴛᴜᴛᴏʀɪᴀʟ ʙᴜᴛᴛᴏɴ ᴏғғ")
    await shortner_panel(client, query)
