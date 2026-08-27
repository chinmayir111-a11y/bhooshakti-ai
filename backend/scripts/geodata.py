"""Reference geography for the BHOOSHAKTI AI demo.

Place names are real North-East India locations and the coordinates are
approximate real centroids, so the map reads correctly to anyone who knows the
region. The zone *polygons* are generated shapes around those centroids, not
surveyed administrative or geological boundaries.

    >>> NOTHING IN THIS FILE IS AN OFFICIAL DATASET. <<<

Terrain attributes (slope / aspect / elevation / lithology / land cover) are
plausible values chosen for the demo, not measured survey figures.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ZoneSpec:
    code: str
    name: str
    district: str
    state: str
    lat: float
    lon: float
    slope_deg: float
    aspect_deg: float
    elevation_m: float
    lithology: str
    land_cover: str
    population: int
    radius_deg: float = 0.040
    # baseline monsoon intensity multiplier — Sohra/Mawsynram are the wettest
    # places on earth, Tawang is a rain shadow. Drives the rainfall generator.
    rain_factor: float = 1.0


LITHOLOGY_CLASSES = [
    "phyllite_schist",
    "gneiss",
    "sandstone_shale",
    "quartzite",
    "limestone",
    "granite",
    "alluvium_terrace",
]

LAND_COVER_CLASSES = [
    "dense_forest",
    "open_forest",
    "tea_plantation",
    "terrace_agriculture",
    "built_up",
    "scrub_grassland",
    "barren_rock",
]

# Relative slope-failure propensity per lithology class, used only to shape the
# synthetic historical event distribution (weak, weathered rock fails more).
LITHOLOGY_WEAKNESS = {
    "phyllite_schist": 1.00,
    "sandstone_shale": 0.92,
    "quartzite": 0.55,
    "gneiss": 0.60,
    "limestone": 0.50,
    "granite": 0.35,
    "alluvium_terrace": 0.70,
}

LAND_COVER_WEAKNESS = {
    "barren_rock": 0.95,
    "built_up": 0.90,
    "scrub_grassland": 0.80,
    "terrace_agriculture": 0.70,
    "tea_plantation": 0.60,
    "open_forest": 0.50,
    "dense_forest": 0.30,
}


ZONES: list[ZoneSpec] = [
    # ---- Sikkim ----------------------------------------------------------
    ZoneSpec("SK-01", "Gangtok–Ranipool Corridor", "Gangtok", "Sikkim",
             27.3314, 88.6138, 34.0, 155.0, 1650, "phyllite_schist", "built_up", 42000, 0.038, 1.15),
    ZoneSpec("SK-02", "Singtam–Rangpo Belt", "Pakyong", "Sikkim",
             27.2350, 88.5010, 31.0, 190.0, 380, "phyllite_schist", "open_forest", 18500, 0.042, 1.10),
    ZoneSpec("SK-03", "Namchi Ridge", "Namchi", "Sikkim",
             27.1670, 88.3630, 29.0, 210.0, 1320, "gneiss", "terrace_agriculture", 15200, 0.040, 1.05),
    ZoneSpec("SK-04", "Mangan Slopes", "Mangan", "Sikkim",
             27.5090, 88.5290, 38.0, 130.0, 1950, "gneiss", "dense_forest", 8100, 0.045, 1.12),
    ZoneSpec("SK-05", "Pelling–Geyzing Scarp", "Gyalshing", "Sikkim",
             27.2180, 88.2410, 36.0, 245.0, 2050, "quartzite", "dense_forest", 9400, 0.042, 1.08),
    ZoneSpec("SK-06", "Chungthang Valley", "Mangan", "Sikkim",
             27.6020, 88.6420, 41.0, 115.0, 1790, "gneiss", "scrub_grassland", 5300, 0.048, 1.18),

    # ---- Darjeeling corridor (West Bengal) -------------------------------
    ZoneSpec("DJ-01", "Darjeeling Town Slopes", "Darjeeling", "West Bengal",
             27.0410, 88.2663, 33.0, 175.0, 2045, "phyllite_schist", "built_up", 118800, 0.036, 1.20),
    ZoneSpec("DJ-02", "Kurseong Ridge", "Darjeeling", "West Bengal",
             26.8800, 88.2770, 30.0, 200.0, 1458, "phyllite_schist", "tea_plantation", 42000, 0.038, 1.22),
    ZoneSpec("DJ-03", "Kalimpong Escarpment", "Kalimpong", "West Bengal",
             27.0600, 88.4700, 32.0, 150.0, 1247, "sandstone_shale", "terrace_agriculture", 49400, 0.040, 1.10),
    ZoneSpec("DJ-04", "Tindharia–Paglajhora", "Darjeeling", "West Bengal",
             26.9530, 88.3210, 39.0, 165.0, 860, "sandstone_shale", "open_forest", 6800, 0.032, 1.25),
    ZoneSpec("DJ-05", "Mirik Basin", "Darjeeling", "West Bengal",
             26.8860, 88.1870, 27.0, 225.0, 1495, "phyllite_schist", "tea_plantation", 11500, 0.036, 1.15),

    # ---- Meghalaya -------------------------------------------------------
    ZoneSpec("ML-01", "Sohra (Cherrapunji) Plateau Edge", "East Khasi Hills", "Meghalaya",
             25.2700, 91.7320, 35.0, 180.0, 1430, "sandstone_shale", "scrub_grassland", 14800, 0.044, 1.60),
    ZoneSpec("ML-02", "Shillong Peak Slopes", "East Khasi Hills", "Meghalaya",
             25.5570, 91.8830, 26.0, 160.0, 1961, "granite", "built_up", 143000, 0.042, 1.20),
    ZoneSpec("ML-03", "Mawsynram Belt", "East Khasi Hills", "Meghalaya",
             25.2980, 91.5820, 33.0, 195.0, 1400, "limestone", "dense_forest", 8600, 0.042, 1.65),
    ZoneSpec("ML-04", "Tura Range", "West Garo Hills", "Meghalaya",
             25.5140, 90.2030, 28.0, 205.0, 872, "gneiss", "dense_forest", 74800, 0.046, 1.25),

    # ---- Mizoram ---------------------------------------------------------
    ZoneSpec("MZ-01", "Aizawl Ridge", "Aizawl", "Mizoram",
             23.7271, 92.7176, 37.0, 250.0, 1132, "sandstone_shale", "built_up", 293400, 0.040, 1.15),
    ZoneSpec("MZ-02", "Lunglei Slopes", "Lunglei", "Mizoram",
             22.8800, 92.7330, 34.0, 265.0, 868, "sandstone_shale", "open_forest", 57000, 0.044, 1.10),
    ZoneSpec("MZ-03", "Serchhip Corridor", "Serchhip", "Mizoram",
             23.3020, 92.8510, 31.0, 230.0, 890, "sandstone_shale", "terrace_agriculture", 23000, 0.042, 1.08),
    ZoneSpec("MZ-04", "Champhai Escarpment", "Champhai", "Mizoram",
             23.4560, 93.3290, 35.0, 95.0, 1310, "sandstone_shale", "dense_forest", 19000, 0.044, 1.05),

    # ---- Assam hill roads ------------------------------------------------
    ZoneSpec("AS-01", "Haflong Hills", "Dima Hasao", "Assam",
             25.1650, 93.0170, 32.0, 170.0, 680, "sandstone_shale", "open_forest", 45300, 0.044, 1.30),
    ZoneSpec("AS-02", "Umrangso–Lumding Rail Belt", "Dima Hasao", "Assam",
             25.4600, 92.6600, 29.0, 145.0, 620, "sandstone_shale", "dense_forest", 12700, 0.050, 1.28),
    ZoneSpec("AS-03", "Diphu Slopes", "Karbi Anglong", "Assam",
             25.8400, 93.4300, 22.0, 190.0, 186, "gneiss", "terrace_agriculture", 62000, 0.048, 1.12),

    # ---- Arunachal Pradesh ----------------------------------------------
    ZoneSpec("AR-01", "Itanagar Foothills", "Papum Pare", "Arunachal Pradesh",
             27.0844, 93.6053, 25.0, 185.0, 440, "sandstone_shale", "open_forest", 59500, 0.046, 1.18),
    ZoneSpec("AR-02", "Tawang Pass Corridor", "Tawang", "Arunachal Pradesh",
             27.5860, 91.8590, 40.0, 120.0, 3048, "gneiss", "barren_rock", 11200, 0.050, 0.65),
    ZoneSpec("AR-03", "Dibang Valley Slopes", "Lower Dibang Valley", "Arunachal Pradesh",
             28.1300, 95.8500, 36.0, 155.0, 620, "quartzite", "dense_forest", 7300, 0.052, 1.35),
]

assert len({z.code for z in ZONES}) == len(ZONES), "duplicate zone code"

# The three zones the scripted monsoon demo escalates (Sikkim/Darjeeling corridor).
DEMO_ZONE_CODES = ["SK-02", "DJ-04", "DJ-01"]
DEMO_CRITICAL_CODE = "DJ-04"  # Tindharia–Paglajhora goes CRITICAL


# ---------------------------------------------------------------------------
# Roads (LineStrings). Vertices are routed through zone centroids so PostGIS
# ST_Intersects against the zone polygons genuinely returns them.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoadSpec:
    name: str
    road_class: str
    criticality: str
    coords: list[tuple[float, float]]  # (lon, lat)


ROADS: list[RoadSpec] = [
    RoadSpec("NH-10 Sevoke–Rangpo–Singtam–Gangtok", "NH", "lifeline", [
        (88.4700, 26.9000), (88.4290, 27.0300), (88.4740, 27.1550),
        (88.5010, 27.2350), (88.5560, 27.2880), (88.6138, 27.3314),
    ]),
    RoadSpec("NH-310 Gangtok–Nathu La", "NH", "strategic", [
        (88.6138, 27.3314), (88.6800, 27.3600), (88.7600, 27.3800), (88.8400, 27.3900),
    ]),
    RoadSpec("SH-12 Jorethang–Namchi–Damthang", "SH", "district", [
        (88.3230, 27.1050), (88.3630, 27.1670), (88.4000, 27.2000),
    ]),
    RoadSpec("NH-510 Singtam–Mangan–Chungthang", "NH", "lifeline", [
        (88.5010, 27.2350), (88.5290, 27.3800), (88.5290, 27.5090),
        (88.5900, 27.5600), (88.6420, 27.6020),
    ]),
    RoadSpec("SH-05 Geyzing–Pelling–Yuksom", "SH", "district", [
        (88.2600, 27.1800), (88.2410, 27.2180), (88.2200, 27.2600),
    ]),
    RoadSpec("NH-110 Siliguri–Kurseong–Darjeeling (Hill Cart Road)", "NH", "lifeline", [
        (88.4200, 26.7100), (88.3210, 26.9530), (88.2770, 26.8800),
        (88.2600, 26.9600), (88.2663, 27.0410),
    ]),
    RoadSpec("NH-717A Bagrakote–Algarah–Kalimpong", "NH", "lifeline", [
        (88.6100, 26.8600), (88.5400, 26.9800), (88.4700, 27.0600),
    ]),
    RoadSpec("SH-16 Mirik–Sukhiapokhri", "SH", "district", [
        (88.1870, 26.8860), (88.2100, 26.9500), (88.2400, 27.0000),
    ]),
    RoadSpec("NH-206 Shillong–Sohra (Cherrapunji)", "NH", "lifeline", [
        (91.8830, 25.5570), (91.8200, 25.4200), (91.7320, 25.2700),
    ]),
    RoadSpec("SH-11 Shillong–Mawsynram", "SH", "district", [
        (91.8830, 25.5570), (91.7100, 25.4200), (91.5820, 25.2980),
    ]),
    RoadSpec("NH-6 Shillong–Jowai–Haflong–Silchar", "NH", "lifeline", [
        (91.8830, 25.5570), (92.2000, 25.4480), (92.6600, 25.4600),
        (93.0170, 25.1650), (92.7800, 24.8300),
    ]),
    RoadSpec("NH-217 Tura–Williamnagar", "NH", "district", [
        (90.2030, 25.5140), (90.4500, 25.5000), (90.6200, 25.5100),
    ]),
    RoadSpec("NH-306 Aizawl–Serchhip–Lunglei", "NH", "lifeline", [
        (92.7176, 23.7271), (92.8510, 23.3020), (92.7330, 22.8800),
    ]),
    RoadSpec("NH-102B Aizawl–Champhai", "NH", "strategic", [
        (92.7176, 23.7271), (93.0500, 23.6000), (93.3290, 23.4560),
    ]),
    RoadSpec("NH-27 Diphu–Lumding Link", "NH", "lifeline", [
        (93.4300, 25.8400), (93.1700, 25.7500), (92.6600, 25.4600),
    ]),
    RoadSpec("NH-415 Banderdewa–Itanagar–Ziro", "NH", "lifeline", [
        (93.7400, 27.0300), (93.6053, 27.0844), (93.8300, 27.5400),
    ]),
    RoadSpec("NH-13 Bomdila–Tawang (Trans-Arunachal)", "NH", "strategic", [
        (92.4000, 27.2600), (92.0500, 27.4500), (91.8590, 27.5860),
    ]),
    RoadSpec("NH-313 Roing–Anini (Dibang Valley)", "NH", "district", [
        (95.8500, 28.1300), (95.8900, 28.4000), (95.9100, 28.6000),
    ]),
]


# ---------------------------------------------------------------------------
# Villages (Points) and bridges
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VillageSpec:
    name: str
    district: str
    state: str
    lat: float
    lon: float
    population: int


VILLAGES: list[VillageSpec] = [
    VillageSpec("Ranipool", "Gangtok", "Sikkim", 27.2790, 88.5930, 6200),
    VillageSpec("Tadong", "Gangtok", "Sikkim", 27.3160, 88.6080, 4800),
    VillageSpec("Singtam", "Pakyong", "Sikkim", 27.2340, 88.5010, 5900),
    VillageSpec("Rangpo", "Pakyong", "Sikkim", 27.1760, 88.5310, 4300),
    VillageSpec("Dikchu", "Mangan", "Sikkim", 27.4100, 88.5000, 1900),
    VillageSpec("Mangan Bazar", "Mangan", "Sikkim", 27.5090, 88.5290, 2400),
    VillageSpec("Chungthang", "Mangan", "Sikkim", 27.6020, 88.6420, 1600),
    VillageSpec("Damthang", "Namchi", "Sikkim", 27.1900, 88.3800, 1400),
    VillageSpec("Pelling", "Gyalshing", "Sikkim", 27.2180, 88.2410, 2300),
    VillageSpec("Tindharia", "Darjeeling", "West Bengal", 26.9530, 88.3210, 3100),
    VillageSpec("Paglajhora", "Darjeeling", "West Bengal", 26.9700, 88.3050, 900),
    VillageSpec("Sukhiapokhri", "Darjeeling", "West Bengal", 27.0100, 88.1900, 2700),
    VillageSpec("Ghum", "Darjeeling", "West Bengal", 27.0060, 88.2470, 5400),
    VillageSpec("Lebong", "Darjeeling", "West Bengal", 27.0700, 88.2700, 3300),
    VillageSpec("Sonada", "Darjeeling", "West Bengal", 26.9400, 88.2600, 4100),
    VillageSpec("Algarah", "Kalimpong", "West Bengal", 27.1100, 88.5400, 2200),
    VillageSpec("Lava", "Kalimpong", "West Bengal", 27.0900, 88.6600, 1100),
    VillageSpec("Mirik Bazar", "Darjeeling", "West Bengal", 26.8860, 88.1870, 4600),
    VillageSpec("Sohra Bazar", "East Khasi Hills", "Meghalaya", 25.2700, 91.7320, 3900),
    VillageSpec("Laitkynsew", "East Khasi Hills", "Meghalaya", 25.2200, 91.7000, 1200),
    VillageSpec("Mawsynram", "East Khasi Hills", "Meghalaya", 25.2980, 91.5820, 2100),
    VillageSpec("Mawphlang", "East Khasi Hills", "Meghalaya", 25.4500, 91.7500, 1800),
    VillageSpec("Tura Bazar", "West Garo Hills", "Meghalaya", 25.5140, 90.2030, 8700),
    VillageSpec("Durtlang", "Aizawl", "Mizoram", 23.7700, 92.7200, 7200),
    VillageSpec("Sairang", "Aizawl", "Mizoram", 23.7500, 92.6600, 3400),
    VillageSpec("Serchhip Town", "Serchhip", "Mizoram", 23.3020, 92.8510, 5100),
    VillageSpec("Thenzawl", "Serchhip", "Mizoram", 23.3200, 92.7600, 2900),
    VillageSpec("Champhai Town", "Champhai", "Mizoram", 23.4560, 93.3290, 6800),
    VillageSpec("Haflong Bazar", "Dima Hasao", "Assam", 25.1650, 93.0170, 5600),
    VillageSpec("Umrangso", "Dima Hasao", "Assam", 25.4600, 92.6600, 3800),
    VillageSpec("Mahur", "Dima Hasao", "Assam", 25.2100, 93.1100, 2100),
    VillageSpec("Diphu Town", "Karbi Anglong", "Assam", 25.8400, 93.4300, 9400),
    VillageSpec("Naharlagun", "Papum Pare", "Arunachal Pradesh", 27.1050, 93.6900, 8300),
    VillageSpec("Nirjuli", "Papum Pare", "Arunachal Pradesh", 27.1300, 93.7300, 4200),
    VillageSpec("Jang", "Tawang", "Arunachal Pradesh", 27.5300, 91.9500, 1500),
    VillageSpec("Roing", "Lower Dibang Valley", "Arunachal Pradesh", 28.1300, 95.8500, 5200),
]


@dataclass(frozen=True)
class BridgeSpec:
    name: str
    lat: float
    lon: float
    span_m: float
    road_name: str


BRIDGES: list[BridgeSpec] = [
    BridgeSpec("Teesta Bridge (Singtam)", 27.2320, 88.4980, 140.0, "NH-10 Sevoke–Rangpo–Singtam–Gangtok"),
    BridgeSpec("Rangpo Bailey Bridge", 27.1750, 88.5300, 90.0, "NH-10 Sevoke–Rangpo–Singtam–Gangtok"),
    BridgeSpec("Dikchu Bridge", 27.4090, 88.5010, 75.0, "NH-510 Singtam–Mangan–Chungthang"),
    BridgeSpec("Chungthang Teesta Crossing", 27.6010, 88.6410, 110.0, "NH-510 Singtam–Mangan–Chungthang"),
    BridgeSpec("Paglajhora Culvert Span", 26.9690, 88.3060, 35.0, "NH-110 Siliguri–Kurseong–Darjeeling (Hill Cart Road)"),
    BridgeSpec("Relli River Bridge", 27.0400, 88.5100, 60.0, "NH-717A Bagrakote–Algarah–Kalimpong"),
    BridgeSpec("Umiam Approach Bridge", 25.6600, 91.8900, 120.0, "NH-6 Shillong–Jowai–Haflong–Silchar"),
    BridgeSpec("Kopili Bridge (Umrangso)", 25.4580, 92.6620, 95.0, "NH-27 Diphu–Lumding Link"),
    BridgeSpec("Jatinga Rail Overbridge", 25.1400, 92.9900, 55.0, "NH-6 Shillong–Jowai–Haflong–Silchar"),
    BridgeSpec("Tuirial Bridge", 23.7000, 92.8300, 80.0, "NH-102B Aizawl–Champhai"),
    BridgeSpec("Tlawng Bridge (Sairang)", 23.7480, 92.6580, 70.0, "NH-306 Aizawl–Serchhip–Lunglei"),
    BridgeSpec("Pare River Bridge", 27.1000, 93.6600, 85.0, "NH-415 Banderdewa–Itanagar–Ziro"),
]


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def jittered_polygon(
    lat: float,
    lon: float,
    radius_deg: float,
    rng: random.Random,
    vertices: int = 11,
) -> list[tuple[float, float]]:
    """An irregular closed ring around (lat, lon), returned as (lon, lat) pairs.

    Longitude spacing is widened by 1/cos(lat) so the shape looks roughly
    circular on a web-Mercator map instead of squashed.
    """
    lon_scale = 1.0 / max(math.cos(math.radians(lat)), 0.3)
    ring: list[tuple[float, float]] = []
    for i in range(vertices):
        theta = 2.0 * math.pi * i / vertices
        r = radius_deg * rng.uniform(0.78, 1.22)
        ring.append((
            round(lon + r * math.cos(theta) * lon_scale, 6),
            round(lat + r * math.sin(theta), 6),
        ))
    ring.append(ring[0])
    return ring


def ring_to_wkt(ring: list[tuple[float, float]]) -> str:
    body = ", ".join(f"{lon} {lat}" for lon, lat in ring)
    return f"POLYGON(({body}))"


def line_to_wkt(coords: list[tuple[float, float]]) -> str:
    body = ", ".join(f"{lon} {lat}" for lon, lat in coords)
    return f"LINESTRING({body})"


def point_to_wkt(lat: float, lon: float) -> str:
    return f"POINT({lon} {lat})"


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def polyline_length_km(coords: list[tuple[float, float]]) -> float:
    total = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(coords, coords[1:]):
        total += haversine_km(lat1, lon1, lat2, lon2)
    return round(total, 2)


ZONE_BY_CODE = {z.code: z for z in ZONES}
