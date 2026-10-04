import os, re, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helper import help_text, reactions  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _channel_post_excluded() -> set:
    src = open(os.path.join(ROOT, "plugins", "channel_post.py"), encoding="utf-8").read()
    block = re.search(r"~filters\.command\(\[(.*?)\]\)", src, re.S).group(1)
    return set(re.findall(r"'([^']+)'", block))


class HelpTests(unittest.TestCase):
    def test_user_and_admin_commands_are_excluded_from_upload_handler(self):
        listed = {c for c, _ in help_text.USER_COMMANDS}
        for _, rows in help_text.ADMIN_COMMANDS:
            listed |= {c for c, _ in rows}
        missing = listed - _channel_post_excluded()
        # `bots` has its own handler in create_bot.py; everything else must be excluded here.
        self.assertEqual(missing - {"bots"}, set())
        self.assertTrue({"help", "commands", "info"} <= _channel_post_excluded())

    def test_every_listed_command_has_a_handler(self):
        src = ""
        for name in os.listdir(os.path.join(ROOT, "plugins")):
            if name.endswith(".py"):
                src += open(os.path.join(ROOT, "plugins", name), encoding="utf-8").read()
        for cmd in help_text.all_listed_commands():
            self.assertRegex(src, r"""command\(\s*[\[\(]?[^)\]]*["']%s["']""" % re.escape(cmd), cmd)

    def test_render_levels(self):
        user, admin, owner = (help_text.render(False), help_text.render(True), help_text.render(True, True))
        self.assertIn("/search", user); self.assertNotIn("/gencode", user)
        self.assertIn("/gencode", admin); self.assertNotIn("/backup", admin)
        self.assertIn("/backup", owner)


class ReactionTests(unittest.TestCase):
    def test_emoji_pool(self):
        self.assertEqual(len(set(reactions.REACTION_EMOJIS)), len(reactions.REACTION_EMOJIS))
        for _ in range(50):
            self.assertIn(reactions.pick(), reactions.REACTION_EMOJIS)


class SafeReactTests(unittest.IsolatedAsyncioTestCase):
    async def test_never_raises(self):
        class Boom:
            async def send_reaction(self, **kw): raise RuntimeError("REACTION_INVALID")
        class Ok:
            async def send_reaction(self, **kw): self.kw = kw
        self.assertFalse(await reactions.safe_react(Boom(), 1, 2))
        ok = Ok()
        self.assertTrue(await reactions.safe_react(ok, 1, 2, "🔥"))
        self.assertEqual(ok.kw, {"chat_id": 1, "message_id": 2, "emoji": "🔥"})


if __name__ == "__main__":
    unittest.main()
