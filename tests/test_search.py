import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helper import search  # noqa: E402
from tests.fakedb import FakeDB  # noqa: E402


class SearchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = FakeDB()
        rows = [("Avengers.Endgame.2019.1080p.mkv", "", 100, -1001, 5), ("Avengers Infinity War 720p.mp4", "marvel", 101, -1001, 6),
                ("Naruto S01E01.mkv", "anime ep", 102, -1002, 7), ("a+b (test).pdf", "", 103, -1001, 8)]
        for i, (name, cap, added, chat, mid) in enumerate(rows):
            await self.db["files"].insert_one({"_id": f"f{i}", "name": name, "caption": cap, "added": added, "chat_id": chat, "msg_id": mid})

    async def test_all_words_any_order_and_separators(self):
        rows, total = await search.search(self.db, "1080 avengers")
        self.assertEqual([r["name"] for r in rows], ["Avengers.Endgame.2019.1080p.mkv"])
        rows, _ = await search.search(self.db, "AVENGERS")
        self.assertEqual(len(rows), 2); self.assertEqual(rows[0]["_id"], "f1")            # newest first
        rows, _ = await search.search(self.db, "anime")                                    # caption match
        self.assertEqual([r["_id"] for r in rows], ["f2"])
        rows, _ = await search.search(self.db, "naruto.s01e01")                            # dots in query act as spaces
        self.assertEqual([r["_id"] for r in rows], ["f2"])

    async def test_regex_characters_are_literal(self):
        rows, _ = await search.search(self.db, "a+b")
        self.assertEqual([r["_id"] for r in rows], ["f3"])
        for q in (".*", "(", "[a-z]", "\\"):
            rows, total = await search.search(self.db, q)        # must neither crash nor match everything
            self.assertLessEqual(total, 1)

    async def test_empty_and_paging_and_channel_limit(self):
        self.assertEqual(await search.search(self.db, "   "), ([], 0))
        self.assertEqual(await search.search(self.db, "._-"), ([], 0))
        rows, total = await search.search(self.db, "mkv", page=1, per_page=1)
        self.assertEqual((len(rows), total), (1, 2)); self.assertEqual(search.pages(total, 1), 2)
        rows, _ = await search.search(self.db, "mkv", page=2, per_page=1)
        self.assertEqual(len(rows), 1)
        rows, total = await search.search(self.db, "mkv", allowed_chats={-1002})
        self.assertEqual([r["_id"] for r in rows], ["f2"])
        self.assertEqual(search.words("a b c d e f g h"), list("abcdef"))                  # query length capped

    async def test_payload_matches_genlink_format(self):
        from helper.helper_func import decode
        p = await search.payload_for({"msg_id": 5, "chat_id": -1001})
        self.assertEqual(await decode(p), f"get-{5 * 1001}")


if __name__ == "__main__":
    unittest.main()
