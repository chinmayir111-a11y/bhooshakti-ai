"""Common Alerting Protocol 1.2 — the format NDMA's SACHET platform and
cell-broadcast systems consume.

Every message carries status=Exercise: this is a prototype on demo data, and
CAP has a field for exactly that. Moving to status=Actual is a government
integration decision, not a code change (see README, "Rural / offline access").

Mapping
    tier ADVISORY  -> certainty Possible, urgency Expected,  responseType Monitor/Avoid
    tier WARNING   -> certainty Likely (Observed if human-confirmed), urgency Immediate,
                      responseType Avoid/Evacuate
    all-clear      -> msgType Cancel referencing the advisory, responseType AllClear
    upgrade        -> msgType Update referencing the advisory
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Alert

CAP_NS = "urn:oasis:names:tc:emergency:cap:1.2"
ATOM_NS = "http://www.w3.org/2005/Atom"
IST = timezone(timedelta(hours=5, minutes=30))

SEVERITY = {"LOW": "Minor", "MODERATE": "Moderate", "HIGH": "Severe", "CRITICAL": "Extreme"}
LANG_TAG = {"en": "en-IN", "hi": "hi-IN", "as": "as-IN", "bn": "bn-IN", "ne": "ne-NP"}


def cap_time(dt: datetime | None) -> str:
    """CAP forbids 'Z'; it wants an explicit offset. Rendered in IST."""
    dt = dt or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).isoformat(timespec="seconds")


def identifier(alert: Alert) -> str:
    return f"bhooshakti-alert-{alert.id}"


def _kind(alert: Alert) -> str:
    if alert.source == "all-clear":
        return "all_clear"
    if alert.source == "moderator-confirmed":
        return "confirmed"
    if alert.source == "auto-advisory":
        return "advisory"
    return "risk"


def _polygon(db: Session, zone_id: int) -> str | None:
    gj = db.execute(text("SELECT ST_AsGeoJSON(geom, 5) FROM zones WHERE id = :z"),
                    {"z": zone_id}).scalar()
    if not gj:
        return None
    ring = json.loads(gj)["coordinates"][0]
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return " ".join(f"{lat},{lon}" for lon, lat in ring)


def _sub(parent: ET.Element, tag: str, value: str | None = None) -> ET.Element:
    el = ET.SubElement(parent, f"{{{CAP_NS}}}{tag}")
    if value is not None:
        el.text = value
    return el


def alert_element(db: Session, alert: Alert) -> ET.Element:
    zone = db.execute(text("SELECT name, district, state FROM zones WHERE id = :z"),
                      {"z": alert.zone_id}).mappings().first()
    kind = _kind(alert)
    parent = db.get(Alert, alert.parent_alert_id) if alert.parent_alert_id else None

    root = ET.Element(f"{{{CAP_NS}}}alert")
    _sub(root, "identifier", identifier(alert))
    _sub(root, "sender", settings.cap_sender)
    _sub(root, "sent", cap_time(alert.created_at))
    _sub(root, "status", "Exercise")
    msg_type = "Cancel" if kind == "all_clear" else ("Update" if parent else "Alert")
    _sub(root, "msgType", msg_type)
    _sub(root, "scope", "Public")
    _sub(root, "note", "DEMO DATA — BHOOSHAKTI AI prototype (SIH 2026, PS 26001). Not an official warning.")
    if parent is not None:
        _sub(root, "references", f"{settings.cap_sender},{identifier(parent)},{cap_time(parent.created_at)}")

    info = _sub(root, "info")
    _sub(info, "language", LANG_TAG.get(alert.language, "en-IN"))
    _sub(info, "category", "Geo")
    _sub(info, "event", "Landslide")
    if kind == "all_clear":
        response = ["AllClear"]
    elif alert.tier == "WARNING":
        response = ["Evacuate", "Avoid"] if alert.severity.value == "CRITICAL" else ["Avoid"]
    else:
        response = ["Monitor", "Avoid"]
    for r in response:
        _sub(info, "responseType", r)
    _sub(info, "urgency", "Past" if kind == "all_clear" else
         ("Immediate" if alert.tier == "WARNING" else "Expected"))
    _sub(info, "severity", "Minor" if kind == "all_clear" else SEVERITY.get(alert.severity.value, "Unknown"))
    if kind == "all_clear":
        certainty = "Unlikely"
    elif kind == "confirmed":
        certainty = "Observed"
    elif alert.tier == "WARNING":
        certainty = "Likely"
    else:
        certainty = "Possible"
    _sub(info, "certainty", certainty)
    created = alert.created_at or datetime.now(timezone.utc)
    hours = 12 if alert.tier == "WARNING" else 6
    _sub(info, "expires", cap_time(created + timedelta(hours=hours)))
    _sub(info, "senderName", "BHOOSHAKTI AI — SIH 2026 prototype (demo)")
    _sub(info, "headline", alert.title[:160])
    _sub(info, "description", alert.message)
    if kind == "advisory":
        _sub(info, "instruction", "Stay alert, avoid the slope/road, await official confirmation.")
    elif kind == "all_clear":
        _sub(info, "instruction", "No action needed. The earlier advisory is cancelled.")
    else:
        _sub(info, "instruction", "Move away from steep slopes and hill roads. Follow official instructions.")
    _sub(info, "web", f"{settings.public_dashboard_url}/control?zone={alert.zone_id}")
    for name, value in (("BHOOSHAKTI_TIER", alert.tier), ("BHOOSHAKTI_RISK_SCORE", f"{alert.risk_score:.0f}"),
                        ("BHOOSHAKTI_CONFIDENCE", f"{alert.confidence:.2f}"),
                        ("DATA", "SIMULATED/DEMO")):
        p = _sub(info, "parameter")
        _sub(p, "valueName", name)
        _sub(p, "value", value)

    area = _sub(info, "area")
    desc = f"{zone['name']}, {zone['district']}, {zone['state']}" if zone else alert.zone_name
    _sub(area, "areaDesc", desc)
    poly = _polygon(db, alert.zone_id)
    if poly:
        _sub(area, "polygon", poly)
    return root


def alert_xml(db: Session, alert: Alert) -> bytes:
    ET.register_namespace("", CAP_NS)
    return ET.tostring(alert_element(db, alert), encoding="utf-8", xml_declaration=True)


def feed_xml(db: Session, limit: int = 50) -> bytes:
    """Atom index of recent alerts, each entry carrying its full CAP message —
    the shape public-alert aggregators poll."""
    ET.register_namespace("", ATOM_NS)
    ET.register_namespace("cap", CAP_NS)
    alerts = db.query(Alert).filter(Alert.source != "manual-test") \
               .order_by(Alert.created_at.desc(), Alert.id.desc()).limit(limit).all()

    feed = ET.Element(f"{{{ATOM_NS}}}feed")
    def a(parent, tag, value=None, **attrs):
        el = ET.SubElement(parent, f"{{{ATOM_NS}}}{tag}", attrs)
        if value is not None:
            el.text = value
        return el
    a(feed, "id", f"{settings.public_api_url}/api/cap/alerts.xml")
    a(feed, "title", "BHOOSHAKTI AI — landslide alerts (CAP 1.2, status=Exercise, DEMO DATA)")
    a(feed, "updated", cap_time(alerts[0].created_at if alerts else None))
    au = a(feed, "author")
    a(au, "name", "BHOOSHAKTI AI prototype")
    a(feed, "link", href=f"{settings.public_api_url}/api/cap/alerts.xml", rel="self")
    for al in alerts:
        e = a(feed, "entry")
        a(e, "id", f"{settings.public_api_url}/api/cap/alerts/{al.id}.xml")
        a(e, "title", al.title[:160])
        a(e, "updated", cap_time(al.created_at))
        a(e, "link", href=f"{settings.public_api_url}/api/cap/alerts/{al.id}.xml",
          type="application/cap+xml")
        content = a(e, "content", type="application/cap+xml")
        content.append(alert_element(db, al))
    return ET.tostring(feed, encoding="utf-8", xml_declaration=True)
