import contextlib
import io
import json
import math
import tempfile
import unittest
from pathlib import Path

from geo_points_view.cli import build_parser, coordinates_last, main, slug

from ._tiff import write_tile


class HelpersTest(unittest.TestCase):
    def test_slug_transliterates_and_cleans(self):
        self.assertEqual(slug('Казбек'), 'kazbek')
        self.assertEqual(slug('Ставрополь (юго-запад)'), 'stavropol-yugo-zapad')
        self.assertEqual(slug('Mt. Ararat'), 'mt-ararat')
        self.assertEqual(slug('!!!'), 'point')

    def test_coordinates_are_validated(self):
        parser = build_parser()
        with contextlib.redirect_stderr(io.StringIO()):
            for bad in ('41.7', '41.7;44.8', '91,0'):
                with self.assertRaises(SystemExit):
                    parser.parse_args([bad, '1,1'])
        opt = parser.parse_args(['--', '-33.9, 18.4', '1,1'])
        self.assertEqual(opt.a, (-33.9, 18.4))
        self.assertEqual(opt.lang, 'en')

    def test_negative_coordinates_need_no_double_dash(self):
        argv = coordinates_last(['-33.96,18.40', '--name-a', 'X', '-34.35,-18.47', '--h-a', '-5', '--no-png'])
        self.assertEqual(argv, ['--name-a', 'X', '--h-a', '-5', '--no-png', '--', '-33.96,18.40', '-34.35,-18.47'])
        opt = build_parser().parse_args(argv)
        self.assertEqual((opt.a, opt.b, opt.h_a), ((-33.96, 18.40), (-34.35, -18.47), -5.0))
        self.assertEqual(coordinates_last(['--', '1,2', '3,4']), ['--', '1,2', '3,4'])


class EndToEndTest(unittest.TestCase):
    def test_run_writes_outputs_and_diagram(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cache = root / 'cache'
            cache.mkdir()
            # 1 x 1 degree of 100 m plains with a 3000 m cone around (0.9, 0.9)
            n = 200
            grid = [[max(100.0, 3000 - 20_000 * math.hypot((r + 0.5) / n - 0.1, (c + 0.5) / n - 0.9))
                     for c in range(n)] for r in range(n)]
            write_tile(cache / 'Copernicus_DSM_COG_10_N00_00_E000_00_DEM.tif', grid, 0.0, 1.0, 1 / n, tile_size=64)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = main(['0.1,0.1', '0.9,0.9', '--name-a', 'Low Point', '--name-b', 'Пик', '--step', '500',
                           '--summit-zone', '2000',
                           '--cache-dir', str(cache), '--output-dir', str(root / 'output'),
                           '--diagrams-dir', str(root / 'diagrams'), '--no-png', '--quiet'])
            self.assertEqual(rc, 0)
            runs = list((root / 'output').iterdir())
            self.assertEqual(len(runs), 1)
            self.assertTrue(runs[0].name.startswith('low-point-pik-'))
            self.assertEqual(sorted(p.name for p in runs[0].iterdir()), ['profile.csv', 'profile.svg', 'result.json'])
            diagram = root / 'diagrams' / 'low-point-pik.svg'
            self.assertEqual(diagram.read_bytes(), (runs[0] / 'profile.svg').read_bytes())
            result = json.loads((runs[0] / 'result.json').read_text())
            self.assertTrue(all(c['visible'] for c in result['cases']))
            self.assertAlmostEqual(result['target']['h_m'], 3000, delta=100)  # summit falls between pixel centres
            self.assertIn('YES', out.getvalue())


if __name__ == '__main__':
    unittest.main()
