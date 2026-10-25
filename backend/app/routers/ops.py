"""Officer tools for a zone at HIGH / CRITICAL: 'What to do now' steps built
from data the system already has (each tick is audited), and a one-click
situation report (PDF) for the DM / SDMA."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import Principal, audit, require_authority, require_roles
from ..models import Zone
from ..services import pdf, risk_service, shelters, spatial, volunteers

router = APIRouter(prefix="/zones", tags=["operations"])
IST = timezone(timedelta(hours=5, minutes=30))
officers = require_roles("authority", "field_officer")


def _zone(db: Session, zone_id: int) -> Zone:
    z = db.get(Zone, zone_id)
    if z is None:
        raise HTTPException(404, "No such zone")
    return z


def steps(db: Session, zone: Zone) -> list[dict[str, Any]]:
    """3-5 plain steps from this zone's roads, villages, shelters, volunteers
    and open reports. Nothing is invented: a step appears only if its data does."""
    out: list[dict[str, Any]] = []
    for r in spatial.roads_intersecting_zone(db, zone.id)[:2]:
        out.append({"key": f"road:{r['id']}", "text": f"Close {r['name']} where it crosses {zone.name}"
                    + (f" ({r['exposed_km']} km exposed)" if r.get("exposed_km") else "")})
    vil = spatial.villages_in_zone(db, zone.id)
    if vil:
        people = sum(int(v.get("population") or 0) for v in vil)
        names = ", ".join(v["name"] for v in vil[:3]) + ("…" if len(vil) > 3 else "")
        out.append({"key": "villages", "text": f"Alert {len(vil)} village{'s' if len(vil) > 1 else ''} "
                                               f"({people:,} people): {names}"})
    s = shelters.for_zone(db, zone.id)
    if s:
        out.append({"key": f"shelter:{s['id']}", "text": f"Open shelter: {s['name']} ({s['kind_label']}, "
                                                         f"{s['distance_m'] / 1000:.1f} km {s['direction']} of the zone centre)"})
    for v in [x for x in volunteers.listing(db) if x["zone_id"] == zone.id][:1]:
        out.append({"key": f"volunteer:{v['id']}", "text": f"Call volunteer {v['name']} (gauge at {v['place']}, "
                                                           f"{v['total_24h']:.0f} mm in 24 h)"})
    pending = db.execute(text("SELECT COUNT(*) FROM citizen_reports WHERE zone_id = :z AND status = 'PENDING'"),
                         {"z": zone.id}).scalar() or 0
    if pending:
        out.append({"key": "reports", "text": f"Check {pending} open citizen report{'s' if pending > 1 else ''} in this zone"})
    return out[:5]


def _done(db: Session, zone_id: int) -> dict[str, dict[str, Any]]:
    rows = db.execute(text("""
        SELECT detail->>'key' AS k, username, ts FROM audit_log
        WHERE resource = 'zone' AND resource_id = :z AND action = 'todo_done' AND ts > NOW() - INTERVAL '24 hours'
        ORDER BY ts
    """), {"z": str(zone_id)}).mappings().all()
    return {r["k"]: {"by": r["username"], "at": r["ts"].isoformat()} for r in rows}


@router.get("/{zone_id}/todo", summary="What to do now: steps from the zone's own data (officers)")
def todo(zone_id: int, db: Session = Depends(get_db), _: Principal = Depends(officers)) -> list[dict]:
    zone = _zone(db, zone_id)
    done = _done(db, zone_id)
    return [{**s, "done": done.get(s["key"])} for s in steps(db, zone)]


@router.post("/{zone_id}/todo/{key}/done", summary="Tick a step as done (audited)")
def tick(zone_id: int, key: str, request: Request, db: Session = Depends(get_db),
         principal: Principal = Depends(require_authority)) -> dict:
    zone = _zone(db, zone_id)
    step = next((s for s in steps(db, zone) if s["key"] == key), None)
    if step is None:
        raise HTTPException(404, "No such step for this zone now")
    audit(db, principal, "todo_done", "zone", zone_id, request, {"key": key, "text": step["text"]}, commit=False)
    db.commit()
    return {"key": key, "done": {"by": principal.username, "at": datetime.now(timezone.utc).isoformat()}}


@router.get("/{zone_id}/sitrep.pdf", summary="Situation report for the DM / SDMA (PDF)")
def sitrep(zone_id: int, request: Request, db: Session = Depends(get_db),
           principal: Principal = Depends(officers)) -> Response:
    zone = _zone(db, zone_id)
    d = risk_service.zone_detail(db, zone)
    r = d.get("risk") or {}
    ist = datetime.now(IST)
    L: list[tuple[str, str]] = [
        ("h1", f"Situation report — {zone.name}"),
        ("p", f"{zone.code} · {zone.district}, {zone.state} · {ist:%d %b %Y, %H:%M} IST · prepared by {principal.username}"),
        ("small", "BHOOSHAKTI AI prototype. Weather and past landslides are real; zones, sensors and some "
                  "infrastructure are SIMULATED. Decision support, not a guaranteed prediction."),
        ("h2", "Risk now"),
        ("p", f"{r.get('severity', 'not scored')} · risk {r.get('risk_score', 0):.0f}/100 · confidence "
              f"{(r.get('confidence') or 0) * 100:.0f}% · computed "
              + (datetime.fromisoformat(r["computed_at"]).astimezone(IST).strftime("%d %b, %H:%M IST") if r.get("computed_at") else "—")),
        ("h2", "Why"),
    ]
    L += [("p", f"- {f.get('text', '')}") for f in (r.get("contributing_factors") or [])[:8]]
    L += [("h2", "Rain"),
          ("p", f"24 h {r.get('rainfall_24h') or 0:.0f} mm · 72 h {r.get('rainfall_72h') or 0:.0f} mm · "
                f"15-day {r.get('antecedent_rain_15d') or 0:.0f} mm · next 24 h (forecast) {r.get('forecast_24h_mm') or 0:.0f} mm "
                f"· soil moisture {r.get('soil_moisture_pct') or 0:.0f}% (Open-Meteo)")]
    gauge = d.get("volunteer_gauge") or []
    if gauge:
        L.append(("p", f"Village gauge (volunteer): latest {gauge[-1]['mm']:.0f} mm, {gauge[-1]['total_24h']:.0f} mm in 24 h"))
    reps = db.execute(text("""
        SELECT id, issue_type, corroboration_score, status::text AS status, created_at FROM citizen_reports
        WHERE zone_id = :z AND created_at > NOW() - INTERVAL '24 hours' ORDER BY created_at DESC
    """), {"z": zone.id}).mappings().all()
    L += [("h2", f"Citizen reports, last 24 h ({len(reps)})")]
    L += [("p", f"#{x['id']} {x['issue_type'].replace('_', ' ')} · trust {x['corroboration_score']:.0f}/100 · {x['status']}")
          for x in reps[:8]] or [("p", "None.")]
    roads = [x for x in d.get("roads", []) if x["status"] != "OPEN"]
    cut = [v for v in d.get("villages", []) if v.get("is_cut_off")]
    L += [("h2", "Roads and villages"),
          ("p", "Roads not open: " + (", ".join(f"{x['name']} ({x['status']})" for x in roads) or "none")),
          ("p", "Villages cut off: " + (", ".join(v["name"] for v in cut) or "none")),
          ("p", "Villages in the zone: " + (", ".join(f"{v['name']} ({v['population']:,})" for v in d.get("villages", [])) or "none"))]
    sh = d.get("shelters") or []
    L += [("h2", "Safe places (OpenStreetMap)")]
    L += [("p", f"- {s['name']} ({s['kind_label']})" + (" — MARKED UNSAFE" if s["unsafe"] else "")) for s in sh[:8]] \
        or [("p", "None mapped within 3 km.")]
    acts = db.execute(text("""
        SELECT ts, username, action, detail->>'text' AS t FROM audit_log
        WHERE ts > NOW() - INTERVAL '24 hours' AND (
              (resource = 'zone' AND resource_id = :z)
           OR (resource = 'citizen_report' AND resource_id IN (SELECT id::text FROM citizen_reports WHERE zone_id = :zi))
        ) AND action IN ('todo_done', 'confirm', 'dismiss', 'acknowledge', 'confirm_prepare', 'mark_unsafe')
        ORDER BY ts
    """), {"z": str(zone.id), "zi": zone.id}).mappings().all()
    L += [("h2", f"Actions taken, last 24 h ({len(acts)})")]
    L += [("p", f"{a['ts'].astimezone(IST):%H:%M} IST · {a['username']} · "
                f"{a['action'].replace('_', ' ')}{(': ' + a['t']) if a['t'] else ''}") for a in acts] or [("p", "None recorded.")]
    alerts = db.execute(text("""
        SELECT tier, severity::text AS sev, title, created_at FROM alerts
        WHERE zone_id = :z AND created_at > NOW() - INTERVAL '24 hours' ORDER BY created_at
    """), {"z": zone.id}).mappings().all()
    L += [("h2", f"Alerts issued, last 24 h ({len(alerts)})")]
    L += [("p", f"{a['created_at'].astimezone(IST):%H:%M} IST · {a['tier']} {a['sev']} · {a['title']}")
          for a in alerts] or [("p", "None.")]
    audit(db, principal, "sitrep", "zone", zone.id, request, commit=False)
    db.commit()
    name = f"sitrep-{zone.code}-{ist:%Y%m%d-%H%M}.pdf"
    return Response(pdf.build(L), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
