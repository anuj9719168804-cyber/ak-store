import os, re, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helper import aq_panel, transcode  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FakeDB:
    """Just the two bot-setting calls the panel uses."""
    def __init__(self): self.s = {}
    async def update_bot_setting(self, key, value): self.s[key] = value
    async def get_bot_setting(self, key, default=None): return self.s.get(key, default)


class RowsTests(unittest.TestCase):
    def test_layout_and_marks(self):
        rows = aq_panel.build_rows(True, ["360p", "720p"])
        self.assertIn("ON", rows[0][0][0]); self.assertEqual(rows[0][0][1], "aq_toggle")
        flat = [b for r in rows[1:-1] for b in r]
        self.assertEqual([d for _, d in flat], [f"aq_q_{l}" for l in transcode.ORDER])
        marks = {d: t.startswith("✅") for t, d in flat}
        self.assertTrue(marks["aq_q_360p"] and marks["aq_q_720p"])
        self.assertFalse(marks["aq_q_144p"] or marks["aq_q_4K"])
        self.assertTrue(all(len(r) <= 4 for r in rows))
        self.assertEqual(rows[-1], [("✖️ Close", "aq_close")])
        self.assertIn("OFF", aq_panel.build_rows(False, [])[0][0][0])

    def test_callback_data_fits_telegram_limit(self):
        for r in aq_panel.build_rows(True, transcode.ORDER):
            for _, d in r:
                self.assertLessEqual(len(d.encode()), 64)


class ApplyTests(unittest.IsolatedAsyncioTestCase):
    async def test_toggle_flips_and_saves(self):
        db = FakeDB()
        on, wanted, toast = await aq_panel.apply(db, "aq_toggle", False, ["720p"])
        self.assertTrue(on); self.assertEqual(db.s["auto_quality"], True); self.assertIn("ON", toast)
        on, _, toast = await aq_panel.apply(db, b"aq_toggle", on, wanted)   # bytes callback data works too
        self.assertFalse(on); self.assertEqual(db.s["auto_quality"], False); self.assertIn("OFF", toast)

    async def test_quality_add_remove_keeps_order(self):
        db = FakeDB()
        _, wanted, _ = await aq_panel.apply(db, "aq_q_144p", True, ["480p", "720p"])
        self.assertEqual(wanted, ["144p", "480p", "720p"])
        self.assertEqual(db.s["auto_quality_list"], "144p,480p,720p")
        _, wanted, toast = await aq_panel.apply(db, "aq_q_480p", True, wanted)
        self.assertEqual(wanted, ["144p", "720p"]); self.assertIn("removed", toast)
        self.assertEqual(db.s["auto_quality_list"], "144p,720p")

    async def test_cannot_untick_last_quality(self):
        db = FakeDB()
        _, wanted, toast = await aq_panel.apply(db, "aq_q_720p", True, ["720p"])
        self.assertEqual(wanted, ["720p"]); self.assertNotIn("auto_quality_list", db.s)
        self.assertIn("at least one", toast)

    async def test_unknown_data_changes_nothing(self):
        db = FakeDB()
        for bad in ("aq_q_999p", "aq_q_", "aq_other", None, ""):
            on, wanted, toast = await aq_panel.apply(db, bad, True, ["720p"])
            self.assertEqual((on, wanted), (True, ["720p"]))
        self.assertEqual(db.s, {})


class WiringTests(unittest.TestCase):
    """pyrogram is not needed: check the source files are wired to each other."""
    def _src(self, *p): return open(os.path.join(ROOT, *p), encoding="utf-8").read()

    def test_guard_blocks_aq_buttons_for_non_admins(self):
        block = re.search(r'_ADMIN_ONLY = re\.compile\((.*?)\n\)', self._src("plugins", "admin_callback_guard.py"), re.S).group(1)
        pattern = re.compile("".join(re.findall(r'r"(.*?)"', block)))
        for data in ("aq_toggle", "aq_q_720p", "aq_q_4K", "aq_close"):
            self.assertTrue(pattern.match(data), data)

    def test_plugin_handles_every_button(self):
        src = self._src("plugins", "auto_quality.py")
        self.assertIn('on_callback_query(filters.regex(r"^aq_"))', src)
        self.assertIn("aq_panel.apply(", src)
        self.assertIn("reply_markup=_panel_markup(on, wanted)", src)
        self.assertIn("client.admins", src)


if __name__ == "__main__":
    unittest.main()
