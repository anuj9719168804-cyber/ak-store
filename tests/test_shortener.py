"""Shortener: get_short fallbacks, the honest probe behind the panel / Test button, and the old verify flow."""
import os, sys, unittest
from types import SimpleNamespace as NS
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tests  # noqa: F401  (stubs)
import plugins.shortner as sh  # noqa: E402
import plugins.start as start  # noqa: E402
from helper import verify_web as vw  # noqa: E402
from tests.test_start_flow import Base, run  # noqa: E402


class Resp:
    def __init__(self, code, js=None, text=""):
        self.status_code, self._js, self.text = code, js, text

    def json(self):
        if self._js is None:
            raise ValueError("no json")
        return self._js


class Patched(unittest.TestCase):
    def setUp(self):
        self._get = sh.requests.get
        self.calls = []
        sh.shortened_urls_cache.clear()

    def tearDown(self):
        sh.requests.get = self._get

    def answer(self, resp):
        def fake(url, params=None, timeout=None):
            self.calls.append((url, dict(params or {})))
            if isinstance(resp, Exception):
                raise resp
            return resp
        sh.requests.get = fake


class GetShortTests(Patched):
    client = NS(shortner_enabled=True, short_url="s.example", short_api="key")

    def test_success_fallbacks_and_cache(self):
        url = "https://t.me/bot?start=abc"
        self.answer(Resp(200, {"status": "success", "shortenedUrl": "https://s.example/ab"}))
        self.assertEqual(sh.get_short(url, self.client), "https://s.example/ab")
        self.assertEqual(sh.get_short(url, self.client), "https://s.example/ab")
        self.assertEqual(len(self.calls), 1)                                   # second answer came from the cache
        for bad in (Resp(200, {"status": "error", "message": "Invalid API token"}), Resp(500, None, "oops"),
                    Resp(200, ["x"]), RuntimeError("down")):
            sh.shortened_urls_cache.clear()
            self.answer(bad)
            self.assertEqual(sh.get_short(url, self.client), url)               # always something usable
        sh.shortened_urls_cache.clear()
        self.answer(Resp(200, None, "https://s.example/zz"))
        self.assertEqual(sh.get_short(url, self.client), "https://s.example/zz")   # plain-text shorteners
        off = NS(shortner_enabled=False, short_url="s.example", short_api="key")
        self.assertEqual(sh.get_short(url, off), url)


class ProbeTests(Patched):
    def test_wrong_api_key_is_not_reported_as_working(self):
        self.answer(Resp(200, {"status": "error", "message": "Invalid API token"}))
        self.assertEqual(sh.probe_api("s.example", "bad"), (False, "Invalid API token"))   # HTTP 200 but NOT working

    def test_working_plain_text_and_failures(self):
        self.answer(Resp(200, {"status": "success", "shortenedUrl": "https://s.example/q"}))
        self.assertEqual(sh.probe_api("s.example", "k"), (True, "https://s.example/q"))
        self.answer(Resp(200, None, "https://s.example/t"))
        self.assertEqual(sh.probe_api("s.example", "k"), (True, "https://s.example/t"))
        self.answer(Resp(503, None, "busy"))
        self.assertEqual(sh.probe_api("s.example", "k"), (False, "HTTP 503"))
        self.answer(RuntimeError("timeout"))
        self.assertEqual(sh.probe_api("s.example", "k"), (False, "timeout"))

    def test_alias_is_new_every_time(self):
        self.answer(Resp(200, {"status": "success", "shortenedUrl": "https://s.example/q"}))
        for _ in range(5):
            sh.probe_api("s.example", "k")
        aliases = {p["alias"] for _, p in self.calls}
        self.assertGreater(len(aliases), 1)                                     # a fixed alias is refused from the 2nd test on
        self.assertNotIn("test", aliases)


class OldFlowTests(Base):
    async def test_shortener_down_does_not_hand_out_the_bare_link_or_strike_the_user(self):
        vw.VERIFY_WEB_ACTIVE = False
        async def broken(url, client): return url
        start.get_short_async = broken
        await self.add_user(10, credits=0)
        m = await run(self.c, 10, f"/start {self.payload}")
        self.assertEqual(self.c.photos, [])                                     # no "Open link" button with the t.me link
        self.assertTrue(any("Couldn't generate" in r for r in m.replies))
        saved = await self.db["users"].find_one({"_id": 10})
        self.assertFalse(saved.get("verify_payload"))                           # no half-open session left behind

    async def test_shortener_up_still_sends_the_short_link(self):
        vw.VERIFY_WEB_ACTIVE = False
        await self.add_user(10, credits=0)
        await run(self.c, 10, f"/start {self.payload}")
        self.assertEqual(self.c.photos[-1]["reply_markup"].inline_keyboard[0][0].url, "https://short.example/s")


if __name__ == "__main__":
    unittest.main()
