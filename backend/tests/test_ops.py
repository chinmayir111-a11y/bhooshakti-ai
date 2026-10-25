"""Officer tools: steps come only from data the zone has; the PDF is a PDF."""
from app.services.pdf import build

from .conftest import requires_db


def test_pdf_writer_makes_a_valid_multi_page_pdf():
    b = build([("h1", "Situation report — Test"), ("p", "x " * 400)] * 30)
    assert b.startswith(b"%PDF-1.4") and b.rstrip().endswith(b"%%EOF") and b.count(b"/Type /Page ") > 1


@requires_db
def test_steps_are_built_from_the_zones_own_data(tx_db):
    from app.models import Zone
    from app.routers.ops import steps
    from app.services import spatial
    zone = tx_db.query(Zone).filter(Zone.code == "DJ-04").one()
    out = steps(tx_db, zone)
    assert 1 <= len(out) <= 5 and len({s["key"] for s in out}) == len(out)
    roads = spatial.roads_intersecting_zone(tx_db, zone.id)
    assert any(s["key"].startswith("road:") for s in out) == bool(roads)
    assert all("None" not in s["text"] for s in out)
