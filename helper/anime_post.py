"""Pure helpers for /animepost: parse the details form, build the caption and the quality buttons.

No Telegram or Mongo in here, so it can be tested on its own (see tests/test_anime_post.py).
"""
import html
import re

from helper.quality import quality_rank

FIELDS = ("title", "audio", "rating", "episode", "genres", "network", "synopsis")
_FIELD_RE = re.compile(r"^\s*(%s)\s*[:=]\s*(.*)$" % "|".join(FIELDS), re.IGNORECASE)
CAPTION_LIMIT = 1024          # Telegram's limit for a photo caption
LINE = "◇" + "─" * 22 + "◇"

TEMPLATE = (
    "Title: Black Clover\n"
    "Audio: Chinese | Eng-Sub\n"
    "Rating: 7.9 / 10\n"
    "Episode: S2 Ep 1\n"
    "Genres: Action, Adventure, Comedy, Fantasy\n"
    "Network: @Donghua_Xin\n"
    "Synopsis: In a world where magic is everything, Asta and Yuno are both found abandoned at a church..."
)


def parse_form(text: str) -> dict:
    """'Key: value' lines -> dict. A line without a key continues the previous field (multi-line synopsis)."""
    data, current = {}, None
    for line in (text or "").splitlines():
        m = _FIELD_RE.match(line)
        if m:
            current = m.group(1).lower()
            data[current] = m.group(2).strip()
        elif current and line.strip():
            data[current] = (data[current] + "\n" + line.strip()).strip()
    return data


def hashtags(genres: str) -> str:
    tags = []
    for g in re.split(r"[,|/]+", genres or ""):
        g = re.sub(r"[^0-9A-Za-z_]+", "", g.strip())
        if g:
            tags.append("#" + g)
    return " ".join(tags)


def sort_qualities(items: list) -> list:
    """items: [(quality_label, link)] -> lowest quality first, one entry per quality."""
    seen, out = set(), []
    for q, link in sorted(items, key=lambda x: quality_rank(x[0])):
        if q.lower() not in seen:
            seen.add(q.lower())
            out.append((q, link))
    return out


def button_label(quality: str) -> str:
    return f"🚀 {quality.upper()} Download"


def build_buttons(items: list, per_row: int = 2) -> list:
    """Rows of (text, url) pairs; the caller turns them into InlineKeyboardButtons."""
    btns = [(button_label(q), link) for q, link in items]
    return [btns[i:i + per_row] for i in range(0, len(btns), per_row)]


def _plain_len(caption: str) -> int:
    return len(html.unescape(re.sub(r"<[^>]+>", "", caption)))


def build_caption(d: dict, qualities: list) -> str:
    """Caption in the Donghua-channel style. The synopsis is shortened if the caption would pass 1024."""
    esc = lambda s: html.escape((s or "").strip())

    def make(synopsis: str) -> str:
        lines = [f"<b>{esc(d.get('title', 'Untitled'))}</b>", LINE]
        if d.get("audio"):
            lines.append(f"▸ Audio ≡ {esc(d['audio'])}")
        if d.get("rating"):
            lines.append(f"▸ Rating ≡ {esc(d['rating'])}")
        if qualities:
            lines.append("▸ Quality ≡ " + " | ".join(esc(q) for q in qualities))
        if d.get("episode"):
            lines.append(f"▸ Episode ≡ {esc(d['episode'])}")
        tags = hashtags(d.get("genres", ""))
        if tags:
            lines.append(f"▸ Genres ≡ {tags}")
        lines.append(LINE)
        if synopsis:
            lines.append("▸ Synopsis ≡")
            lines.append(f"<blockquote expandable>{esc(synopsis)}</blockquote>")
        if d.get("network"):
            lines.append(f"\n🔗 <b>Our Network</b> {esc(d['network'])}")
        return "\n".join(lines)

    syn = (d.get("synopsis") or "").strip()
    caption = make(syn)
    over = _plain_len(caption) - CAPTION_LIMIT
    if over > 0 and syn:
        keep = max(len(syn) - over - 3, 0)
        syn = syn[:keep].rstrip() + "…" if keep else ""
        caption = make(syn)
    return caption
