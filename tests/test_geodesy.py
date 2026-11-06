import math
import unittest

from geo_points_view.geodesy import (R_EARTH, bearing, effective_radius, elevation_angle, great_circle, haversine,
                                     ray_height, tangent_xy)


class GeodesyTest(unittest.TestCase):
    def test_haversine_one_degree_of_latitude(self):
        self.assertAlmostEqual(haversine(0, 0, 1, 0), R_EARTH * math.pi / 180, places=3)

    def test_bearing_cardinal_directions(self):
        self.assertAlmostEqual(bearing(0, 0, 1, 0), 0)
        self.assertAlmostEqual(bearing(0, 0, 0, 1), 90)
        self.assertAlmostEqual(bearing(1, 0, 0, 0), 180)
        self.assertAlmostEqual(bearing(0, 1, 0, 0), 270)

    def test_great_circle_endpoints_and_spacing(self):
        pts = great_circle(41.69, 44.79, 42.70, 44.52, 10)
        self.assertEqual(len(pts), 11)
        self.assertAlmostEqual(pts[0][0], 41.69)
        self.assertAlmostEqual(pts[-1][1], 44.52)
        steps = [haversine(*pts[i], *pts[i + 1]) for i in range(10)]
        self.assertAlmostEqual(min(steps), max(steps), places=3)

    def test_curvature_drop(self):
        # without refraction the surface falls ~d^2 / 2R below the observer's horizontal
        _, y = tangent_xy(100_000, 0, R_EARTH)
        self.assertAlmostEqual(-y, 100_000 ** 2 / (2 * R_EARTH), delta=1)
        # refraction makes the effective Earth flatter
        self.assertGreater(effective_radius(0.13), R_EARTH)

    def test_ray_height_inverts_elevation_angle(self):
        re = effective_radius(0.13)
        for s, h in ((5_000, 300.0), (113_000, 5025.0), (190_000, 0.0)):
            a = elevation_angle(s, h, 734.0, re)
            self.assertAlmostEqual(ray_height(s, a, 734.0, re), h, places=4)


if __name__ == '__main__':
    unittest.main()
