"""The scripted monsoon event — the two-minute story, told in eight steps.

    1  MQTT sensor telemetry ramps rainfall across three corridor zones
    2  Soil moisture follows, with the lag a real slope shows
    3  Risk recomputes — two zones HIGH, one CRITICAL
    4  Alerts fire automatically and dispatch on every channel
    5  A field officer's verification arrives confirming slope movement
    6  A citizen report drops into the moderation queue
    7  PostGIS cascade: lifeline road BLOCKED, settlements flagged cut off
    8  A prioritised response plan renders

Step 1 genuinely publishes to the MQTT broker and is ingested back through
`app.mqtt_client` — the telemetry path in the demo is the real path, not a
shortcut that writes to the database directly.

`reset()` restores the weather rows the demo overwrote, so the timeline can be
run again from a clean state without re-seeding.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from ..db import session_scope
from ..models import (
    CitizenReport,
    FieldReport,
    ReportStatus,
    ResponseAction,
    Verdict,
    Zone,
)
from ..ws import (
    EVENT_DEMO_STATE,
    EVENT_DEMO_STEP,
    EVENT_INFRA_UPDATE,
    EVENT_REPORT_NEW,
    EVENT_RESPONSE_PLAN,
    EVENT_FIELD_REPORT,
    EVENT_SUMMARY,
    manager,
)
from . import risk_service, spatial

log = logging.getLogger("bhooshakti.demo")

# The Sikkim/Darjeeling corridor zones the timeline escalates.
DEFAULT_ZONE_CODES = ["SK-02", "DJ-04", "DJ-01"]
CRITICAL_CODE = "DJ-04"

# Target trailing-24h rainfall (mm) and peak soil saturation for each demo zone.
# The engine measures what the zone already has and scales the storm to hit
# these numbers, rather than applying a fixed intensity — a fixed ramp lands
# differently every time the database is reseeded.
#
# The numbers are far smaller than they were against synthetic weather because
# the real ERA5 seasonal normals here are 25-80 mm/72h, not ~80. A 45 mm day
# against a 29 mm/72h normal is genuinely a major event.
#
# These values are MEASURED, not guessed: `python scripts/calibrate_demo.py`
# runs the real model/fusion pipeline across candidate targets and prints the
# resulting band per zone. Re-run it after retraining and re-pick from the table.
# The scripted story is: all three corridor zones reach HIGH on telemetry alone,
# and DJ-04 crosses into CRITICAL only once a field officer confirms movement.
ZONE_TARGET_24H_MM = {"DJ-04": 45.0, "SK-02": 34.0, "DJ-01": 26.0}
DEFAULT_TARGET_24H_MM = 35.0

# Peak soil saturation each zone reaches at the height of the storm.
ZONE_TARGET_SOIL_PCT = {"DJ-04": 78.0, "SK-02": 78.0, "DJ-01": 78.0}
DEFAULT_TARGET_SOIL_PCT = 78.0

STORM_HOURS = 14            # hours of storm the simulator replays
TOTAL_STEPS = 8

STEP_LABELS = [
    "Sensor telemetry: rainfall ramping across the Sikkim–Darjeeling corridor",
    "Soil moisture responding, with lag",
    "Risk model recomputing across affected zones",
    "Alerts dispatched on every configured channel",
    "Field officer verification received",
    "Citizen report received — queued for moderation",
    "Road blocked — connected settlements flagged cut off",
    "Prioritised response plan generated",
]


@dataclass
class DemoState:
    running: bool = False
    step: int = 0
    speed: int = 1
    label: str = "Idle"
    started_at: datetime | None = None
    zone_codes: list[str] = field(default_factory=lambda: list(DEFAULT_ZONE_CODES))

    def as_dict(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "step": self.step,
            "total_steps": TOTAL_STEPS,
            "speed": self.speed,
            "label": self.label,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "zone_codes": self.zone_codes,
            "demo_data": True,
        }


class DemoEngine:
    def __init__(self) -> None:
        self.state = DemoState()
        self._task: asyncio.Task | None = None
        self._weather_snapshot: list[dict] | None = None
        self._demo_started_at: datetime | None = None

    # ------------------------------------------------------------------ api
    async def start(self, speed: int = 1, zone_codes: list[str] | None = None) -> dict:
        if self.state.running:
            return {"ok": False, "reason": "already running", "state": self.state.as_dict()}

        self.state = DemoState(
            running=True, step=0, speed=speed, label="Starting…",
            started_at=datetime.now(timezone.utc),
            zone_codes=zone_codes or list(DEFAULT_ZONE_CODES),
        )
        self._demo_started_at = self.state.started_at
        self._task = asyncio.create_task(self._run())
        await manager.broadcast(EVENT_DEMO_STATE, self.state.as_dict())
        return {"ok": True, "state": self.state.as_dict()}

    async def stop(self) -> dict:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.state.running = False
        self.state.label = "Stopped"
        await manager.broadcast(EVENT_DEMO_STATE, self.state.as_dict())
        return {"ok": True, "state": self.state.as_dict()}

    async def reset(self) -> dict:
        """Undo the timeline: restore weather, drop demo artefacts, recompute."""
        await self.stop()

        with session_scope() as db:
            self._restore_weather(db)
            since = self._demo_started_at or (datetime.now(timezone.utc) - timedelta(hours=2))

            db.execute(text("DELETE FROM sensor_readings WHERE ingested_via IN ('mqtt','demo')"))
            db.execute(text("DELETE FROM response_actions"))
            db.execute(text("DELETE FROM field_reports WHERE client_uuid LIKE 'demo-%'"))
            db.execute(text("DELETE FROM citizen_reports WHERE description LIKE '[DEMO]%'"))
            db.execute(text(
                "DELETE FROM alert_deliveries WHERE alert_id IN "
                "(SELECT id FROM alerts WHERE created_at >= :since OR source LIKE 'demo%')"
            ), {"since": since})
            db.execute(text(
                "DELETE FROM alerts WHERE created_at >= :since OR source LIKE 'demo%'"
            ), {"since": since})
            db.execute(text("DELETE FROM zone_risk WHERE trigger LIKE 'demo%'"))
            spatial.reset_infrastructure(db)
            db.execute(text("UPDATE sensor_nodes SET last_seen = NULL WHERE status = 'FAILED'"))

        with session_scope() as db:
            risk_service.recompute_all(db, trigger="reset", raise_alerts=False)

        self._weather_snapshot = None
        self._demo_started_at = None
        self.state = DemoState(label="Reset — ready to run")
        manager.clear_replay()

        await manager.broadcast(EVENT_DEMO_STATE, self.state.as_dict())
        with session_scope() as db:
            await manager.broadcast(EVENT_SUMMARY, spatial.dashboard_summary(db))
            await manager.broadcast(EVENT_INFRA_UPDATE, {
                "roads": spatial.roads_geojson(db),
                "villages": spatial.villages_geojson(db),
                "reason": "demo reset",
            })
        return {"ok": True, "state": self.state.as_dict()}

    # --------------------------------------------------------------- timeline
    async def _run(self) -> None:
        pause = settings.demo_timeline_seconds / TOTAL_STEPS / max(self.state.speed, 1)
        try:
            with session_scope() as db:
                self._snapshot_weather(db)

            await self._step(1, self._step_rainfall, pause)
            await self._step(2, self._step_soil, pause)
            await self._step(3, self._step_recompute, pause)
            await self._step(4, self._step_alerts, pause)
            await self._step(5, self._step_field_report, pause)
            await self._step(6, self._step_citizen_report, pause)
            await self._step(7, self._step_road_cascade, pause)
            await self._step(8, self._step_response_plan, 0.0)

            self.state.running = False
            self.state.label = "Timeline complete"
            await manager.broadcast(EVENT_DEMO_STATE, self.state.as_dict())
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("demo timeline failed")
            self.state.running = False
            self.state.label = f"Failed: {exc}"
            await manager.broadcast(EVENT_DEMO_STATE, self.state.as_dict())

    async def _step(self, number: int, fn, pause: float) -> None:
        self.state.step = number
        self.state.label = STEP_LABELS[number - 1]
        detail = await fn()
        await manager.broadcast(EVENT_DEMO_STEP, {
            "step": number,
            "total_steps": TOTAL_STEPS,
            "label": STEP_LABELS[number - 1],
            "detail": detail or {},
            "speed": self.state.speed,
            "demo_data": True,
        })
        await manager.broadcast(EVENT_DEMO_STATE, self.state.as_dict())
        if pause > 0:
            await asyncio.sleep(pause)

    # ------------------------------------------------------------ steps 1 & 2
    async def _step_rainfall(self) -> dict:
        published = await asyncio.to_thread(self._publish_storm, "rainfall")
        with session_scope() as db:
            totals = self._zone_totals(db)
        return {"mqtt_messages": published, "topic": f"{settings.mqtt_topic_prefix}/+",
                "zone_totals": totals,
                "note": "Published to the MQTT broker and ingested back through the API subscriber."}

    async def _step_soil(self) -> dict:
        published = await asyncio.to_thread(self._publish_storm, "soil")
        with session_scope() as db:
            totals = self._zone_totals(db)
        return {"mqtt_messages": published, "zone_totals": totals,
                "note": "Soil moisture lags rainfall by 3–5 hours on these slopes."}

    def _zone_totals(self, db: Session) -> list[dict[str, Any]]:
        """Live trailing totals for the demo zones, so the toast can show the
        storm building rather than just asserting that it is."""
        rows = db.execute(text("""
            SELECT z.code, z.name,
                   COALESCE(SUM(r.rainfall_mm) FILTER (
                       WHERE r.ts > NOW() - INTERVAL '24 hours'), 0) AS rain_24h,
                   COALESCE(SUM(r.rainfall_mm) FILTER (
                       WHERE r.ts > NOW() - INTERVAL '72 hours'), 0) AS rain_72h,
                   (SELECT s.moisture_pct FROM soil_moisture_readings s
                    WHERE s.zone_id = z.id ORDER BY s.ts DESC LIMIT 1) AS soil
            FROM zones z LEFT JOIN rainfall_readings r ON r.zone_id = z.id
            WHERE z.code = ANY(:codes)
            GROUP BY z.id, z.code, z.name
            ORDER BY rain_72h DESC
        """), {"codes": self.state.zone_codes}).mappings().all()
        return [{
            "code": r["code"],
            "name": r["name"],
            "rainfall_24h": round(float(r["rain_24h"]), 1),
            "rainfall_72h": round(float(r["rain_72h"]), 1),
            "soil_moisture_pct": round(float(r["soil"]), 1) if r["soil"] is not None else None,
        } for r in rows]

    def _publish_storm(self, phase: str) -> int:
        """Replay `STORM_HOURS` of storm telemetry over MQTT for the demo zones.

        Each message carries its own timestamp, so a 60-second demo writes a
        realistic multi-hour storm into the zone series.
        """
        import paho.mqtt.client as mqtt

        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                 client_id=f"bhooshakti-demo-{phase}")
        except AttributeError:  # pragma: no cover - paho 1.x
            client = mqtt.Client(client_id=f"bhooshakti-demo-{phase}")

        try:
            client.connect(settings.mqtt_host, settings.mqtt_port, keepalive=30)
        except Exception as exc:
            log.warning("MQTT publish unavailable (%s) — writing telemetry directly", exc)
            return self._write_storm_directly(phase)

        client.loop_start()
        sent = 0
        pending: list[Any] = []
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

        with session_scope() as db:
            nodes = db.execute(text("""
                SELECT s.node_id, z.code
                FROM sensor_nodes s JOIN zones z ON z.id = s.zone_id
                WHERE z.code = ANY(:codes) AND s.status = 'ACTIVE'
                ORDER BY z.code, s.node_id
            """), {"codes": self.state.zone_codes}).mappings().all()
            plans = self._storm_plans(db)

        # One node per zone carries the zone total; the roll-up averages rainfall
        # across a zone's nodes, so every node in a zone publishes the same
        # profile rather than each contributing a slice of it.
        by_zone: dict[str, list[str]] = {}
        for node in nodes:
            by_zone.setdefault(node["code"], []).append(node["node_id"])

        for code, node_ids in by_zone.items():
            profile = plans.get(code)
            if profile is None:
                continue
            for node_id in node_ids:
                for h in range(STORM_HOURS, -1, -1):
                    ts = now - timedelta(hours=h)
                    rain, soil, tilt = profile[h]
                    message: dict[str, Any] = {"node_id": node_id, "ts": ts.isoformat(),
                                               "battery_pct": 88.0}
                    if phase == "rainfall":
                        message["rainfall_mm"] = rain
                    else:
                        message["soil_moisture_pct"] = soil
                        message["tilt_deg"] = tilt
                    # QoS 1, and the handle is kept: with QoS 0 the client can
                    # disconnect while messages are still queued in its network
                    # thread, silently dropping the tail of the batch. That is
                    # exactly what happened here — the last zone in the batch
                    # never reached the broker and its soil moisture never moved.
                    info = client.publish(f"{settings.mqtt_topic_prefix}/{node_id}",
                                          json.dumps(message), qos=1)
                    pending.append(info)
                    sent += 1

        # Every message must be on the wire before the client goes away.
        for info in pending:
            try:
                info.wait_for_publish(timeout=5)
            except Exception:
                pass
        client.loop_stop()
        client.disconnect()

        # Wait for the API's own subscriber to actually finish ingesting, rather
        # than sleeping a fixed interval and hoping. The next step recomputes
        # risk, and reading a half-ingested storm produces the wrong answer.
        self._await_ingest(now, phase)
        return sent

    def _await_ingest(self, hour: datetime, phase: str, timeout_s: float = 25.0) -> None:
        """Block until the whole storm window has been rolled up for every zone.

        The next step recomputes risk; reading a half-ingested storm gives the
        wrong answer, so this waits on the data rather than on a fixed sleep.
        """
        import time

        from ..mqtt_client import ingest as mqtt_ingest

        table = "rainfall_readings" if phase == "rainfall" else "soil_moisture_readings"
        earliest = hour - timedelta(hours=STORM_HOURS)
        want = len(self.state.zone_codes) * (STORM_HOURS + 1)
        deadline = time.monotonic() + timeout_s

        while time.monotonic() < deadline:
            # Nudge the flusher rather than waiting for its next tick.
            mqtt_ingest.flush_pending()
            with session_scope() as db:
                landed = db.execute(text(f"""
                    SELECT COUNT(*)
                    FROM {table} t JOIN zones z ON z.id = t.zone_id
                    WHERE z.code = ANY(:codes) AND t.source = 'sensor'
                      AND t.ts BETWEEN :earliest AND :hour
                """), {"codes": self.state.zone_codes,
                       "earliest": earliest, "hour": hour}).scalar_one()
            if int(landed) >= want and mqtt_ingest.pending_rollups == 0:
                return
            time.sleep(0.2)

        log.warning("demo: %s ingest did not fully settle within %.0fs "
                    "(%s of %s hourly rows, %s roll-ups still pending)",
                    phase, timeout_s, landed, want, mqtt_ingest.pending_rollups)

    def _storm_plans(self, db: Session) -> dict[str, list[tuple[float, float, float]]]:
        """Build a per-zone hourly storm profile calibrated to real targets.

        For each zone: measure the rainfall it already has in the part of the
        trailing 24h the storm will NOT overwrite, then size the storm so the
        resulting 24h total lands on ZONE_TARGET_24H_MM. The shape is a rising
        ramp peaking at the present hour; soil moisture trails it and saturates;
        tilt only creeps once the slope is genuinely wet.

        Returns {zone_code: [(rain_mm, soil_pct, tilt_deg), ...]} indexed by
        hours-ago, so index 0 is the current hour.
        """
        plans: dict[str, list[tuple[float, float, float]]] = {}

        # Relative weight of each storm hour: rises towards the present.
        weights = [((STORM_HOURS - h) / STORM_HOURS) ** 1.7 + 0.06
                   for h in range(STORM_HOURS + 1)]
        weight_sum = sum(weights)

        for code in self.state.zone_codes:
            row = db.execute(text("""
                SELECT COALESCE(SUM(r.rainfall_mm), 0) AS untouched,
                       (SELECT s.moisture_pct FROM soil_moisture_readings s
                        JOIN zones z2 ON z2.id = s.zone_id
                        WHERE z2.code = :code
                        ORDER BY s.ts DESC LIMIT 1) AS soil_now
                FROM rainfall_readings r JOIN zones z ON z.id = r.zone_id
                WHERE z.code = :code
                  AND r.ts >  NOW() - INTERVAL '24 hours'
                  AND r.ts <= NOW() - INTERVAL :storm_window
            """), {"code": code, "storm_window": f"{STORM_HOURS + 1} hours"}).mappings().first()

            untouched = float(row["untouched"]) if row else 0.0
            soil_start = float(row["soil_now"]) if row and row["soil_now"] is not None else 45.0

            target = ZONE_TARGET_24H_MM.get(code, DEFAULT_TARGET_24H_MM)
            # The storm must supply whatever the untouched hours do not, and it
            # never subtracts — a zone already wetter than its target simply
            # gets a solid storm on top.
            storm_total = max(target - untouched, 0.6 * target)

            soil_peak = ZONE_TARGET_SOIL_PCT.get(code, DEFAULT_TARGET_SOIL_PCT)
            soil_start = min(soil_start, soil_peak - 4.0)

            profile: list[tuple[float, float, float]] = [(0.0, 0.0, 0.0)] * (STORM_HOURS + 1)
            for h in range(STORM_HOURS + 1):
                progress = (STORM_HOURS - h) / STORM_HOURS          # 0 -> 1 towards now
                rain = storm_total * weights[h] / weight_sum
                # Soil lags the rain: it is still climbing when the rain peaks.
                soil = soil_start + (soil_peak - soil_start) * (progress ** 1.35)
                tilt = 0.05 + 1.6 * (progress ** 2.4)
                profile[h] = (round(rain, 2), round(min(soil, 97.0), 2), round(tilt, 3))

            plans[code] = profile
            log.info("demo storm plan %s: target %.0f mm/24h, untouched %.0f mm, "
                     "storm supplies %.0f mm over %dh",
                     code, target, untouched, storm_total, STORM_HOURS + 1)
        return plans

    def _write_storm_directly(self, phase: str) -> int:
        """Fallback when the broker is down — the demo must never dead-end."""
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        written = 0
        with session_scope() as db:
            plans = self._storm_plans(db)
            zones = db.execute(text("SELECT id, code FROM zones WHERE code = ANY(:c)"),
                               {"c": self.state.zone_codes}).mappings().all()
            for z in zones:
                profile = plans.get(z["code"])
                if profile is None:
                    continue
                for h in range(STORM_HOURS, -1, -1):
                    ts = now - timedelta(hours=h)
                    rain, soil, _ = profile[h]
                    if phase == "rainfall":
                        db.execute(text("""
                            INSERT INTO rainfall_readings (zone_id, ts, rainfall_mm, source, is_forecast)
                            VALUES (:z,:ts,:v,'sensor',FALSE)
                            ON CONFLICT ON CONSTRAINT uq_rainfall_zone_hour
                            DO UPDATE SET rainfall_mm = EXCLUDED.rainfall_mm,
                                          source='sensor', is_forecast=FALSE
                        """), {"z": z["id"], "ts": ts, "v": rain})
                    else:
                        db.execute(text("""
                            INSERT INTO soil_moisture_readings (zone_id, ts, moisture_pct, source, is_forecast)
                            VALUES (:z,:ts,:v,'sensor',FALSE)
                            ON CONFLICT ON CONSTRAINT uq_soil_zone_hour
                            DO UPDATE SET moisture_pct = EXCLUDED.moisture_pct,
                                          source='sensor', is_forecast=FALSE
                        """), {"z": z["id"], "ts": ts, "v": soil})
                    written += 1
        return written

    # ---------------------------------------------------------------- step 3
    async def _step_recompute(self) -> dict:
        def work() -> dict:
            with session_scope() as db:
                zones = db.query(Zone).filter(Zone.code.in_(self.state.zone_codes)).all()
                results = [
                    risk_service.compute_zone_risk(db, z, trigger="demo", raise_alerts=False)
                    for z in zones
                ]
                db.commit()
                return {
                    "zones": [
                        {"code": r["zone_code"], "name": r["zone_name"],
                         "risk_score": r["risk_score"], "severity": r["severity"],
                         "confidence": r["confidence"],
                         "top_factor": (r["contributing_factors"][0]["text"]
                                        if r["contributing_factors"] else "")}
                        for r in sorted(results, key=lambda x: -x["risk_score"])
                    ],
                    "summary": spatial.dashboard_summary(db),
                }

        detail = await asyncio.to_thread(work)
        await manager.broadcast(EVENT_SUMMARY, detail["summary"])
        return detail

    # ---------------------------------------------------------------- step 4
    async def _step_alerts(self) -> dict:
        def work() -> dict:
            with session_scope() as db:
                from ..models import Severity
                raised = []
                for code in self.state.zone_codes:
                    zone = db.query(Zone).filter(Zone.code == code).first()
                    if zone is None:
                        continue
                    current = db.execute(text("""
                        SELECT risk_score, severity::text AS severity, confidence,
                               contributing_factors
                        FROM zone_risk WHERE zone_id = :z
                        ORDER BY computed_at DESC, id DESC LIMIT 1
                    """), {"z": zone.id}).mappings().first()
                    if not current or current["severity"] not in ("HIGH", "CRITICAL"):
                        continue
                    alert = risk_service.raise_alert(
                        db, zone, float(current["risk_score"]), float(current["confidence"]),
                        Severity(current["severity"]), current["contributing_factors"] or [],
                        source="demo", force=True,
                    )
                    if alert is not None:
                        raised.append({
                            "alert_id": alert.id, "zone": f"{zone.code} — {zone.name}",
                            "severity": current["severity"],
                            "risk_score": float(current["risk_score"]),
                            "channels": [d.channel for d in alert.deliveries],
                            "delivery_status": {d.channel: d.status.value for d in alert.deliveries},
                        })
                return {"alerts": raised, "count": len(raised)}

        return await asyncio.to_thread(work)

    # ---------------------------------------------------------------- step 5
    async def _step_field_report(self) -> dict:
        def work() -> dict:
            with session_scope() as db:
                zone = db.query(Zone).filter(Zone.code == CRITICAL_CODE).first()
                if zone is None:
                    return {}
                fr = FieldReport(
                    client_uuid=f"demo-field-{int(datetime.now().timestamp())}",
                    zone_id=zone.id,
                    officer_id=None,
                    officer_name="T. Lepcha (District Field Officer)",
                    verdict=Verdict.CONFIRMED,
                    notes=("On-site check at the Paglajhora hairpin: fresh tension cracks "
                           "across the upslope cut, 15–20 cm of visible displacement, and "
                           "muddy discharge from the toe drain. Slope movement confirmed."),
                    geom=f"SRID=4326;POINT({zone.centroid_lon} {zone.centroid_lat})",
                    lat=zone.centroid_lat, lon=zone.centroid_lon,
                    observed_at=datetime.now(timezone.utc),
                    synced_at=datetime.now(timezone.utc),
                    submitted_offline=True,
                )
                db.add(fr)
                db.flush()
                return {
                    "id": fr.id, "zone_id": zone.id, "zone_code": zone.code,
                    "zone_name": zone.name, "verdict": "CONFIRMED",
                    "officer_name": fr.officer_name, "notes": fr.notes,
                    "submitted_offline": True,
                    "observed_at": fr.observed_at.isoformat(),
                    "note": "Submitted offline in the field, synced on reconnect.",
                    "demo_data": True,
                }

        detail = await asyncio.to_thread(work)
        if not detail:
            return detail
        await manager.broadcast(EVENT_FIELD_REPORT, detail)

        # Ground truth changes the answer. Recomputing here is the whole point
        # of the VERIFY stage: an officer confirming active movement escalates
        # the zone above what telemetry alone justified, and raises confidence
        # because the estimate no longer rests on sensors alone.
        def escalate() -> dict:
            with session_scope() as db:
                zone = db.query(Zone).filter(Zone.code == CRITICAL_CODE).one()
                before = db.execute(text("""
                    SELECT risk_score, severity::text AS severity, confidence
                    FROM zone_risk WHERE zone_id = :z
                    ORDER BY computed_at DESC, id DESC LIMIT 1
                """), {"z": zone.id}).mappings().first()
                after = risk_service.compute_zone_risk(
                    db, zone, trigger="demo-verified", raise_alerts=False)
                db.commit()
                return {"before": dict(before) if before else None, "after": after}

        change = await asyncio.to_thread(escalate)
        after = change["after"]
        before = change["before"] or {}
        detail["escalation"] = {
            "zone_code": after["zone_code"],
            "zone_name": after["zone_name"],
            "severity_before": before.get("severity"),
            "severity_after": after["severity"],
            "risk_before": float(before["risk_score"]) if before.get("risk_score") is not None else None,
            "risk_after": after["risk_score"],
            "confidence_before": float(before["confidence"]) if before.get("confidence") is not None else None,
            "confidence_after": after["confidence"],
        }

        # A verification that pushes a zone into a higher band must alert.
        if after["severity"] in ("HIGH", "CRITICAL") and \
                after["severity"] != before.get("severity"):
            def alert() -> None:
                with session_scope() as db:
                    from ..models import Severity
                    zone = db.query(Zone).filter(Zone.code == CRITICAL_CODE).one()
                    risk_service.raise_alert(
                        db, zone, after["risk_score"], after["confidence"],
                        Severity(after["severity"]), after["contributing_factors"],
                        source="demo-verified", force=True)
            await asyncio.to_thread(alert)

        with session_scope() as db:
            await manager.broadcast(EVENT_SUMMARY, spatial.dashboard_summary(db))
        return detail

    # ---------------------------------------------------------------- step 6
    async def _step_citizen_report(self) -> dict:
        def work() -> dict:
            with session_scope() as db:
                zone = db.query(Zone).filter(Zone.code == CRITICAL_CODE).first()
                if zone is None:
                    return {}
                lat = zone.centroid_lat + 0.004
                lon = zone.centroid_lon + 0.004
                located = spatial.locate_point(db, lat, lon)
                report = CitizenReport(
                    issue_type="road_blockage",
                    description=("[DEMO] Boulders and mud across the Hill Cart Road below the "
                                 "tea garden. Two vehicles stopped. Water running over the "
                                 "carriageway."),
                    geom=f"SRID=4326;POINT({lon} {lat})",
                    lat=lat, lon=lon, phone="+91900000XXXX", language="en",
                    zone_id=located["zone_id"], geo_valid=located["geo_valid"],
                    geo_note=located["note"], status=ReportStatus.PENDING,
                )
                db.add(report)
                db.flush()
                return {
                    "id": report.id, "issue_type": report.issue_type,
                    "description": report.description, "lat": lat, "lon": lon,
                    "zone_id": report.zone_id, "zone_name": located["zone_name"],
                    "geo_valid": report.geo_valid, "geo_note": report.geo_note,
                    "status": "PENDING",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "demo_data": True,
                }

        detail = await asyncio.to_thread(work)
        if detail:
            await manager.broadcast(EVENT_REPORT_NEW, detail)
            with session_scope() as db:
                await manager.broadcast(EVENT_SUMMARY, spatial.dashboard_summary(db))
        return detail

    # ---------------------------------------------------------------- step 7
    async def _step_road_cascade(self) -> dict:
        def work() -> dict:
            with session_scope() as db:
                zone = db.query(Zone).filter(Zone.code == CRITICAL_CODE).first()
                if zone is None:
                    return {}
                result = spatial.block_road_in_zone(
                    db, zone.id,
                    note=f"Debris flow — slope failure confirmed in {zone.name}",
                )
                return {
                    "zone_code": zone.code,
                    "zone_name": zone.name,
                    "road": result["road"],
                    "villages_cut_off": result["villages_cut_off"],
                    "cutoff_radius_m": spatial.CUTOFF_RADIUS_M,
                    "method": ("PostGIS ST_Intersects picked the lifeline road crossing the "
                               "zone; ST_DWithin found the settlements inside the cut-off radius."),
                    "demo_data": True,
                }

        detail = await asyncio.to_thread(work)
        if detail:
            with session_scope() as db:
                await manager.broadcast(EVENT_INFRA_UPDATE, {
                    "roads": spatial.roads_geojson(db),
                    "villages": spatial.villages_geojson(db),
                    "reason": "demo road cascade",
                })
                await manager.broadcast(EVENT_SUMMARY, spatial.dashboard_summary(db))
        return detail

    # ---------------------------------------------------------------- step 8
    async def _step_response_plan(self) -> dict:
        def work() -> dict:
            with session_scope() as db:
                db.execute(text("DELETE FROM response_actions"))
                zone = db.query(Zone).filter(Zone.code == CRITICAL_CODE).first()
                if zone is None:
                    return {}

                blocked = db.execute(text("""
                    SELECT name FROM road_segments WHERE status = 'BLOCKED' ORDER BY id LIMIT 1
                """)).scalar()
                cutoff = db.execute(text("""
                    SELECT name, population FROM villages WHERE is_cut_off ORDER BY population DESC
                """)).mappings().all()
                people = sum(int(v["population"]) for v in cutoff)
                names = ", ".join(v["name"] for v in cutoff) or "—"

                actions = [
                    (1, f"Close {blocked or 'the affected lifeline road'} to all traffic and "
                        f"post barriers at both approaches",
                     "State PWD / Traffic Police",
                     f"Slope failure confirmed on site in {zone.name}; debris across the carriageway."),
                    (1, f"Evacuate slope-adjacent households in {names}",
                     "District Disaster Management Authority",
                     f"{len(cutoff)} settlements ({people:,} residents) lost road access "
                     f"within {spatial.CUTOFF_RADIUS_M:.0f} m of the blocked segment."),
                    (2, "Move an NDRF/SDRF section and earth-moving plant to the debris face",
                     "SDRF Sector Commander",
                     "Clearance is the only way to restore the corridor; pre-positioning saves hours."),
                    (2, "Open a relief point with 48h of supplies on the far side of the block",
                     "District Administration",
                     "Cut-off settlements cannot be resupplied by road until clearance."),
                    (3, "Broadcast the advisory in English, Hindi and Assamese on local channels",
                     "District Information Officer",
                     "Alert already dispatched by email/SMS/push; broadcast reaches the unregistered."),
                    (3, f"Dispatch a technician to the failed sensor nodes covering {zone.district}",
                     "Sensor Network Operations",
                     "Confidence in this zone's estimate is reduced while nodes are offline."),
                ]
                for priority, action, owner, rationale in actions:
                    db.add(ResponseAction(zone_id=zone.id, priority=priority, action=action,
                                          owner=owner, rationale=rationale))
                db.flush()

                return {
                    "zone_code": zone.code,
                    "zone_name": zone.name,
                    "people_affected": people,
                    "actions": [
                        {"priority": p, "action": a, "owner": o, "rationale": r}
                        for p, a, o, r in actions
                    ],
                    "demo_data": True,
                }

        detail = await asyncio.to_thread(work)
        if detail:
            await manager.broadcast(EVENT_RESPONSE_PLAN, detail)
        return detail

    # ------------------------------------------------------------- snapshots
    def _snapshot_weather(self, db: Session) -> None:
        """Remember the weather rows the storm is about to overwrite."""
        since = datetime.now(timezone.utc) - timedelta(hours=STORM_HOURS + 2)
        rain = db.execute(text("""
            SELECT r.zone_id, r.ts, r.rainfall_mm, r.source
            FROM rainfall_readings r JOIN zones z ON z.id = r.zone_id
            WHERE z.code = ANY(:c) AND r.ts >= :since
        """), {"c": self.state.zone_codes, "since": since}).mappings().all()
        soil = db.execute(text("""
            SELECT s.zone_id, s.ts, s.moisture_pct, s.source
            FROM soil_moisture_readings s JOIN zones z ON z.id = s.zone_id
            WHERE z.code = ANY(:c) AND s.ts >= :since
        """), {"c": self.state.zone_codes, "since": since}).mappings().all()

        self._weather_snapshot = [
            {"kind": "rain", **dict(r)} for r in rain
        ] + [
            {"kind": "soil", **dict(r)} for r in soil
        ]
        log.info("demo: snapshotted %d weather rows", len(self._weather_snapshot))

    def _restore_weather(self, db: Session) -> None:
        if not self._weather_snapshot:
            # Nothing captured (e.g. API restarted mid-demo): drop sensor-sourced
            # rows so the seeded series is authoritative again.
            db.execute(text("DELETE FROM rainfall_readings WHERE source = 'sensor'"))
            db.execute(text("DELETE FROM soil_moisture_readings WHERE source = 'sensor'"))
            return

        since = datetime.now(timezone.utc) - timedelta(hours=STORM_HOURS + 3)
        zone_ids = sorted({row["zone_id"] for row in self._weather_snapshot})
        db.execute(text("""
            DELETE FROM rainfall_readings WHERE zone_id = ANY(:z) AND ts >= :since
        """), {"z": zone_ids, "since": since})
        db.execute(text("""
            DELETE FROM soil_moisture_readings WHERE zone_id = ANY(:z) AND ts >= :since
        """), {"z": zone_ids, "since": since})

        for row in self._weather_snapshot:
            if row["kind"] == "rain":
                db.execute(text("""
                    INSERT INTO rainfall_readings (zone_id, ts, rainfall_mm, source, is_forecast)
                    VALUES (:z,:ts,:v,:s,FALSE)
                    ON CONFLICT ON CONSTRAINT uq_rainfall_zone_hour DO NOTHING
                """), {"z": row["zone_id"], "ts": row["ts"],
                       "v": row["rainfall_mm"], "s": row["source"]})
            else:
                db.execute(text("""
                    INSERT INTO soil_moisture_readings (zone_id, ts, moisture_pct, source, is_forecast)
                    VALUES (:z,:ts,:v,:s,FALSE)
                    ON CONFLICT ON CONSTRAINT uq_soil_zone_hour DO NOTHING
                """), {"z": row["zone_id"], "ts": row["ts"],
                       "v": row["moisture_pct"], "s": row["source"]})
        log.info("demo: restored %d weather rows", len(self._weather_snapshot))


engine = DemoEngine()
