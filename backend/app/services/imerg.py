"""NASA GPM IMERG Final daily precipitation for one point, via GES DISC OPeNDAP.

Needs a free Earthdata login (EARTHDATA_USER / EARTHDATA_PASSWORD in .env,
never logged). One request per day, server-side subset to the single 0.1°
cell, so the response is a few hundred bytes — but the server takes ~1-2 min
per request, which is why the replay page reads a cache filled by
scripts/fetch_imerg.py rather than calling NASA live.
"""
from __future__ import annotations

import http.cookiejar
import re
import urllib.request
from datetime import date

from ..config import settings

BASE = "https://gpm1.gesdisc.eosdis.nasa.gov/opendap/GPM_L3/GPM_3IMERGDF.07"


class NotConfigured(RuntimeError):
    pass


def cell(lat: float, lon: float) -> tuple[int, int, float, float]:
    """Grid indices and centre of the 0.1° cell containing the point."""
    i_lon, i_lat = int((lon + 180.0) / 0.1), int((lat + 90.0) / 0.1)
    return i_lon, i_lat, round(-89.95 + i_lat * 0.1, 2), round(-179.95 + i_lon * 0.1, 2)


def _opener():
    if not settings.earthdata_user or not settings.earthdata_password:
        raise NotConfigured("EARTHDATA_USER / EARTHDATA_PASSWORD not set in .env")
    pm = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    pm.add_password(None, "https://urs.earthdata.nasa.gov", settings.earthdata_user, settings.earthdata_password)
    return urllib.request.build_opener(urllib.request.HTTPBasicAuthHandler(pm),
                                       urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def parse(ascii_body: str) -> float:
    """The single value out of an OPeNDAP .ascii reply for precipitation[0][x][y]."""
    rows = [line.split("], ", 1)[1] for line in ascii_body.splitlines() if line.startswith("precipitation.precipitation[")]
    if not rows:
        m = re.search(r"precipitation\[1\]\[1\]\[1\]\s*\n\[0\]\[0\],\s*([-\d.eE]+)", ascii_body)
        if not m:
            raise ValueError("no precipitation value in the reply")
        return max(0.0, float(m.group(1)))
    return max(0.0, float(rows[0].split(",")[0]))


def daily_mm(day: date, lat: float, lon: float, opener=None, timeout: int = 240) -> float:
    i_lon, i_lat, _, _ = cell(lat, lon)
    url = (f"{BASE}/{day:%Y}/{day:%m}/3B-DAY.MS.MRG.3IMERG.{day:%Y%m%d}-S000000-E235959.V07B.nc4"
           f".ascii?precipitation[0:0][{i_lon}:{i_lon}][{i_lat}:{i_lat}]")
    with (opener or _opener()).open(url, timeout=timeout) as r:
        return parse(r.read().decode())
