#!/usr/bin/env python3
"""Simulated IoT field nodes publishing over MQTT.

    python scripts/sensor_simulator.py                 # all ACTIVE nodes, 5s cadence
    python scripts/sensor_simulator.py --zones SK-02 DJ-04
    python scripts/sensor_simulator.py --storm --speed 8

Publishes JSON to `bhooshakti/sensors/{node_id}`:

    {"node_id":"DJ-04-N01","ts":"...","rainfall_mm":4.2,
     "soil_moisture_pct":78.4,"tilt_deg":0.31,"battery_pct":91.0}

Nodes marked FAILED in the database publish nothing at all — that silence is
what the dashboard's fallback logic and the reduced confidence score respond to.

This is a synthetic telemetry generator. No physical sensor exists.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import paho.mqtt.client as mqtt  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import session_scope  # noqa: E402

_running = True


def _stop(*_args) -> None:
    global _running
    _running = False
    print("\n  stopping simulator …")


class NodeState:
    """Per-node state so successive readings evolve instead of jittering."""

    def __init__(self, node_id: str, zone_code: str, zone_name: str,
                 slope_deg: float, rng: random.Random) -> None:
        self.node_id = node_id
        self.zone_code = zone_code
        self.zone_name = zone_name
        self.slope_deg = slope_deg
        self.rng = rng
        self.soil = rng.uniform(38.0, 62.0)
        self.tilt = rng.uniform(0.01, 0.15)
        self.battery = rng.uniform(62.0, 100.0)
        self.rain_intensity = rng.uniform(0.0, 1.5)

    def tick(self, storm: float) -> dict:
        """Advance one reading. `storm` is 0-1 additional forcing."""
        # Rainfall wanders, with the storm term pushing it up.
        drift = self.rng.gauss(0.0, 0.8) + 6.0 * storm
        self.rain_intensity = max(0.0, self.rain_intensity * 0.82 + drift * 0.35)
        rainfall = round(self.rain_intensity, 2)

        # Soil moisture: infiltration up, drainage down (faster on steep slopes).
        drainage = 0.30 + 0.010 * self.slope_deg
        headroom = max(0.0, (97.0 - self.soil) / 97.0)
        self.soil += rainfall * 0.9 * (0.35 + 0.65 * headroom) - drainage
        self.soil = min(max(self.soil + self.rng.gauss(0, 0.2), 8.0), 97.0)

        # Tilt only creeps once the slope is genuinely wet.
        if self.soil > 80.0:
            self.tilt += max(0.0, self.rng.gauss(0.02, 0.02)) * (1.0 + 2.0 * storm)
        else:
            self.tilt = max(0.0, self.tilt - 0.004)

        self.battery = max(5.0, self.battery - self.rng.uniform(0.0, 0.02))

        return {
            "node_id": self.node_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "rainfall_mm": rainfall,
            "soil_moisture_pct": round(self.soil, 2),
            "tilt_deg": round(self.tilt, 3),
            "battery_pct": round(self.battery, 1),
        }


def load_nodes(zone_codes: list[str] | None, rng: random.Random) -> list[NodeState]:
    with session_scope() as db:
        sql = """
            SELECT s.node_id, z.code, z.name, z.slope_deg
            FROM sensor_nodes s JOIN zones z ON z.id = s.zone_id
            WHERE s.status = 'ACTIVE'
        """
        params: dict = {}
        if zone_codes:
            sql += " AND z.code = ANY(:codes)"
            params["codes"] = zone_codes
        sql += " ORDER BY s.node_id"
        rows = db.execute(text(sql), params).mappings().all()

        failed = int(db.execute(text(
            "SELECT COUNT(*) FROM sensor_nodes WHERE status <> 'ACTIVE'")).scalar_one())

    print(f"  {len(rows)} ACTIVE nodes will publish; {failed} node(s) are FAILED/MAINTENANCE "
          f"and stay silent by design")
    return [NodeState(r["node_id"], r["code"], r["name"], float(r["slope_deg"]), rng)
            for r in rows]


def main() -> int:
    ap = argparse.ArgumentParser(description="BHOOSHAKTI AI simulated sensor network")
    ap.add_argument("--zones", nargs="*", help="limit to these zone codes")
    ap.add_argument("--interval", type=float, default=5.0, help="seconds between rounds")
    ap.add_argument("--storm", action="store_true",
                    help="ramp a monsoon storm instead of publishing fair weather")
    ap.add_argument("--speed", type=float, default=1.0, help="storm ramp multiplier")
    ap.add_argument("--rounds", type=int, default=0, help="stop after N rounds (0 = forever)")
    ap.add_argument("--seed", type=int, default=settings.seed_random_state)
    args = ap.parse_args()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    rng = random.Random(args.seed)

    print("=" * 74)
    print("BHOOSHAKTI AI — simulated sensor network   [SYNTHETIC TELEMETRY]")
    print("=" * 74)

    nodes = load_nodes(args.zones, rng)
    if not nodes:
        print("  No active nodes found. Run `python scripts/seed.py --reset` first.")
        return 1

    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="bhooshakti-simulator")
    except AttributeError:  # paho 1.x
        client = mqtt.Client(client_id="bhooshakti-simulator")

    try:
        client.connect(settings.mqtt_host, settings.mqtt_port, keepalive=45)
    except Exception as exc:
        print(f"\n  Cannot reach the MQTT broker at "
              f"{settings.mqtt_host}:{settings.mqtt_port} — {exc}")
        print("  Start it with:  brew services start mosquitto   (or docker compose up mqtt)")
        return 1

    client.loop_start()
    print(f"  publishing to {settings.mqtt_topic_prefix}/{{node_id}} "
          f"on {settings.mqtt_host}:{settings.mqtt_port}")
    print(f"  cadence: every {args.interval:g}s"
          + ("   mode: STORM RAMP" if args.storm else "   mode: fair weather"))
    print("  Ctrl-C to stop.\n")

    round_no = 0
    published = 0
    while _running and (args.rounds == 0 or round_no < args.rounds):
        round_no += 1
        # Storm forcing climbs from 0 to 1 over ~40 rounds, then holds.
        storm = min(1.0, (round_no * args.speed) / 40.0) if args.storm else 0.0
        # A little diurnal shape even in fair weather.
        storm += 0.06 * max(0.0, math.sin(round_no / 9.0))

        for node in nodes:
            reading = node.tick(storm)
            client.publish(f"{settings.mqtt_topic_prefix}/{node.node_id}",
                           json.dumps(reading), qos=0)
            published += 1

        wettest = max(nodes, key=lambda n: n.soil)
        print(f"  round {round_no:>4}  published {len(nodes):>3} readings "
              f"(total {published:>6})   storm={storm:0.2f}   "
              f"wettest: {wettest.node_id} soil {wettest.soil:0.1f}% tilt {wettest.tilt:0.2f}°")

        deadline = time.monotonic() + args.interval
        while _running and time.monotonic() < deadline:
            time.sleep(0.1)

    client.loop_stop()
    client.disconnect()
    print(f"\n  stopped after {round_no} rounds, {published} readings published.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
