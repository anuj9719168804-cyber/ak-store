"""Drives the real plugins.start.start_command with a fake Telegram client and the fake database."""
import os, sys, time, types, unittest
from types import SimpleNamespace as NS
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tests  # noqa: F401  (stubs)
from helper.database import MongoDB  # noqa: E402
from helper.helper_func import encode  # noqa: E402
from helper import links, rewards, verify_web as vw  # noqa: E402
from tests.fakedb import FakeDB  # noqa: E402
import plugins.start as start  # noqa: E402

CH = -1001


def make_mongo():
    m = object.__new__(MongoDB)
    m.db = FakeDB()
    m.user_data, m.premium_users = m.db["users"], m.db["pros"]
    m.fsub_status, m.request_sub, m.files, m.channel_data = m.db["fsub_status"], m.db["request_sub"], m.db["files"], m.db["channels"]
    return m


class FakeFile:
    def __init__(self, mid, log):
        self.id, self.caption, self.document, self.reply_markup, self.empty = mid, None, None, None, False
        self._log = log
    async def copy(self, chat_id, **kw):
        self._log.append((chat_id, self.id))
        return NS(id=1000 + self.id, delete=_noop)


async def _noop(*a, **k):
    return None


class FakeMsgReply:
    async def delete(self): pass
    async def edit(self, *a, **k): pass
    edit_text = edit


class FakeClient:
    def __init__(self):
        self.mongodb = make_mongo()
        self.username, self.admins, self.owner = "testbot", [1], 1
        self.messages = {"START": "hi {first}", "START_PHOTO": "", "SHORT_VERIFY": "ok-pic", "SHORT_PIC": "gate-pic", "SHORT_MSG": "verify please"}
        self.auto_del, self.protect, self.disable_btn = 0, False, True
        self.db, self.db_channel, self.db_channels = CH, NS(id=CH), {}
        self.fsub_dict, self.shortner_enabled = {}, True
        self.short_url, self.short_api, self.tutorial_link, self.tutorial_enabled = "short.example", "k", "https://t.me/t/1", True
        self.name, self.custom_caption = "t", ""
        self.LOGGER = lambda *a: NS(info=print, warning=print)
        self.sent, self.photos, self.delivered = [], [], []
    async def send_photo(self, **kw): self.photos.append(kw)
    async def send_message(self, chat_id, text, **kw): self.sent.append((chat_id, text))
    async def get_messages(self, chat_id, message_ids):
        return [FakeFile(i, self.delivered) for i in message_ids]


def msg(client, uid, text):
    replies = []
    async def reply(t, **k):
        replies.append(t); return FakeMsgReply()
    m = NS(text=text, from_user=NS(id=uid, first_name="U", last_name=None, username="u", mention="U"),
           chat=NS(id=uid), reply=reply)
    m.replies = replies
    return m


async def run(client, uid, text):
    m = msg(client, uid, text)
    await start.start_command(client, m)
    return m


class Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.c = FakeClient()
        self.db = self.c.mongodb.db
        async def fake_short(url, client): return "https://short.example/s"
        self._old = (start.get_short_async, start.WEB_URL, vw.VERIFY_WEB_ACTIVE, vw.MIN_SECONDS)
        start.get_short_async = fake_short
        start.WEB_URL, vw.VERIFY_WEB_ACTIVE, vw.MIN_SECONDS = "https://web.test", True, 45
        self.payload = await encode(f"get-{5 * abs(CH)}")

    async def asyncTearDown(self):
        start.get_short_async, start.WEB_URL, vw.VERIFY_WEB_ACTIVE, vw.MIN_SECONDS = self._old

    async def credits(self, uid):
        return (await self.db["users"].find_one({"_id": uid}))["credits"]

    async def add_user(self, uid, credits=5):
        await self.db["users"].insert_one({"_id": uid, "ban": False, "credits": credits, "joined": time.time() - 99999})


class ReferralTests(Base):
    async def test_referral_rewards_inviter_once_and_shows_welcome(self):
        await self.add_user(50)
        old = (rewards.REFERRAL_CREDITS, rewards.REFERRAL_NEW_USER_CREDITS, rewards.QUALIFY)
        rewards.REFERRAL_CREDITS, rewards.REFERRAL_NEW_USER_CREDITS, rewards.QUALIFY = 3, 0, "join"
        try:
            await run(self.c, 60, "/start ref_50")                     # brand new account 60
            self.assertEqual(await self.credits(50), 8)
            self.assertTrue(any(chat == 50 and "referral" in t.lower() for chat, t in self.c.sent))
            await run(self.c, 60, "/start ref_50")                     # again: nothing
            self.assertEqual(await self.credits(50), 8)
            await run(self.c, 50, "/start ref_50")                     # self
            self.assertEqual(await self.credits(50), 8)
        finally:
            rewards.REFERRAL_CREDITS, rewards.REFERRAL_NEW_USER_CREDITS, rewards.QUALIFY = old

    async def test_file_mode_pays_inviter_only_after_first_file(self):
        await self.add_user(50)
        old = (rewards.REFERRAL_CREDITS, rewards.REFERRAL_NEW_USER_CREDITS, rewards.QUALIFY)
        rewards.REFERRAL_CREDITS, rewards.REFERRAL_NEW_USER_CREDITS, rewards.QUALIFY = 3, 0, "file"
        try:
            await run(self.c, 60, "/start ref_50")                     # joins through the link
            self.assertEqual(await self.credits(50), 5)                # nothing yet
            await run(self.c, 60, f"/start {self.payload}")            # first file delivered
            self.assertEqual(await self.credits(50), 8)
            self.assertTrue(any(chat == 50 and "Referral completed" in t for chat, t in self.c.sent))
            await run(self.c, 60, f"/start {self.payload}")            # more files: no second payout
            self.assertEqual(await self.credits(50), 8)
            rows = await self.db["credit_log"].find({"user_id": 50}).to_list()
            self.assertEqual([(r["delta"], r["kind"]) for r in rows], [(3, "referral")])
        finally:
            rewards.REFERRAL_CREDITS, rewards.REFERRAL_NEW_USER_CREDITS, rewards.QUALIFY = old

    async def test_verify_is_written_to_the_ledger(self):
        await self.add_user(10, credits=0)
        doc = await vw.create(self.db, 10, self.payload)
        await self.db["verify_tokens"].update_one({"_id": doc["_id"]}, {"$set": {"state": "passed", "elapsed": 60.0}})
        await run(self.c, 10, f"/start vt_{doc['_id']}")
        rows = await self.db["credit_log"].find({"user_id": 10}).to_list()
        self.assertEqual([(r["delta"], r["kind"]) for r in rows], [(5, "verify")])


class ManagedLinkTests(Base):
    async def test_max_uses_one_person_then_full(self):
        doc = await links.create(self.db, self.payload, 1, max_uses=1)
        token = links.PREFIX + doc["_id"]
        await self.add_user(10); await self.add_user(20)
        await run(self.c, 10, f"/start {token}")
        self.assertEqual(self.c.delivered, [(10, 5)])
        self.assertEqual(await self.credits(10), 4)                      # one credit used, as for any link
        m = await run(self.c, 20, f"/start {token}")
        self.assertEqual(self.c.delivered, [(10, 5)])                    # nothing for the second person
        self.assertTrue(any("ʟɪᴍɪᴛ" in r for r in m.replies))
        self.assertEqual(await self.credits(20), 5)                      # and no credit burned
        await run(self.c, 10, f"/start {token}")                         # first person again is allowed
        self.assertEqual(len(self.c.delivered), 2)
        d = await links.get(self.db, doc["_id"])
        self.assertEqual((d["uses"], d["clicks"]), (1, 2))   # the blocked attempt is not a click

    async def test_expired_and_revoked_and_unknown(self):
        await self.add_user(10)
        d1 = await links.create(self.db, self.payload, 1, ttl_seconds=60)
        await self.db["links"].update_one({"_id": d1["_id"]}, {"$set": {"expires_at": links._now().replace(year=2000)}})
        d2 = await links.create(self.db, self.payload, 1); await links.revoke(self.db, d2["_id"])
        for tok, word in ((d1["_id"], "ᴇxᴘɪʀᴇᴅ"), (d2["_id"], "ᴅɪsᴀʙʟᴇᴅ"), ("zzzzzzzzzzzz", "ɴᴏᴛ ᴇxɪsᴛ")):
            m = await run(self.c, 10, f"/start lk_{tok}")
            self.assertTrue(any(word in r for r in m.replies), (tok, m.replies))
        self.assertEqual(self.c.delivered, [])
        self.assertEqual(await self.credits(10), 5)

    async def test_admin_bypasses_limits_without_using_slots(self):
        doc = await links.create(self.db, self.payload, 1, max_uses=1)
        await self.add_user(1)
        await run(self.c, 1, f"/start lk_{doc['_id']}"); await run(self.c, 1, f"/start lk_{doc['_id']}")
        self.assertEqual(len(self.c.delivered), 2)
        self.assertEqual((await links.get(self.db, doc["_id"]))["uses"], 0)

    async def test_plain_link_still_works_and_counts_click(self):
        await self.add_user(10)
        await run(self.c, 10, f"/start {self.payload}")
        self.assertEqual(self.c.delivered, [(10, 5)])
        self.assertEqual((await self.db["link_stats"].find_one({"_id": self.payload}))["clicks"], 1)
        self.assertEqual((await self.db["stats_daily"].find_one({}))["delivered"], 1)


class WebVerifyChain(Base):
    async def test_no_credits_gate_then_verify_then_redeem_then_unlock(self):
        doc = await links.create(self.db, self.payload, 1, max_uses=3)
        token = links.PREFIX + doc["_id"]
        await self.add_user(10, credits=0)
        await run(self.c, 10, f"/start {token}")
        # gate: files NOT sent, a go-URL button sent, token stored with the ORIGINAL (managed) payload
        self.assertEqual(self.c.delivered, [])
        go_btn = self.c.photos[-1]["reply_markup"].inline_keyboard[0][0]
        toks = self.db["verify_tokens"].docs
        self.assertEqual(len(toks), 1)
        self.assertEqual(toks[0]["payload"], token)
        self.assertEqual(toks[0]["short_url"], "https://short.example/s")
        self.assertEqual((await links.get(self.db, doc["_id"]))["uses"], 0)           # gate did not take a slot
        tid = toks[0]["_id"]
        self.assertEqual(go_btn.url, f"https://web.test/go/{tid}")                         # button opens OUR page, not the shortener
        # redeeming before passing the web check does nothing
        m = await run(self.c, 10, f"/start vt_{tid}")
        self.assertEqual(await self.credits(10), 0)
        # the browser flow (as the web routes would run it)
        ua = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/126 Mobile Safari/537.36"
        from tests.test_verify_web import solve
        code, _ = await vw.begin_go(self.db, tid, ua=ua, ip="1.1.1.1", nonce=solve(toks[0]["ch1"]), signals={"wd": False}, now_ts=1000.0)
        self.assertEqual(code, "ok")
        code, _, _ = await vw.finish(self.db, tid, ua=ua, ip="1.1.1.1", cookie=vw.cookie_value(tid, vw.ua_hash(ua)),
                                     nonce=solve(toks[0]["ch2"]), signals={"wd": False, "trusted": True, "ptr": 2, "ms": 5000},
                                     now_ts=1100.0)
        self.assertEqual(code, "ok")
        # someone else's /start vt_ gets nothing
        await self.add_user(30, credits=0)
        await run(self.c, 30, f"/start vt_{tid}")
        self.assertEqual(await self.credits(30), 0)
        # the owner of the token gets credits + an unlock button pointing at the managed link
        await run(self.c, 10, f"/start vt_{tid}")
        self.assertEqual(await self.credits(10), 5)
        self.assertEqual(self.c.photos[-1]["reply_markup"].inline_keyboard[0][0].url, f"https://t.me/testbot?start={token}")
        # single use
        await run(self.c, 10, f"/start vt_{tid}")
        self.assertEqual(await self.credits(10), 5)
        # and now the link itself delivers (credit comes off), the slot is taken at that moment
        await run(self.c, 10, f"/start {token}")
        self.assertEqual(self.c.delivered, [(10, 5)])
        self.assertEqual((await links.get(self.db, doc["_id"]))["uses"], 1)

    async def test_shortener_failure_does_not_hand_out_the_bare_verify_link(self):
        async def broken(url, client): return url                      # get_short falls back to the input on failure
        start.get_short_async = broken
        await self.add_user(10, credits=0)
        m = await run(self.c, 10, f"/start {self.payload}")
        self.assertEqual(self.c.photos, [])
        self.assertTrue(any("Couldn't generate" in r for r in m.replies))

    async def test_web_off_uses_old_flow_with_original_payload(self):
        vw.VERIFY_WEB_ACTIVE = False
        doc = await links.create(self.db, self.payload, 1)
        token = links.PREFIX + doc["_id"]
        await self.add_user(10, credits=0)
        await run(self.c, 10, f"/start {token}")
        saved = await self.db["users"].find_one({"_id": 10})
        self.assertEqual(saved["verify_payload"], token)                 # managed link stays managed after the shortener
        self.assertEqual(len(self.db["verify_tokens"].docs), 0)


if __name__ == "__main__":
    unittest.main()
