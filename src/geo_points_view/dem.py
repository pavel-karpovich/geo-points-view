"""Copernicus DEM access: on-demand tile download, caching and a small GeoTIFF reader.

The reader handles exactly what Copernicus COG tiles use (little-endian classic TIFF, tiled,
float32, DEFLATE, no predictor or the floating-point predictor), so no GDAL/numpy is needed.
"""
from __future__ import annotations

import itertools
import logging
import math
import os
import shutil
import struct
import urllib.error
import urllib.request
import zlib
from pathlib import Path

from .geodesy import haversine

log = logging.getLogger(__name__)

_TAGS = {256: 'width', 257: 'height', 258: 'bits', 259: 'compression', 317: 'predictor',
         322: 'tile_width', 323: 'tile_height', 324: 'tile_offsets', 325: 'tile_counts',
         339: 'sample_format', 33550: 'pixel_scale', 33922: 'tiepoint'}
_ARRAY_TAGS = {324, 325, 33550, 33922}
_TYPES = {1: ('B', 1), 2: ('c', 1), 3: ('H', 2), 4: ('I', 4), 5: ('II', 8), 12: ('d', 8), 16: ('Q', 8)}


class CogTile:
    """One 1x1 degree DEM tile. Pixel values are read lazily, one internal TIFF tile at a time."""

    def __init__(self, path: str | os.PathLike, label: str = ''):
        self.path = Path(path)
        self.label = label
        self._f = open(self.path, 'rb')
        hdr = self._f.read(8)
        if hdr[:2] != b'II':
            raise ValueError('%s: only little-endian TIFF is supported' % path)
        magic, offset = struct.unpack('<HI', hdr[2:8])
        if magic != 42:
            raise ValueError('%s: BigTIFF is not supported' % path)
        t = self._read_ifd(offset)
        if (t.get('compression'), t.get('sample_format'), t.get('bits')) != (8, 3, 32):
            raise ValueError('%s: expected DEFLATE float32 tiles, got %r' % (path, t))
        self.width, self.height = t['width'], t['height']
        self.tile_w, self.tile_h = t['tile_width'], t['tile_height']
        self.predictor = t.get('predictor', 1)
        self.sx, self.sy = t['pixel_scale'][0], t['pixel_scale'][1]
        self.x0, self.y0 = t['tiepoint'][3], t['tiepoint'][4]  # outer corner of pixel (0, 0)
        self._offsets, self._counts = t['tile_offsets'], t['tile_counts']
        self._tiles_x = (self.width + self.tile_w - 1) // self.tile_w
        self._cache: dict[tuple[int, int], list[tuple[float, ...]]] = {}

    def close(self) -> None:
        self._f.close()

    def _read_ifd(self, offset: int) -> dict:
        self._f.seek(offset)
        count, = struct.unpack('<H', self._f.read(2))
        tags = {}
        for _ in range(count):
            tag, typ, n, value = struct.unpack('<HHI4s', self._f.read(12))
            if tag not in _TAGS:
                continue
            fmt, size = _TYPES[typ]
            if size * n > 4:
                pos = self._f.tell()
                self._f.seek(struct.unpack('<I', value)[0])
                raw = self._f.read(size * n)
                self._f.seek(pos)
            else:
                raw = value[:size * n]
            vals = struct.unpack('<' + fmt * n, raw)
            tags[_TAGS[tag]] = vals if tag in _ARRAY_TAGS else vals[0]
        return tags

    def _block(self, bx: int, by: int) -> list[tuple[float, ...]]:
        key = (bx, by)
        if key not in self._cache:
            i = by * self._tiles_x + bx
            self._f.seek(self._offsets[i])
            self._cache[key] = self._decode(zlib.decompress(self._f.read(self._counts[i])))
        return self._cache[key]

    def _decode(self, data: bytes) -> list[tuple[float, ...]]:
        w, rows = self.tile_w, []
        row_len = w * 4
        for r in range(self.tile_h):
            raw = data[r * row_len:(r + 1) * row_len]
            if self.predictor == 1:
                rows.append(struct.unpack('<%df' % w, raw))
            elif self.predictor == 3:
                # floating-point predictor: byte-wise horizontal differencing over byte planes,
                # planes stored most-significant byte first
                row = bytes(b & 0xFF for b in itertools.accumulate(raw))
                planes = row[0:w], row[w:2 * w], row[2 * w:3 * w], row[3 * w:]
                rows.append(struct.unpack('>%df' % w, bytes(itertools.chain.from_iterable(zip(*planes)))))
            else:
                raise NotImplementedError('TIFF predictor %d' % self.predictor)
        return rows

    def pixel(self, col: int, row: int) -> float:
        col = min(max(col, 0), self.width - 1)
        row = min(max(row, 0), self.height - 1)
        return self._block(col // self.tile_w, row // self.tile_h)[row % self.tile_h][col % self.tile_w]

    def colrow(self, lat: float, lon: float) -> tuple[float, float]:
        """Fractional pixel coordinates; integer values are pixel centres."""
        return (lon - self.x0) / self.sx - 0.5, (self.y0 - lat) / self.sy - 0.5

    def centre(self, col: int, row: int) -> tuple[float, float]:
        return self.y0 - (row + 0.5) * self.sy, self.x0 + (col + 0.5) * self.sx

    def bilinear(self, lat: float, lon: float) -> float:
        c, r = self.colrow(lat, lon)
        c0, r0 = math.floor(c), math.floor(r)
        fc, fr = c - c0, r - r0
        return (self.pixel(c0, r0) * (1 - fc) * (1 - fr) + self.pixel(c0 + 1, r0) * fc * (1 - fr)
                + self.pixel(c0, r0 + 1) * (1 - fc) * fr + self.pixel(c0 + 1, r0 + 1) * fc * fr)

    def max4(self, lat: float, lon: float) -> float:
        """Highest of the 4 surrounding pixels: a pessimistic obstacle height."""
        c, r = self.colrow(lat, lon)
        c0, r0 = math.floor(c), math.floor(r)
        return max(self.pixel(c0, r0), self.pixel(c0 + 1, r0), self.pixel(c0, r0 + 1), self.pixel(c0 + 1, r0 + 1))


def tile_name(lat_floor: int, lon_floor: int) -> str:
    return '%s%02d_00_%s%03d_00' % ('N' if lat_floor >= 0 else 'S', abs(lat_floor),
                                     'E' if lon_floor >= 0 else 'W', abs(lon_floor))


class Terrain:
    """Elevation lookup over any number of Copernicus tiles, downloaded on first use."""

    # tried in order; GLO-30 is not published for some tiles, GLO-90 covers them
    SOURCES = (
        ('GLO-30', 'https://copernicus-dem-30m.s3.amazonaws.com', 10),
        ('GLO-90', 'https://copernicus-dem-90m.s3.amazonaws.com', 30),
    )

    def __init__(self, cache_dir: str | os.PathLike):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._tiles: dict[tuple[int, int], CogTile | None] = {}

    def close(self) -> None:
        for t in self.tiles:
            t.close()

    def __enter__(self) -> Terrain:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def tiles(self) -> list[CogTile]:
        return [t for t in self._tiles.values() if t is not None]

    def tile(self, lat: float, lon: float) -> CogTile | None:
        key = (math.floor(lat), math.floor(lon))
        if key not in self._tiles:
            self._tiles[key] = self._load(*key)
        return self._tiles[key]

    def _load(self, lat_floor: int, lon_floor: int) -> CogTile | None:
        tag = tile_name(lat_floor, lon_floor)
        for label, base, arcsec in self.SOURCES:
            name = 'Copernicus_DSM_COG_%d_%s_DEM' % (arcsec, tag)
            path = self.cache_dir / (name + '.tif')
            missing = path.with_name(path.name + '.missing')
            if missing.exists():
                continue
            if not path.exists():
                log.info('downloading %s tile %s', label, tag)
                part = path.with_name(path.name + '.part')
                try:
                    with urllib.request.urlopen('%s/%s/%s.tif' % (base, name, name), timeout=120) as r, \
                            open(part, 'wb') as f:
                        shutil.copyfileobj(r, f)
                except urllib.error.HTTPError as e:
                    part.unlink(missing_ok=True)
                    if e.code not in (403, 404):
                        raise
                    missing.touch()  # remember: this source has no such tile
                    continue
                part.replace(path)
            return CogTile(path, label)
        log.info('no DEM tile for %s, treating it as sea level', tag)
        return None

    def height(self, lat: float, lon: float, pessimistic: bool = False) -> float:
        t = self.tile(lat, lon)
        if t is None:
            return 0.0
        return t.max4(lat, lon) if pessimistic else t.bilinear(lat, lon)

    def peak(self, lat: float, lon: float, radius_m: float) -> tuple[float, float, float]:
        """Highest DEM pixel within radius_m of (lat, lon) as (height, lat, lon)."""
        dlat = radius_m / 110950
        dlon = radius_m / (111320 * math.cos(math.radians(lat)))
        best = (self.height(lat, lon), lat, lon)
        candidates = {self.tile(la, lo) for la in (lat - dlat, lat + dlat) for lo in (lon - dlon, lon + dlon)}
        for t in candidates - {None}:
            c, r = t.colrow(lat, lon)
            dc, dr = int(dlon / t.sx) + 1, int(dlat / t.sy) + 1
            for row in range(max(0, int(r) - dr), min(t.height, int(r) + dr + 1)):
                for col in range(max(0, int(c) - dc), min(t.width, int(c) + dc + 1)):
                    plat, plon = t.centre(col, row)
                    if haversine(lat, lon, plat, plon) <= radius_m:
                        v = t.pixel(col, row)
                        if v > best[0]:
                            best = (v, plat, plon)
        return best
