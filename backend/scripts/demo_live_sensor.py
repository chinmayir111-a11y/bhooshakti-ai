#!/usr/bin/env python3
"""Keyboard-controlled FAKE sensor node, for demos with no ESP32 to hand.

    make demo-live-sensor          (or: python scripts/demo_live_sensor.py)

    T  tilt the "board" +1.5°       W  wet the soil +12%
    R  a burst of rain (8 mm)       0  reset to calm
    Q  quit

Publishes as node KB-01, which the database registers as source='simulated',
so the dashboard labels it SIMULATED and it can never show the hardware LIVE
dot. Same MQTT topic and JSON schema as the real ESP32 (hardware/esp32_node).
"""
from __future__ import annotations

import json
import select
import sys
import termios
import time
import tty
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import paho.mqtt.client as mqtt  # noqa: E402

from app.config import settings  # noqa: E402

NODE_ID = "KB-01"
EVERY_S = 2.0


def main() -> int:
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="bhooshakti-kb-node")
    except AttributeError:
        client = mqtt.Client(client_id="bhooshakti-kb-node")
    try:
        client.connect(settings.mqtt_host, settings.mqtt_port, keepalive=30)
    except Exception as exc:
        print(f"Cannot reach MQTT at {settings.mqtt_host}:{settings.mqtt_port} — {exc}")
        return 1
    client.loop_start()

    tilt, soil, rain = 0.05, 55.0, 0.0
    print("=" * 70)
    print(f" FAKE hardware node {NODE_ID} — SIMULATED (keyboard-driven)")
    print(f" topic {settings.mqtt_topic_prefix}/{NODE_ID}")
    print("  T tilt +1.5°   W wet soil +12%   R rain burst   0 reset   Q quit")
    print("=" * 70)

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    next_pub = 0.0
    try:
        while True:
            if select.select([sys.stdin], [], [], 0.1)[0]:
                k = sys.stdin.read(1).lower()
                if k == "q":
                    break
                if k == "t":
                    tilt += 1.5
                elif k == "w":
                    soil = min(99.0, soil + 12.0)
                elif k == "r":
                    rain += 8.0
                elif k == "0":
                    tilt, soil, rain = 0.05, 55.0, 0.0
                next_pub = 0.0                      # publish the change at once
            if time.monotonic() >= next_pub:
                reading = {"node_id": NODE_ID, "ts": datetime.now(timezone.utc).isoformat(),
                           "rainfall_mm": round(rain, 2), "soil_moisture_pct": round(soil, 1),
                           "tilt_deg": round(tilt, 3), "battery_pct": 100.0, "source": "simulated"}
                client.publish(f"{settings.mqtt_topic_prefix}/{NODE_ID}", json.dumps(reading), qos=0)
                print(f"\r  SIMULATED  tilt {tilt:5.2f}°   soil {soil:5.1f}%   rain {rain:4.1f} mm   ",
                      end="", flush=True)
                rain = 0.0                          # a burst is one reading's worth
                next_pub = time.monotonic() + EVERY_S
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        client.loop_stop()
        client.disconnect()
        print("\n  stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
