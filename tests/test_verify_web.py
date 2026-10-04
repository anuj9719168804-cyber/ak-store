import hashlib
import os
import sys
import unittest
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helper import verify_web as vw      # noqa: E402
from tests.fakedb import FakeDB          # noqa: E402

UA = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/126.0 Mobile Safari/537.36"
GOOD_GO = {"wd": False}
GOOD_VERIFY = {"wd": False, "trusted": True, "ptr": 3, "ms": 4200}


def solve(challenge, bits=None):
    bits = vw.POW_BITS if bits is None else bits
    n = 0
    while True:
        h = hashlib.sha256(f"{challenge}:{n}".encode()).digest()
        if int.from_bytes(h, "big") >> (256 - bits) == 0:
            return str(n)
        n += 1


class VerifyFlow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = FakeDB()
        vw.MIN_SECONDS = 45
        vw.MAX_SECONDS = 240
        doc = await vw.create(self.db, 111, "Z2V0LTEyMw")
        self.tid = doc["_id"]
        await vw.set_short(self.db, self.tid, "https://short.example/abc")
        self.doc = doc

    async def go(self, now_ts=1000.0, **over):
        args = dict(ua=UA, ip="1.2.3.4", nonce=solve(self.doc["ch1"]), signals=GOOD_GO, now_ts=now_ts)
        args.update(over)
        return await vw.begin_go(self.db, self.tid, **args)

    async def fin(self, now_ts=1060.0, **over):
        uah = vw.ua_hash(UA)
        args = dict(ua=UA, ip="1.2.3.4", cookie=vw.cookie_value(self.tid, uah), nonce=solve(self.doc["ch2"]),
                    signals=GOOD_VERIFY, referer="https://short.example/x", short_domain="short.example",
                    now_ts=now_ts)
        args.update(over)
        return await vw.finish(self.db, self.tid, **args)

    async def test_happy_path_and_single_use(self):
        code, doc = await self.go()
        self.assertEqual(code, "ok")
        self.assertEqual(doc["short_url"], "https://short.example/abc")
        code, doc, elapsed = await self.fin(now_ts=1060.0)
        self.assertEqual((code, round(elapsed)), ("ok", 60))
        # wrong user cannot redeem and learns nothing
        self.assertEqual((await vw.redeem(self.db, self.tid, 222))[0], "wrong_user")
        code, taken = await vw.redeem(self.db, self.tid, 111)
        self.assertEqual((code, taken["payload"]), ("ok", "Z2V0LTEyMw"))
        self.assertEqual((await vw.redeem(self.db, self.tid, 111))[0], "used")     # single use

    async def test_redeem_before_passing(self):
        self.assertEqual((await vw.redeem(self.db, self.tid, 111))[0], "not_passed")
        await self.go()
        self.assertEqual((await vw.redeem(self.db, self.tid, 111))[0], "not_passed")

    async def test_skipping_step_two_fails(self):
        # straight to /verify without ever running /go (what a bypass tool does)
        code, _, _ = await self.fin()
        self.assertEqual(code, "bad_state")

    async def test_too_fast_burns_the_token(self):
        await self.go(now_ts=1000.0)
        code, _, elapsed = await self.fin(now_ts=1010.0)
        self.assertEqual(code, "too_fast")
        self.assertAlmostEqual(elapsed, 10.0)
        # a retry (even after waiting) cannot revive it
        code, _, _ = await self.fin(now_ts=1100.0)
        self.assertEqual(code, "bad_state")
        self.assertEqual((await vw.redeem(self.db, self.tid, 111))[0], "failed")

    async def test_too_slow_expires(self):
        await self.go(now_ts=1000.0)
        code, _, _ = await self.fin(now_ts=1000.0 + 241)
        self.assertEqual(code, "expired")

    async def test_cookie_missing_other_device_rejected(self):
        await self.go()
        code, _, _ = await self.fin(cookie=None, ip="9.9.9.9")
        self.assertEqual(code, "cookie")

    async def test_cookie_missing_same_device_accepted_by_fallback(self):
        await self.go(ip="10.20.30.4")
        code, doc, _ = await self.fin(cookie=None, ip="10.20.30.77")     # same /24, same UA
        self.assertEqual(code, "ok")
        self.assertFalse(doc["cookie_ok"])

    async def test_forged_cookie_other_ip_rejected(self):
        await self.go()
        code, _, _ = await self.fin(cookie="0" * 32, ip="8.8.8.8")
        self.assertEqual(code, "cookie")

    async def test_other_browser_rejected(self):
        await self.go()
        code, _, _ = await self.fin(ua=UA + " Other")
        self.assertEqual(code, "ua")

    async def test_bad_pow_and_signals(self):
        self.assertEqual((await self.go(nonce="123"))[0], "browser")          # not a solution (overwhelmingly)
        self.assertEqual((await self.go(signals={"wd": True}))[0], "browser")  # webdriver flag
        self.assertEqual((await self.go(ua="python-requests/2.31 (compatible)"))[0], "browser")
        await self.go()
        for bad in ({"wd": False, "trusted": False, "ptr": 3, "ms": 4000},     # synthetic click
                    {"wd": False, "trusted": True, "ptr": 0, "ms": 4000},      # no pointer events
                    {"wd": False, "trusted": True, "ptr": 2, "ms": 100},       # tapped instantly
                    {"wd": True, "trusted": True, "ptr": 2, "ms": 4000}, "junk", None):
            self.assertEqual((await self.fin(signals=bad))[0], "browser", bad)
        self.assertEqual((await self.fin(nonce="5"))[0], "browser")
        self.assertEqual((await self.fin())[0], "ok")                          # real one still works

    async def test_pow_checker(self):
        n = solve("abc", 12)
        self.assertTrue(vw.pow_ok("abc", n, 12))
        self.assertFalse(vw.pow_ok("abd", n, 12) and vw.pow_ok("abe", n, 12) and vw.pow_ok("abf", n, 12))
        self.assertFalse(vw.pow_ok("abc", "-1", 12))
        self.assertFalse(vw.pow_ok("abc", "1e3", 12))
        self.assertFalse(vw.pow_ok("abc", "9" * 20, 12))
        self.assertTrue(vw.pow_ok("abc", "anything", 0))                        # bits=0: off

    async def test_expired_token(self):
        await self.go()
        await self.db["verify_tokens"].update_one({"_id": self.tid}, {"$set": {"expires_at": vw._now() - timedelta(seconds=1)}})
        self.assertEqual((await self.fin())[0], "expired")
        self.assertEqual((await self.go())[0], "expired")

    async def test_reload_after_pass_is_idempotent_but_needs_cookie(self):
        await self.go()
        self.assertEqual((await self.fin())[0], "ok")
        self.assertEqual((await self.fin())[0], "ok")
        self.assertEqual((await self.fin(cookie=None, ip="9.9.9.9"))[0], "cookie")

    async def test_token_format_guard(self):
        self.assertIsNone(await vw.get(self.db, "short"))
        self.assertIsNone(await vw.get(self.db, "../../etc/passwd" + "x" * 5))
        self.assertEqual((await vw.begin_go(self.db, "nope", ua=UA, ip="1.1.1.1", nonce="1", signals=GOOD_GO))[0], "missing")

    def test_referrer_state(self):
        self.assertTrue(vw.referrer_state("https://short.example/page", "short.example"))
        self.assertTrue(vw.referrer_state("https://go.short.example/p", "short.example"))
        self.assertFalse(vw.referrer_state("https://evil.example/", "short.example"))
        self.assertIsNone(vw.referrer_state("", "short.example"))

    def test_ip_block(self):
        self.assertEqual(vw.ip_block("1.2.3.4"), "1.2.3")
        self.assertEqual(vw.ip_block("2001:db8:1:2:3:4:5:6"), "2001:db8:1:2")


if __name__ == "__main__":
    unittest.main()


class RiskTests(VerifyFlow):
    def test_score_is_combination_based(self):
        s = vw.score_risk
        self.assertEqual(s(elapsed=60, baseline=60, ref=True, cookie_ok=True, ip_changed=False, velocity=1)[0], 0)
        self.assertLess(s(elapsed=60, baseline=60, ref=None, cookie_ok=False, ip_changed=True, velocity=1)[0], 70)    # sloppy but human
        self.assertGreaterEqual(s(elapsed=20, baseline=60, ref=False, cookie_ok=True, ip_changed=False, velocity=1)[0], 70)  # bypass-shaped
        self.assertIsNotNone(s(elapsed=1, baseline=None, ref=True, cookie_ok=True, ip_changed=False, velocity=1))
        self.assertEqual(s(elapsed=1, baseline=None, ref=True, cookie_ok=True, ip_changed=False, velocity=1)[0], 0)     # no baseline: no speed judgement
        self.assertLessEqual(s(elapsed=1, baseline=100, ref=False, cookie_ok=False, ip_changed=True, velocity=50)[0], 100)

    async def _seed(self, n, secs):
        for i in range(n):
            await self.db["verify_tokens"].insert_one({"_id": f"seed{i:012d}", "state": "used", "elapsed": secs + i % 3, "risk": 0, "pass_at": 1.0 + i})

    async def test_fast_without_referrer_is_blocked_once_baseline_exists(self):
        await self._seed(25, 120)                                      # real users take ~120 s
        await self.go(now_ts=1000.0)
        code, doc, _ = await self.fin(now_ts=1050.0, referer="https://evil.example/x")      # 50 s, not from the shortener
        self.assertEqual(code, "risky")
        stored = await vw.get(self.db, self.tid)
        self.assertEqual(stored["state"], "failed"); self.assertTrue(stored["blocked_by_risk"]); self.assertGreaterEqual(stored["risk"], 70)
        self.assertEqual((await vw.redeem(self.db, self.tid, 111))[0], "failed")

    async def test_normal_user_passes_cleanly(self):
        await self._seed(25, 120)
        await self.go(now_ts=1000.0)
        code, doc, _ = await self.fin(now_ts=1000.0 + 122)
        self.assertEqual(code, "ok"); self.assertEqual(doc["risk"], 0); self.assertFalse(doc["flagged"])

    async def test_flag_only_mode_and_no_baseline(self):
        vw.RISK_ACTION = "flag"
        try:
            await self._seed(25, 120)
            await self.go(now_ts=1000.0)
            code, doc, _ = await self.fin(now_ts=1050.0, referer="https://evil.example/x")
            self.assertEqual(code, "ok"); self.assertTrue(doc["flagged"])                    # passes, but marked
        finally:
            vw.RISK_ACTION = "block"

    async def test_many_passes_from_one_network_raise_velocity(self):
        for i in range(6):
            await self.db["verify_tokens"].insert_one({"_id": f"v{i:015d}", "state": "passed", "pass_block": "1.2.3", "pass_at": 995.0})
        await self.go(now_ts=1000.0)
        code, doc, _ = await self.fin(now_ts=1060.0)
        self.assertGreaterEqual(doc["risk"], 30)
