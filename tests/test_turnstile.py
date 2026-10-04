import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tests  # noqa: F401
from helper import turnstile  # noqa: E402


class TurnstileTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.old = (turnstile.ENABLED, turnstile._post)
        turnstile.ENABLED = True
        self.calls = []

    def tearDown(self):
        turnstile.ENABLED, turnstile._post = self.old

    def reply(self, result):
        async def fake(data):
            self.calls.append(data)
            if isinstance(result, Exception):
                raise result
            return result
        turnstile._post = fake

    async def test_success_sends_secret_token_and_ip(self):
        self.reply({"success": True, "hostname": "x"})
        self.assertTrue(await turnstile.check("tok123", "1.2.3.4"))
        self.assertEqual(self.calls[0]["response"], "tok123"); self.assertEqual(self.calls[0]["remoteip"], "1.2.3.4")
        self.assertTrue(self.calls[0]["secret"] is not None)

    async def test_refused_replayed_and_garbage_tokens(self):
        self.reply({"success": False, "error-codes": ["timeout-or-duplicate"]})
        self.assertFalse(await turnstile.check("used-before"))
        self.reply({"success": "true"}); self.assertFalse(await turnstile.check("t"))          # only the real boolean counts
        self.reply(["not", "a", "dict"]); self.assertFalse(await turnstile.check("t"))
        self.calls.clear(); self.reply({"success": True})
        for bad in (None, "", 123, "x" * 5000, {"a": 1}):
            self.assertFalse(await turnstile.check(bad))
        self.assertEqual(self.calls, [])                                                       # no request wasted on junk

    async def test_cloudflare_down_fails_closed(self):
        self.reply(TimeoutError("down"))
        self.assertFalse(await turnstile.check("tok"))

    async def test_off_means_everything_passes(self):
        turnstile.ENABLED = False
        self.assertTrue(await turnstile.check(None)); self.assertEqual(turnstile.site_key(), "")


if __name__ == "__main__":
    unittest.main()
