import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tests  # noqa: F401
from jinja2 import Environment, FileSystemLoader  # noqa: E402
from web.charts import bar_chart  # noqa: E402
from helper import stats  # noqa: E402
from tests.fakedb import FakeDB  # noqa: E402
from tests.test_start_flow import make_mongo  # noqa: E402


class ChartTests(unittest.TestCase):
    def test_chart_is_valid_xml_and_escapes(self):
        import xml.dom.minidom as md
        rows = [{"label": f"10-0{i}", "clicks": i * 3, "delivered": i, "x": 0} for i in range(1, 8)]
        svg = bar_chart(rows, [("clicks", "Clicks <b>"), ("delivered", "Sent & ok")], title='T"<script>')
        md.parseString(svg)                                  # well-formed
        self.assertNotIn("<script>", svg); self.assertNotIn("<b>", svg)
        self.assertEqual(svg.count("<rect"), 7 * 2 + 2)       # bars + 2 legend swatches

    def test_empty_and_all_zero(self):
        import xml.dom.minidom as md
        md.parseString(bar_chart([], [("a", "A")]))
        md.parseString(bar_chart([{"label": "x", "a": 0}], [("a", "A")]))


class NewUserCounter(unittest.IsolatedAsyncioTestCase):
    async def test_add_user_counts_and_stamps_joined(self):
        m = make_mongo()
        await m.add_user(5)
        doc = await m.user_data.find_one({"_id": 5})
        self.assertIn("joined", doc); self.assertEqual(doc["credits"], 5)
        self.assertEqual((await stats.series(m.db, 1))[0]["new_users"], 1)


class TemplateTests(unittest.TestCase):
    def setUp(self):
        self.env = Environment(loader=FileSystemLoader("templates"), autoescape=True)
        from helper.timefmt import ist
        self.env.globals.update(panel="/admin", csrf_token=lambda: "tok", ist=ist)

    def test_analytics_and_managed_render_with_hostile_data(self):
        from datetime import datetime
        evil = '<img src=x onerror=alert(1)>'
        out = self.env.get_template("analytics.html").render(
            days=14, totals={k: 1 for k in stats.FIELDS}, rows=[], flashes=[], traffic="<svg></svg>", guard="<svg></svg>",
            top_files=[{"name": evil, "downloads": 2, "last_download": datetime(2026, 1, 1)}],
            top_links=[{"label": evil, "clicks": 3, "last": None, "key": "k", "link": ""}],
            orders=[{"created": datetime(2026, 1, 1), "user_id": 1, "kind": "premium", "plan": "1m", "method": "razorpay",
                     "currency": "INR", "amount": 19900, "status": "paid", "mismatch": evil, "fulfilled": True}])
        self.assertNotIn(evil, out); self.assertIn("&lt;img", out); self.assertIn("₹199", out)
        out = self.env.get_template("managed.html").render(flashes=[], rows=[
            {"token": "abc", "state": "ok", "uses": 1, "max_uses": 5, "clicks": 2, "expires_at": None, "note": evil, "created": None, "link": "https://t.me/b?start=lk_abc"},
            {"token": "def", "state": "full", "uses": 5, "max_uses": 5, "clicks": 9, "expires_at": datetime(2026, 1, 1), "note": "", "created": None, "link": ""}])
        self.assertNotIn(evil, out); self.assertIn("Revoke", out); self.assertEqual(out.count('value="revoke"'), 1)  # only live links can be revoked


if __name__ == "__main__":
    unittest.main()
