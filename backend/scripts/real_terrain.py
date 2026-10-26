#!/usr/bin/env python3
"""Real elevation and mean slope for every zone, from the same AWS Terrain
Tiles DEM the 3D map uses (Terrarium PNGs, SRTM-based, zoom 12 ≈ 34 m/px here).

    python scripts/real_terrain.py

For each zone: fetch the z12 tiles over its polygon, decode them (a small
stdlib PNG decoder — no imaging library needed), keep the pixels inside the
polygon, and store the mean elevation and mean slope (from neighbouring-pixel
differences). Prints old (simulated) vs new (real) values. Lithology and land
cover stay as they were (SIMULATED). The model does not use slope or
elevation (hydro features only), so the backtest numbers do not change.
"""
from __future__ import annotations

import json
import math
import struct
import sys
import time
import urllib.request
import zlib
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.db import ensure_schema_additions, session_scope  # noqa: E402

Z = 12
URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"


def decode_png(data: bytes) -> np.ndarray:
    """8-bit RGB/RGBA, non-interlaced PNG -> (h, w, channels) uint8."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    pos, idat, w, h, ch = 8, b"", 0, 0, 3
    while pos < len(data):
        n, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        if kind == b"IHDR":
            w, h, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
            assert depth == 8 and interlace == 0 and ctype in (2, 6), "unsupported PNG"
            ch = 3 if ctype == 2 else 4
        elif kind == b"IDAT":
            idat += body
        pos += 12 + n
    raw = np.frombuffer(zlib.decompress(idat), dtype=np.uint8).reshape(h, 1 + w * ch)
    out = np.zeros((h, w * ch), dtype=np.int32)
    for r in range(h):
        f, line = raw[r, 0], raw[r, 1:].astype(np.int32)
        prev = out[r - 1] if r else np.zeros(w * ch, dtype=np.int32)
        if f == 0:
            cur = line
        elif f == 2:
            cur = (line + prev) & 255
        else:                                     # 1 sub, 3 average, 4 paeth: left-dependent, per byte
            cur = np.zeros(w * ch, dtype=np.int32)
            for i in range(w * ch):
                a = cur[i - ch] if i >= ch else 0
                b, c = prev[i], (prev[i - ch] if i >= ch else 0)
                if f == 1:
                    pred = a
                elif f == 3:
                    pred = (a + b) // 2
                else:
                    p = a + b - c
                    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                cur[i] = (line[i] + pred) & 255
        out[r] = cur
    return out.reshape(h, w, ch).astype(np.uint8)


def fetch(url: str, tries: int = 4) -> bytes:
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return r.read()
        except OSError as exc:
            if i == tries - 1:
                raise
            print(f"    retry {url.rsplit('/', 3)[-3:]}: {exc}")
            time.sleep(3 * (i + 1))
    raise RuntimeError("unreachable")


def tile_xy(lat: float, lon: float, z: int) -> tuple[float, float]:
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    return x, y


def pixel_latlon(px: np.ndarray, py: np.ndarray, z: int) -> tuple[np.ndarray, np.ndarray]:
    n = 256 * 2 ** z
    lon = px / n * 360.0 - 180.0
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * py / n))))
    return lat, lon


def inside(lat: np.ndarray, lon: np.ndarray, ring: list) -> np.ndarray:
    """Ray casting, vectorised over points, for one polygon ring [[lon, lat], ...]."""
    res = np.zeros(lat.shape, dtype=bool)
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        cond = (y1 > lat) != (y2 > lat)
        xint = (x2 - x1) * (lat - y1) / ((y2 - y1) or 1e-12) + x1
        res ^= cond & (lon < xint)
    return res


def main() -> int:
    ensure_schema_additions()
    with session_scope() as db:
        zones = db.execute(text("SELECT id, code, name, slope_deg, elevation_m, ST_AsGeoJSON(geom) g FROM zones ORDER BY code")).mappings().all()
        print(f"  {'zone':<6} {'slope sim→real':>16} {'elevation sim→real':>22}  pixels")
        for z in zones:
            ring = json.loads(z["g"])["coordinates"][0]
            lats, lons = [p[1] for p in ring], [p[0] for p in ring]
            x0, y0 = tile_xy(max(lats), min(lons), Z)
            x1, y1 = tile_xy(min(lats), max(lons), Z)
            tx0, ty0, tx1, ty1 = int(x0), int(y0), int(x1), int(y1)
            mosaic = np.zeros(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256), dtype=np.float64)
            for ty in range(ty0, ty1 + 1):
                for tx in range(tx0, tx1 + 1):
                    px = decode_png(fetch(URL.format(z=Z, x=tx, y=ty))).astype(np.float64)
                    elev = px[..., 0] * 256 + px[..., 1] + px[..., 2] / 256 - 32768
                    mosaic[(ty - ty0) * 256:(ty - ty0 + 1) * 256, (tx - tx0) * 256:(tx - tx0 + 1) * 256] = elev
            gy, gx = np.mgrid[0:mosaic.shape[0], 0:mosaic.shape[1]]
            lat, lon = pixel_latlon(gx + tx0 * 256 + 0.5, gy + ty0 * 256 + 0.5, Z)
            mask = inside(lat, lon, [list(p) for p in ring[:-1]] if ring[0] == ring[-1] else ring)
            res = 156543.03392 * math.cos(math.radians(float(np.mean(lats)))) / 2 ** Z      # metres per pixel
            dzdy, dzdx = np.gradient(mosaic, res)
            slope = np.degrees(np.arctan(np.hypot(dzdx, dzdy)))
            m_slope, m_elev = float(slope[mask].mean()), float(mosaic[mask].mean())
            db.execute(text("""UPDATE zones SET slope_deg = :s, elevation_m = :e,
                               terrain_source = 'REAL · SRTM/AWS terrain (z12, mean over the zone)' WHERE id = :i"""),
                       {"s": round(m_slope, 1), "e": round(m_elev), "i": z["id"]})
            print(f"  {z['code']:<6} {z['slope_deg']:>6.1f}° → {m_slope:>5.1f}° {z['elevation_m']:>9.0f} m → {m_elev:>6.0f} m  {int(mask.sum())}")
        db.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
