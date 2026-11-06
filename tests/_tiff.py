"""Writes small synthetic DEM tiles in the same TIFF layout as the Copernicus COGs."""
from __future__ import annotations

import struct
import zlib
from pathlib import Path


def _encode_row(values: list[float], predictor: int) -> bytes:
    if predictor == 1:
        return struct.pack('<%df' % len(values), *values)
    be = struct.pack('>%df' % len(values), *values)
    planes = b''.join(be[i::4] for i in range(4))  # most-significant byte plane first
    return bytes([planes[0]] + [(planes[i] - planes[i - 1]) & 0xFF for i in range(1, len(planes))])


def write_tile(path: Path, grid: list[list[float]], west: float, north: float, pixel_deg: float,
               tile_size: int = 4, predictor: int = 3) -> None:
    """grid[row][col], row 0 at the north edge; (west, north) is the outer corner of pixel (0, 0)."""
    h, w = len(grid), len(grid[0])
    blocks = []
    for ty in range(0, h, tile_size):
        for tx in range(0, w, tile_size):
            rows = []
            for r in range(ty, ty + tile_size):
                row = [grid[r][c] if r < h and c < w else 0.0 for c in range(tx, tx + tile_size)]
                rows.append(_encode_row(row, predictor))
            blocks.append(zlib.compress(b''.join(rows)))

    data_start = 8
    offsets, pos = [], data_start
    for b in blocks:
        offsets.append(pos)
        pos += len(b)
    extra_start = pos
    # out-of-line values: tile offsets, tile counts, pixel scale, tiepoint
    extra = b''
    def put(raw: bytes) -> int:
        nonlocal extra
        off = extra_start + len(extra)
        extra += raw
        return off

    entries = []
    def entry(tag: int, typ: int, values: tuple, fmt: str):
        raw = struct.pack('<' + fmt * len(values), *values)
        if len(raw) <= 4:
            entries.append(struct.pack('<HHI', tag, typ, len(values)) + raw.ljust(4, b'\0'))
        else:
            entries.append(struct.pack('<HHII', tag, typ, len(values), put(raw)))

    entry(256, 4, (w,), 'I')
    entry(257, 4, (h,), 'I')
    entry(258, 3, (32,), 'H')
    entry(259, 3, (8,), 'H')
    entry(317, 3, (predictor,), 'H')
    entry(322, 4, (tile_size,), 'I')
    entry(323, 4, (tile_size,), 'I')
    entry(324, 4, tuple(offsets), 'I')
    entry(325, 4, tuple(len(b) for b in blocks), 'I')
    entry(339, 3, (3,), 'H')
    entry(33550, 12, (pixel_deg, pixel_deg, 0.0), 'd')
    entry(33922, 12, (0.0, 0.0, 0.0, west, north, 0.0), 'd')

    ifd_offset = extra_start + len(extra)
    with open(path, 'wb') as f:
        f.write(b'II' + struct.pack('<HI', 42, ifd_offset))
        for b in blocks:
            f.write(b)
        f.write(extra)
        f.write(struct.pack('<H', len(entries)) + b''.join(entries) + struct.pack('<I', 0))
