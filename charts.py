"""Tiny chart helpers that draw charts as inline SVG (no internet or extra library needed)."""
from markupsafe import Markup, escape

COLORS = ["#1f5c3f", "#b8860b", "#2a6fb0", "#b5413a", "#6a4c93", "#2c9a8f"]


def _nice_max(v):
    if v <= 0:
        return 10
    for step in (5, 10, 20, 25, 50, 100, 200, 500):
        if v <= step:
            return step
    return int(v * 1.1)


def bar_chart(labels, series, width=560, height=290, unit="", title=None):
    """series: list of (name, [values]) - grouped bars."""
    left, right, top, bottom = 46, 12, 28, 52
    pw, ph = width - left - right, height - top - bottom
    vmax = _nice_max(max((max(v) for _, v in series if v), default=0))
    n, m = len(labels), len(series)
    gw = pw / max(n, 1)
    bw = gw * 0.7 / m
    out = [f'<svg viewBox="0 0 {width} {height}" class="chart" role="img" aria-label="{escape(title or "chart")}">']
    for i in range(5):
        y = top + ph - ph * i / 4
        out.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" stroke="#e3e6e4"/>')
        out.append(f'<text x="{left - 6}" y="{y + 4:.1f}" text-anchor="end" font-size="10" fill="#555">{vmax * i / 4:g}</text>')
    for si, (name, vals) in enumerate(series):
        for i, v in enumerate(vals):
            if v is None:
                continue
            h = ph * v / vmax
            x = left + i * gw + gw * 0.15 + si * bw
            out.append(f'<rect x="{x:.1f}" y="{top + ph - h:.1f}" width="{bw - 2:.1f}" height="{h:.1f}" fill="{COLORS[si % 6]}" rx="2"/>')
            out.append(f'<text x="{x + bw / 2 - 1:.1f}" y="{top + ph - h - 4:.1f}" text-anchor="middle" font-size="9" fill="#333">{v:g}{unit}</text>')
    for i, lab in enumerate(labels):
        out.append(f'<text x="{left + i * gw + gw / 2:.1f}" y="{top + ph + 16}" text-anchor="middle" font-size="10" fill="#333">{escape(lab)}</text>')
    if m > 1:
        for si, (name, _) in enumerate(series):
            out.append(f'<rect x="{left + si * 130}" y="{height - 16}" width="10" height="10" fill="{COLORS[si % 6]}"/>'
                       f'<text x="{left + si * 130 + 14}" y="{height - 7}" font-size="10" fill="#333">{escape(name)}</text>')
    if title:
        out.append(f'<text x="{left}" y="14" font-size="12" font-weight="bold" fill="#1f5c3f">{escape(title)}</text>')
    out.append("</svg>")
    return Markup("".join(out))


def line_chart(xs, series, width=560, height=290, title=None, forecast_from=None):
    """series: list of (name, [values]); optional forecast_from index draws dashed segment."""
    left, right, top, bottom = 46, 14, 28, 52
    pw, ph = width - left - right, height - top - bottom
    vmax = _nice_max(max(max(v) for _, v in series))
    n = len(xs)
    sx = lambda i: left + pw * i / max(n - 1, 1)
    sy = lambda v: top + ph - ph * v / vmax
    out = [f'<svg viewBox="0 0 {width} {height}" class="chart" role="img" aria-label="{escape(title or "chart")}">']
    for i in range(5):
        y = top + ph - ph * i / 4
        out.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" stroke="#e3e6e4"/>')
        out.append(f'<text x="{left - 6}" y="{y + 4:.1f}" text-anchor="end" font-size="10" fill="#555">{vmax * i / 4:g}</text>')
    for i, x in enumerate(xs):
        out.append(f'<text x="{sx(i):.1f}" y="{top + ph + 16}" text-anchor="middle" font-size="10" fill="#333">{escape(str(x))}</text>')
    for si, (name, vals) in enumerate(series):
        col = COLORS[si % 6]
        solid = vals if forecast_from is None else vals[:forecast_from]
        pts = " ".join(f"{sx(i):.1f},{sy(v):.1f}" for i, v in enumerate(solid))
        out.append(f'<polyline fill="none" stroke="{col}" stroke-width="2.2" points="{pts}"/>')
        if forecast_from is not None and len(vals) > forecast_from:
            seg = " ".join(f"{sx(i):.1f},{sy(vals[i]):.1f}" for i in range(forecast_from - 1, len(vals)))
            out.append(f'<polyline fill="none" stroke="{col}" stroke-width="2.2" stroke-dasharray="5 4" points="{seg}"/>')
        for i, v in enumerate(vals):
            out.append(f'<circle cx="{sx(i):.1f}" cy="{sy(v):.1f}" r="3" fill="{col}"/>')
        out.append(f'<rect x="{left + si * 120}" y="{height - 16}" width="10" height="10" fill="{col}"/>'
                   f'<text x="{left + si * 120 + 14}" y="{height - 7}" font-size="10" fill="#333">{escape(name)}</text>')
    if title:
        out.append(f'<text x="{left}" y="14" font-size="12" font-weight="bold" fill="#1f5c3f">{escape(title)}</text>')
    out.append("</svg>")
    return Markup("".join(out))
