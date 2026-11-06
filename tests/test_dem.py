import tempfile
import unittest
from pathlib import Path

from geo_points_view.dem import CogTile, Terrain, tile_name

from ._tiff import write_tile

GRID = [[float(r * 10 + c) for c in range(6)] for r in range(5)]  # 6 x 5 pixels, 3 x 2 internal tiles of 4 x 4


class CogTileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def tile(self, predictor):
        path = Path(self.tmp.name) / ('p%d.tif' % predictor)
        write_tile(path, GRID, west=10.0, north=20.0, pixel_deg=0.1, predictor=predictor)
        t = CogTile(path)
        self.addCleanup(t.close)
        return t

    def test_decodes_every_pixel(self):
        for predictor in (1, 3):
            t = self.tile(predictor)
            self.assertEqual((t.width, t.height), (6, 5))
            for r in range(5):
                for c in range(6):
                    self.assertEqual(t.pixel(c, r), GRID[r][c], (predictor, r, c))

    def test_bilinear_hits_pixel_centres_and_interpolates(self):
        t = self.tile(3)
        lat, lon = t.centre(2, 1)
        self.assertAlmostEqual(lat, 19.85)
        self.assertAlmostEqual(lon, 10.25)
        self.assertAlmostEqual(t.bilinear(lat, lon), 12.0)
        # halfway between pixels (2,1), (3,1), (2,2), (3,2)
        self.assertAlmostEqual(t.bilinear(19.80, 10.30), (12 + 13 + 22 + 23) / 4)
        self.assertEqual(t.max4(19.80, 10.30), 23.0)

    def test_pixels_are_clamped_at_the_edge(self):
        t = self.tile(3)
        self.assertEqual(t.pixel(-5, -5), GRID[0][0])
        self.assertEqual(t.pixel(99, 99), GRID[4][5])


class TerrainTest(unittest.TestCase):
    def test_tile_names(self):
        self.assertEqual(tile_name(42, 44), 'N42_00_E044_00')
        self.assertEqual(tile_name(-34, -71), 'S34_00_W071_00')

    def test_uses_cache_and_falls_back_to_glo90(self):
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d)
            # GLO-30 marked as unpublished, GLO-90 present: no network access is needed
            (cache / 'Copernicus_DSM_COG_10_N00_00_E000_00_DEM.tif.missing').touch()
            grid = [[100.0] * 10 for _ in range(10)]
            grid[2][7] = 900.0
            write_tile(cache / 'Copernicus_DSM_COG_30_N00_00_E000_00_DEM.tif', grid, 0.0, 1.0, 0.1)
            with Terrain(cache) as terrain:
                self.assertAlmostEqual(terrain.height(0.5, 0.5), 100.0)
                self.assertEqual(terrain.tiles[0].label, 'GLO-90')
                h, lat, lon = terrain.peak(0.7, 0.7, 20000)
                self.assertEqual(h, 900.0)
                self.assertAlmostEqual(lat, 0.75)
                self.assertAlmostEqual(lon, 0.75)


if __name__ == '__main__':
    unittest.main()
