"""Terrain profile between two points and the line-of-sight analysis on top of it."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .dem import Terrain
from .geodesy import bearing, effective_radius, elevation_angle, great_circle, haversine, ray_height


@dataclass
class Observer:
    name: str
    lat: float
    lon: float
    ground_m: float
    eye_m: float

    @property
    def h0(self) -> float:
        return self.ground_m + self.eye_m


@dataclass
class Target:
    name: str
    lat: float
    lon: float
    h_m: float
    h_dem_m: float
    h_source: str  # 'dem', 'dem-peak' or 'override'


@dataclass
class Sample:
    dist_m: float
    lat: float
    lon: float
    h: float      # bilinear DEM height
    h_max: float  # highest of the 4 surrounding pixels


@dataclass
class Zones:
    """Parts of the profile that are not treated as obstacles."""
    near_skip_m: float = 300     # around the observer: buildings and trees in the surface model
    summit_zone_m: float = 300   # the target's own summit cone
    massif_zone_m: float = 5000  # 'foreground' stops this far from the target


@dataclass
class Obstacle:
    dist_km: float
    lat: float
    lon: float
    h_m: float
    angle_deg: float
    clearance_m: float  # how far below the ray to the target summit (negative = it blocks)


@dataclass
class Case:
    """Result for one refraction coefficient and one DEM sampling mode."""
    k: float
    dem: str  # 'bilinear' or 'max4'
    target_angle_deg: float
    visible: bool
    curvature_drop_m: float
    blocker: Obstacle  # highest-angle point anywhere on the route
    target_hidden_below_m: float
    target_visible_m: float
    foreground_blocker: Obstacle  # highest-angle point outside the target's massif
    target_visible_above_foreground_m: float


@dataclass
class Result:
    observer: Observer
    target: Target
    distance_km: float
    bearing_deg: float
    dem_tiles: list[str]
    cases: list[Case] = field(default_factory=list)
    top_obstacles: list[Obstacle] = field(default_factory=list)

    def case(self, k: float, dem: str = 'bilinear') -> Case:
        return next(c for c in self.cases if c.k == k and c.dem == dem)


def build_profile(terrain: Terrain, obs: Observer, tgt: Target, step_m: float) -> list[Sample]:
    dist = haversine(obs.lat, obs.lon, tgt.lat, tgt.lon)
    n = max(2, int(dist / step_m))
    return [Sample(dist * i / n, la, lo, terrain.height(la, lo), terrain.height(la, lo, pessimistic=True))
            for i, (la, lo) in enumerate(great_circle(obs.lat, obs.lon, tgt.lat, tgt.lon, n))]


def _candidates(profile: list[Sample], zones: Zones, pessimistic: bool) -> list[tuple[float, float, float, float]]:
    """(dist, lat, lon, h) of every sample that may act as an obstacle."""
    end = profile[-1].dist_m
    return [(p.dist_m, p.lat, p.lon, p.h_max if pessimistic else p.h) for p in profile
            if zones.near_skip_m <= p.dist_m <= end - zones.summit_zone_m]


def _obstacle(s: float, lat: float, lon: float, h: float, angle: float, target_angle: float,
              h0: float, re: float) -> Obstacle:
    return Obstacle(s / 1000, lat, lon, h, math.degrees(angle), ray_height(s, target_angle, h0, re) - h)


def analyse(profile: list[Sample], obs: Observer, tgt: Target, k: float, zones: Zones,
            pessimistic: bool = False) -> Case:
    re = effective_radius(k)
    h0, dist = obs.h0, profile[-1].dist_m
    a_tgt = elevation_angle(dist, tgt.h_m, h0, re)
    pts = [(elevation_angle(s, h, h0, re), s, la, lo, h) for s, la, lo, h in _candidates(profile, zones, pessimistic)]
    if not pts:
        raise ValueError('the route is too short for the configured zones')
    blk = max(pts)
    fg_pts = [p for p in pts if p[1] <= dist - zones.massif_zone_m]
    fg = max(fg_pts) if fg_pts else blk
    hidden = ray_height(dist, blk[0], h0, re)
    hidden_fg = ray_height(dist, fg[0], h0, re)
    return Case(
        k=k, dem='max4' if pessimistic else 'bilinear',
        target_angle_deg=math.degrees(a_tgt),
        visible=a_tgt > blk[0],
        curvature_drop_m=dist ** 2 / (2 * re),
        blocker=_obstacle(blk[1], blk[2], blk[3], blk[4], blk[0], a_tgt, h0, re),
        target_hidden_below_m=hidden,
        target_visible_m=tgt.h_m - hidden,
        foreground_blocker=_obstacle(fg[1], fg[2], fg[3], fg[4], fg[0], a_tgt, h0, re),
        target_visible_above_foreground_m=tgt.h_m - hidden_fg,
    )


def top_obstacles(profile: list[Sample], obs: Observer, tgt: Target, k: float, zones: Zones,
                  count: int = 8, separation_m: float = 2000) -> list[Obstacle]:
    """The highest-angle points along the route, at least separation_m apart, ordered by distance."""
    re = effective_radius(k)
    h0, dist = obs.h0, profile[-1].dist_m
    a_tgt = elevation_angle(dist, tgt.h_m, h0, re)
    pts = sorted(((elevation_angle(s, h, h0, re), s, la, lo, h)
                  for s, la, lo, h in _candidates(profile, zones, False)), reverse=True)
    tops: list[tuple] = []
    for p in pts:
        if all(abs(p[1] - t[1]) > separation_m for t in tops):
            tops.append(p)
            if len(tops) == count:
                break
    return [_obstacle(t[1], t[2], t[3], t[4], t[0], a_tgt, h0, re) for t in sorted(tops, key=lambda t: t[1])]


def run(terrain: Terrain, obs: Observer, tgt: Target, ks: list[float], plot_k: float, zones: Zones,
        step_m: float) -> tuple[Result, list[Sample]]:
    profile = build_profile(terrain, obs, tgt, step_m)
    result = Result(
        observer=obs, target=tgt,
        distance_km=profile[-1].dist_m / 1000,
        bearing_deg=bearing(obs.lat, obs.lon, tgt.lat, tgt.lon),
        dem_tiles=sorted('%s %s' % (t.label, t.path.name) for t in terrain.tiles),
    )
    for k in sorted(set(ks) | {plot_k}):
        for pessimistic in (False, True):
            result.cases.append(analyse(profile, obs, tgt, k, zones, pessimistic))
    result.top_obstacles = top_obstacles(profile, obs, tgt, plot_k, zones)
    return result, profile
