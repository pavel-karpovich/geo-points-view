"""SVG profile diagram and its PNG rendering through a headless Chrome/Chromium."""
from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

from .analysis import Result, Sample, Zones
from .geodesy import effective_radius, tangent_xy
from .i18n import tr

WIDTH, HEIGHT = 1100, 540
_MARGIN_L, _MARGIN_R, _MARGIN_T, _MARGIN_B = 64, 64, 58, 62
_BROWSERS = ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser', 'chrome')


def _nice_step(span: float) -> int:
    for step in (100, 200, 250, 500, 1000, 2000, 2500, 5000):
        if span / step <= 9:
            return step
    return 10000


def draw_svg(result: Result, profile: list[Sample], k: float, zones: Zones, lang: str) -> str:
    """Profile in the observer's tangent-plane frame: rays are straight, altitude lines curve down."""
    case = result.case(k)
    obs, tgt = result.observer, result.target
    re = effective_radius(k)
    dist = profile[-1].dist_m
    h0 = obs.h0
    a_tgt = math.radians(case.target_angle_deg)
    # the second ray goes over whatever matters more: the blocker if hidden, else the foreground
    second = case.foreground_blocker if case.visible else case.blocker
    a_second = math.radians(second.angle_deg)

    terr = [tangent_xy(p.dist_m, p.h, re) for p in profile[::max(1, len(profile) // 3000)]]
    terr.append(tangent_xy(dist, tgt.h_m, re))
    end_sea = tangent_xy(dist, 0, re)[1]
    lo = min(min(y for _, y in terr), end_sea)
    hi = max(max(y for _, y in terr), h0)
    step = _nice_step(hi - lo)
    ymin = math.floor((lo - 0.04 * (hi - lo)) / step) * step
    ymax = math.ceil((hi + 0.12 * (hi - lo)) / step) * step
    xmax = tangent_xy(dist, 0, re)[0]
    ml, mr, mt, mb = _MARGIN_L, _MARGIN_R, _MARGIN_T, _MARGIN_B
    pw, ph = WIDTH - ml - mr, HEIGHT - mt - mb

    def X(x: float) -> float:
        return ml + x / xmax * pw

    def Y(y: float) -> float:
        return mt + (ymax - y) / (ymax - ymin) * ph

    exaggeration = (ph / (ymax - ymin)) / (pw / xmax)

    def altitude_line(alt: float, n: int = 120) -> str:
        points = (tangent_xy(dist * i / n, alt, re) for i in range(n + 1))
        return ' '.join('%.1f,%.1f' % (X(x), Y(y)) for x, y in points)

    def ray(angle: float) -> str:
        return '%.1f,%.1f %.1f,%.1f' % (X(0), Y(h0), X(xmax), Y(h0 + xmax * math.tan(angle)))

    def t(key: str, **kw) -> str:
        return escape(tr(lang, key, **kw))

    o = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" '
         'font-family="DejaVu Sans, Arial, sans-serif" font-size="13">' % (WIDTH, HEIGHT, WIDTH, HEIGHT),
         '<style>text{paint-order:stroke;stroke:#fff;stroke-width:3px;stroke-linejoin:round}</style>',
         '<defs><clipPath id="plot"><rect x="%d" y="%d" width="%d" height="%d"/></clipPath></defs>' % (ml, mt, pw, ph),
         '<rect width="100%" height="100%" fill="#fff"/>',
         '<g clip-path="url(#plot)">']
    poly = ' '.join('%.1f,%.1f' % (X(x), Y(y)) for x, y in terr)
    o.append('<polygon points="%s %.1f,%.1f %.1f,%.1f" fill="#c9b79c" stroke="#7a6248" stroke-width="1"/>'
             % (poly, X(xmax), Y(ymin) + 2, X(0), Y(ymin) + 2))
    # constant-altitude lines bend down with the Earth; lines above ymax at the observer dip into view later
    grid = list(range(int(ymin), int(ymax - end_sea) + 1, step))
    for alt in grid:
        sea = alt == 0
        o.append('<polyline points="%s" fill="none" stroke="%s" stroke-opacity="%s" stroke-width="1"%s/>' % (
            altitude_line(alt), '#333' if sea else '#000', '0.7' if sea else '0.16',
            ' stroke-dasharray="5 4"' if sea else ''))
    o.append('<polyline points="%s" fill="none" stroke="#1f77b4" stroke-width="1.3" stroke-dasharray="7 4"/>'
             % ray(a_second))
    o.append('<polyline points="%s" fill="none" stroke="#d62728" stroke-width="1.6"/>' % ray(a_tgt))
    o.append('</g>')
    o.append('<rect x="%d" y="%d" width="%d" height="%d" fill="none" stroke="#999"/>' % (ml, mt, pw, ph))

    # altitude labels at both ends of each line that is inside the plot there
    for alt in grid:
        for s, x, anchor, dx in ((0, 0, 'end', -6), (dist, xmax, 'start', 6)):
            y = tangent_xy(s, alt, re)[1]
            if ymin <= y <= ymax:
                o.append('<text x="%.1f" y="%.1f" text-anchor="%s" fill="#555">%d</text>'
                         % (X(x) + dx, Y(y) + 4, anchor, alt))
    o.append('<text x="%.1f" y="%.1f" text-anchor="end" fill="#777" font-size="11">%s</text>'
             % (X(xmax) - 6, Y(end_sea) - 6, t('sea_level')))
    km_step = 10 if dist < 150_000 else 20 if dist < 300_000 else 50
    for km in range(0, int(dist / 1000) + 1, km_step):
        o.append('<text x="%.1f" y="%d" text-anchor="middle">%d</text>' % (X(km * 1000), HEIGHT - mb + 18, km))
    o.append('<text x="%.1f" y="%d" text-anchor="middle">%s</text>'
             % (ml + pw / 2, HEIGHT - 14, t('x_axis', a=obs.name, ex='%.0f' % exaggeration)))

    # observer, target and the obstacle the second ray touches
    o.append('<circle cx="%.1f" cy="%.1f" r="3.5" fill="#000"/>' % (X(0), Y(h0)))
    o.append('<text x="%.1f" y="%.1f" font-weight="bold">%s %.0f %s</text>'
             % (X(0) + 8, Y(h0) + 18, escape(obs.name), obs.ground_m, t('m')))
    bx, by = tangent_xy(dist, tgt.h_m, re)
    o.append('<circle cx="%.1f" cy="%.1f" r="3.5" fill="#d62728"/>' % (X(bx), Y(by)))
    o.append('<text x="%.1f" y="%.1f" text-anchor="end" font-weight="bold">%s %.0f %s</text>'
             % (X(bx) - 8, Y(by) - 8, escape(tgt.name), tgt.h_m, t('m')))
    sx, sy = tangent_xy(second.dist_km * 1000, second.h_m, re)
    o.append('<circle cx="%.1f" cy="%.1f" r="3" fill="#1f77b4"/>' % (X(sx), Y(sy)))
    anchor = 'end' if X(sx) > WIDTH - mr - 160 else 'start' if X(sx) < ml + 160 else 'middle'
    o.append('<text x="%.1f" y="%.1f" text-anchor="%s" fill="#1f5f99">%.0f %s, %.1f %s</text>' % (
        # near either edge the label goes under the point, clear of the rays converging there;
        # near the observer it also has to clear the observer's own label
        X(sx) + {'end': -8, 'start': 8, 'middle': 0}[anchor], Y(sy) + {'end': 22, 'start': 38, 'middle': -10}[anchor],
        anchor,
        second.h_m, t('m'), second.dist_km, t('km')))

    # title and legend
    verdict = (tr(lang, 'verdict_visible', b=tgt.name, v=case.target_visible_above_foreground_m) if case.visible
               else tr(lang, 'verdict_hidden', b=tgt.name, h=case.blocker.h_m, d=case.blocker.dist_km))
    o.append('<text x="%d" y="22" font-size="15" font-weight="bold">%s → %s · %.1f %s · %s</text>' % (
        ml, escape(obs.name), escape(tgt.name), dist / 1000, t('km'), escape(verdict)))
    legend = [('#d62728', '', t('ray_target', b=tgt.name)),
              ('#1f77b4', '7 4', t('ray_foreground', z='%g' % (zones.massif_zone_m / 1000)) if case.visible
               else t('ray_blocker')),
              ('#bbb', '', t('grid', k='%g' % k))]
    for i, (colour, dash, text) in enumerate(legend):
        y = mt + 18 + i * 18
        o.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="%s" stroke-width="2"%s/>' % (
            ml + 10, ml + 34, y - 4, y - 4, colour, ' stroke-dasharray="%s"' % dash if dash else ''))
        o.append('<text x="%d" y="%.1f">%s</text>' % (ml + 40, y, text))
    o.append('</svg>')
    return '\n'.join(o) + '\n'


def find_browser(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit
    return next((p for p in map(shutil.which, _BROWSERS) if p), None)


def render_png(svg: Path, png: Path, browser: str, scale: int = 2) -> None:
    """Screenshot the SVG in a headless browser at `scale` times its size."""
    profile_dir = tempfile.mkdtemp(prefix='geo-points-view-')
    try:
        subprocess.run([browser, '--headless=new', '--disable-gpu', '--no-sandbox', '--hide-scrollbars',
                        '--user-data-dir=' + profile_dir, '--force-device-scale-factor=%d' % scale,
                        '--window-size=%d,%d' % (WIDTH, HEIGHT), '--screenshot=' + str(png.resolve()),
                        svg.resolve().as_uri()],
                       check=True, capture_output=True, timeout=120)
    finally:
        shutil.rmtree(profile_dir, ignore_errors=True)
