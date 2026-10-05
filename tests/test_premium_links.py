import os, re, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helper import help_text, links  # noqa: E402
from tests.fakedb import FakeDB  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class LinkOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_recent_and_owner_checks(self):
        db = FakeDB()
        a = await links.create(db, "Z2V0LTE", 5, 3600)       # made by premium user 5
        b = await links.create(db, "Z2V0LTI", 1, 3600)       # made by admin 1
        self.assertEqual({d["_id"] for d in await links.recent(db, 15)}, {a["_id"], b["_id"]})
        self.assertEqual([d["_id"] for d in await links.recent(db, 15, 5)], [a["_id"]])
        self.assertEqual(await links.recent(db, 15, 77), [])
        self.assertTrue(await links.is_owned_by(db, links.PREFIX + a["_id"], 5))
        self.assertFalse(await links.is_owned_by(db, links.PREFIX + b["_id"], 5))
        self.assertFalse(await links.is_owned_by(db, "lk_doesnotexist", 5))


class HelpTests(unittest.TestCase):
    def test_premium_sees_member_commands_but_not_admin_ones(self):
        text = help_text.render(False, False, True)
        for c in ("/explink", "/links", "/revoke"):
            self.assertIn(c, text)
        for c in ("/ban", "/broadcast", "/addpremium", "/autoquality", "/adddb", "/genlink"):
            self.assertNotIn(c + " ", text)
        self.assertNotIn("/explink", help_text.render(False, False, False))
        self.assertIn("/genlink", help_text.render(True))


class WiringTests(unittest.TestCase):
    def _src(self, name): return open(os.path.join(ROOT, "plugins", name), encoding="utf-8").read()

    def test_member_commands_use_premium_check_and_admin_commands_do_not(self):
        ex = self._src("explink.py")
        self.assertEqual(ex.count("has_premium_access(client"), 3)
        for name in ("link_generator.py", "flink.py", "auto_quality.py", "broadcast.py", "pro_users.py"):
            self.assertNotIn("has_premium_access", self._src(name), name)   # they show DB-channel info / change settings

    def test_default_upload_access_is_premium(self):
        cfg = open(os.path.join(ROOT, "config.py"), encoding="utf-8").read()
        self.assertIn('or "premium")', cfg)


if __name__ == "__main__":
    unittest.main()
