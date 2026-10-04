"""One free premium trial per user (/trial). Ported idea: AK Ultra's /trial.

    users doc:  trial_used (True once claimed), trial_at (epoch)

The claim is an atomic update on the user document, so two taps at once give ONE trial.
A user who is already premium is turned away WITHOUT using up their trial.
"""
import time

from helper import grants


async def claim(mongo, user_id: int, days: int):
    """-> (code, text). code: off | premium | used | ok.   text = what was given when ok."""
    if days <= 0:
        return "off", ""
    if not await mongo.present_user(user_id):
        await mongo.add_user(user_id)
    if await mongo.is_pro(user_id):
        return "premium", ""
    res = await mongo.user_data.update_one(
        {"_id": user_id, "trial_used": {"$ne": True}},
        {"$set": {"trial_used": True, "trial_at": time.time()}},
    )
    if res.modified_count != 1:
        return "used", ""
    return "ok", await grants.grant_premium(mongo, user_id, days)
