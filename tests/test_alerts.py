import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helper import alerts  # noqa: E402


class Bot:
    owner = 1
    def __init__(self): self.sent = []
    async def send_message(self, chat, text, **k): self.sent.append(text)


class AlertTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        alerts._active.clear(); alerts._bypass_hits.clear(); alerts._last_spike = None

    async def test_same_problem_reported_once_then_recovery_once(self):
        b = Bot()
        self.assertTrue(await alerts.raise_alert(b, "db:1", "down"))
        self.assertFalse(await alerts.raise_alert(b, "db:1", "down"))      # cooldown
        await alerts.clear_alert(b, "db:1", "back")
        await alerts.clear_alert(b, "db:1", "back")                        # nothing to clear now
        self.assertEqual(b.sent, ["down", "back"])
        self.assertTrue(await alerts.raise_alert(b, "db:1", "down again"))  # new incident reported again

    async def test_cooldown_expiry_resends(self):
        b = Bot()
        await alerts.raise_alert(b, "k", "x")
        alerts._active["k"] -= alerts.COOLDOWN + 1
        self.assertTrue(await alerts.raise_alert(b, "k", "x"))

    async def test_bypass_spike_fires_once_per_window(self):
        b = Bot()
        old = alerts.BYPASS_SPIKE_COUNT
        alerts.BYPASS_SPIKE_COUNT = 3
        try:
            for _ in range(2): await alerts.note_bypass(b)
            self.assertEqual(b.sent, [])
            for _ in range(5): await alerts.note_bypass(b)
            self.assertEqual(len(b.sent), 1)
            self.assertIn("Bypass spike", b.sent[0])
        finally:
            alerts.BYPASS_SPIKE_COUNT = old

    async def test_failed_send_is_not_marked_reported(self):
        class Dead(Bot):
            async def send_message(self, *a, **k): raise RuntimeError("blocked")
        b = Dead()
        self.assertFalse(await alerts.raise_alert(b, "k", "x"))
        self.assertNotIn("k", alerts._active)                              # will retry next check

    async def test_disabled_sends_nothing(self):
        b = Bot(); old = alerts.ALERTS_ENABLED; alerts.ALERTS_ENABLED = False
        try: self.assertFalse(await alerts.send(b, "x"))
        finally: alerts.ALERTS_ENABLED = old
        self.assertEqual(b.sent, [])


if __name__ == "__main__":
    unittest.main()
