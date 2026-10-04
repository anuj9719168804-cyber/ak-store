"""Tiny server-side SVG charts for the panel: no JavaScript, no external files, nothing to block."""
from html import escape

_COLORS = ["#2a7de1", "#1f9d55", "#e08a1e", "#d64545", "#8e5bd6"]


def bar_chart(rows, series, width=720, height=220, title="") -> str:
    """rows: [{"label": "10-01", "clicks": 3, ...}], series: [("clicks", "Clicks"), ...] (max 5).
    Grouped bars per row, a y-axis with 4 ticks, a legend. Returns an <svg> string."""
    series = list(series)[:5]
    pad_l, pad_r, pad_t, pad_b = 44, 10, 28, 34
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b
    peak = max([int(r.get(key, 0) or 0) for r in rows for key, _ in series] + [1])
    top = _nice_max(peak)
    n = max(len(rows), 1)
    group_w = plot_w / n
    bar_w = max(min(group_w * 0.8 / max(len(series), 1), 22), 2)

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" '
           f'aria-label="{escape(title or "chart")}" class="chart">']
    if title:
        out.append(f'<text x="{pad_l}" y="16" class="ct">{escape(title)}</text>')
    for i in range(5):                                         # grid + y labels
        val = top * i / 4
        y = pad_t + plot_h - plot_h * i / 4
        out.append(f'<line x1="{pad_l}" x2="{width - pad_r}" y1="{y:.1f}" y2="{y:.1f}" class="cg"/>')
        out.append(f'<text x="{pad_l - 6}" y="{y + 4:.1f}" text-anchor="end" class="cl">{_fmt(val)}</text>')
    step = max(n // 7, 1)
    for gi, row in enumerate(rows):
        gx = pad_l + gi * group_w + (group_w - bar_w * len(series)) / 2
        for si, (key, name) in enumerate(series):
            value = int(row.get(key, 0) or 0)
            h = plot_h * value / top if top else 0
            x, y = gx + si * bar_w, pad_t + plot_h - h
            out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w - 1:.1f}" height="{max(h, 0):.1f}" '
                       f'fill="{_COLORS[si]}"><title>{escape(str(row.get("label", "")))}: {escape(name)} {value}</title></rect>')
        if gi % step == 0:
            out.append(f'<text x="{pad_l + gi * group_w + group_w / 2:.1f}" y="{height - 14}" text-anchor="middle" '
                       f'class="cl">{escape(str(row.get("label", "")))}</text>')
    lx = pad_l
    for si, (key, name) in enumerate(series):                  # legend
        out.append(f'<rect x="{lx}" y="{height - 8}" width="8" height="8" fill="{_COLORS[si]}"/>'
                   f'<text x="{lx + 12}" y="{height - 0.5}" class="cl">{escape(name)}</text>')
        lx += 22 + 7 * len(name)
    out.append("</svg>")
    return "".join(out)


def _nice_max(peak: int) -> int:
    for step in (1, 2, 4, 5, 8, 10, 20, 40, 50, 80, 100, 200, 400, 500, 800, 1000):
        if peak <= step:
            return step
    magnitude = 10 ** (len(str(peak)) - 1)
    return ((peak // magnitude) + 1) * magnitude


def _fmt(value: float) -> str:
    return f"{value / 1000:.1f}k" if value >= 10000 else f"{value:g}"
