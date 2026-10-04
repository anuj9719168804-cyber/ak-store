import os, re, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helper import caption_clean as cc  # noqa: E402
from helper.caption_logic import apply_custom_caption, get_file_details  # noqa: E402


def cfg(**kw): return cc.normalize(kw)


def balanced(s):
    stack = []
    for m in re.finditer(r"<(/?)([a-z-]+)[^>]*>", s):
        if m.group(1):
            if not stack or stack.pop() != m.group(2): return False
        else:
            stack.append(m.group(2))
    return not stack


class CleanTests(unittest.TestCase):
    def test_nothing_on_is_a_noop(self):
        self.assertIsNone(cc.build_cleaner({}))
        self.assertEqual(cc.clean("<b>hi</b> @someone", cfg()), "<b>hi</b> @someone")

    def test_links(self):
        c = cfg(links=True)
        out = cc.clean('Watch <a href="https://x.com/a">here</a> or https://y.com/b?q=1 or t.me/chan end', c)
        self.assertEqual(out, "Watch here or or end")
        self.assertNotIn("http", out)

    def test_usernames(self):
        s = "Join @MyChannel now, mail a@b.com, @abc stays"
        self.assertEqual(cc.clean(s, cfg(usernames="remove")), "Join now, mail a@b.com, @abc stays")
        self.assertEqual(cc.clean(s, cfg(usernames="replace", username_value="@Mine_bot")),
                         "Join @Mine_bot now, mail a@b.com, @abc stays")
        self.assertEqual(cc.clean(s, cfg(usernames="replace")), s)            # no own name -> inactive

    def test_remove_words_keeps_tags_balanced_and_links_intact(self):
        s = '<b>Movie</b> <a href="http://spam.com/spam">Spam site</a> <b>foo</b> bar'
        out = cc.clean(s, cfg(remove=["foo bar", "SPAM"]))
        self.assertTrue(balanced(out), out)
        self.assertIn('href="http://spam.com/spam"', out)                      # attribute untouched
        self.assertNotIn("foo", out)
        self.assertIn("Movie", out)

    def test_phrase_across_tag_boundary(self):
        out = cc.clean("<b>Join us</b> today", cfg(remove=["us</b> to"]))     # pathological input never breaks tags
        self.assertTrue(balanced(out))
        out = cc.clean("<b>foo</b> bar baz", cfg(remove=["foo bar"]))
        self.assertTrue(balanced(out), out)
        self.assertEqual(re.sub(r"<[^>]+>", "", out).strip(), "baz")

    def test_replace_is_last_and_html_safe(self):
        c = cfg(usernames="remove", replace=[{"old": "Join", "new": "Visit @OurChannel"}, {"old": "a&b", "new": "x<y"}])
        out = cc.clean("Join @Other now a&amp;b", c)
        self.assertIn("Visit @OurChannel", out)                                # survives the username remover
        self.assertNotIn("@Other", out)
        self.assertIn("x&lt;y", out)                                           # stray "<" is escaped
        self.assertNotIn("a&amp;b", out)
        ok = cc.clean("go now", cfg(replace=[{"old": "go", "new": "<b>GO</b>"}]))
        self.assertEqual(ok, "<b>GO</b> now")                                  # balanced markup is kept
        bad = cc.clean("go now", cfg(replace=[{"old": "go", "new": "<b>GO"}]))
        self.assertTrue(balanced(bad), bad)

    def test_no_replacement_inside_tags(self):
        out = cc.clean('<a href="https://join.com">Join</a>', cfg(replace=[{"old": "join", "new": "go"}]))
        self.assertEqual(out, '<a href="https://join.com">go</a>')

    def test_tidy_whitespace(self):
        out = cc.clean("A\n\n\n@Someone1\n\n\nB   C", cfg(usernames="remove"))
        self.assertEqual(out, "A\n\nB C")

    def test_empty_tags_removed(self):
        self.assertEqual(cc.clean("<b>@Someone1</b> rest", cfg(usernames="remove")), "rest")

    def test_parse_helpers(self):
        self.assertEqual(cc.parse_words(" a \n\n b "), ["a", "b"])
        self.assertEqual(cc.parse_pairs("x => y\nbad line\n => z\nq=>"), [{"old": "x", "new": "y"}, {"old": "q", "new": ""}])

    def test_normalize_is_defensive(self):
        n = cc.normalize({"usernames": "bogus", "remove": ["", "ok"], "replace": [{"old": ""}, {"old": "a"}, "junk"]})
        self.assertEqual((n["usernames"], n["remove"], n["replace"]), ("off", ["ok"], [{"old": "a", "new": ""}]))


class NewFeatureTests(unittest.TestCase):
    def test_link_replace(self):
        c = cfg(links="replace", link_value="t.me/mychan")
        out = cc.clean('Get <a href="https://old.com/x?a=1&amp;b=2">it</a> at https://spam.com/y now', c)
        self.assertEqual(out, 'Get <a href="https://t.me/mychan">it</a> at https://t.me/mychan now')
        self.assertEqual(cc.clean("see https://spam.com", cfg(links="replace")), "see https://spam.com")   # no own link -> off

    def test_link_value_is_validated(self):
        self.assertEqual(cc.valid_link('https://a.com/"><script>'), "")
        self.assertEqual(cc.valid_link("javascript:alert(1)"), "")
        self.assertEqual(cc.valid_link("tg://resolve?domain=x"), "tg://resolve?domain=x")
        self.assertEqual(cc.normalize({"links": "replace", "link_value": "bad link"})["link_value"], "")

    def test_old_boolean_links_setting_still_loads(self):
        self.assertEqual(cc.normalize({"links": True})["links"], "remove")
        self.assertEqual(cc.normalize({"links": False})["links"], "off")

    def test_decorate(self):
        n = cc.normalize({"numbering": "dot", "bullet": "🚀"})
        self.assertEqual(cc.decorate("hello", n, 3), "3. 🚀 hello")
        self.assertEqual(cc.decorate("hello", cc.normalize({"numbering": "emoji"}), 12), "1\ufe0f\u20e32\ufe0f\u20e3 hello")
        self.assertEqual(cc.decorate("hello", cc.normalize({"numbering": "bracket"}), 2), "2) hello")
        self.assertEqual(cc.decorate("", n, 1), "")                                # nothing to number
        self.assertEqual(cc.decorate("hello", cc.normalize({}), 1), "hello")      # off
        big = "x" * 1023
        self.assertEqual(cc.decorate(big, n, 1), big)                              # would pass Telegram's limit

    def test_modes_cycle(self):
        self.assertEqual(cc.next_mode("off", cc.MODES), "remove")
        self.assertEqual(cc.next_mode("replace", cc.MODES), "off")
        self.assertEqual(cc.next_mode("🚀", cc.BULLETS), "🔥")

    def test_file_name_is_cleaned_too(self):
        cleaner = cc.build_cleaner(cfg(remove=["WEB-DL"], usernames="remove"))
        out = apply_custom_caption("{file_name}", Msg(None, "Movie WEB-DL.mkv"), "", "bot", cleaner=cleaner)
        self.assertNotIn("WEB-DL", out)
        self.assertIn("Movie", out)


class ModeTests(unittest.TestCase):
    def test_replace_mode_sends_only_the_template(self):
        m = Msg("original @Spammer text")
        cleaner = cc.build_cleaner(cfg(usernames="remove"))
        self.assertEqual(apply_custom_caption("{file_name} | {file_caption}", m, "original @Spammer text", "bot", cleaner=cleaner, mode="replace"),
                         "Movie 2019 1080p mkv | original text")
        self.assertEqual(apply_custom_caption("T", m, "orig", "bot", mode="replace"), "T")
        self.assertEqual(apply_custom_caption("T", m, "orig", "bot", mode="append"), "orig\n\nT")
        self.assertEqual(apply_custom_caption("T", m, "orig", "bot"), "orig\n\nT")              # default stays append
        self.assertEqual(apply_custom_caption("", m, "orig", "bot", mode="replace"), "orig")      # no template: untouched
        self.assertEqual(apply_custom_caption("x" * 1100, m, "orig", "bot", mode="replace"), "orig")

    def test_type_placeholder(self):
        self.assertEqual(apply_custom_caption("{type}", Msg("c"), "", "b", mode="replace"), "Document")
        photo = Msg("c"); photo.document = None
        photo.photo = type("P", (), {"file_size": 2048, "file_name": None})()
        self.assertEqual(apply_custom_caption("{type} {size}", photo, "", "b", mode="replace"), "Photo 2.00 KB")


class Msg:
    def __init__(self, caption, name="Movie.2019.1080p.mkv"):
        self.media, self.caption = True, caption
        self.video = None
        self.photo = None
        self.document = type("D", (), {"file_name": name, "file_size": 1024, "duration": None})()
        self.audio = self.voice = None


class ApplyTests(unittest.TestCase):
    def test_cleaner_does_not_touch_template_but_cleans_file_caption(self):
        cleaner = cc.build_cleaner(cfg(links=True, usernames="remove"))
        m = Msg("Nice @Spammer https://spam.com")
        out = apply_custom_caption("{file_caption} | https://my.link @mine_ch", m, "Nice @Spammer https://spam.com", "bot", cleaner=cleaner)
        self.assertEqual(out, "Nice\n\nNice | https://my.link @mine_ch")

    def test_cleaner_without_template(self):
        cleaner = cc.build_cleaner(cfg(usernames="remove"))
        self.assertEqual(apply_custom_caption("", Msg("x @Spammer"), "x @Spammer", "bot", cleaner=cleaner), "x")

    def test_failing_cleaner_is_ignored(self):
        def boom(t): raise RuntimeError
        self.assertEqual(apply_custom_caption("", Msg("x"), "x", "bot", cleaner=boom), "x")

    def test_year_placeholder(self):
        d = get_file_details(Msg(None))
        self.assertEqual(d["year"], "2019")
        self.assertEqual(apply_custom_caption("{year} {quality}", Msg(None), "", "b"), "2019 1080p")


if __name__ == "__main__":
    unittest.main()
