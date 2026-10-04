# made by botifyx-bots 
# support @BotifyX_Pro_Botz
from pyrogram import Client
from pyrogram.enums import ParseMode
import sys
from datetime import datetime
from config import LOGGER, OWNER_ID, SHORT_URL, SHORT_API, SHORT_TUT, STREAM_CONCURRENCY
from helper import MongoDB


version = "v2.0.0"

class Bot(Client):
    def __init__(self, session, workers, db, fsub, token, admins, messages, auto_del, db_uri, db_name, api_id, api_hash, protect, disable_btn):
        super().__init__(
            name=session,
            api_hash=api_hash,
            api_id=api_id,
            plugins={
                "root": "plugins"
            },
            workers=workers,
            bot_token=token,
            # Video players open several Range requests at once; the default (1)
            # would make them queue behind each other.
            max_concurrent_transmissions=STREAM_CONCURRENCY
        )
        self.LOGGER = LOGGER
        self.name = session
        self.db = db
        self.fsub = fsub
        self.owner = OWNER_ID
        self.fsub_dict = {}
        self.admins = admins + [OWNER_ID] if OWNER_ID not in admins else admins
        self.messages = messages
        self.auto_del = auto_del
        self.protect = protect
        self.req_fsub = {}
        self.disable_btn = disable_btn
        self.tutorial_enabled = True  # show the Tutorial button on the shortener screen
        self.caption_clean, self.caption_cleaner = {}, None  # helper/caption_clean.py settings + ready cleaner
        self.custom_buttons = []  # rows of url buttons under delivered files (helper/custom_buttons.py)
        self.caption_mode = "append"  # "append" the template under the file caption, or "replace" it
        self.thumb_enabled = True  # the saved thumbnail can be switched off without deleting it
        self.custom_thumb = ""  # local path of the thumbnail put on delivered files (helper/thumbnail.py)
        self.custom_caption = ""  # template appended to delivered files (see helper/caption_logic.py)
        self.permanent_link = False  # links go through the Cloudflare Worker (needs BACKEND_API_URL)
        self.reply_text = messages.get('REPLY', 'ғᴜᴄᴋ ᴏғғ ʙɪᴛᴄʜ !!!')
        self.mongodb = MongoDB(db_uri, db_name)
        self.req_channels = []
        self.db_channels = {}  # Initialize DB channels dictionary
        self.primary_db_channel = db  # Set initial primary DB channel
    
    async def start(self):
        await super().start()
        usr_bot_me = await self.get_me()
        self.uptime = datetime.now()
        
        # Load fsub channels from static config first
        if len(self.fsub) > 0:
            for channel in self.fsub:
                try:
                    chat = await self.get_chat(channel[0])
                    name = chat.title
                    link = None
                    if not channel[1]:
                        link = chat.invite_link
                    if not link and not channel[2]:
                        chat_link = await self.create_chat_invite_link(channel[0], creates_join_request=channel[1])
                        link = chat_link.invite_link
                    if not channel[1]:
                        self.fsub_dict[channel[0]] = [name, link, False, 0]
                    if channel[1]:
                        self.fsub_dict[channel[0]] = [name, link, True, 0]
                        self.req_channels.append(channel[0])
                    if channel[2] > 0:
                        self.fsub_dict[channel[0]] = [name, None, channel[1], channel[2]]
                except Exception as e:
                    self.LOGGER(__name__, self.name).warning("Bot can't Export Invite link from Force Sub Channel!")
                    self.LOGGER(__name__, self.name).warning("\nBot Stopped.")
                    sys.exit()
                    
        # Load dynamically added fsub channels from database
        try:
            db_fsub_channels = await self.mongodb.get_fsub_channels()
            for channel_id_str, channel_data in db_fsub_channels.items():
                channel_id = int(channel_id_str)
                # Skip if already loaded from static config
                if channel_id in self.fsub_dict:
                    continue
                try:
                    chat = await self.get_chat(channel_id)
                    name = chat.title
                    # Update name in case it changed
                    channel_data[0] = name
                    self.fsub_dict[channel_id] = channel_data
                    if channel_data[2]:  # if request is True
                        self.req_channels.append(channel_id)
                except Exception as e:
                    self.LOGGER(__name__, self.name).warning(f"Could not load dynamic fsub channel {channel_id}: {e}")
                    # Remove invalid channel from database
                    await self.mongodb.remove_fsub_channel(channel_id)
        except Exception as e:
            self.LOGGER(__name__, self.name).warning(f"Error loading dynamic fsub channels: {e}")
            
        await self.mongodb.set_channels(self.req_channels)

        # Admins added from the bot or the web panel are stored in the DB; without
        # this they would be forgotten on every restart.
        try:
            for admin_id in await self.mongodb.get_admins_list():
                if admin_id not in self.admins:
                    self.admins.append(admin_id)
        except Exception as e:
            self.LOGGER(__name__, self.name).warning(f"Could not load admins from database: {e}")
        
        # Settings changed from the bot's /settings menu or the web panel are stored
        # in the DB; load them so they survive a restart.
        try:
            saved = await self.mongodb.get_bot_settings()
            if "protect" in saved:
                self.protect = bool(saved["protect"])
            if "auto_del" in saved:
                self.auto_del = int(saved["auto_del"])
            self.custom_caption = saved.get("custom_caption", "") or ""
            self.caption_mode = "replace" if saved.get("caption_mode") == "replace" else "append"
            self.thumb_enabled = bool(saved.get("thumb_enabled", True))
            from helper import caption_clean
            self.caption_clean = caption_clean.normalize(saved.get("caption_clean"))
            self.caption_cleaner = caption_clean.build_cleaner(self.caption_clean)
            from helper import custom_buttons
            self.custom_buttons = custom_buttons.normalize(saved.get("custom_buttons"))
            self.permanent_link = bool(saved.get("permanent_link", False))
            from helper import linkttl
            await linkttl.load(self.mongodb)
            from helper import thumbnail
            await thumbnail.load(self)
            # Texts and photos edited from /settings (saved by plugins/texts.py and plugins/settings.py)
            saved_msgs = await self.mongodb.get_messages_settings()
            for key, value in saved_msgs.items():
                self.messages[key] = value
            if "REPLY" in saved_msgs:
                self.reply_text = saved_msgs["REPLY"]
        except Exception as e:
            self.LOGGER(__name__, self.name).warning(f"Could not load saved settings: {e}")

        # Load DB channels from database
        try:
            db_channels_data = await self.mongodb.get_db_channels()
            self.db_channels = {}
            self.primary_db_channel = self.db
            
            for channel_id_str, channel_data in db_channels_data.items():
                channel_id = int(channel_id_str)
                try:
                    # Verify channel still exists and is accessible
                    chat = await self.get_chat(channel_id)
                    # Update name in case it changed
                    channel_data['name'] = chat.title
                    self.db_channels[channel_id_str] = channel_data
                    
                    # Set primary channel if marked as primary
                    if channel_data.get('is_primary', False):
                        self.primary_db_channel = channel_id
                        self.db = channel_id  # Update current db reference
                        
                except Exception as e:
                    self.LOGGER(__name__, self.name).warning(f"Could not load DB channel {channel_id}: {e}")
                    # Remove invalid channel from database
                    await self.mongodb.remove_db_channel(channel_id)
        except Exception as e:
            self.LOGGER(__name__, self.name).warning(f"Error loading DB channels: {e}")
        
        # Load shortner settings from database
        try:
            shortner_settings = await self.mongodb.get_shortner_settings()
            self.short_url = shortner_settings.get('short_url', SHORT_URL)
            self.short_api = shortner_settings.get('short_api', SHORT_API)
            self.tutorial_link = shortner_settings.get('tutorial_link', SHORT_TUT)
            self.tutorial_enabled = bool(shortner_settings.get('tutorial_enabled', True))
            self.shortner_enabled = shortner_settings.get('enabled', True)
        except Exception as e:
            self.LOGGER(__name__, self.name).warning(f"Error loading shortner settings: {e}")
            # Set defaults from config if loading fails
            self.short_url = SHORT_URL
            self.short_api = SHORT_API
            self.tutorial_link = SHORT_TUT
            self.shortner_enabled = True
        
        try:
            db_channel = await self.get_chat(self.db)
            self.db_channel = db_channel
            test = await self.send_message(chat_id = db_channel.id, text = "Testing Message by @ProYato")
            await test.delete()
            
            # Log DB channels info
            self.LOGGER(__name__, self.name).info(f"Primary DB Channel: {self.primary_db_channel}")
            self.LOGGER(__name__, self.name).info(f"Total DB Channels: {len(self.db_channels)}")
        except Exception as e:
            self.LOGGER(__name__, self.name).warning(e)
            self.LOGGER(__name__, self.name).warning(f"Make Sure bot is Admin in DB Channel, and Double check the database channel Value, Current Value {self.db}")
            self.LOGGER(__name__, self.name).info("\nBot Stopped. Join https://t.me/BotifyX_Pro_Botz for support")
            sys.exit()
        self.LOGGER(__name__, self.name).info("Bot Started!!")
        await self._set_command_menu()
        
        # Send restart msge to owner
        try:
            restart_message = "<b>›› ʜᴇʏ sᴇɴᴘᴀɪ!!\n ɪ'ᴍ ᴀʟɪᴠᴇ ɴᴏᴡ 🍃...</b>"
            await self.send_message(chat_id=self.owner, text=restart_message)
            self.LOGGER(__name__, self.name).info(f"Restart notification sent to owner: {self.owner}")
        except Exception as e:
            self.LOGGER(__name__, self.name).warning(f"Failed to send restart notification to owner: {e}")
        
        self.username = usr_bot_me.username
    async def _set_command_menu(self):
        """Telegram's '/' menu: user commands for everyone, more for admins and the owner.

        Never raises. Admins added later get their menu on the next restart.
        """
        from pyrogram.types import BotCommand, BotCommandScopeDefault, BotCommandScopeChat
        user_cmds = [("start", "Start the bot / get files"), ("profile", "View your profile"),
                     ("credits", "Check your credits"), ("buy", "Premium plans"), ("request", "Send a request"),
                     ("bots", "Create / manage your own file-store bot"),
                     ("daily", "Free daily credits"), ("redeem", "Redeem a gift code"), ("refer", "Invite friends, get credits"), ("search", "Search files by name"),
                     ("contact", "Write to the admins"), ("trial", "Free premium trial")]
        admin_cmds = [("genlink", "Link for one file"), ("batch", "Link for a range of files"),
                      ("nbatch", "Link for the next N files"), ("custom_batch", "Link for chosen files"),
                      ("flink", "Formatted link list for many files"),
                      ("explink", "Link that expires / has a download limit"), ("gencode", "Make a gift code"), ("codes", "List gift codes"), ("delcode", "Switch off a gift code"), ("ledger", "Where a user's credits came from"), ("links", "List limited links"), ("revoke", "Disable a limited link"),
                      ("shortner", "Shortener settings"), ("stats", "Bot stats"), ("users", "User count"),
                      ("broadcast", "Broadcast to all users"), ("pbroadcast", "Broadcast to premium users"),
                      ("ban", "Ban users (optional reason)"), ("unban", "Unban users"), ("reply", "Answer a /contact message"), ("set_expiry", "Web link validity"), ("db", "Database channels")]
        owner_cmds = [("addadmin", "Add admin(s)"), ("removeadmin", "Remove admin(s)"),
                      ("addpremium", "Add premium user"), ("delpremium", "Remove premium user"),
                      ("premiumusers", "List premium users"), ("add_credit", "Add credits"),
                      ("adddb", "Add DB channel"), ("removedb", "Remove DB channel"), ("backup", "Backup database now"), ("logs", "Latest log lines"), ("restart", "Restart the bot"),
                       ("mban", "Ban a user from creating bots"), ("munban", "Unban from creating bots"),
                       ("mcast", "Broadcast to bot-creator users"), ("check", "List all user bots"),
                       ("sysstats", "Multi-bot system stats")]
        mk = lambda items: [BotCommand(c, d) for c, d in items]
        try:
            await self.set_bot_commands(mk(user_cmds), scope=BotCommandScopeDefault())
            for admin_id in set(self.admins):
                cmds = user_cmds + admin_cmds + (owner_cmds if admin_id == self.owner else [])
                try:
                    await self.set_bot_commands(mk(cmds), scope=BotCommandScopeChat(admin_id))
                except Exception:
                    pass  # admin never opened the bot: Telegram refuses a chat scope for them
        except Exception as e:
            self.LOGGER(__name__, self.name).warning(f"Could not set the command menu: {e}")

    async def stop(self, *args):
        await super().stop()
        self.LOGGER(__name__, self.name).info("Bot stopped.")
