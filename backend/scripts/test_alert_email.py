#!/usr/bin/env python3
"""Send a real alert email and report exactly what happened.

    python scripts/test_alert_email.py
    python scripts/test_alert_email.py --to someone@example.com --zone DJ-04 --lang hi

Builds the alert from a real zone's current risk — severity, score, confidence,
ranked contributing factors, exposed roads and settlements, and a deep link back
into the dashboard — then pushes it through the email channel.

With SMTP_HOST unset the channel reports SIMULATED and prints the rendered
message instead of sending. That is a configuration state, not a failure, and
this script says so plainly rather than pretending a message went out.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import session_scope  # noqa: E402
from app.models import Zone  # noqa: E402
from app.notify import templates  # noqa: E402
from app.notify.base import AlertPayload  # noqa: E402
from app.notify.channels import EmailChannel  # noqa: E402
from app.services import spatial  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Send a BHOOSHAKTI AI test alert email")
    ap.add_argument("--to", default=settings.alert_test_email, help="recipient address")
    ap.add_argument("--zone", default=None, help="zone code, e.g. DJ-04 (default: highest risk)")
    ap.add_argument("--lang", default="en", choices=["en", "hi", "as"])
    ap.add_argument("--dump-html", default=None, help="also write the HTML body to this path")
    args = ap.parse_args()

    print("=" * 74)
    print("BHOOSHAKTI AI — alert email test   [DEMO DATA]")
    print("=" * 74)
    print(f"  SMTP host    : {settings.smtp_host or '(unset)'}")
    print(f"  SMTP port    : {settings.smtp_port}")
    print(f"  SMTP user    : {settings.smtp_user or '(unset)'}")
    print(f"  From         : {settings.smtp_from}")
    print(f"  To           : {args.to}")
    print(f"  Mode         : {'LIVE SMTP SEND' if settings.email_configured else 'SIMULATED (SMTP_HOST is unset)'}")
    print()

    with session_scope() as db:
        if args.zone:
            zone = db.query(Zone).filter(Zone.code == args.zone.upper()).first()
            if zone is None:
                print(f"  No zone with code {args.zone!r}.")
                return 2
        else:
            row = db.execute(text("""
                SELECT z.id FROM zones z
                JOIN LATERAL (
                    SELECT risk_score FROM zone_risk zr WHERE zr.zone_id = z.id
                    ORDER BY computed_at DESC, id DESC LIMIT 1
                ) r ON TRUE
                ORDER BY r.risk_score DESC LIMIT 1
            """)).first()
            if row is None:
                print("  No zone risk computed yet. Start the API, or POST /risk/recompute.")
                return 2
            zone = db.query(Zone).filter(Zone.id == row[0]).one()

        current = db.execute(text("""
            SELECT risk_score, severity::text AS severity, confidence, contributing_factors
            FROM zone_risk WHERE zone_id = :z ORDER BY computed_at DESC, id DESC LIMIT 1
        """), {"z": zone.id}).mappings().first()
        if current is None:
            print(f"  Zone {zone.code} has no computed risk. Run POST /risk/recompute first.")
            return 2

        roads = spatial.roads_intersecting_zone(db, zone.id)
        villages = spatial.villages_in_zone(db, zone.id)

        # Read every attribute while the session is still open — session_scope
        # commits on exit, which expires the instance.
        payload = AlertPayload(
            alert_id=None, zone_id=zone.id, zone_code=zone.code, zone_name=zone.name,
            district=zone.district, state=zone.state,
            severity=current["severity"], risk_score=float(current["risk_score"]),
            confidence=float(current["confidence"]),
            contributing_factors=current["contributing_factors"] or [],
            language=args.lang,
            deep_link=f"{settings.public_dashboard_url}/?zone={zone.id}",
            affected_roads=[r["name"] for r in roads[:4]],
            affected_villages=[v["name"] for v in villages[:6]],
            source="script-test",
        )
        payload.title = templates.subject(payload)
        payload.message = templates.plain_text(payload)
        zone_line = f"{zone.code} — {zone.name}, {zone.district}, {zone.state}"

    print(f"  Zone         : {zone_line}")
    print(f"  Severity     : {payload.severity}")
    print(f"  Risk score   : {payload.risk_score:.0f}/100")
    print(f"  Confidence   : {payload.confidence * 100:.0f}%")
    print(f"  Factors      : {len(payload.factor_lines)}")
    for i, line in enumerate(payload.factor_lines, 1):
        print(f"      {i}. {line}")
    print(f"  Roads        : {', '.join(payload.affected_roads) or '—'}")
    print(f"  Settlements  : {', '.join(payload.affected_villages) or '—'}")
    print(f"  Deep link    : {payload.deep_link}")
    print()

    if args.dump_html:
        Path(args.dump_html).write_text(templates.html_body(payload), encoding="utf-8")
        print(f"  HTML body written to {args.dump_html}")

    results = EmailChannel([args.to]).send(payload)

    print("  ---- delivery ----")
    ok = True
    for r in results:
        print(f"  {r.channel:<8} {r.recipient:<34} {r.status:<10} {r.detail}")
        if r.status == "FAILED":
            ok = False

    print()
    if not settings.email_configured:
        print("  RESULT: SIMULATED — nothing left this machine.")
        print("  To send for real, set these in .env and re-run:")
        print("      SMTP_HOST=smtp.gmail.com")
        print("      SMTP_PORT=587")
        print("      SMTP_USER=<your gmail address>")
        print("      SMTP_PASSWORD=<16-char app password from")
        print("                     https://myaccount.google.com/apppasswords>")
        return 3
    if not ok:
        print("  RESULT: FAILED — see the detail above.")
        return 1
    print(f"  RESULT: SENT — check the inbox for {args.to}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
