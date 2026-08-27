"""All spatial logic, expressed as PostGIS SQL.

Nothing in here approximates geometry in Python — zone lookup, road/zone
intersection, and proximity cut-off analysis are ST_Contains / ST_Intersects /
ST_DWithin queries executed by the database.

Distance predicates cast to `geography` so the radius argument is in metres
rather than degrees.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

# Metres from a blocked road within which a settlement is treated as losing
# its road access. Roughly "no alternative approach on foot in hill terrain".
CUTOFF_RADIUS_M = 2500.0


# ---------------------------------------------------------------------------
# GeoJSON emitters
# ---------------------------------------------------------------------------


def zones_geojson(db: Session) -> dict[str, Any]:
    """Zone polygons joined to their most recent risk computation."""
    sql = text("""
        SELECT
            z.id, z.code, z.name, z.district, z.state,
            z.slope_deg, z.aspect_deg, z.elevation_m,
            z.lithology, z.land_cover, z.population, z.area_km2,
            z.centroid_lat, z.centroid_lon,
            ST_AsGeoJSON(z.geom)::json AS geometry,
            r.risk_score, r.severity::text AS severity, r.confidence,
            r.contributing_factors, r.computed_at
        FROM zones z
        LEFT JOIN LATERAL (
            SELECT zr.risk_score, zr.severity, zr.confidence,
                   zr.contributing_factors, zr.computed_at
            FROM zone_risk zr
            WHERE zr.zone_id = z.id
            ORDER BY zr.computed_at DESC, zr.id DESC
            LIMIT 1
        ) r ON TRUE
        ORDER BY z.id
    """)
    features = []
    for row in db.execute(sql).mappings():
        features.append({
            "type": "Feature",
            "id": row["id"],
            "geometry": row["geometry"],
            "properties": {
                "id": row["id"],
                "code": row["code"],
                "name": row["name"],
                "district": row["district"],
                "state": row["state"],
                "slope_deg": row["slope_deg"],
                "aspect_deg": row["aspect_deg"],
                "elevation_m": row["elevation_m"],
                "lithology": row["lithology"],
                "land_cover": row["land_cover"],
                "population": row["population"],
                "area_km2": row["area_km2"],
                "centroid": [row["centroid_lat"], row["centroid_lon"]],
                "risk_score": row["risk_score"],
                "severity": row["severity"] or "LOW",
                "confidence": row["confidence"],
                "contributing_factors": row["contributing_factors"] or [],
                "computed_at": row["computed_at"].isoformat() if row["computed_at"] else None,
            },
        })
    return {"type": "FeatureCollection", "features": features}


def roads_geojson(db: Session) -> dict[str, Any]:
    sql = text("""
        SELECT id, name, road_class, status::text AS status, length_km,
               criticality, status_note, ST_AsGeoJSON(geom)::json AS geometry
        FROM road_segments ORDER BY id
    """)
    return _collection(db, sql)


def villages_geojson(db: Session) -> dict[str, Any]:
    sql = text("""
        SELECT id, name, district, state, population, households,
               is_cut_off, cut_off_reason, ST_AsGeoJSON(geom)::json AS geometry
        FROM villages ORDER BY id
    """)
    return _collection(db, sql)


def bridges_geojson(db: Session) -> dict[str, Any]:
    sql = text("""
        SELECT id, name, span_m, status::text AS status, road_name,
               ST_AsGeoJSON(geom)::json AS geometry
        FROM bridges ORDER BY id
    """)
    return _collection(db, sql)


def sensors_geojson(db: Session) -> dict[str, Any]:
    sql = text("""
        SELECT s.id, s.node_id, s.zone_id, z.code AS zone_code, z.name AS zone_name,
               s.status::text AS status, s.sensor_types, s.battery_pct,
               s.last_seen, s.note, ST_AsGeoJSON(s.geom)::json AS geometry
        FROM sensor_nodes s JOIN zones z ON z.id = s.zone_id
        ORDER BY s.node_id
    """)
    return _collection(db, sql)


def historical_geojson(db: Session) -> dict[str, Any]:
    sql = text("""
        SELECT h.id, h.zone_id, z.name AS zone_name, h.occurred_at,
               h.rainfall_72h, h.soil_moisture_pct, h.fatalities, h.trigger,
               ST_AsGeoJSON(h.geom)::json AS geometry
        FROM historical_landslides h JOIN zones z ON z.id = h.zone_id
        ORDER BY h.occurred_at DESC
    """)
    return _collection(db, sql)


def _collection(db: Session, sql) -> dict[str, Any]:
    features = []
    for row in db.execute(sql).mappings():
        props = {k: v for k, v in row.items() if k != "geometry"}
        for k, v in list(props.items()):
            if hasattr(v, "isoformat"):
                props[k] = v.isoformat()
        features.append({
            "type": "Feature",
            "id": props.get("id"),
            "geometry": row["geometry"],
            "properties": props,
        })
    return {"type": "FeatureCollection", "features": features}


# ---------------------------------------------------------------------------
# Point-in-polygon: geo-validating citizen and field reports
# ---------------------------------------------------------------------------


def locate_point(db: Session, lat: float, lon: float) -> dict[str, Any]:
    """Which monitored zone contains this point? ST_Contains, then nearest.

    Returns zone_id (None when outside every zone), geo_valid, a human note,
    and the distance to the nearest zone edge in km when it falls outside.
    """
    contained = db.execute(text("""
        SELECT id, code, name, district, state
        FROM zones
        WHERE ST_Contains(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
        LIMIT 1
    """), {"lat": lat, "lon": lon}).mappings().first()

    if contained:
        return {
            "zone_id": contained["id"],
            "zone_code": contained["code"],
            "zone_name": contained["name"],
            "geo_valid": True,
            "distance_km": 0.0,
            "note": f"Inside monitored zone {contained['code']} — {contained['name']}, "
                    f"{contained['district']}, {contained['state']}",
        }

    nearest = db.execute(text("""
        SELECT id, code, name, district, state,
               ST_Distance(
                   geom::geography,
                   ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
               ) / 1000.0 AS distance_km
        FROM zones
        ORDER BY geom <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)
        LIMIT 1
    """), {"lat": lat, "lon": lon}).mappings().first()

    if not nearest:
        return {"zone_id": None, "zone_code": None, "zone_name": None,
                "geo_valid": False, "distance_km": None,
                "note": "No monitored zones are configured."}

    return {
        "zone_id": None,
        "zone_code": nearest["code"],
        "zone_name": nearest["name"],
        "geo_valid": False,
        "distance_km": round(float(nearest["distance_km"]), 2),
        "note": f"Outside every monitored zone — {nearest['distance_km']:.1f} km from "
                f"{nearest['code']} ({nearest['name']}). Flagged for manual review.",
    }


# ---------------------------------------------------------------------------
# Zone → infrastructure exposure
# ---------------------------------------------------------------------------


def roads_intersecting_zone(db: Session, zone_id: int) -> list[dict[str, Any]]:
    """Road segments whose geometry crosses the zone polygon (ST_Intersects)."""
    sql = text("""
        SELECT r.id, r.name, r.road_class, r.status::text AS status,
               r.criticality, r.status_note, r.length_km,
               ROUND((ST_Length(ST_Intersection(r.geom, z.geom)::geography) / 1000.0)::numeric, 2)
                   AS exposed_km
        FROM road_segments r
        JOIN zones z ON z.id = :zone_id
        WHERE ST_Intersects(r.geom, z.geom)
        ORDER BY exposed_km DESC NULLS LAST, r.name
    """)
    return [dict(r) for r in db.execute(sql, {"zone_id": zone_id}).mappings()]


def villages_in_zone(db: Session, zone_id: int) -> list[dict[str, Any]]:
    """Settlements inside the zone polygon (ST_Contains)."""
    sql = text("""
        SELECT v.id, v.name, v.district, v.state, v.population, v.households,
               v.is_cut_off, v.cut_off_reason
        FROM villages v
        JOIN zones z ON z.id = :zone_id
        WHERE ST_Contains(z.geom, v.geom)
        ORDER BY v.population DESC
    """)
    return [dict(r) for r in db.execute(sql, {"zone_id": zone_id}).mappings()]


def bridges_in_zone(db: Session, zone_id: int) -> list[dict[str, Any]]:
    sql = text("""
        SELECT b.id, b.name, b.span_m, b.status::text AS status, b.road_name
        FROM bridges b
        JOIN zones z ON z.id = :zone_id
        WHERE ST_Contains(z.geom, b.geom)
        ORDER BY b.name
    """)
    return [dict(r) for r in db.execute(sql, {"zone_id": zone_id}).mappings()]


def sensors_in_zone(db: Session, zone_id: int) -> list[dict[str, Any]]:
    sql = text("""
        SELECT node_id, status::text AS status, battery_pct, last_seen, note,
               ST_Y(geom) AS lat, ST_X(geom) AS lon
        FROM sensor_nodes
        WHERE zone_id = :zone_id
        ORDER BY node_id
    """)
    out = []
    for r in db.execute(sql, {"zone_id": zone_id}).mappings():
        d = dict(r)
        if d.get("last_seen") is not None:
            d["last_seen"] = d["last_seen"].isoformat()
        out.append(d)
    return out


def villages_near_road(db: Session, road_id: int,
                       radius_m: float = CUTOFF_RADIUS_M) -> list[dict[str, Any]]:
    """Settlements within `radius_m` of a road segment (ST_DWithin on geography)."""
    sql = text("""
        SELECT v.id, v.name, v.district, v.state, v.population, v.households,
               ROUND((ST_Distance(v.geom::geography, r.geom::geography))::numeric, 0) AS distance_m
        FROM villages v
        JOIN road_segments r ON r.id = :road_id
        WHERE ST_DWithin(v.geom::geography, r.geom::geography, :radius_m)
        ORDER BY distance_m
    """)
    return [dict(r) for r in db.execute(sql, {"road_id": road_id, "radius_m": radius_m}).mappings()]


def reports_in_zone(db: Session, zone_id: int, limit: int = 20) -> list[dict[str, Any]]:
    sql = text("""
        SELECT id, issue_type, description, status::text AS status,
               geo_valid, created_at, lat, lon, photo_path, language
        FROM citizen_reports
        WHERE zone_id = :zone_id
        ORDER BY created_at DESC
        LIMIT :limit
    """)
    out = []
    for r in db.execute(sql, {"zone_id": zone_id, "limit": limit}).mappings():
        d = dict(r)
        d["created_at"] = d["created_at"].isoformat()
        out.append(d)
    return out


def field_reports_in_zone(db: Session, zone_id: int, limit: int = 20) -> list[dict[str, Any]]:
    sql = text("""
        SELECT id, verdict::text AS verdict, notes, officer_name, observed_at,
               created_at, submitted_offline, photo_path, lat, lon
        FROM field_reports
        WHERE zone_id = :zone_id
        ORDER BY observed_at DESC
        LIMIT :limit
    """)
    out = []
    for r in db.execute(sql, {"zone_id": zone_id, "limit": limit}).mappings():
        d = dict(r)
        for k in ("observed_at", "created_at"):
            if d.get(k) is not None:
                d[k] = d[k].isoformat()
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# Cascade: block a road, then work out who loses access
# ---------------------------------------------------------------------------


def block_road_in_zone(db: Session, zone_id: int, note: str) -> dict[str, Any]:
    """Flip the most-exposed lifeline road crossing a zone to BLOCKED and flag
    every settlement that falls inside the cut-off radius of that segment.

    Both steps are PostGIS: ST_Intersects picks the road, ST_DWithin picks the
    settlements that lose their approach.
    """
    roads = roads_intersecting_zone(db, zone_id)
    if not roads:
        return {"road": None, "villages_cut_off": []}

    lifelines = [r for r in roads if r["criticality"] == "lifeline"] or roads
    road = lifelines[0]

    db.execute(text("""
        UPDATE road_segments
        SET status = 'BLOCKED', status_note = :note, updated_at = NOW()
        WHERE id = :road_id
    """), {"road_id": road["id"], "note": note})

    affected = villages_near_road(db, road["id"])
    if affected:
        db.execute(text("""
            UPDATE villages
            SET is_cut_off = TRUE, cut_off_reason = :reason
            WHERE id = ANY(:ids)
        """), {"ids": [v["id"] for v in affected],
               "reason": f"Road access severed — {road['name']} BLOCKED"})

    db.execute(text("""
        UPDATE bridges SET status = 'RESTRICTED'
        WHERE road_name = :road_name AND status = 'OPEN'
    """), {"road_name": road["name"]})

    road["status"] = "BLOCKED"
    road["status_note"] = note
    return {"road": road, "villages_cut_off": affected}


def reset_infrastructure(db: Session) -> None:
    db.execute(text("UPDATE road_segments SET status='OPEN', status_note='', updated_at=NOW()"))
    db.execute(text("UPDATE villages SET is_cut_off=FALSE, cut_off_reason=''"))
    db.execute(text("UPDATE bridges SET status='OPEN'"))


# ---------------------------------------------------------------------------
# Dashboard roll-up
# ---------------------------------------------------------------------------


def dashboard_summary(db: Session) -> dict[str, Any]:
    severity_counts = db.execute(text("""
        SELECT r.severity::text AS severity, COUNT(*) AS n
        FROM zones z
        JOIN LATERAL (
            SELECT zr.severity FROM zone_risk zr
            WHERE zr.zone_id = z.id
            ORDER BY zr.computed_at DESC, zr.id DESC LIMIT 1
        ) r ON TRUE
        GROUP BY r.severity
    """)).mappings().all()

    counts = {"LOW": 0, "MODERATE": 0, "HIGH": 0, "CRITICAL": 0}
    for row in severity_counts:
        counts[row["severity"]] = int(row["n"])
    scored = sum(counts.values())
    counts["UNSCORED"] = int(db.execute(text("SELECT COUNT(*) FROM zones")).scalar_one()) - scored

    scalar = lambda q: int(db.execute(text(q)).scalar_one())  # noqa: E731
    return {
        "severity_counts": counts,
        "active_alerts": scalar(
            "SELECT COUNT(*) FROM alerts WHERE acknowledged = FALSE"),
        "alerts_24h": scalar(
            "SELECT COUNT(*) FROM alerts WHERE created_at > NOW() - INTERVAL '24 hours'"),
        "unverified_reports": scalar(
            "SELECT COUNT(*) FROM citizen_reports WHERE status = 'PENDING'"),
        "roads_flagged": scalar(
            "SELECT COUNT(*) FROM road_segments WHERE status <> 'OPEN'"),
        "villages_cut_off": scalar(
            "SELECT COUNT(*) FROM villages WHERE is_cut_off"),
        "sensors_total": scalar("SELECT COUNT(*) FROM sensor_nodes"),
        "sensors_failed": scalar(
            "SELECT COUNT(*) FROM sensor_nodes WHERE status = 'FAILED'"),
        "field_reports_24h": scalar(
            "SELECT COUNT(*) FROM field_reports WHERE created_at > NOW() - INTERVAL '24 hours'"),
    }
