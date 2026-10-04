"""The one place that gives credits or premium time. Used by payments, gift codes and the admin tools,
so the stacking rules (renewals add to the time left, lifetime stays lifetime) live in one spot."""
from datetime import datetime, timedelta

from helper import ledger


async def grant_credits(mongo, user_id: int, amount: int, kind: str, ref: str = "", note: str = "") -> str:
    if not await mongo.present_user(user_id):
        await mongo.add_user(user_id)
    await mongo.add_credits(user_id, amount)
    await ledger.record(mongo.db, user_id, amount, kind, ref, note)
    return f"{amount} credits"


async def grant_premium(mongo, user_id: int, days: int) -> str:
    """days <= 0 = lifetime. Renewal stacks on the time left; a lifetime user is never downgraded."""
    if not await mongo.present_user(user_id):
        await mongo.add_user(user_id)
    is_pro = await mongo.is_pro(user_id)
    current = await mongo.get_expiry_date(user_id) if is_pro else None
    if is_pro and current is None:
        return "lifetime already"
    if days <= 0:
        await mongo.add_pro(user_id, None)
        return "lifetime premium"
    base = current if current and current > datetime.now() else datetime.now()
    expiry = base + timedelta(days=int(days))
    await mongo.add_pro(user_id, expiry)
    return f"premium until {expiry:%Y-%m-%d}"
