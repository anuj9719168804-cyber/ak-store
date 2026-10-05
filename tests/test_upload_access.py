import os, sys, types, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helper import upload_access as ua  # noqa: E402


class Db:
    def __init__(self, pro): self.pro = pro
    async def is_pro(self, uid): return uid in self.pro


def client(pro=()):
    return types.SimpleNamespace(admins=[1], mongodb=Db(set(pro)), reply_text="REPLY")


def msg(uid, media=True):
    return types.SimpleNamespace(from_user=types.SimpleNamespace(id=uid), document=object() if media else None,
                                 video=None, audio=None)


class UploadAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_modes(self):
        c = client(pro={5})
        for mode, expect in (("admin", (True, False, False)), ("premium", (True, True, False)), ("all", (True, True, True))):
            ua.UPLOAD_ACCESS = mode
            got = (await ua.can_upload(c, msg(1)), await ua.can_upload(c, msg(5)), await ua.can_upload(c, msg(9)))
            self.assertEqual(got, expect, mode)

    async def test_text_from_premium_is_not_stored_and_gets_a_hint(self):
        c = client(pro={5})
        ua.UPLOAD_ACCESS = "premium"
        m = msg(5, media=False)
        self.assertFalse(await ua.can_upload(c, m))
        self.assertIn("Send me a file", ua.denied_text(c, m))

    def test_denied_text(self):
        c = client()
        ua.UPLOAD_ACCESS = "admin"
        self.assertEqual(ua.denied_text(c, msg(9)), "REPLY")
        ua.UPLOAD_ACCESS = "premium"
        self.assertIn("premium", ua.denied_text(c, msg(9)))


if __name__ == "__main__":
    unittest.main()


class PremiumFeatureTests(unittest.IsolatedAsyncioTestCase):
    async def test_has_premium_access(self):
        c = client(pro={5})
        self.assertTrue(await ua.has_premium_access(c, 1))      # admin
        self.assertTrue(await ua.has_premium_access(c, 5))      # premium
        self.assertFalse(await ua.has_premium_access(c, 9))     # normal user
        self.assertFalse(await ua.has_premium_access(c, None))
