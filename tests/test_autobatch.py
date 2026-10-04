import asyncio, os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helper import autobatch, quality  # noqa: E402
from helper.switch import CachedFlag  # noqa: E402


class QualityTests(unittest.TestCase):
    def test_extract(self):
        self.assertEqual(quality.extract_quality("Show.S01E01.720p.mkv"), "720p")
        self.assertEqual(quality.extract_quality("Movie 2160p HDR.mkv"), "4K")
        self.assertEqual(quality.extract_quality("Movie.HD-Rip.mkv"), "HDRip")
        self.assertEqual(quality.extract_quality("Movie.1440p.mkv"), "1440p")    # not mistaken for 144p
        self.assertEqual(quality.extract_quality("Movie 2K.mkv"), "1440p")
        self.assertIsNone(quality.extract_quality("notes.pdf"))

    def test_same_title_same_episode_share_a_key(self):
        a = quality.group_key("Ancient.Magus.Bride.S01E07.480p.mkv")
        b = quality.group_key("Ancient Magus Bride S01E07 1080p WEB-DL x265.mkv")
        c = quality.group_key("Ancient.Magus.Bride.S01E08.480p.mkv")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)               # next episode is a different batch
        self.assertNotEqual(a, quality.group_key("Other.Show.S01E07.480p.mkv"))

    def test_year_and_tags_do_not_split_a_movie(self):
        self.assertEqual(quality.group_key("Avengers.Endgame.2019.720p.mkv"), quality.group_key("[Grp] Avengers Endgame (2019) 1080p BluRay x264.mkv"))

    def test_empty_key(self):
        self.assertEqual(quality.group_key("720p.mkv"), "")


class GroupingTests(unittest.TestCase):
    def test_needs_two_different_qualities(self):
        mk = lambda i, n: autobatch.make_upload(i, n)[1]
        self.assertEqual(autobatch.ready([mk(1, "A.Show.S01E01.720p.mkv")]), [])
        self.assertEqual(autobatch.ready([mk(1, "A.Show.S01E01.720p.mkv"), mk(2, "A.Show.S01E01.720p.mp4")]), [])
        out = autobatch.ready([mk(5, "A.Show.S01E01.1080p.mkv"), mk(3, "A.Show.S01E01.480p.mkv"), mk(4, "A.Show.S01E01.720p.mkv")])
        self.assertEqual([u.quality for u in out], ["480p", "720p", "1080p"])
        self.assertEqual([u.msg_id for u in out], [3, 4, 5])

    def test_duplicate_message_ids_collapse(self):
        mk = lambda i, n: autobatch.make_upload(i, n)[1]
        out = autobatch.ready([mk(1, "X.S01E01.480p.mkv"), mk(1, "X.S01E01.480p.mkv"), mk(2, "X.S01E01.720p.mkv")])
        self.assertEqual(len(out), 2)

    def test_unparseable_names_are_ignored(self):
        self.assertIsNone(autobatch.make_upload(1, "holiday.pdf"))
        self.assertIsNone(autobatch.make_upload(1, ""))

    def test_parse_window(self):
        self.assertEqual(autobatch.parse_window("45", 30), 45)
        self.assertEqual(autobatch.parse_window("1", 30), 5)
        self.assertEqual(autobatch.parse_window("99999", 30), 600)
        self.assertIsNone(autobatch.parse_window("abc", 30))


class CachedFlagTests(unittest.IsolatedAsyncioTestCase):
    async def test_cache_refresh_set_and_failure(self):
        t = [0.0]; calls = []; stored = [False]
        async def loader():
            calls.append(1)
            if stored[0] == "boom": raise RuntimeError("db down")
            return stored[0]
        f = CachedFlag(loader, ttl=15, clock=lambda: t[0])
        self.assertFalse(await f.get()); self.assertFalse(await f.get()); self.assertEqual(len(calls), 1)
        stored[0] = True; self.assertFalse(await f.get())          # still cached
        t[0] = 16; self.assertTrue(await f.get())                  # refreshed after the ttl
        f.set(False); self.assertFalse(await f.get())              # set() is instant
        stored[0] = "boom"; t[0] = 40; self.assertFalse(await f.get())   # storage error keeps the last value


if __name__ == "__main__":
    unittest.main()
