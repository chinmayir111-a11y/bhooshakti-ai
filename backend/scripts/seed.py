#!/usr/bin/env python3
"""Seed the BHOOSHAKTI AI demo database.

    python scripts/seed.py [--reset]

Everything written here is SIMULATED DATA generated from a fixed random seed.
Place names and approximate coordinates are real; measurements, events,
sensor readings and populations are synthetic.

Generates:
  * 25 zones across NER as PostGIS polygons
  * 30 days of hourly rainfall per zone, with a configurable monsoon spike
  * 30 days of hourly soil moisture, lag-correlated with rainfall
  * ~120 labelled historical landslide events with features at occurrence
  * road segments (LineStrings), villages (Points), bridges (Points)
  * ~40 sensor nodes, a few deliberately FAILED to exercise fallback logic
  * 3 demo logins (authority / field officer / citizen)
"""
from __future__ import annotations

import argparse
import math
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import Base, engine, session_scope  # noqa: E402
from app.models import (  # noqa: E402
    Bridge,
    HistoricalLandslide,
    RainfallReading,
    RoadSegment,
    RoadStatus,
    Role,
    SensorNode,
    SensorStatus,
    SoilMoistureReading,
    User,
    Village,
    Zone,
    ZoneAssignment,
)
from app.security import hash_password  # noqa: E402
from scripts.geodata import (  # noqa: E402
    BRIDGES,
    LAND_COVER_WEAKNESS,
    LITHOLOGY_WEAKNESS,
    ROADS,
    VILLAGES,
    ZONES,
    ZoneSpec,
    jittered_polygon,
    line_to_wkt,
    point_to_wkt,
    polyline_length_km,
    ring_to_wkt,
)

HOURS = 24 * 30           # 30 days of hourly history
MONSOON_SPIKE_DAYS_AGO = 6   # centre of the built-in heavy spell
HISTORICAL_EVENTS = 120
SENSOR_NODES = 40


# ---------------------------------------------------------------------------
# Weather generation
# ---------------------------------------------------------------------------


def susceptibility_index(z: ZoneSpec) -> float:
    """0-1 static propensity, used to weight where historical events land."""
    slope_term = min(max((z.slope_deg - 15.0) / 30.0, 0.0), 1.0)
    litho = LITHOLOGY_WEAKNESS.get(z.lithology, 0.6)
    cover = LAND_COVER_WEAKNESS.get(z.land_cover, 0.6)
    elev_term = min(z.elevation_m / 3000.0, 1.0) * 0.3
    return min(0.15 + 0.45 * slope_term + 0.25 * litho + 0.20 * cover + elev_term, 1.0)


def generate_rainfall(
    z: ZoneSpec,
    rng: random.Random,
    start: datetime,
    hours: int,
    monsoon_spike: bool,
) -> list[float]:
    """Hourly rainfall (mm) as a sum of synoptic wet spells + diurnal noise."""
    series = [0.0] * hours

    # Background drizzle with a mild afternoon/evening diurnal peak.
    for h in range(hours):
        hour_of_day = (start + timedelta(hours=h)).hour
        diurnal = 0.6 + 0.5 * math.sin((hour_of_day - 9) / 24.0 * 2 * math.pi)
        if rng.random() < 0.28:
            series[h] += max(0.0, rng.gauss(0.8, 0.7)) * diurnal * z.rain_factor

    # A handful of multi-hour wet spells over the month.
    n_spells = rng.randint(4, 8)
    for _ in range(n_spells):
        onset = rng.randint(0, max(hours - 8, 1))
        duration = rng.randint(5, 30)
        peak = rng.uniform(3.0, 11.0) * z.rain_factor
        for i in range(duration):
            h = onset + i
            if h >= hours:
                break
            # smooth rise-and-fall envelope
            shape = math.sin(math.pi * (i + 0.5) / duration) ** 1.4
            series[h] += peak * shape * rng.uniform(0.6, 1.35)

    # The configurable monsoon spike — a sustained ~48h event.
    if monsoon_spike:
        centre = hours - MONSOON_SPIKE_DAYS_AGO * 24
        duration = rng.randint(38, 56)
        onset = max(0, centre - duration // 2)
        peak = rng.uniform(13.0, 22.0) * z.rain_factor
        for i in range(duration):
            h = onset + i
            if h >= hours:
                break
            shape = math.sin(math.pi * (i + 0.5) / duration) ** 1.1
            series[h] += peak * shape * rng.uniform(0.7, 1.3)

    return [round(v, 2) for v in series]


def generate_soil_moisture(
    z: ZoneSpec,
    rainfall: list[float],
    rng: random.Random,
) -> list[float]:
    """Lagged, saturating response to rainfall with steady drainage.

    Drainage is faster on steep slopes and slower under dense forest litter,
    so wet zones with gentle slopes stay saturated longer.
    """
    lag = 3 if z.slope_deg > 33 else 5           # hours
    infiltration = 1.35 if z.land_cover in ("dense_forest", "open_forest") else 1.05
    drainage = 0.42 + 0.011 * z.slope_deg        # %/hour
    capacity = 96.0

    sm = [0.0] * len(rainfall)
    level = rng.uniform(34.0, 46.0)
    for h in range(len(rainfall)):
        recharge = rainfall[h - lag] * infiltration if h >= lag else 0.0
        headroom = max(0.0, (capacity - level) / capacity)
        level += recharge * (0.35 + 0.65 * headroom)
        level -= drainage * (level / capacity) ** 1.3
        level += rng.gauss(0.0, 0.25)
        level = min(max(level, 8.0), capacity)
        sm[h] = round(level, 2)
    return sm


# ---------------------------------------------------------------------------
# Seeding steps
# ---------------------------------------------------------------------------


def reset_schema() -> None:
    print("  dropping and recreating schema ...")
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    Base.metadata.drop_all(bind=engine)
    with engine.begin() as conn:
        for enum_name in (
            "role_enum", "severity_enum", "alert_severity_enum", "sensor_status_enum",
            "road_status_enum", "bridge_status_enum", "report_status_enum",
            "verdict_enum", "delivery_status_enum",
        ):
            conn.execute(text(f"DROP TYPE IF EXISTS {enum_name}"))
    Base.metadata.create_all(bind=engine)


def ensure_schema() -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    Base.metadata.create_all(bind=engine)


def seed_zones(db, rng: random.Random) -> dict[str, Zone]:
    zones: dict[str, Zone] = {}
    for spec in ZONES:
        ring = jittered_polygon(spec.lat, spec.lon, spec.radius_deg, rng)
        z = Zone(
            code=spec.code,
            name=spec.name,
            district=spec.district,
            state=spec.state,
            geom=f"SRID=4326;{ring_to_wkt(ring)}",
            centroid_lat=spec.lat,
            centroid_lon=spec.lon,
            slope_deg=spec.slope_deg,
            aspect_deg=spec.aspect_deg,
            elevation_m=spec.elevation_m,
            lithology=spec.lithology,
            land_cover=spec.land_cover,
            population=spec.population,
        )
        db.add(z)
        zones[spec.code] = z
    db.flush()

    # Let PostGIS compute the areas rather than approximating in Python.
    db.execute(text(
        "UPDATE zones SET area_km2 = ROUND((ST_Area(geom::geography) / 1e6)::numeric, 2)"
    ))
    return zones


def seed_weather_real(db, zones: dict[str, Zone]) -> dict[str, dict] | None:
    """Fetch real precipitation and soil moisture from Open-Meteo.

    Returns the per-zone series (so the historical-event generator can work
    from real climatology), or None if the network is unavailable so the
    caller can fall back to the synthetic generator.
    """
    from app.services import openmeteo

    points = [
        openmeteo.ZonePoint(z.id, code, z.centroid_lat, z.centroid_lon)
        for code, z in zones.items()
    ]
    result = openmeteo.refresh(db, zones=points)
    if not result["ok"]:
        print(f"  Open-Meteo unavailable ({'; '.join(result['errors'])})")
        return None

    print(f"  fetched {result['rows']:,} hourly rows "
          f"({result['archive_rows']:,} ERA5 archive + {result['forecast_rows']:,} forecast)")

    # Read the observed series back out, so downstream generation sees exactly
    # what the risk engine will see.
    now = datetime.now(timezone.utc)
    series: dict[str, dict] = {}
    thin = 0
    for code, z in zones.items():
        rain = [float(r[0]) for r in db.execute(text("""
            SELECT rainfall_mm FROM rainfall_readings
            WHERE zone_id = :z AND NOT is_forecast AND ts <= :now ORDER BY ts
        """), {"z": z.id, "now": now})]
        soil = [float(r[0]) for r in db.execute(text("""
            SELECT moisture_pct FROM soil_moisture_readings
            WHERE zone_id = :z AND NOT is_forecast AND ts <= :now ORDER BY ts
        """), {"z": z.id, "now": now})]
        if len(rain) < 24 * 20:
            thin += 1
        series[code] = {"rain": rain, "soil": soil, "start": None}

    if thin:
        print(f"  {thin} zone(s) returned a short series — check coverage")
    total_mm = sum(sum(v["rain"]) for v in series.values())
    print(f"  observed rainfall across all zones: {total_mm:,.0f} mm over the window")
    return series


def seed_weather(db, zones: dict[str, Zone], rng: random.Random, monsoon_spike: bool) -> dict[str, dict]:
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = now - timedelta(hours=HOURS - 1)
    series: dict[str, dict] = {}

    rain_rows: list[dict] = []
    soil_rows: list[dict] = []

    for spec in ZONES:
        z = zones[spec.code]
        rain = generate_rainfall(spec, rng, start, HOURS, monsoon_spike)
        soil = generate_soil_moisture(spec, rain, rng)
        series[spec.code] = {"rain": rain, "soil": soil, "start": start}

        for h in range(HOURS):
            ts = start + timedelta(hours=h)
            rain_rows.append({"zone_id": z.id, "ts": ts, "rainfall_mm": rain[h], "source": "simulated"})
            soil_rows.append({"zone_id": z.id, "ts": ts, "moisture_pct": soil[h], "source": "simulated"})

    db.bulk_insert_mappings(RainfallReading, rain_rows)
    db.bulk_insert_mappings(SoilMoistureReading, soil_rows)
    print(f"  rainfall rows: {len(rain_rows):,}   soil-moisture rows: {len(soil_rows):,}")
    return series


def _rolling_totals(series: list[float], window: int) -> list[float]:
    if len(series) < window:
        return [sum(series)] if series else [0.0]
    cumulative = [0.0]
    for v in series:
        cumulative.append(cumulative[-1] + v)
    return [cumulative[i + window] - cumulative[i] for i in range(len(series) - window + 1)]


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return ordered[idx]


def seed_historical(db, zones: dict[str, Zone], rng: random.Random,
                    series: dict[str, dict]) -> int:
    """~120 labelled events, distributed by static susceptibility and monsoon month.

    Rainfall features for each event are drawn from the UPPER TAIL OF THAT
    ZONE'S OWN generated series, not from an independent distribution. This
    matters: the negative class is sampled from the same series, so if positives
    came from a different scale the model would learn the gap between the two
    generators instead of the relationship between rain and slope failure.
    (An earlier version drew antecedent rainfall from a fixed distribution that
    topped out well below what the series actually reaches, and the model duly
    concluded that the wettest conditions were the safest.)
    """
    weights = [susceptibility_index(s) ** 1.6 for s in ZONES]
    picks = rng.choices(ZONES, weights=weights, k=HISTORICAL_EVENTS)

    month_weights = [1, 1, 3, 6, 14, 22, 26, 21, 14, 6, 2, 1]  # Jan..Dec
    triggers = ["rainfall", "rainfall", "rainfall", "cloudburst", "toe_erosion", "road_cutting", "seismic"]

    # Per-zone climatology derived from the series seeded in the previous step.
    climatology: dict[str, dict[str, float]] = {}
    for spec in ZONES:
        rain = series[spec.code]["rain"]
        climatology[spec.code] = {
            "p50_24": _percentile(_rolling_totals(rain, 24), 0.50),
            "p90_24": _percentile(_rolling_totals(rain, 24), 0.90),
            "p99_24": _percentile(_rolling_totals(rain, 24), 0.99),
            "p90_72": _percentile(_rolling_totals(rain, 72), 0.90),
            "p99_72": _percentile(_rolling_totals(rain, 72), 0.99),
            "p50_15d": _percentile(_rolling_totals(rain, 24 * 15), 0.50),
            "p90_15d": _percentile(_rolling_totals(rain, 24 * 15), 0.90),
        }

    rows: list[HistoricalLandslide] = []
    for spec in picks:
        z = zones[spec.code]
        clim = climatology[spec.code]
        year = rng.randint(2018, 2025)
        month = rng.choices(range(1, 13), weights=month_weights, k=1)[0]
        day = rng.randint(1, 28)
        occurred = datetime(year, month, day, rng.randint(0, 23), tzinfo=timezone.utc)

        trigger = rng.choice(triggers)

        if trigger in ("rainfall", "cloudburst"):
            # Rain-triggered: the tail of this zone's own rainfall distribution.
            severity_draw = rng.random()
            rf_24 = rng.uniform(clim["p90_24"],
                                clim["p99_24"] * (1.45 if severity_draw > 0.7 else 1.05))
            rf_24 = max(rf_24, clim["p50_24"] + 15.0)
            soil = min(97.0, max(48.0, rng.gauss(85.0, 7.0)))
        else:
            # Toe erosion, road cutting and seismic shaking bring slopes down in
            # ordinary weather. Without these the two classes separate perfectly
            # on rainfall alone, the model collapses into a step function, and
            # the intermediate risk bands become unreachable — which is both
            # unrealistic and useless as decision support.
            rf_24 = rng.uniform(clim["p50_24"], clim["p90_24"] * 1.05)
            soil = min(97.0, max(38.0, rng.gauss(72.0, 11.0)))

        rf_72 = max(rf_24 * rng.uniform(1.15, 1.9), clim["p90_72"] * 0.55)
        # The slope was already wet going in — upper half of the antecedent range.
        antecedent = max(rf_72, rng.uniform(clim["p50_15d"] * 0.8, clim["p90_15d"] * 1.25))

        # Point of failure sits inside the zone, offset from the centroid.
        bearing = rng.uniform(0, 2 * math.pi)
        dist = spec.radius_deg * rng.uniform(0.1, 0.8)
        lat = spec.lat + dist * math.sin(bearing)
        lon = spec.lon + dist * math.cos(bearing) / max(math.cos(math.radians(spec.lat)), 0.3)

        fatal_roll = rng.random()
        fatalities = 0 if fatal_roll < 0.72 else (rng.randint(1, 4) if fatal_roll < 0.94 else rng.randint(5, 23))

        rows.append(HistoricalLandslide(
            zone_id=z.id,
            geom=f"SRID=4326;{point_to_wkt(lat, lon)}",
            occurred_at=occurred,
            rainfall_24h=round(rf_24, 1),
            rainfall_72h=round(rf_72, 1),
            antecedent_rain_15d=round(antecedent, 1),
            soil_moisture_pct=round(soil, 1),
            slope_deg=round(spec.slope_deg + rng.gauss(0, 2.5), 1),
            aspect_deg=round((spec.aspect_deg + rng.gauss(0, 18)) % 360, 1),
            elevation_m=round(spec.elevation_m + rng.gauss(0, 120), 0),
            lithology=spec.lithology,
            land_cover=spec.land_cover,
            label=1,
            fatalities=fatalities,
            trigger=trigger,
            notes=f"Simulated slope failure recorded in {spec.name}.",
        ))
    db.add_all(rows)
    return len(rows)


def seed_infrastructure(db, rng: random.Random) -> tuple[int, int, int]:
    for spec in ROADS:
        db.add(RoadSegment(
            name=spec.name,
            road_class=spec.road_class,
            geom=f"SRID=4326;{line_to_wkt(spec.coords)}",
            status=RoadStatus.OPEN,
            length_km=polyline_length_km(spec.coords),
            criticality=spec.criticality,
        ))
    for spec in VILLAGES:
        db.add(Village(
            name=spec.name,
            district=spec.district,
            state=spec.state,
            geom=f"SRID=4326;{point_to_wkt(spec.lat, spec.lon)}",
            population=spec.population,
            households=max(1, int(spec.population / rng.uniform(4.2, 5.4))),
        ))
    for spec in BRIDGES:
        db.add(Bridge(
            name=spec.name,
            geom=f"SRID=4326;{point_to_wkt(spec.lat, spec.lon)}",
            span_m=spec.span_m,
            status=RoadStatus.OPEN,
            road_name=spec.road_name,
        ))
    return len(ROADS), len(VILLAGES), len(BRIDGES)


def seed_sensors(db, zones: dict[str, Zone], rng: random.Random) -> tuple[int, int]:
    """~40 nodes spread over the zones; a few FAILED to exercise fallback logic."""
    # Every zone gets one node, then the remainder go to the busiest zones.
    allocation: list[ZoneSpec] = list(ZONES)
    extra_pool = sorted(ZONES, key=lambda s: -(s.population * s.rain_factor))
    i = 0
    while len(allocation) < SENSOR_NODES:
        allocation.append(extra_pool[i % len(extra_pool)])
        i += 1

    failed_targets = {"SK-04", "MZ-02", "AR-02"}   # deliberately offline
    counters: dict[str, int] = {}
    failed = 0

    for spec in allocation:
        counters[spec.code] = counters.get(spec.code, 0) + 1
        node_id = f"{spec.code}-N{counters[spec.code]:02d}"
        z = zones[spec.code]

        bearing = rng.uniform(0, 2 * math.pi)
        dist = spec.radius_deg * rng.uniform(0.15, 0.75)
        lat = spec.lat + dist * math.sin(bearing)
        lon = spec.lon + dist * math.cos(bearing) / max(math.cos(math.radians(spec.lat)), 0.3)

        is_failed = spec.code in failed_targets and counters[spec.code] == 1
        status = SensorStatus.FAILED if is_failed else (
            SensorStatus.MAINTENANCE if rng.random() < 0.05 else SensorStatus.ACTIVE
        )
        if status is SensorStatus.FAILED:
            failed += 1

        now = datetime.now(timezone.utc)
        db.add(SensorNode(
            node_id=node_id,
            zone_id=z.id,
            geom=f"SRID=4326;{point_to_wkt(lat, lon)}",
            status=status,
            sensor_types=["rainfall", "soil_moisture", "tilt"],
            battery_pct=round(rng.uniform(12, 40) if status is SensorStatus.FAILED else rng.uniform(58, 100), 1),
            installed_at=now - timedelta(days=rng.randint(120, 900)),
            last_seen=None if status is SensorStatus.FAILED else now - timedelta(minutes=rng.randint(1, 45)),
            note="No telemetry since last monsoon surge — battery/uplink fault."
            if status is SensorStatus.FAILED else "",
        ))
    return len(allocation), failed


def seed_users(db, zones: dict[str, Zone]) -> list[tuple[str, str]]:
    pw = settings.demo_password
    people = [
        ("authority", Role.AUTHORITY, "R. Baruah", "State EOC Duty Officer, MDoNER",
         "authority@bhooshakti.local", "+919000000001"),
        ("field.officer", Role.FIELD_OFFICER, "T. Lepcha", "District Field Officer, Darjeeling–Sikkim corridor",
         "field@bhooshakti.local", "+919000000002"),
        ("citizen", Role.CITIZEN, "Demo Citizen", "Public reporting account",
         "citizen@bhooshakti.local", "+919000000003"),
    ]
    created: list[tuple[str, str]] = []
    officer: User | None = None
    for username, role, full_name, designation, email, phone in people:
        u = User(
            username=username,
            role=role,
            full_name=full_name,
            designation=designation,
            email=email,
            phone=phone,
            hashed_password=hash_password(pw),
        )
        db.add(u)
        if role is Role.FIELD_OFFICER:
            officer = u
        created.append((username, role.value))
    db.flush()

    if officer is not None:
        for code in ["SK-01", "SK-02", "SK-04", "DJ-01", "DJ-03", "DJ-04", "DJ-05"]:
            db.add(ZoneAssignment(user_id=officer.id, zone_id=zones[code].id))
    return created


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed the BHOOSHAKTI AI demo database")
    ap.add_argument("--reset", action="store_true", help="drop all tables first")
    ap.add_argument("--no-monsoon-spike", action="store_true",
                    help="generate a calm month with no heavy spell")
    ap.add_argument("--weather", choices=["open-meteo", "simulated"],
                    default=settings.weather_provider,
                    help="real observed weather, or the synthetic generator")
    ap.add_argument("--seed", type=int, default=settings.seed_random_state)
    args = ap.parse_args()

    rng = random.Random(args.seed)

    print("=" * 74)
    print("BHOOSHAKTI AI — seeding demo database   [ALL DATA SIMULATED]")
    print("=" * 74)

    if args.reset:
        reset_schema()
    else:
        ensure_schema()

    with session_scope() as db:
        if db.query(Zone).count() > 0 and not args.reset:
            print("\n  Database already contains zones. Re-run with --reset to rebuild.")
            return 1

        print("\n[1/6] zones")
        zones = seed_zones(db, rng)
        print(f"  {len(zones)} PostGIS polygons across "
              f"{len({s.state for s in ZONES})} states/UTs")

        print("\n[2/6] rainfall + soil moisture (30 days hourly)")
        series = None
        if args.weather == "open-meteo":
            print("  provider: Open-Meteo (real observed weather)")
            series = seed_weather_real(db, zones)
            if series is None:
                print("  falling back to the synthetic generator")
        if series is None:
            print("  provider: synthetic generator [SIMULATED]")
            series = seed_weather(db, zones, rng, monsoon_spike=not args.no_monsoon_spike)

        print("\n[3/6] historical landslide events")
        n = seed_historical(db, zones, rng, series)
        print(f"  {n} labelled events, 2018–2025")

        print("\n[4/6] infrastructure")
        roads, villages, bridges = seed_infrastructure(db, rng)
        print(f"  {roads} road segments, {villages} villages, {bridges} bridges")

        print("\n[5/6] sensor nodes")
        total, failed = seed_sensors(db, zones, rng)
        print(f"  {total} nodes ({failed} FAILED — fallback logic demo)")

        print("\n[6/6] demo users")
        users = seed_users(db, zones)
        for username, role in users:
            print(f"  {username:<16} {role:<14} password: {settings.demo_password}")

    print("\n" + "=" * 74)
    print("Seed complete.  Next:  python scripts/train.py")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
