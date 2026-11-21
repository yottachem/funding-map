"""Server-rendered SVG charts: no JavaScript, readable without CSS, colors from the page's tokens.

fmt matches the sibling trackers so the sites read alike.
"""
import math
from html import escape


def fmt(v, kind="usd"):
    if v is None:
        return "–"
    if kind == "usd":
        return f"${v / 1e6:,.2f}M" if abs(v) >= 999_500 else f"${v / 1e3:,.0f}K"
    if kind == "pct":
        return f"{v:.0%}"
    return f"{v:,.0f}"


def scale(d0, d1, r0, r1):
    k = (r1 - r0) / (d1 - d0) if d1 != d0 else 0
    return lambda v: r0 + (v - d0) * k


def _place_labels(placed, width, left, char_w=7.2):
    """placed: [(cx, cy, label)]. Returns [(tx, ty, anchor)] chosen to overlap dots and earlier labels least."""
    boxes = [(cx - 8, cy - 8, cx + 8, cy + 8) for cx, cy, _ in placed]
    out = []
    for cx, cy, label in placed:
        tw = char_w * len(label)
        cands = [(cx + 11, cy + 4, "start"), (cx - 11, cy + 4, "end"), (cx + 6, cy - 12, "start"),
                 (cx - 6, cy - 12, "end"), (cx + 6, cy + 21, "start"), (cx - 6, cy + 21, "end")]

        def box(c):
            tx, ty, a = c
            x0 = tx if a == "start" else tx - tw
            return (x0, ty - 11, x0 + tw, ty + 3)

        def bad(bx):
            return sum(max(0, min(bx[2], o[2]) - max(bx[0], o[0])) * max(0, min(bx[3], o[3]) - max(bx[1], o[1]))
                       for o in boxes) + (1e6 if bx[2] > width or bx[0] < left - 4 else 0)

        best = min(cands, key=lambda c: bad(box(c)))
        boxes.append(box(best))
        out.append(best)
    return out


def size_odds(points, *, width=960, height=430, desc=""):
    """points: [{"label", "href", "size" (USD > 0), "rate" (0-1), "kind" ("entry" | "follow-on"), "tip"}].
    x: typical award, log scale. y: published success rate."""
    top, bottom, left, right = 16, 52, 58, 24
    lo = min(p["size"] for p in points) * 0.75
    hi = max(p["size"] for p in points) * 1.35
    ymax = math.ceil((max(p["rate"] for p in points) + 0.04) * 10) / 10
    x = (lambda f: lambda v: f(math.log10(v)))(scale(math.log10(lo), math.log10(hi), left, width - right))
    y = scale(0, ymax, height - bottom, top)
    out = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{escape(desc)}" class="chart scatter">']
    for t in [i / 10 for i in range(0, int(round(ymax * 10)) + 1)]:
        out.append(f'<line x1="{left}" x2="{width - right}" y1="{y(t):.1f}" y2="{y(t):.1f}" class="grid{" zero" if t == 0 else ""}"/>'
                   f'<text x="{left - 8}" y="{y(t) + 4:.1f}" text-anchor="end" class="tick">{t:.0%}</text>')
    for v in (25e3, 50e3, 100e3, 200e3, 500e3, 1e6, 2e6, 5e6):
        if lo <= v <= hi:
            out.append(f'<line x1="{x(v):.1f}" x2="{x(v):.1f}" y1="{top}" y2="{height - bottom}" class="grid"/>'
                       f'<text x="{x(v):.1f}" y="{height - bottom + 16}" text-anchor="middle" class="tick">{fmt(v)}</text>')
    out.append(f'<text x="{width - right}" y="{height - 8}" text-anchor="end" class="axis">'
               f'Typical award (log scale) →</text>')
    placed = []
    for p in sorted(points, key=lambda p: (p["size"], p["rate"])):
        cx, cy = x(p["size"]), y(p["rate"])
        for dy in (0, -14, 14):
            if all((cx - qx) ** 2 + ((cy + dy) - qy) ** 2 >= 16 ** 2 for qx, qy, _ in placed):
                cy += dy
                break
        placed.append((cx, cy, p))
    spots = _place_labels([(cx, cy, p["label"]) for cx, cy, p in placed], width, left)
    dots, labels = [], []
    for (cx, cy, p), (tx, ty, a) in zip(placed, spots):
        dots.append(f'<a href="{p["href"]}"><circle cx="{cx:.1f}" cy="{cy:.1f}" r="7" class="k-{p["kind"]}">'
                    f'<title>{escape(p["tip"])}</title></circle></a>')
        labels.append(f'<a href="{p["href"]}"><text x="{tx:.1f}" y="{ty:.1f}" text-anchor="{a}" class="lab">'
                      f'{escape(p["label"])}</text></a>')
    out += dots + labels + ["</svg>"]
    return "".join(out)


def history(rows, *, width=560, height=230, desc=""):
    """rows: [{"year", "awards", "p10", "median", "p90"}], oldest first. Bars are the median award; the whisker runs
    from the 10th to the 90th percentile; the count of awards sits above."""
    top, bottom, left, right = 22, 34, 62, 12
    ymax = max(r["p90"] or r["median"] for r in rows) * 1.12
    y = scale(0, ymax, height - bottom, top)
    band = (width - left - right) / len(rows)
    bw = min(46, band * 0.55)
    out = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{escape(desc)}" class="chart">']
    step = _nice(ymax / 4)
    t = 0.0
    while t <= ymax:
        out.append(f'<line x1="{left}" x2="{width - right}" y1="{y(t):.1f}" y2="{y(t):.1f}" class="grid{" zero" if t == 0 else ""}"/>'
                   f'<text x="{left - 8}" y="{y(t) + 4:.1f}" text-anchor="end" class="tick">{fmt(t) if t else "$0"}</text>')
        t += step
    for i, r in enumerate(rows):
        cx = left + band * i + band / 2
        out.append(f'<rect x="{cx - bw / 2:.1f}" y="{y(r["median"]):.1f}" width="{bw:.1f}" '
                   f'height="{y(0) - y(r["median"]):.1f}" class="bar"><title>FY{r["year"]}: median {fmt(r["median"])} '
                   f'of {r["awards"]} awards</title></rect>')
        if r["p10"] is not None and r["p90"] is not None:
            out.append(f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{y(r["p10"]):.1f}" y2="{y(r["p90"]):.1f}" class="whisk"/>'
                       f'<line x1="{cx - 6:.1f}" x2="{cx + 6:.1f}" y1="{y(r["p90"]):.1f}" y2="{y(r["p90"]):.1f}" class="whisk"/>'
                       f'<line x1="{cx - 6:.1f}" x2="{cx + 6:.1f}" y1="{y(r["p10"]):.1f}" y2="{y(r["p10"]):.1f}" class="whisk"/>')
        top_y = y(r["p90"] if r["p90"] is not None else r["median"])
        out.append(f'<text x="{cx:.1f}" y="{top_y - 6:.1f}" text-anchor="middle" class="note">n={r["awards"]}</text>'
                   f'<text x="{cx:.1f}" y="{height - bottom + 16}" text-anchor="middle" class="tick">FY{r["year"]}</text>')
    out.append("</svg>")
    return "".join(out)


def _nice(v):
    e = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * e:
            return m * e
    return 10 * e
