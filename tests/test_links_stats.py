import asyncio
import os
import sys
import unittest
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helper import links, stats          # noqa: E402
from tests.fakedb import FakeDB          # noqa: E402


class LinkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = FakeDB()

    def test_parse_duration(self):
        self.assertEqual(links.parse_duration("24h"), 86400)
        self.assertEqual(links.parse_duration("7d"), 7 * 86400)
        self.assertEqual(links.parse_duration("90m"), 5400)
        self.assertEqual(links.parse_duration("2"), 7200)       # bare number = hours
        self.assertEqual(links.parse_duration("0"), 0)
        self.assertEqual(links.parse_duration("never"), 0)
        self.assertIsNone(links.parse_duration("soon"))
        self.assertIsNone(links.parse_duration("-5h"))

    async def test_max_uses_counts_people_not_opens(self):
        doc = await links.create(self.db, "abc", 1, max_uses=2)
        t = doc["_id"]
        self.assertEqual(await links.reserve(self.db, t, 100), "ok")
        self.assertEqual(await links.reserve(self.db, t, 100), "ok")     # same person again: free
        self.assertEqual(await links.reserve(self.db, t, 200), "ok")
        self.assertEqual(await links.reserve(self.db, t, 300), "full")   # third person: no slot
        d = await links.get(self.db, t)
        self.assertEqual((d["uses"], d["left"]), (2, 0))
        # the failed claim did not leave a ghost hit behind
        self.assertIsNone(await self.db["link_hits"].find_one({"_id": f"{t}:300"}))
        # someone who already got it can still fetch it again after it is full
        state, _ = await links.check(self.db, t, 100)
        self.assertEqual(state, "ok")
        state, _ = await links.check(self.db, t, 300)
        self.assertEqual(state, "full")

    async def test_release_returns_the_slot(self):
        doc = await links.create(self.db, "abc", 1, max_uses=1)
        t = doc["_id"]
        self.assertEqual(await links.reserve(self.db, t, 1), "ok")
        await links.release(self.db, t, 1)
        d = await links.get(self.db, t)
        self.assertEqual((d["uses"], d["left"]), (0, 1))
        self.assertEqual(await links.reserve(self.db, t, 2), "ok")

    async def test_unlimited_link_counts_uses(self):
        doc = await links.create(self.db, "abc", 1)
        t = doc["_id"]
        for uid in range(5):
            self.assertEqual(await links.reserve(self.db, t, uid), "ok")
        d = await links.get(self.db, t)
        self.assertEqual((d["uses"], d["left"], d["max_uses"]), (5, -1, 0))
        await links.release(self.db, t, 0)
        self.assertEqual((await links.get(self.db, t))["uses"], 4)

    async def test_expiry_and_revoke(self):
        doc = await links.create(self.db, "abc", 1, ttl_seconds=3600)
        t = doc["_id"]
        self.assertEqual((await links.check(self.db, t))[0], "ok")
        # push the expiry into the past
        await self.db["links"].update_one({"_id": t}, {"$set": {"expires_at": links._now() - timedelta(seconds=1)}})
        self.assertEqual((await links.check(self.db, t))[0], "expired")
        self.assertEqual(await links.reserve(self.db, t, 9), "expired")
        self.assertIsNone(await self.db["link_hits"].find_one({"_id": f"{t}:9"}))

        doc2 = await links.create(self.db, "abc", 1)
        self.assertTrue(await links.revoke(self.db, links.PREFIX + doc2["_id"]))   # accepts the lk_ form
        self.assertEqual((await links.check(self.db, doc2["_id"]))[0], "revoked")
        self.assertEqual(await links.reserve(self.db, doc2["_id"], 5), "revoked")
        self.assertFalse(await links.revoke(self.db, "nope"))
        self.assertEqual((await links.check(self.db, "nope"))[0], "missing")

    async def test_revoked_blocks_even_returning_users(self):
        doc = await links.create(self.db, "abc", 1)
        t = doc["_id"]
        await links.reserve(self.db, t, 7)
        await links.revoke(self.db, t)
        self.assertEqual(await links.reserve(self.db, t, 7), "revoked")

    def test_token_helpers(self):
        t = links.new_token()
        self.assertEqual(len(t), 12)
        self.assertTrue(links.is_managed(links.PREFIX + t))
        self.assertFalse(links.is_managed("Z2V0LTEyMw"))
        self.assertEqual(links.token_of(links.PREFIX + t), t)
        self.assertLessEqual(len(links.PREFIX + t), 64)


class StatsTests(unittest.IsolatedAsyncioTestCase):
    async def test_bump_and_series(self):
        db = FakeDB()
        await stats.bump(db, "clicks", 3)
        await stats.bump(db, "delivered")
        rows = await stats.series(db, 7)
        self.assertEqual(len(rows), 7)
        self.assertEqual(rows[-1]["clicks"], 3)
        self.assertEqual(rows[-1]["delivered"], 1)
        self.assertEqual(rows[0]["clicks"], 0)
        self.assertEqual(rows[-1]["day"], stats.day_key())

    async def test_click_counter_and_top(self):
        db = FakeDB()
        for _ in range(3):
            await stats.count_click(db, "AAA")
        await stats.count_click(db, "BBB")
        top = await stats.top_links(db, 5)
        self.assertEqual([(t["_id"], t["clicks"]) for t in top], [("AAA", 3), ("BBB", 1)])
        self.assertEqual((await stats.link_detail(db, "AAA"))["clicks"], 3)

    async def test_never_raises(self):
        class Broken:
            def __getitem__(self, k):
                raise RuntimeError("db down")
        await stats.bump(Broken(), "clicks")
        await stats.count_click(Broken(), "x")
        self.assertEqual(len(await stats.series(Broken(), 3)), 3)


if __name__ == "__main__":
    unittest.main()


class ExtractTests(unittest.TestCase):
    def test_extract_payload(self):
        e = links.extract_payload
        self.assertEqual(e("https://t.me/mybot?start=Z2V0LTEyMw"), "Z2V0LTEyMw")
        self.assertEqual(e("https://worker.dev/?url=Z2V0LTEyMw"), "Z2V0LTEyMw")
        self.assertEqual(e("  Z2V0LTEyMw  "), "Z2V0LTEyMw")
        self.assertEqual(e("t.me/mybot?start=abc_-9&x=1"), "abc_-9")
        self.assertIsNone(e("")); self.assertIsNone(e("hello world!")); self.assertIsNone(e("a" * 65)); self.assertIsNone(e(None))
