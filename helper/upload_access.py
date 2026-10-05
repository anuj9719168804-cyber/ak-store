from config import UPLOAD_ACCESS

_MEDIA = ("document", "video", "audio")


async def can_upload(client, message) -> bool:
    """May this private message be copied into the DB channel?

    Admins/owner: always (any message type, as in stock Pro).
    Others: only when UPLOAD_ACCESS allows it, and only for real files, so a
    stray "hi" from a premium user never ends up in the DB channel.
    """
    user = message.from_user
    if not user:
        return False
    if user.id in client.admins:
        return True

    if UPLOAD_ACCESS == "admin":
        return False
    if not any(getattr(message, kind, None) for kind in _MEDIA):
        return False
    if UPLOAD_ACCESS == "all":
        return True
    return bool(await client.mongodb.is_pro(user.id))  # "premium"


async def has_premium_access(client, user_id) -> bool:
    """Admins/owner and users with active premium may use the member features (store files, /explink, /links,
    /revoke). Admin commands (settings, bans, broadcast, DB channels, ...) stay admin-only."""
    if not user_id:
        return False
    if user_id in client.admins:
        return True
    return bool(await client.mongodb.is_pro(user_id))


def denied_text(client, message) -> str:
    """What a user who may not store this message is told.

    Admin-only mode (or a non-premium user): the configured REPLY text, as before.
    A premium / allowed user who sent plain text: say what to send instead of the REPLY text.
    """
    if UPLOAD_ACCESS != "admin" and not any(getattr(message, kind, None) for kind in _MEDIA):
        return "<b>Send me a file (video, document or audio) and I will give you its link.</b>"
    if UPLOAD_ACCESS == "premium":
        return "<b>Only premium users can store files here.</b> Use /buy to get premium."
    return client.reply_text
