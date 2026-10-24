"""CAP 1.2 output, validated against the official OASIS schema
(tests/fixtures/CAP-v1.2.xsd, downloaded from docs.oasis-open.org)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
import xmlschema
from sqlalchemy import text

from app.services.cap import ATOM_NS, CAP_NS, cap_time

from .conftest import requires_db

XSD = xmlschema.XMLSchema(str(Path(__file__).parent / "fixtures" / "CAP-v1.2.xsd"))


@pytest.fixture(autouse=True)
def clean_advisories(request, tx_db):
    """Advisories left ACTIVE by a demo run would make a new report join them
    instead of issuing its own. Close them inside the test transaction, and
    detach any open demo reports from them so a dismiss sends its all-clear."""
    # Open demo reports would be worked by tick() too and could issue the
    # advisory this test's report then joins: mark them seen for the test.
    tx_db.execute(text("UPDATE citizen_reports SET advisory_alert_id = NULL, acknowledged_at = NOW(), "
                       "acknowledged_by = 'test-fixture' WHERE status = 'PENDING' AND acknowledged_at IS NULL"))
    tx_db.execute(text("UPDATE alerts SET status = 'SUPERSEDED' WHERE tier = 'ADVISORY' AND status = 'ACTIVE'"))
    tx_db.flush()


def test_cap_time_has_an_explicit_offset_never_z():
    s = cap_time(datetime(2026, 7, 1, 6, 30, tzinfo=timezone.utc))
    assert s == "2026-07-01T12:00:00+05:30"
    assert not s.endswith("Z")


@pytest.fixture()
def alerts(tx_db, no_siren):
    """An advisory, its WARNING upgrade, and a dismissed advisory + all-clear."""
    from app.deps import Principal
    from app.models import CitizenReport, ReportStatus, Severity, Zone
    from app.services import alerting, escalation

    zone = tx_db.query(Zone).filter(Zone.code == "DJ-04").one()
    me = Principal(1, "authority", "authority")
    out = []
    for decide in (escalation.confirm, escalation.dismiss):
        r = CitizenReport(issue_type="landslide", lat=zone.centroid_lat, lon=zone.centroid_lon,
                          geom=f"SRID=4326;POINT({zone.centroid_lon} {zone.centroid_lat})",
                          zone_id=zone.id, geo_valid=True, status=ReportStatus.PENDING,
                          created_at=datetime.now(timezone.utc), corroboration_score=90,
                          corroboration_reasons=[])
        tx_db.add(r)
        tx_db.flush()
        escalation.issue_advisory(tx_db, r, "test", datetime.now(timezone.utc))
        out.append(r.advisory_alert_id)
        out.append(decide(tx_db, r, me).id)
    out.append(alerting.issue(tx_db, zone=zone, tier="WARNING", severity=Severity.CRITICAL,
                              risk_score=81, confidence=0.7, factors=[], source="auto").id)
    return out


@requires_db
def test_every_alert_is_schema_valid_cap(tx_db, alerts):
    from app.models import Alert
    from app.services import cap
    for alert_id in alerts:
        xml = cap.alert_xml(tx_db, tx_db.get(Alert, alert_id))
        XSD.validate(xml)                       # raises with the exact violation


@requires_db
def test_feed_embeds_valid_cap_in_every_entry(client, alerts):
    r = client.get("/api/cap/alerts.xml")
    assert r.status_code == 200 and "atom" in r.headers["content-type"]
    feed = ET.fromstring(r.content)
    assert feed.tag == f"{{{ATOM_NS}}}feed"
    embedded = feed.findall(f".//{{{CAP_NS}}}alert")
    assert len(embedded) >= len(alerts)
    for el in embedded:
        XSD.validate(ET.tostring(el))


@requires_db
def test_cap_semantics_for_each_tier(tx_db, alerts):
    from app.models import Alert
    from app.services import cap
    adv1, warn, adv2, clear, auto_warn = alerts

    def parsed(i):
        root = ET.fromstring(cap.alert_xml(tx_db, tx_db.get(Alert, i)))
        f = lambda path: root.findtext(path, namespaces={"c": CAP_NS})  # noqa: E731
        return root, f

    _, f = parsed(adv1)
    assert (f("c:status"), f("c:msgType"), f("c:info/c:certainty")) == ("Exercise", "Alert", "Possible")

    root, f = parsed(warn)
    assert f("c:msgType") == "Update" and f("c:info/c:certainty") == "Observed"
    assert f("c:references").split(",")[1] == f"bhooshakti-alert-{adv1}"

    root, f = parsed(clear)
    assert f("c:msgType") == "Cancel"
    assert f("c:info/c:responseType") == "AllClear"

    root, f = parsed(auto_warn)
    assert f("c:info/c:severity") == "Extreme" and f("c:info/c:urgency") == "Immediate"
    poly = f("c:info/c:area/c:polygon").split()
    assert poly[0] == poly[-1] and len(poly) >= 4, "CAP polygons must be closed"
