import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helper import custom_buttons as cb  # noqa: E402

TEXT = """[Join Channel][buttonurl:https://t.me/mychannel]
[Backup][buttonurl:https://t.me/backup:same]
[Bad][buttonurl:javascript:alert(1)]
[How][buttonurl:t.me/howto]"""


class Btn:
    def __init__(self, text, url): self.text, self.url = text, url


class Markup:
    def __init__(self, rows): self.inline_keyboard = rows


class ParseTests(unittest.TestCase):
    def test_parse_rows_same_and_invalid(self):
        rows = cb.parse(TEXT)
        self.assertEqual([[b["text"] for b in r] for r in rows], [["Join Channel", "Backup"], ["How"]])
        self.assertEqual(rows[1][0]["url"], "https://t.me/howto")

    def test_limits(self):
        many = "\n".join(f"[B{i}][buttonurl:https://t.me/c{i}]" for i in range(20))
        self.assertEqual(sum(len(r) for r in cb.parse(many)), cb.MAX_BUTTONS)
        self.assertEqual(cb.parse("[" + "x" * 80 + "][buttonurl:https://a.com]")[0][0]["text"], "x" * cb.MAX_TEXT)
        self.assertEqual(cb.parse("nothing here"), [])

    def test_normalize_drops_junk(self):
        rows = cb.normalize([[{"text": "ok", "url": "https://a.com"}, {"text": "", "url": "https://a.com"}, "x"], "y", []])
        self.assertEqual(rows, [[{"text": "ok", "url": "https://a.com"}]])
        self.assertEqual(cb.normalize(None), [])

    def test_combine(self):
        rows = cb.parse(TEXT)
        self.assertIsNone(cb.combine(None, []))
        base = Markup([[Btn("orig", "https://o.com")]])
        self.assertIs(cb.combine(base, []), base)
        m = cb.combine(base, rows)
        self.assertEqual([[b.text for b in r] for r in m.inline_keyboard], [["orig"], ["Join Channel", "Backup"], ["How"]])
        self.assertEqual([[b.text for b in r] for r in cb.combine(None, rows).inline_keyboard], [["Join Channel", "Backup"], ["How"]])


if __name__ == "__main__":
    unittest.main()
