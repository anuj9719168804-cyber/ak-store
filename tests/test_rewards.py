import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helper import rewards  # noqa: E402
from tests.fakedb import FakeDB  # noqa: E402


async def user(db, uid, joined, **extra):
    await db["users"].insert_one({"_id": uid, "credits": 5, "joined": joined, **extra})


class RewardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.old = (rewards.REFERRAL_CREDITS, rewards.REFERRAL_NEW_USER_CREDITS, rewards.REFERRAL_MAX_PER_USER, rewards.DAILY_BONUS_CREDITS, rewards.QUALIFY); rewards.QUALIFY = "join"
        rewards.REFERRAL_CREDITS, rewards.REFERRAL_NEW_USER_CREDITS, rewards.REFERRAL_MAX_PER_USER, rewards.DAILY_BONUS_CREDITS = 3, 1, 2, 2

    def tearDown(self):
        (rewards.REFERRAL_CREDITS, rewards.REFERRAL_NEW_USER_CREDITS, rewards.REFERRAL_MAX_PER_USER, rewards.DAILY_BONUS_CREDITS, rewards.QUALIFY) = self.old

    def test_parse(self):
        self.assertEqual(rewards.parse_ref("ref_123"), 123)
        for bad in ("ref_", "ref_abc", "xref_1", "ref_1 2", "", None, "ref_" + "9" * 16):
            self.assertIsNone(rewards.parse_ref(bad))

    async def test_daily_once_per_24h(self):
        db = FakeDB(); await user(db, 1, 0)
        self.assertEqual(await rewards.claim_daily(db, 1, now=1000.0), (True, 2))
        ok, wait = await rewards.claim_daily(db, 1, now=1000.0 + 3600)
        self.assertFalse(ok); self.assertEqual(wait, 86400 - 3600)
        self.assertEqual(await rewards.claim_daily(db, 1, now=1000.0 + 86400), (True, 2))
        self.assertEqual((await db["users"].find_one({"_id": 1}))["credits"], 9)

    async def test_daily_off_and_unknown_user(self):
        db = FakeDB(); rewards.DAILY_BONUS_CREDITS = 0
        self.assertEqual(await rewards.claim_daily(db, 1), (False, -1))
        rewards.DAILY_BONUS_CREDITS = 2
        self.assertFalse((await rewards.claim_daily(db, 99))[0])

    async def test_referral_rewards_both_sides_once(self):
        db = FakeDB(); now = 10_000.0
        await user(db, 1, 0); await user(db, 2, now - 60); await user(db, 5, 0)
        self.assertEqual(await rewards.register_referral(db, 2, 1, now), (True, "ok"))
        self.assertEqual((await db["users"].find_one({"_id": 1}))["credits"], 8)       # 5 + 3
        self.assertEqual((await db["users"].find_one({"_id": 2}))["credits"], 6)       # 5 + 1
        self.assertEqual((await db["users"].find_one({"_id": 2}))["referred_by"], 1)
        self.assertEqual(await rewards.register_referral(db, 2, 1, now), (False, "already"))
        self.assertEqual((await db["users"].find_one({"_id": 1}))["credits"], 8)        # no double pay
        self.assertEqual(await rewards.register_referral(db, 2, 5, now), (False, "already"))  # cannot be re-referred
        self.assertEqual((await db["users"].find_one({"_id": 5}))["credits"], 5)              # 5 got nothing

    async def test_self_old_account_banned_inviter_unknown_inviter(self):
        db = FakeDB(); now = 10_000_000.0
        await user(db, 1, 0); await user(db, 2, 0); await user(db, 3, now - 5, ); await user(db, 4, 0, ban=True)
        self.assertEqual(await rewards.register_referral(db, 1, 1, now), (False, "self"))
        self.assertEqual(await rewards.register_referral(db, 2, 1, now), (False, "not_new"))   # old account
        self.assertEqual(await rewards.register_referral(db, 3, 4, now), (False, "no_inviter"))
        self.assertEqual(await rewards.register_referral(db, 3, 777, now), (False, "no_inviter"))
        await db["users"].insert_one({"_id": 8, "credits": 5})                        # legacy account, no `joined`
        self.assertEqual(await rewards.register_referral(db, 8, 1, now), (False, "not_new"))

    async def test_cap(self):
        db = FakeDB(); now = 5_000.0
        await user(db, 1, 0)
        for uid in (10, 11, 12):
            await user(db, uid, now - 1)
        self.assertTrue((await rewards.register_referral(db, 10, 1, now))[0])
        self.assertTrue((await rewards.register_referral(db, 11, 1, now))[0])
        self.assertEqual(await rewards.register_referral(db, 12, 1, now), (False, "cap"))
        self.assertEqual((await db["users"].find_one({"_id": 1}))["credits"], 5 + 6)

    async def test_disabled(self):
        db = FakeDB(); rewards.REFERRAL_CREDITS = 0; rewards.REFERRAL_NEW_USER_CREDITS = 0
        await user(db, 1, 0); await user(db, 2, 99)
        self.assertEqual(await rewards.register_referral(db, 2, 1, 100.0), (False, "disabled"))


if __name__ == "__main__":
    unittest.main()
