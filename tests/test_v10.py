import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tests  # noqa: F401
from datetime import datetime
from jinja2 import Environment, FileSystemLoader  # noqa: E402
from helper import support, trial, codes  # noqa: E402
from helper.utils import split_ban_args, ban_notice  # noqa: E402
from tests.test_start_flow import make_mongo  # noqa: E402
from web import data10  # noqa: E402


class BanTests(unittest.IsolatedAsyncioTestCase):
    def test_split_args(self):
        self.assertEqual(split_ban_args(["1", "2", "spam", "bot"]), ([1, 2], "spam bot"))
        self.assertEqual(split_ban_args(["spam"]), ([], "spam"))
        self.assertEqual(len(split_ban_args(["1", "x" * 500])[1]), 200)

    async def test_reason_roundtrip(self):
        m = make_mongo()
        await m.add_user(7)
        await m.ban_user(7, "  spamming ")
        self.assertTrue(await m.is_banned(7))
        self.assertEqual(await m.get_ban_reason(7), "spamming")
        self.assertIn("spamming", await ban_notice(m, 7))
        await m.unban_user(7)
        self.assertEqual(await m.get_ban_reason(7), "")
        self.assertEqual(await ban_notice(m, 7), "**You have been banned from using this bot!**")

    async def test_ban_without_reason_clears_old_one(self):
        m = make_mongo(); await m.add_user(7)
        await m.ban_user(7, "a"); await m.ban_user(7)
        self.assertEqual(await m.get_ban_reason(7), "")

    async def test_unban_all_clears_reasons(self):
        m = make_mongo()
        for u in (5, 6): await m.add_user(u); await m.ban_user(u, "x")
        self.assertEqual(await m.unban_all_users(), 2)
        rows, total = await data10.banned_users(m)
        self.assertEqual(total, 0)


class SupportTests(unittest.IsolatedAsyncioTestCase):
    async def test_flow(self):
        db = make_mongo().db
        t = await support.add_user_message(db, 9, " hello ", "Ann", "ann")
        self.assertEqual((t["unread"], t["open"], t["msgs"]), (1, True, 1))
        await support.add_user_message(db, 9, "again")
        self.assertEqual((await support.counts(db)), {"open": 1, "unread": 1})
        t = await support.add_admin_reply(db, 9, "ok", "1")
        self.assertEqual((t["unread"], t["last_from"], t["msgs"]), (0, "admin", 3))
        self.assertEqual([m["sender"] for m in await support.messages(db, 9)], ["user", "user", "admin"])
        await support.set_open(db, 9, False)
        self.assertEqual(await support.threads(db), [])
        self.assertEqual(len(await support.threads(db, only_open=False)), 1)

    async def test_rejects_empty_and_unknown(self):
        db = make_mongo().db
        with self.assertRaises(ValueError): await support.add_user_message(db, 1, "   ")
        with self.assertRaises(LookupError): await support.add_admin_reply(db, 1, "x")

    async def test_cooldown(self):
        db = make_mongo().db
        self.assertEqual(await support.seconds_until_allowed(db, 3, 30, now=1000), 0)
        await support.add_user_message(db, 3, "hi")
        import time
        self.assertGreater(await support.seconds_until_allowed(db, 3, 30), 0)
        self.assertEqual(await support.seconds_until_allowed(db, 3, 0), 0)
        self.assertEqual(await support.seconds_until_allowed(db, 3, 30, now=time.time() + 31), 0)

    async def test_text_is_cut(self):
        db = make_mongo().db
        await support.add_user_message(db, 4, "a" * 5000)
        self.assertEqual(len((await support.messages(db, 4))[0]["text"]), support.MAX_TEXT)


class TrialTests(unittest.IsolatedAsyncioTestCase):
    async def test_once_only(self):
        m = make_mongo()
        self.assertEqual((await trial.claim(m, 5, 0))[0], "off")
        self.assertEqual((await trial.claim(m, 5, 3))[0], "ok")
        self.assertTrue(await m.is_pro(5))
        await m.remove_pro(5)
        self.assertEqual((await trial.claim(m, 5, 3))[0], "used")
        self.assertFalse(await m.is_pro(5))

    async def test_premium_user_keeps_trial(self):
        m = make_mongo(); await m.add_user(6); await m.add_pro(6, None)
        self.assertEqual((await trial.claim(m, 6, 3))[0], "premium")
        self.assertFalse((await m.user_data.find_one({"_id": 6})).get("trial_used"))


class AdjustCreditsTests(unittest.IsolatedAsyncioTestCase):
    async def test_modes_and_floor(self):
        m = make_mongo(); await m.add_user(8)      # starts with 5
        self.assertEqual(await data10.adjust_credits(m, 8, "add", 10), (5, 15))
        self.assertEqual(await data10.adjust_credits(m, 8, "deduct", 100), (15, 0))
        self.assertEqual(await data10.adjust_credits(m, 8, "set", 7), (0, 7))
        self.assertEqual(await m.get_credits(8), 7)
        led = await data10.user_detail(m, 8)
        self.assertEqual([r["delta"] for r in led["ledger"]].count(10), 1)

    async def test_bad_input(self):
        m = make_mongo(); await m.add_user(8)
        for args in (("bogus", 1), ("add", 0), ("add", -1)):
            with self.assertRaises(ValueError): await data10.adjust_credits(m, 8, *args)
        with self.assertRaises(LookupError): await data10.adjust_credits(m, 999, "add", 1)


class CodesAdminTests(unittest.IsolatedAsyncioTestCase):
    async def test_switch_and_delete(self):
        db = make_mongo().db
        await codes.create(db, "credits", 5, 2, "panel", code="WELCOME")
        self.assertTrue(await codes.set_active(db, "welcome", False))
        self.assertEqual(data10.code_rows(await codes.recent(db))[0]["state"], "off")
        self.assertTrue(await codes.set_active(db, "WELCOME", True))
        self.assertEqual(data10.code_rows(await codes.recent(db))[0]["state"], "ok")
        self.assertTrue(await codes.remove(db, "WELCOME"))
        self.assertFalse(await codes.remove(db, "WELCOME"))
        self.assertFalse(await codes.set_active(db, "NOPE", True))


class DetailAndBoardTests(unittest.IsolatedAsyncioTestCase):
    async def test_user_detail_and_board(self):
        m = make_mongo()
        await m.add_user(10); await m.add_user(11)
        await m.user_data.update_one({"_id": 10}, {"$set": {"referrals": 3}})
        await m.db["referrals"].insert_one({"_id": 11, "inviter": 10, "at": 1.0, "qualified": True})
        self.assertIsNone(await data10.user_detail(m, 1))
        self.assertIsNone(await data10.user_detail(m, 424242))
        d = await data10.user_detail(m, 10)
        self.assertEqual(d["referrals"], 3); self.assertEqual(d["invited"][0]["id"], 11)
        rows, total, summary = await data10.referral_board(m)
        self.assertEqual((rows[0]["id"], total, summary["paid_out"]), (10, 1, 1))


class TemplateTests(unittest.TestCase):
    def setUp(self):
        self.env = Environment(loader=FileSystemLoader("templates"), autoescape=True)
        from helper.timefmt import ist
        self.env.globals.update(panel="/admin", csrf_token=lambda: "tok", ist=ist)
        self.evil = '<img src=x onerror=alert(1)>'

    def render(self, name, **ctx):
        out = self.env.get_template(name).render(flashes=[], **ctx)
        self.assertNotIn(self.evil, out)
        return out

    def test_all_new_pages_escape_hostile_data(self):
        e, now = self.evil, datetime(2026, 1, 1)
        u = dict(id=5, credits=3, banned=True, ban_reason=e, banned_at=now, joined=now, verified=True, premium=True,
                 premium_expired=False, premium_until=now, premium_lifetime=False, referrals=1, referred_by=9,
                 invited=[{"id": 6, "at": now, "qualified": False}], trial_used=True, last_daily=None,
                 ledger=[{"at": now, "delta": -2, "kind": e, "ref": e, "note": e}],
                 orders=[{"created": now, "kind": e, "plan": e, "method": "x", "currency": "INR", "amount": 100, "status": e}],
                 support={"msgs": 2, "unread": 1})
        self.assertIn("&lt;img", self.render("user_detail.html", u=u, is_admin=False))
        self.render("bans.html", rows=[{"id": 5, "reason": e, "at": now}], total=1)
        self.render("referrals.html", rows=[{"id": 1, "referrals": 2, "credits": 3}], total=1, page=1, has_next=False,
                    first_rank=1, summary={"invited_total": 1, "paid_out": 1, "waiting": 0})
        self.render("codes.html", rows=[{"code": e, "kind": "credits", "amount": 5, "uses": 0, "max_uses": 2, "left": 2,
                                         "expires_at": None, "state": "ok", "note": e, "created": now, "created_by": "x"}])
        self.render("support.html", rows=[{"_id": 5, "name": e, "username": e, "msgs": 1, "last_at": now, "last_from": "user",
                                           "unread": 1, "open": True}], show_all=False, counts={"open": 1, "unread": 1})
        self.render("support_thread.html", t={"_id": 5, "name": e, "username": e, "open": True},
                    msgs=[{"sender": "user", "text": e, "at": now}])
        self.render("restart.html", restarting=False)
        self.assertIn("setTimeout", self.render("restart.html", restarting=True))

    def test_dashboard_and_settings(self):
        stats = dict(users=1, banned=0, premium=0, files=0, files_size="0 B", downloads=0, admins=1)
        today = dict(clicks=0, delivered=0, new_users=0, verified=0, bypass=0, revenue=0)
        out = self.render("dashboard.html", stats=stats, uptime="1h", today=today, db_count=1, fsub_count=0,
                          web_links=True, support={"open": 2, "unread": 1})
        self.assertIn('data-stat="support_open"', out)
        out = self.render("settings.html", s=dict(protect=True, shortner=True, auto_del=0, permanent_link=False),
                          permanent_url="", maintenance=True)
        self.assertRegex(out, r'name="maintenance"\s+checked')


if __name__ == "__main__":
    unittest.main()


class BanGuardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from helper import banguard
        self.g = banguard; banguard.clear()

    def test_cache_ttl(self):
        self.assertIsNone(self.g.get(1, now=0))
        self.g.put(1, True, now=0)
        self.assertTrue(self.g.get(1, now=self.g.TTL - 1))
        self.assertIsNone(self.g.get(1, now=self.g.TTL + 1))

    async def test_ban_and_unban_take_effect_at_once(self):
        m = make_mongo(); await m.add_user(5)
        self.g.put(5, False)                  # guard cached "not banned"
        await m.ban_user(5, "x")
        self.assertIsNone(self.g.get(5))      # cache dropped -> next message asks the database
        self.g.put(5, True)
        await m.unban_user(5)
        self.assertIsNone(self.g.get(5))

    async def test_unban_all_and_pre_ban_clear_cache(self):
        m = make_mongo(); await m.add_user(5)
        self.g.put(5, True); self.g.put(6, False)
        await m.unban_all_users()
        self.assertIsNone(self.g.get(5)); self.assertIsNone(self.g.get(6))
        self.g.put(9, False)
        await m.add_user(9, True)
        self.assertIsNone(self.g.get(9))

    def test_guard_handlers_are_registered_before_everything(self):
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugins", "ban_guard.py")).read()
        self.assertEqual(src.count("group=-25"), 2)


class IstTests(unittest.TestCase):
    def test_conversion(self):
        from helper.timefmt import ist
        self.assertEqual(ist(datetime(2026, 1, 1, 20, 0)), "2026-01-02 01:30")      # +5:30 crosses midnight
        self.assertEqual(ist(datetime(2026, 1, 1, 0, 0), "%H:%M"), "05:30")
        self.assertEqual(ist(None), "-")
        self.assertEqual(ist("2026-01-01"), "-")

    def test_no_panel_page_still_says_utc(self):
        import glob
        for f in glob.glob("templates/*.html"):
            if f.endswith("premium.html"):
                continue
            self.assertNotIn("UTC", open(f, encoding="utf-8").read(), f)


class LinkTtlTests(unittest.IsolatedAsyncioTestCase):
    def test_parse(self):
        from helper.linkttl import parse_duration as p
        self.assertEqual((p("1h30m"), p("45m"), p("2d"), p("3600"), p("0"), p("OFF")), (5400, 2700, 172800, 3600, 0, 0))
        for bad in ("", "abc", "1x", "-5", "1.5h", "9999d", "h"):
            self.assertIsNone(p(bad), bad)

    def test_readable(self):
        from helper.linkttl import readable
        self.assertEqual(readable(5400), "1h 30m"); self.assertEqual(readable(86400), "1d")
        self.assertIn("never", readable(0))

    async def test_override_is_used_for_signing_and_survives_reload(self):
        import time
        from helper import linkttl, stream_links
        m = make_mongo()
        try:
            await linkttl.save(m, 600)
            exp = int(stream_links.sign_query("1_2").split("&")[0].split("=")[1])
            self.assertLessEqual(abs(exp - (time.time() + 600)), 5)
            linkttl.apply(None)
            await linkttl.load(m)                                   # "restart"
            self.assertEqual(linkttl.get(), 600)
            await linkttl.save(m, 0)
            self.assertEqual(stream_links.sign_query("1_2").split("&")[0], "exp=0")
            await linkttl.save(m, None)
            self.assertFalse(linkttl.is_override())
        finally:
            linkttl.apply(None)


class LogViewTests(unittest.TestCase):
    def test_redaction(self):
        from helper.logview import redact
        tok = "123456789:" + "A" * 35
        text = (f"error calling https://short.io/api?api=SECRETKEY123&url=x\nuri mongodb+srv://u:p%40ss@c.mongodb.net/db?x=1\n"
                f"token {tok}\npw hunter2222 and key=abc123 and sig=ff00\nplain line stays")
        out = redact(text, secrets=["hunter2222", "", "ab"])
        for leaked in ("SECRETKEY123", "p%40ss", tok, "hunter2222", "abc123", "ff00"):
            self.assertNotIn(leaked, out)
        self.assertIn("plain line stays", out)
        self.assertIn("url=x", out)                      # harmless parameters survive
        self.assertIn("ab", redact("a ab c", secrets=["ab"]))   # too-short secrets are not blanked

    def test_tail(self):
        import tempfile
        from helper.logview import tail
        with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False, encoding="utf-8") as fh:
            fh.write("".join(f"line {i}\n" for i in range(1000)))
        try:
            out = tail(fh.name, 200)
            self.assertTrue(out.endswith("line 999\n"))
            self.assertTrue(out.startswith("line "))     # never starts mid-line
            self.assertLess(len(out), 220)
            self.assertEqual(tail("/nonexistent/x.log"), "")
        finally:
            os.unlink(fh.name)


class BroadcastKeepsBansTests(unittest.IsolatedAsyncioTestCase):
    async def test_del_user_does_not_erase_a_ban(self):
        m = make_mongo()
        await m.add_user(1001); await m.add_user(1002)
        await m.ban_user(1001, "abuse")
        self.assertFalse(await m.del_user(1001))          # banned: kept
        self.assertTrue(await m.is_banned(1001))
        self.assertTrue(await m.del_user(1002))           # normal user: removed
        self.assertFalse(await m.present_user(1002))
