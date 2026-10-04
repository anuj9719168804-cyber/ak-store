"""Admin-only guard for settings buttons (main bot).

A button press carries `callback_data` that a custom Telegram client can fake, so hiding the
menu from normal users is not enough. This handler runs before every other callback handler
(group -30, ahead of the ban/maintenance guards) and refuses admin-only callback data from
anybody who is not an admin or the owner.
"""
import re

from pyrogram import Client
from pyrogram.types import CallbackQuery

from config import OWNER_ID

_ADMIN_ONLY = re.compile(
    r"^(?:"
    r"settings|settings_page_2|fsub|db_channels|add_db_channel|rm_db_channel|set_primary_db|toggle_db_status|"
    r"admins|photos|protect|permanent_link|auto_del|texts|"
    r"rm_start_photo|rm_fsub_photo|add_start_photo|add_fsub_photo|"
    r"caption_cfg|caption_mode|set_caption|rm_caption|"
    r"thumb_cfg|toggle_thumb|set_thumb|rm_thumb|view_thumb|"
    r"cclean_.*|cbtn_.*|"
    r"start_txt|fsub_txt|about_txt|channels_txt|reply_txt|"
    r"add_fsub|rm_fsub|toggle_fsub_mode|add_admin|rm_admin|"
    r"shortner|toggle_shortner|add_shortner|set_tutorial_link|test_shortner|toggle_tutorial"
    r")$"
)


def is_admin_only(data) -> bool:
    if isinstance(data, bytes):
        data = data.decode("utf-8", "ignore")
    return bool(data) and bool(_ADMIN_ONLY.match(str(data)))


@Client.on_callback_query(group=-30)
async def admin_callback_guard(client: Client, query: CallbackQuery):
    if not is_admin_only(query.data):
        return
    uid = query.from_user.id if query.from_user else 0
    if uid == OWNER_ID or uid == getattr(client, "owner", None) or uid in (getattr(client, "admins", None) or []):
        return
    try:
        await query.answer("Admins only.", show_alert=True)
    except Exception:
        pass
    query.stop_propagation()
