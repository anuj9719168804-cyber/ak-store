"""Credit ledger: one line for every time credits are GIVEN to a user (verify, daily, referral,
payment, gift code, admin). Spending is not logged (one line per file would be a flood); the
current balance stays on the user document. Purpose: answer "where did this user's credits come
from?" and settle payment disputes. Logging never raises.

    credit_log   user_id, delta, kind, ref, note, at (naive UTC)
"""
import logging
from datetime import datetime, timezone

log = logging.getLogger("ledger")


async def record(db, user_id, delta: int, kind: str, ref: str = "", note: str = ""):
    try:
        await db["credit_log"].insert_one({
            "user_id": int(user_id), "delta": int(delta), "kind": kind, "ref": str(ref)[:80], "note": str(note)[:120],
            "at": datetime.now(timezone.utc).replace(tzinfo=None),
        })
    except Exception as e:
        log.warning("Could not write the credit ledger: %s", e)


async def recent(db, user_id, limit: int = 15) -> list:
    try:
        return await db["credit_log"].find({"user_id": int(user_id)}).sort([("at", -1)]).limit(limit).to_list(length=limit)
    except Exception:
        return []


async def totals(db, user_id) -> dict:
    """{kind: total credits granted} for one user."""
    out = {}
    try:
        async for row in db["credit_log"].find({"user_id": int(user_id)}):
            out[row["kind"]] = out.get(row["kind"], 0) + row["delta"]
    except Exception:
        pass
    return out
