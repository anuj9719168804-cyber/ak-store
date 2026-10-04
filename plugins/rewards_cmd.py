"""/daily and /refer — free credits for coming back and for inviting people."""
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import DAILY_BONUS_CREDITS, REFERRAL_CREDITS, REFERRAL_MAX_PER_USER, REFERRAL_NEW_USER_CREDITS
from helper import rewards
from helper.utils import ban_notice


def _left(seconds: int) -> str:
    h, rest = divmod(int(seconds), 3600)
    return f"{h}h {rest // 60}m" if h else f"{max(rest // 60, 1)}m"


@Client.on_message(filters.command("daily") & filters.private)
async def daily_command(client: Client, message: Message):
    if DAILY_BONUS_CREDITS <= 0:
        return await message.reply("The daily bonus is turned off.")
    uid = message.from_user.id
    if await client.mongodb.is_banned(uid):
        return await message.reply(await ban_notice(client.mongodb, message.from_user.id))
    if not await client.mongodb.present_user(uid):
        await client.mongodb.add_user(uid)
    ok, value = await rewards.claim_daily(client.mongodb.db, uid)
    if ok:
        credits = await client.mongodb.get_credits(uid)
        return await message.reply(f"<blockquote>🎁 <b>Daily bonus</b></blockquote>\n+<b>{value}</b> credits added.\n"
                                   f"You now have <b>{credits}</b> credits. Come back in 24 hours!")
    await message.reply(f"⏳ You already took today's bonus. Next one in <b>{_left(value)}</b>.")


@Client.on_message(filters.command(["refer", "invite"]) & filters.private)
async def refer_command(client: Client, message: Message):
    if REFERRAL_CREDITS <= 0 and REFERRAL_NEW_USER_CREDITS <= 0:
        return await message.reply("Referrals are turned off.")
    uid = message.from_user.id
    link = rewards.ref_link(client, uid)
    info = await rewards.referral_stats(client.mongodb.db, uid)
    lines = [f"<blockquote>👥 <b>Invite friends, get credits</b></blockquote>",
             f"You get <b>+{REFERRAL_CREDITS}</b> credits for every new person who joins with your link."]
    if REFERRAL_NEW_USER_CREDITS > 0:
        lines.append(f"They get <b>+{REFERRAL_NEW_USER_CREDITS}</b> too.")
    if REFERRAL_MAX_PER_USER > 0:
        lines.append(f"(Up to {REFERRAL_MAX_PER_USER} invites count.)")
    lines += ["", f"<b>Your link:</b>\n<code>{link}</code>", "",
              f"Invited so far: <b>{info['referrals']}</b> · earned: <b>{info['earned']}</b> credits"]
    await message.reply("\n".join(lines), disable_web_page_preview=True,
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                            "🔁 sʜᴀʀᴇ", url=f"https://telegram.me/share/url?url={link}&text=Get%20files%20here")]]))
