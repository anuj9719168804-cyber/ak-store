from helper import anime_post as ap


def test_parse_and_caption():
    d = ap.parse_form(ap.TEMPLATE + "\nsecond line")
    assert d["title"] == "Black Clover" and d["synopsis"].endswith("second line")
    items = ap.sort_qualities([("1080p", "u4"), ("360p", "u1"), ("720p", "u3"), ("480p", "u2"), ("720P", "dup")])
    assert [q for q, _ in items] == ["360p", "480p", "720p", "1080p"]
    cap = ap.build_caption(d, [q for q, _ in items])
    assert "▸ Quality ≡ 360p | 480p | 720p | 1080p" in cap
    assert "#Action #Adventure #Comedy #Fantasy" in cap
    rows = ap.build_buttons(items)
    assert len(rows) == 2 and rows[0][0][0] == "🚀 360P Download"


def test_long_synopsis_fits():
    d = {"title": "T", "synopsis": "x" * 3000}
    assert ap._plain_len(ap.build_caption(d, ["720p"])) <= ap.CAPTION_LIMIT
