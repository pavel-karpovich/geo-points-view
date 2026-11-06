"""Spherical-Earth geometry: distances, great circles and the observer's tangent-plane frame."""
from __future__ import annotations

import math

R_EARTH = 6371008.8  # mean Earth radius, m


def effective_radius(k: float) -> float:
    """Earth radius that turns refracted (curved) light rays into straight lines."""
    return R_EARTH / (1 - k)


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * R_EARTH * math.asin(math.sqrt(a))


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial great-circle bearing from point 1 to point 2, degrees clockwise from north."""
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def great_circle(lat1: float, lon1: float, lat2: float, lon2: float, n: int) -> list[tuple[float, float]]:
    """n + 1 evenly spaced (lat, lon) points along the great circle, endpoints included."""
    def vec(la: float, lo: float) -> tuple[float, float, float]:
        la, lo = math.radians(la), math.radians(lo)
        return math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la)

    a, b = vec(lat1, lon1), vec(lat2, lon2)
    om = math.acos(max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b)))))
    if om == 0:
        return [(lat1, lon1)] * (n + 1)
    pts = []
    for i in range(n + 1):
        f = i / n
        k1, k2 = math.sin((1 - f) * om) / math.sin(om), math.sin(f * om) / math.sin(om)
        x, y, z = (k1 * a[j] + k2 * b[j] for j in range(3))
        pts.append((math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x))))
    return pts


def tangent_xy(s: float, h: float, re: float) -> tuple[float, float]:
    """Point at arc distance s and altitude h in the observer's tangent-plane frame.

    x runs along the observer's horizontal, y is up, and sea level under the observer is y = 0.
    With the effective radius re, light rays are straight lines in this frame."""
    th = s / re
    return (re + h) * math.sin(th), (re + h) * math.cos(th) - re


def elevation_angle(s: float, h: float, h0: float, re: float) -> float:
    """Elevation angle (radians) of a point at arc distance s and altitude h, seen from altitude h0."""
    x, y = tangent_xy(s, h, re)
    return math.atan2(y - h0, x)


def ray_height(s: float, angle: float, h0: float, re: float) -> float:
    """Altitude at arc distance s of a ray leaving altitude h0 at the given elevation angle (radians)."""
    th = s / re
    return (re + h0) / (math.cos(th) - math.tan(angle) * math.sin(th)) - re
