import asyncio, os, sys, time, unittest
from datetime import timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tests  # noqa: F401
from helper import codes, ledger, rewards, grants  # noqa: E402
from tests.test_payments import Mongo  # noqa: E402
from tests.fakedb import FakeDB  # noqa: E402


class CodeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.m = Mongo(); self.db = self.m.db

    async def test_credit_code_once_per_person_and_limited_people(self):
        c = await codes.create(self.db, "credits", 20, 2, 1, code="welcome20")
        self.assertEqual(c["_id"], "WELCOME20")
        self.assertEqual(await codes.redeem(self.m, 10, " welcome20 "), ("ok", "20 credits"))      # case/space tolerant
        self.assertEqual((await codes.redeem(self.m, 10, "WELCOME20"))[0], "already")
        self.assertEqual((await codes.redeem(self.m, 11, "WELCOME20"))[0], "ok")
        self.assertEqual((await codes.redeem(self.m, 12, "WELCOME20"))[0], "full")
        self.assertEqual((await self.db["users"].find_one({"_id": 12}) or {}).get("credits", 5), 5)  # nothing given
        self.assertIsNone(await self.db["code_uses"].find_one({"_id": "WELCOME20:12"}))             # failed claim leaves no trace
        self.assertEqual((await self.db["users"].find_one({"_id": 10}))["credits"], 25)
        rows = await ledger.recent(self.db, 10)
        self.assertEqual([(r["delta"], r["kind"], r["ref"]) for r in rows], [(20, "gift", "WELCOME20")])

    async def test_race_for_last_slot(self):
        await codes.create(self.db, "credits", 5, 1, 1, code="LAST1")
        res = await asyncio.gather(*[codes.redeem(self.m, u, "LAST1") for u in range(100, 108)])
        self.assertEqual([r[0] for r in res].count("ok"), 1)
        self.assertEqual((await self.db["codes"].find_one({"_id": "LAST1"}))["uses"], 1)

    async def test_premium_code_and_stacking(self):
        await codes.create(self.db, "premium", 30, 5, 1, code="PREM30"); await codes.create(self.db, "premium", 0, 5, 1, code="LIFE")
        self.assertIn("premium until", (await codes.redeem(self.m, 7, "PREM30"))[1])
        self.assertEqual((await codes.redeem(self.m, 7, "LIFE"))[1], "lifetime premium")
        await codes.create(self.db, "premium", 30, 5, 1, code="PREM31")
        self.assertEqual((await codes.redeem(self.m, 7, "PREM31"))[1], "lifetime already")            # never downgraded
        self.assertIsNone(await self.m.get_expiry_date(7))

    async def test_expired_inactive_missing_invalid(self):
        await codes.create(self.db, "credits", 5, 5, 1, ttl_seconds=60, code="SOON")
        await self.db["codes"].update_one({"_id": "SOON"}, {"$set": {"expires_at": codes._now() - timedelta(seconds=1)}})
        self.assertEqual((await codes.redeem(self.m, 1, "SOON"))[0], "expired")
        await codes.create(self.db, "credits", 5, 5, 1, code="OFFX"); self.assertTrue(await codes.deactivate(self.db, "offx"))
        self.assertEqual((await codes.redeem(self.m, 1, "OFFX"))[0], "inactive")
        for bad in ("NOPE", "", "x", "A B", "../../x", None):
            self.assertEqual((await codes.redeem(self.m, 1, bad))[0], "missing")
        self.assertFalse(await codes.deactivate(self.db, "nope"))

    async def test_create_validation(self):
        for args in (("gold", 1, 1), ("credits", 0, 1), ("credits", 5, 0), ("premium", -1, 1)):
            with self.assertRaises(ValueError): await codes.create(self.db, *args, 1)
        await codes.create(self.db, "credits", 5, 1, 1, code="DUPE")
        with self.assertRaises(ValueError): await codes.create(self.db, "credits", 5, 1, 1, code="dupe")
        with self.assertRaises(ValueError): await codes.create(self.db, "credits", 5, 1, 1, code="no spaces!")
        auto = await codes.create(self.db, "credits", 5, 1, 1); self.assertTrue(codes.valid_format(auto["_id"]))

    async def test_failed_grant_returns_the_slot(self):
        await codes.create(self.db, "credits", 5, 1, 1, code="BOOM")
        real = grants.grant_credits
        async def broken(*a, **k): raise RuntimeError("db down")
        grants.grant_credits = broken
        try:
            with self.assertRaises(RuntimeError): await codes.redeem(self.m, 1, "BOOM")
        finally:
            grants.grant_credits = real
        self.assertEqual((await codes.redeem(self.m, 1, "BOOM"))[0], "ok")                          # still redeemable


class LedgerTests(unittest.IsolatedAsyncioTestCase):
    async def test_totals_recent_and_never_raises(self):
        db = FakeDB()
        await ledger.record(db, 1, 5, "verify"); await ledger.record(db, 1, 2, "daily"); await ledger.record(db, 1, 5, "verify"); await ledger.record(db, 2, 9, "gift")
        self.assertEqual(await ledger.totals(db, 1), {"verify": 10, "daily": 2})
        self.assertEqual(len(await ledger.recent(db, 1, 2)), 2)
        class Broken:
            def __getitem__(self, k): raise RuntimeError("x")
        await ledger.record(Broken(), 1, 1, "x"); self.assertEqual(await ledger.recent(Broken(), 1), [])


class ReferralQualify(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.old = (rewards.REFERRAL_CREDITS, rewards.REFERRAL_NEW_USER_CREDITS, rewards.REFERRAL_MAX_PER_USER, rewards.QUALIFY)
        rewards.REFERRAL_CREDITS, rewards.REFERRAL_NEW_USER_CREDITS, rewards.REFERRAL_MAX_PER_USER, rewards.QUALIFY = 3, 1, 2, "file"

    def tearDown(self):
        rewards.REFERRAL_CREDITS, rewards.REFERRAL_NEW_USER_CREDITS, rewards.REFERRAL_MAX_PER_USER, rewards.QUALIFY = self.old

    async def users(self, db, *new):
        await db["users"].insert_one({"_id": 1, "credits": 5, "joined": 0})
        for u in new:
            await db["users"].insert_one({"_id": u, "credits": 5, "joined": time.time() - 5})

    async def test_paid_only_after_first_file_and_only_once(self):
        db = FakeDB(); await self.users(db, 2)
        self.assertEqual(await rewards.register_referral(db, 2, 1), (False, "pending"))
        self.assertEqual((await db["users"].find_one({"_id": 1}))["credits"], 5)                  # joining alone pays nothing
        self.assertIsNone(await rewards.qualify(db, 2, "verify"))                                  # wrong event
        self.assertEqual(await rewards.qualify(db, 2, "file"), 1)
        self.assertIsNone(await rewards.qualify(db, 2, "file"))                                    # second file: nothing
        self.assertEqual((await db["users"].find_one({"_id": 1}))["credits"], 8)
        self.assertEqual((await db["users"].find_one({"_id": 2}))["credits"], 6)
        kinds = sorted(r["kind"] for r in db["credit_log"].docs); self.assertEqual(kinds, ["referral", "referral_bonus"])

    async def test_nobody_invited_and_cap_at_payout(self):
        db = FakeDB(); await self.users(db, 2, 3, 4, 5)
        self.assertIsNone(await rewards.qualify(db, 2, "file"))                                    # not invited: no reward, no crash
        for u in (3, 4, 5):
            await rewards.register_referral(db, u, 1)
        self.assertEqual(await rewards.qualify(db, 3, "file"), 1); self.assertEqual(await rewards.qualify(db, 4, "file"), 1)
        self.assertIsNone(await rewards.qualify(db, 5, "file"))                                    # cap of 2 reached
        self.assertEqual((await db["users"].find_one({"_id": 1}))["credits"], 5 + 6)

    async def test_verify_mode_and_join_mode(self):
        db = FakeDB(); await self.users(db, 2, 3)
        rewards.QUALIFY = "verify"
        await rewards.register_referral(db, 2, 1)
        self.assertIsNone(await rewards.qualify(db, 2, "file")); self.assertEqual(await rewards.qualify(db, 2, "verify"), 1)
        rewards.QUALIFY = "join"
        self.assertEqual(await rewards.register_referral(db, 3, 1), (True, "ok"))                  # immediate
        self.assertIsNone(await rewards.qualify(db, 3, "file"))                                    # nothing left to pay

    async def test_banned_inviter_gets_nothing_at_payout(self):
        db = FakeDB(); await self.users(db, 2)
        await rewards.register_referral(db, 2, 1)
        await db["users"].update_one({"_id": 1}, {"$set": {"ban": True}})
        self.assertIsNone(await rewards.qualify(db, 2, "file"))
        self.assertEqual((await db["users"].find_one({"_id": 1}))["credits"], 5)


if __name__ == "__main__":
    unittest.main()
