"""MQTT ingest for simulated sensor telemetry.

`scripts/sensor_simulator.py` publishes JSON on

    bhooshakti/sensors/{node_id}

and this subscriber persists each reading, rolls it up into the zone's
canonical hourly rainfall / soil-moisture series (so the risk engine sees live
telemetry the same way it sees history), and pushes it to the dashboard.

paho runs its network loop on its own thread, so every broadcast from here
goes through `manager.publish_threadsafe`.

Ingest is deliberately split in two:

  * the MQTT callback does one cheap INSERT and marks (zone, hour) dirty;
  * a background flusher recomputes the hourly roll-up for dirty pairs.

Doing the roll-up inline per message meant a full aggregate query on paho's
single callback thread for every reading. A demo burst of 150 messages then
took longer to drain than the demo itself ran, so risk was recomputed against a
half-ingested storm and one zone silently kept its pre-storm soil moisture.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from sqlalchemy import text

from .config import settings
from .db import session_scope
from .models import SensorNode, SensorReading, SensorStatus
from .ws import EVENT_SENSOR_READING, manager

log = logging.getLogger("bhooshakti.mqtt")


class SensorIngest:
    def __init__(self) -> None:
        self.client: mqtt.Client | None = None
        self.connected = False
        self.messages_seen = 0
        self._node_cache: dict[str, tuple[int, str]] = {}   # node_id -> (zone_id, status)
        # (zone_id, hour) pairs whose roll-up is stale, and the worker that
        # drains them. A set collapses repeated readings in the same hour into
        # a single recomputation.
        self._dirty: set[tuple[int, datetime]] = set()
        self._dirty_lock = threading.Lock()
        self._flusher: threading.Thread | None = None
        self._stop = threading.Event()
        self.rollups_done = 0

    # ------------------------------------------------------------------ life
    def start(self) -> None:
        if not settings.mqtt_enabled:
            log.info("MQTT ingest disabled (MQTT_ENABLED=false)")
            return
        try:
            self.client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                client_id="bhooshakti-api-ingest",
                clean_session=True,
            )
        except AttributeError:  # pragma: no cover - paho 1.x
            self.client = mqtt.Client(client_id="bhooshakti-api-ingest")

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

        try:
            self._stop.clear()
            self._flusher = threading.Thread(target=self._flush_loop, name="mqtt-rollup",
                                             daemon=True)
            self._flusher.start()
            self.client.connect_async(settings.mqtt_host, settings.mqtt_port, keepalive=45)
            self.client.loop_start()
            log.info("MQTT ingest connecting to %s:%s", settings.mqtt_host, settings.mqtt_port)
        except Exception as exc:
            log.warning("MQTT unavailable (%s) — the API runs without live telemetry", exc)

    def stop(self) -> None:
        self._stop.set()
        if self._flusher is not None and self._flusher.is_alive():
            self._flusher.join(timeout=3)
        if self.client is not None:
            try:
                self.client.loop_stop()
                self.client.disconnect()
            except Exception:
                pass
        self.connected = False

    # -------------------------------------------------------------- callbacks
    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        ok = getattr(reason_code, "is_failure", None)
        failed = ok if isinstance(ok, bool) else (int(reason_code) != 0)
        if failed:
            log.warning("MQTT connect failed: %s", reason_code)
            return
        self.connected = True
        topic = f"{settings.mqtt_topic_prefix}/+"
        client.subscribe(topic, qos=0)
        log.info("MQTT connected — subscribed to %s", topic)

    def _on_disconnect(self, client, userdata, *args, **kwargs):
        self.connected = False
        log.info("MQTT disconnected")

    def _on_message(self, client, userdata, msg):
        try:
            reading = json.loads(msg.payload.decode("utf-8"))
        except Exception:
            log.warning("unparseable MQTT payload on %s", msg.topic)
            return
        node_id = reading.get("node_id") or msg.topic.rsplit("/", 1)[-1]
        try:
            self.ingest(node_id, reading)
        except Exception:
            log.exception("failed to ingest reading from %s", node_id)

    # ----------------------------------------------------------------- ingest
    def ingest(self, node_id: str, reading: dict) -> None:
        """Persist one reading and roll it into the zone's hourly series."""
        self.messages_seen += 1

        ts_raw = reading.get("ts")
        try:
            ts = datetime.fromisoformat(ts_raw) if ts_raw else datetime.now(timezone.utc)
        except ValueError:
            ts = datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        with session_scope() as db:
            node = db.query(SensorNode).filter(SensorNode.node_id == node_id).first()
            if node is None:
                log.warning("telemetry from unknown node %s — ignored", node_id)
                return

            # A node marked FAILED must not silently start feeding the model
            # again; that is exactly the fallback case the demo shows.
            if node.status is SensorStatus.FAILED:
                log.debug("ignoring telemetry from FAILED node %s", node_id)
                return

            rainfall = reading.get("rainfall_mm")
            soil = reading.get("soil_moisture_pct")
            tilt = reading.get("tilt_deg")
            battery = reading.get("battery_pct")

            db.add(SensorReading(
                node_id=node_id, zone_id=node.zone_id, ts=ts,
                rainfall_mm=rainfall, soil_moisture_pct=soil,
                tilt_deg=tilt, battery_pct=battery, ingested_via="mqtt",
            ))
            node.last_seen = ts
            if battery is not None:
                node.battery_pct = float(battery)

            with self._dirty_lock:
                self._dirty.add((node.zone_id, ts.replace(minute=0, second=0, microsecond=0)))

            manager.publish_threadsafe(EVENT_SENSOR_READING, {
                "node_id": node_id,
                "zone_id": node.zone_id,
                "ts": ts.isoformat(),
                "rainfall_mm": rainfall,
                "soil_moisture_pct": soil,
                "tilt_deg": tilt,
                "battery_pct": battery,
                "demo_data": True,
            })

    # ---------------------------------------------------------------- flush
    def _flush_loop(self) -> None:
        """Drain dirty (zone, hour) pairs a few times a second."""
        while not self._stop.is_set():
            self.flush_pending()
            self._stop.wait(0.4)
        self.flush_pending()

    def flush_pending(self) -> int:
        """Recompute the roll-up for every dirty (zone, hour). Returns the count."""
        with self._dirty_lock:
            if not self._dirty:
                return 0
            batch = sorted(self._dirty)
            self._dirty.clear()

        try:
            with session_scope() as db:
                for zone_id, hour in batch:
                    self._rollup_hour(db, zone_id, hour)
        except Exception:
            log.exception("roll-up flush failed — requeueing %d pair(s)", len(batch))
            with self._dirty_lock:
                self._dirty.update(batch)
            return 0

        self.rollups_done += len(batch)
        return len(batch)

    @property
    def pending_rollups(self) -> int:
        with self._dirty_lock:
            return len(self._dirty)

    @staticmethod
    def _rollup_hour(db, zone_id: int, ts: datetime) -> None:
        """Aggregate the hour's ACTIVE-node telemetry into the zone series.

        Rainfall is summed per node then averaged across nodes (a zone total,
        not a double count); soil moisture is a plain mean. Written as an
        upsert on (zone_id, hour) so repeated readings within the hour refine
        the same row instead of appending duplicates.
        """
        hour = ts.replace(minute=0, second=0, microsecond=0)
        agg = db.execute(text("""
            SELECT AVG(per_node.rain) AS rain, AVG(per_node.soil) AS soil
            FROM (
                SELECT sr.node_id,
                       SUM(sr.rainfall_mm)      AS rain,
                       AVG(sr.soil_moisture_pct) AS soil
                FROM sensor_readings sr
                JOIN sensor_nodes n ON n.node_id = sr.node_id
                WHERE sr.zone_id = :z
                  AND sr.ts >= :hour AND sr.ts < :hour + INTERVAL '1 hour'
                  AND n.status = 'ACTIVE'
                GROUP BY sr.node_id
            ) per_node
        """), {"z": zone_id, "hour": hour}).mappings().one()

        if agg["rain"] is not None:
            db.execute(text("""
                INSERT INTO rainfall_readings (zone_id, ts, rainfall_mm, source, is_forecast)
                VALUES (:z, :ts, :v, 'sensor', FALSE)
                ON CONFLICT ON CONSTRAINT uq_rainfall_zone_hour
                DO UPDATE SET rainfall_mm = EXCLUDED.rainfall_mm,
                              source = 'sensor', is_forecast = FALSE
            """), {"z": zone_id, "ts": hour, "v": float(agg["rain"])})

        if agg["soil"] is not None:
            db.execute(text("""
                INSERT INTO soil_moisture_readings (zone_id, ts, moisture_pct, source, is_forecast)
                VALUES (:z, :ts, :v, 'sensor', FALSE)
                ON CONFLICT ON CONSTRAINT uq_soil_zone_hour
                DO UPDATE SET moisture_pct = EXCLUDED.moisture_pct,
                              source = 'sensor', is_forecast = FALSE
            """), {"z": zone_id, "ts": hour, "v": float(agg["soil"])})


ingest = SensorIngest()
