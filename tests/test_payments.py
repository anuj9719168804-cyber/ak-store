import asyncio, hashlib, hmac, json, os, sys, unittest
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helper import payments as pay  # noqa: E402
from tests.fakedb import FakeDB  # noqa: E402


class Mongo:                              # the slice of helper.database.MongoDB that fulfill() uses
    def __init__(self):
        self.db = FakeDB(); self.user_data = self.db["users"]; self.premium_users = self.db["pros"]
    async def present_user(self, u): return await self.user_data.find_one({"_id": u}) is not None
    async def add_user(self, u): await self.user_data.insert_one({"_id": u, "credits": 5})
    async def add_credits(self, u, n): await self.user_data.update_one({"_id": u}, {"$inc": {"credits": n}})
    async def add_pro(self, u, exp): await self.premium_users.update_one({"_id": u}, {"$set": {"expiry_date": exp}}, upsert=True)
    async def get_expiry_date(self, u):
        d = await self.premium_users.find_one({"_id": u}); return d.get("expiry_date") if d else None
    async def is_pro(self, u):
        d = await self.premium_users.find_one({"_id": u})
        return bool(d) and (d.get("expiry_date") is None or d["expiry_date"] > datetime.now())


class Bot:
    owner = 1
    def __init__(self): self.mongodb = Mongo(); self.sent = []
    async def send_message(self, chat, text, **k): self.sent.append((chat, text))


def order(db_, oid="o1", kind="premium", plan="1m", cur="INR", amount=19900, uid=7):
    return db_["orders"].insert_one({"_id": oid, "user_id": uid, "kind": kind, "plan": plan, "method": "razorpay",
                                     "currency": cur, "amount": amount, "status": "created"})


class SignatureTests(unittest.TestCase):
    def test_razorpay(self):
        body = b'{"event":"payment_link.paid"}'
        sig = hmac.new(b"whsec", body, hashlib.sha256).hexdigest()
        self.assertTrue(pay.verify_razorpay(body, sig, "whsec"))
        self.assertFalse(pay.verify_razorpay(body + b" ", sig, "whsec"))      # raw body must match exactly
        self.assertFalse(pay.verify_razorpay(body, sig, "other"))
        self.assertFalse(pay.verify_razorpay(body, "", "whsec"))
        self.assertFalse(pay.verify_razorpay(body, sig, ""))                   # unset secret never validates

    def test_nowpayments_sorted_body(self):
        body = {"payment_status": "finished", "order_id": "o1", "price_amount": 2.5, "nested": {"b": 1, "a": [{"z": 1, "y": 2}]}}
        raw = json.dumps(body).encode()                                         # arrives in arbitrary key order
        canon = json.dumps({"nested": {"a": [{"y": 2, "z": 1}], "b": 1}, "order_id": "o1", "payment_status": "finished", "price_amount": 2.5},
                           separators=(",", ":"))
        sig = hmac.new(b"ipn", canon.encode(), hashlib.sha512).hexdigest()
        self.assertTrue(pay.verify_nowpayments(raw, sig, "ipn"))
        self.assertTrue(pay.verify_nowpayments(raw, sig.upper(), "ipn"))
        self.assertFalse(pay.verify_nowpayments(raw, sig, "nope"))
        self.assertFalse(pay.verify_nowpayments(b"not json", sig, "ipn"))
        self.assertFalse(pay.verify_nowpayments(raw, "", "ipn"))


class OrderTests(unittest.IsolatedAsyncioTestCase):
    async def test_mark_paid_exactly_once(self):
        db = FakeDB(); await order(db)
        self.assertEqual((await pay.mark_paid(db, "o1", 19900, "INR", "pay_1"))[0], "paid")
        self.assertEqual((await pay.mark_paid(db, "o1", 19900, "INR", "pay_1"))[0], "already")   # replayed webhook
        self.assertEqual((await pay.mark_paid(db, "nope", 1, "INR"))[0], "unknown")

    async def test_race_only_one_wins(self):
        db = FakeDB(); await order(db)
        res = await asyncio.gather(*[pay.mark_paid(db, "o1", 19900, "INR") for _ in range(5)])
        self.assertEqual(sorted(r[0] for r in res).count("paid"), 1)

    async def test_wrong_amount_or_currency_rejected(self):
        db = FakeDB()
        await order(db, "a"); await order(db, "b", cur="USD", amount=2.5)
        self.assertEqual((await pay.mark_paid(db, "a", 100, "INR"))[0], "mismatch")           # paid ₹1 for ₹199
        self.assertEqual((await db["orders"].find_one({"_id": "a"}))["status"], "created")    # still open
        self.assertEqual((await pay.mark_paid(db, "b", 2.5, "inr"))[0], "mismatch")           # wrong currency
        self.assertEqual((await pay.mark_paid(db, "b", 2.5, "usd"))[0], "paid")               # the right payment still works
        self.assertEqual((await pay.mark_paid(db, "a", 19900, "INR"))[0], "paid")

    async def test_fulfill_premium_new_renew_lifetime(self):
        bot = Bot()
        o = {"user_id": 7, "kind": "premium", "plan": "1m"}
        self.assertIn("premium until", await pay.fulfill(bot, o))
        first = await bot.mongodb.get_expiry_date(7)
        self.assertAlmostEqual((first - datetime.now()).days, 30, delta=1)
        await pay.fulfill(bot, o)                                                             # renewal stacks
        self.assertAlmostEqual((await bot.mongodb.get_expiry_date(7) - first).days, 30, delta=1)
        await pay.fulfill(bot, {"user_id": 7, "kind": "premium", "plan": "life"})
        self.assertIsNone(await bot.mongodb.get_expiry_date(7))                               # lifetime = no expiry
        self.assertEqual(await pay.fulfill(bot, o), "lifetime already")                       # cannot be downgraded by a 1m payment
        self.assertIsNone(await bot.mongodb.get_expiry_date(7))

    async def test_fulfill_credits_and_new_user(self):
        bot = Bot()
        self.assertEqual(await pay.fulfill(bot, {"_id": "o9", "method": "razorpay", "user_id": 9, "kind": "credits", "plan": "c30"}), "30 credits")
        self.assertEqual((await bot.mongodb.user_data.find_one({"_id": 9}))["credits"], 35)

    def test_parsers(self):
        rz = {"event": "payment_link.paid", "payload": {"payment_link": {"entity": {"reference_id": "o1", "amount_paid": 19900}},
                                                          "payment": {"entity": {"id": "pay_9"}}}}
        self.assertEqual(pay.parse_razorpay_event(rz), ("payment_link.paid", "o1", 19900, "pay_9"))
        self.assertIsNone(pay.parse_razorpay_event({"event": "x"}))
        np_ = {"payment_status": "finished", "order_id": "o2", "price_amount": "2.5", "price_currency": "USD", "payment_id": 55}
        self.assertEqual(pay.parse_nowpayments_event(np_), ("finished", "o2", 2.5, "usd", "55"))
        self.assertIsNone(pay.parse_nowpayments_event({"order_id": "o"}))

    def test_plans_and_methods(self):
        self.assertEqual(pay.find_plan("premium", "1m")["days"], 30)
        self.assertIsNone(pay.find_plan("premium", "zzz")); self.assertIsNone(pay.find_plan("x", "1m"))
        self.assertEqual(pay.methods(), [])                                                   # nothing configured in tests


if __name__ == "__main__":
    unittest.main()


class ProcessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = Bot(); self.db = self.bot.mongodb.db
        await order(self.db, "o1", "premium", "1m", "INR", 19900, uid=7)

    async def test_full_flow_pays_once_even_when_replayed_concurrently(self):
        res = await asyncio.gather(*[pay.process_paid(self.bot, "o1", 19900, "INR", "p1") for _ in range(4)])
        self.assertEqual(sorted(res), ["duplicate"] * 3 + ["ok"])
        self.assertTrue(await self.bot.mongodb.is_pro(7))
        exp = await self.bot.mongodb.get_expiry_date(7)
        self.assertAlmostEqual((exp - datetime.now()).days, 30, delta=1)               # one month, not four
        users = [c for c, t in self.bot.sent if c == 7]
        self.assertEqual(len(users), 1)                                                # told once

    async def test_failed_fulfilment_is_retried(self):
        real = pay.fulfill
        calls = {"n": 0}
        async def flaky(bot, order):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("db down")
            return await real(bot, order)
        pay.fulfill = flaky
        try:
            self.assertEqual(await pay.process_paid(self.bot, "o1", 19900, "INR"), "retry")
            self.assertFalse(await self.bot.mongodb.is_pro(7))
            self.assertTrue(any("NOT fulfilled" in t for c, t in self.bot.sent if c == 1))   # owner warned
            self.assertEqual(await pay.process_paid(self.bot, "o1", 19900, "INR"), "ok")     # gateway retry works
            self.assertTrue(await self.bot.mongodb.is_pro(7))
        finally:
            pay.fulfill = real

    async def test_mismatch_gives_nothing_and_warns_owner(self):
        self.assertEqual(await pay.process_paid(self.bot, "o1", 100, "INR"), "mismatch")
        self.assertFalse(await self.bot.mongodb.is_pro(7))
        self.assertTrue(any("mismatch" in t for c, t in self.bot.sent if c == 1))

    async def test_unknown_order(self):
        self.assertEqual(await pay.process_paid(self.bot, "nope", 1, "INR"), "unknown")


class ReuseTests(unittest.IsolatedAsyncioTestCase):
    async def test_open_order_is_reused(self):
        db = FakeDB(); calls = {"n": 0}
        async def fake_rz(order, plan, desc):
            calls["n"] += 1; return {"gateway_id": f"plink_{calls['n']}", "pay_url": f"https://rzp.io/{calls['n']}"}
        old_rz, old_on = pay._razorpay_create_link, pay.razorpay_on
        pay._razorpay_create_link, pay.razorpay_on = fake_rz, lambda: True
        try:
            a = await pay.create_order(db, 7, "premium", "1m", "razorpay")
            b = await pay.create_order(db, 7, "premium", "1m", "razorpay")
            self.assertEqual((a["_id"], calls["n"]), (b["_id"], 1))                    # one gateway call
            c = await pay.create_order(db, 7, "premium", "3m", "razorpay")             # other plan = new order
            self.assertNotEqual(a["_id"], c["_id"])
            d = await pay.create_order(db, 8, "premium", "1m", "razorpay")             # other user = new order
            self.assertNotEqual(a["_id"], d["_id"])
            self.assertEqual(a["amount"], 19900); self.assertEqual(a["currency"], "INR")
            with self.assertRaises(ValueError): await pay.create_order(db, 7, "premium", "zzz", "razorpay")
            with self.assertRaises(ValueError): await pay.create_order(db, 7, "premium", "1m", "crypto")   # not configured
        finally:
            pay._razorpay_create_link, pay.razorpay_on = old_rz, old_on
