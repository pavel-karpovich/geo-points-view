"""Command-line entry point: parse arguments, run the analysis, write outputs, print a summary."""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import shutil
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from . import __version__
from .analysis import Observer, Result, Target, Zones, run
from .dem import Terrain
from .i18n import HEIGHT_SOURCE, LANGUAGES, tr
from .render import draw_svg, find_browser, render_png

REFRACTION_CASES = (0.0, 0.13, 0.20)  # none, standard atmosphere, strong

_TRANSLIT = dict(zip('абвгдеёжзийклмнопрстуфхцчшщъыьэюя',
                     ['a', 'b', 'v', 'g', 'd', 'e', 'e', 'zh', 'z', 'i', 'y', 'k', 'l', 'm', 'n', 'o', 'p', 'r', 's',
                      't', 'u', 'f', 'kh', 'ts', 'ch', 'sh', 'shch', '', 'y', '', 'e', 'yu', 'ya']))


def slug(name: str) -> str:
    """ASCII file-name part: 'Казбек' -> 'kazbek', 'Mt. Ararat' -> 'mt-ararat'."""
    s = ''.join(_TRANSLIT.get(c, c) for c in name.lower())
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-') or 'point'


def latlon(text: str) -> tuple[float, float]:
    try:
        lat, lon = (float(v) for v in text.replace(' ', '').split(','))
    except ValueError:
        raise argparse.ArgumentTypeError('expected "lat,lon" in decimal degrees, got %r' % text) from None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise argparse.ArgumentTypeError('coordinates out of range: %r' % text)
    return lat, lon


_COORD = re.compile(r'^\s*-?\d+(\.\d*)?\s*,\s*-?\d+(\.\d*)?\s*$')


def coordinates_last(argv: list[str]) -> list[str]:
    """Move "lat,lon" tokens behind "--" so argparse does not read "-33.9,18.4" as an option."""
    if '--' in argv:
        return argv
    coords = [a for a in argv if _COORD.match(a)]
    return [a for a in argv if not _COORD.match(a)] + ['--'] + coords


def default_cache_dir() -> Path:
    base = os.environ.get('XDG_CACHE_HOME') or os.path.join(os.path.expanduser('~'), '.cache')
    return Path(base) / 'geo-points-view' / 'dem'


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog='geo-points-view',
        description='Can the summit at point B be seen from point A? Builds a terrain profile from the '
                    'Copernicus DEM and checks the line of sight with Earth curvature and refraction.',
        epilog='Coordinates are decimal degrees "lat,lon"; south and west are negative, '
               'e.g. geo-points-view -33.96,18.40 -34.35,18.47')
    p.add_argument('a', type=latlon, metavar='A', help='observer, "lat,lon"')
    p.add_argument('b', type=latlon, metavar='B', help='target, "lat,lon"')
    p.add_argument('--version', action='version', version='%(prog)s ' + __version__)

    g = p.add_argument_group('points')
    g.add_argument('--name-a', default='A', help='observer name for the diagram and file names (default: A)')
    g.add_argument('--name-b', default='B', help='target name for the diagram and file names (default: B)')
    g.add_argument('--eye', type=float, default=2.0, metavar='M', help='eye height above the ground, m (default: 2)')
    g.add_argument('--h-a', type=float, metavar='M', help='observer ground altitude instead of the DEM value, m')
    g.add_argument('--h-b', type=float, metavar='M', help='target altitude instead of the DEM value, m '
                                                          '(e.g. the official summit height)')
    g.add_argument('--snap-a', type=float, default=0, metavar='M',
                   help='move A to the highest DEM pixel within this radius, m (default: 0 = off)')
    g.add_argument('--snap-b', type=float, default=1000, metavar='M',
                   help='move B to the highest DEM pixel within this radius, m (default: 1000; 0 = off)')

    g = p.add_argument_group('model')
    g.add_argument('--k', type=float, default=0.13, metavar='K',
                   help='refraction coefficient for the diagram and the obstacle list (default: 0.13)')
    g.add_argument('--step', type=float, default=15, metavar='M', help='profile sampling step, m (default: 15)')
    g.add_argument('--near-skip', type=float, default=300, metavar='M',
                   help='ignore terrain this close to A: buildings/trees in the surface model, m (default: 300)')
    g.add_argument('--summit-zone', type=float, default=300, metavar='M',
                   help="ignore the target's own summit cone within this distance of B, m (default: 300)")
    g.add_argument('--massif-zone', type=float, default=5000, metavar='M',
                   help='the "foreground" ends this far before B, m (default: 5000)')

    g = p.add_argument_group('output')
    g.add_argument('--lang', choices=LANGUAGES, default='en', help='language of the diagram and summary (default: en)')
    g.add_argument('--output-dir', type=Path, default=Path('output'), metavar='DIR',
                   help='each run writes to DIR/<a>-<b>-<timestamp>/ (default: ./output)')
    g.add_argument('--diagrams-dir', type=Path, default=Path('diagrams'), metavar='DIR',
                   help='the SVG is also copied to DIR/<a>-<b>.svg (default: ./diagrams)')
    g.add_argument('--no-diagram', action='store_true', help='do not copy the SVG to the diagrams directory')
    g.add_argument('--no-png', action='store_true', help='do not render a PNG')
    g.add_argument('--browser', metavar='PATH', help='Chrome/Chromium executable for the PNG (default: search PATH)')
    g.add_argument('--cache-dir', type=Path, default=default_cache_dir(), metavar='DIR',
                   help='where DEM tiles are cached (default: %(default)s)')
    g.add_argument('-q', '--quiet', action='store_true', help='print only the summary')
    return p


def write_outputs(run_dir: Path, result: Result, profile, opt) -> None:
    run_dir.mkdir(parents=True)
    meta = {'version': __version__, 'generated': datetime.now().astimezone().isoformat(timespec='seconds'),
            'parameters': {'k_diagram': opt.k, 'k_cases': sorted(set(REFRACTION_CASES) | {opt.k}),
                           'step_m': opt.step, 'zones': asdict(opt.zones)}}
    with open(run_dir / 'result.json', 'w', encoding='utf-8') as f:
        json.dump({**meta, **asdict(result)}, f, indent=1, ensure_ascii=False)
    with open(run_dir / 'profile.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['dist_m', 'lat', 'lon', 'h_bilinear_m', 'h_max4_m'])
        for s in profile:
            w.writerow(['%.1f' % s.dist_m, '%.6f' % s.lat, '%.6f' % s.lon, '%.1f' % s.h, '%.1f' % s.h_max])
    (run_dir / 'profile.svg').write_text(draw_svg(result, profile, opt.k, opt.zones, opt.lang), encoding='utf-8')


def print_summary(result: Result, opt, out=None) -> None:
    out = out or sys.stdout
    L = opt.lang
    m, km = tr(L, 'm'), tr(L, 'km')
    o, t = result.observer, result.target
    print('%s: %s (%.5f, %.5f), %s' % (tr(L, 'observer'), o.name, o.lat, o.lon,
                                        tr(L, 'ground', g=o.ground_m, e=o.eye_m)), file=out)
    print('%s: %s (%.5f, %.5f), %.0f %s [%s]' % (tr(L, 'target'), t.name, t.lat, t.lon, t.h_m, m,
                                                HEIGHT_SOURCE[L][t.h_source]), file=out)
    print(tr(L, 'distance', d=result.distance_km, b=result.bearing_deg), file=out)
    print('%s: %s' % (tr(L, 'dem'), ', '.join(result.dem_tiles)), file=out)
    print(file=out)
    row = '%-5s %-9s %-6s %-8s %-30s %-14s %s'
    print(row % (tr(L, 'col_k'), tr(L, 'col_dem'), tr(L, 'col_vis'), tr(L, 'col_angle'), tr(L, 'col_blocker'),
                 tr(L, 'col_top'), tr(L, 'col_fg')), file=out)
    for c in result.cases:
        b, f = c.blocker, c.foreground_blocker
        print(row % ('%.2f' % c.k, c.dem, tr(L, 'yes') if c.visible else tr(L, 'no'),
                     '%.3f°' % c.target_angle_deg,
                     '%.0f %s @ %.1f %s (%.3f°)' % (b.h_m, m, b.dist_km, km, b.angle_deg),
                     '%.0f %s' % (c.target_visible_m, m),
                     '%.0f %s (%.0f %s @ %.1f %s)' % (c.target_visible_above_foreground_m, m, f.h_m, m, f.dist_km, km)),
              file=out)
    print(file=out)
    print(tr(L, 'top', k='%g' % opt.k), file=out)
    for x in result.top_obstacles:
        print('  %6.1f %s  %8.4f, %8.4f  %5.0f %s  %6.3f°  %s %6.0f %s'
              % (x.dist_km, km, x.lat, x.lon, x.h_m, m, x.angle_deg, tr(L, 'clearance'), x.clearance_m, m), file=out)


def main(argv: list[str] | None = None) -> int:
    opt = build_parser().parse_args(coordinates_last(sys.argv[1:] if argv is None else argv))
    logging.basicConfig(level=logging.WARNING if opt.quiet else logging.INFO, format='%(message)s')
    log = logging.getLogger('geo_points_view')
    opt.zones = Zones(opt.near_skip, opt.summit_zone, opt.massif_zone)

    with Terrain(opt.cache_dir) as terrain:
        (lat_a, lon_a), (lat_b, lon_b) = opt.a, opt.b
        if opt.snap_a:
            _, lat_a, lon_a = terrain.peak(lat_a, lon_a, opt.snap_a)
        ground_a = opt.h_a if opt.h_a is not None else terrain.height(lat_a, lon_a)
        if opt.snap_b:
            h_dem_b, lat_b, lon_b = terrain.peak(lat_b, lon_b, opt.snap_b)
            source = 'dem-peak'
        else:
            h_dem_b, source = terrain.height(lat_b, lon_b), 'dem'
        observer = Observer(opt.name_a, lat_a, lon_a, ground_a, opt.eye)
        target = Target(opt.name_b, lat_b, lon_b, opt.h_b if opt.h_b is not None else h_dem_b, h_dem_b,
                        'override' if opt.h_b is not None else source)
        result, profile = run(terrain, observer, target, list(REFRACTION_CASES), opt.k, opt.zones, opt.step)

    pair = '%s-%s' % (slug(opt.name_a), slug(opt.name_b))
    run_dir = opt.output_dir / ('%s-%s' % (pair, datetime.now().strftime('%Y%m%d-%H%M%S')))
    write_outputs(run_dir, result, profile, opt)
    if not opt.no_png:
        browser = find_browser(opt.browser)
        if browser:
            render_png(run_dir / 'profile.svg', run_dir / 'profile.png', browser)
        else:
            log.warning(tr(opt.lang, 'png_skipped'))

    print_summary(result, opt)
    print()
    print(tr(opt.lang, 'written', d=run_dir))
    if not opt.no_diagram:
        opt.diagrams_dir.mkdir(parents=True, exist_ok=True)
        diagram = opt.diagrams_dir / (pair + '.svg')
        shutil.copyfile(run_dir / 'profile.svg', diagram)
        print(tr(opt.lang, 'diagram', p=diagram))
    return 0


if __name__ == '__main__':
    sys.exit(main())
