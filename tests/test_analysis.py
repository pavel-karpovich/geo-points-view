import unittest

from geo_points_view.analysis import Observer, Sample, Target, Zones, analyse, top_obstacles

DIST = 100_000


def profile(bumps: dict[int, float], target_h: float) -> list[Sample]:
    """Flat 100 m terrain sampled every 100 m, with bumps {distance_m: height} and the target at the end."""
    out = []
    for s in range(0, DIST + 1, 100):
        h = target_h if s == DIST else bumps.get(s, 100.0)
        out.append(Sample(float(s), 0.0, 0.0, h, h + 5))
    return out


OBS = Observer('A', 0, 0, 100.0, 10.0)  # eye above the +5 m max4 noise of the flat terrain


class AnalyseTest(unittest.TestCase):
    def test_visible_over_low_ridge(self):
        tgt = Target('B', 0, 0, 3000.0, 3000.0, 'dem')
        case = analyse(profile({50_000: 500.0}, 3000.0), OBS, tgt, 0.13, Zones())
        self.assertTrue(case.visible)
        self.assertEqual(case.foreground_blocker.h_m, 500.0)
        self.assertGreater(case.foreground_blocker.clearance_m, 0)
        self.assertGreater(case.target_visible_above_foreground_m, 0)
        self.assertLess(case.target_visible_above_foreground_m, 3000.0)

    def test_hidden_behind_high_ridge(self):
        tgt = Target('B', 0, 0, 1500.0, 1500.0, 'dem')
        case = analyse(profile({60_000: 2000.0}, 1500.0), OBS, tgt, 0.13, Zones())
        self.assertFalse(case.visible)
        self.assertEqual(case.blocker.h_m, 2000.0)
        self.assertLess(case.blocker.clearance_m, 0)
        self.assertLess(case.target_visible_m, 0)

    def test_zones_exclude_near_buildings_and_the_target_massif(self):
        tgt = Target('B', 0, 0, 3000.0, 3000.0, 'dem')
        bumps = {200: 400.0, DIST - 2000: 2900.0}  # rooftop 200 m away, shoulder 2 km before the summit
        case = analyse(profile(bumps, 3000.0), OBS, tgt, 0.13, Zones(near_skip_m=300, massif_zone_m=5000))
        self.assertTrue(case.visible)
        self.assertEqual(case.blocker.h_m, 2900.0)  # the shoulder is the closest thing to the ray...
        self.assertEqual(case.foreground_blocker.h_m, 100.0)  # ...but not part of the foreground
        hidden = analyse(profile(bumps, 3000.0), OBS, tgt, 0.13, Zones(near_skip_m=0))
        self.assertFalse(hidden.visible)
        self.assertEqual(hidden.blocker.dist_km, 0.2)

    def test_pessimistic_mode_uses_max4(self):
        tgt = Target('B', 0, 0, 3000.0, 3000.0, 'dem')
        case = analyse(profile({50_000: 500.0}, 3000.0), OBS, tgt, 0.13, Zones(), pessimistic=True)
        self.assertEqual(case.dem, 'max4')
        self.assertEqual(case.foreground_blocker.h_m, 505.0)

    def test_top_obstacles_are_separated_and_sorted(self):
        tgt = Target('B', 0, 0, 3000.0, 3000.0, 'dem')
        bumps = {30_000: 600.0, 30_100: 610.0, 70_000: 900.0}
        tops = top_obstacles(profile(bumps, 3000.0), OBS, tgt, 0.13, Zones(), count=2)
        self.assertEqual([t.h_m for t in tops], [610.0, 900.0])


if __name__ == '__main__':
    unittest.main()
