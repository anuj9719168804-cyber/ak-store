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
