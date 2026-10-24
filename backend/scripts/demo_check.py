#!/usr/bin/env python3
"""Pre-judging checklist: is everything the demo needs actually up?

    make demo-check

Asks the running API (not the database directly) wherever it can, because
the API is what the judges' screen talks to. Prints a green/red line per
check and exits non-zero if anything the demo cannot run without is red.
SMTP and a live sensor are reported but optional: the demo labels email
"SIMULATED" honestly when SMTP is unset.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402

API = "http://localhost:8000"
GREEN, RED, AMBER, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"
if not sys.stdout.isatty():
    GREEN = RED = AMBER = DIM = RESET = ""


def get(url: str, timeout: float = 6.0):
    # Some tile CDNs refuse Python's default user agent.
    req = urllib.request.Request(url, headers={"User-Agent": "bhooshakti-demo-check/1.0"})
    return urllib.request.urlopen(req, timeout=timeout)


def fetch(url: str, timeout: float = 6.0):
    with get(url, timeout) as r:
        return json.loads(r.read().decode())


def line(ok: bool | None, name: str, detail: str) -> None:
    mark = f"{GREEN}[ OK ]{RESET}" if ok else f"{AMBER}[WARN]{RESET}" if ok is None else f"{RED}[FAIL]{RESET}"
    print(f"  {mark} {name:<22} {DIM}{detail}{RESET}")


def main() -> int:
    print("BHOOSHAKTI AI — demo check")
    failed = 0

    try:
        health = fetch(f"{API}/health")
        line(True, "API", f"{API} responding")
    except Exception as e:                                   # noqa: BLE001
        line(False, "API", f"not reachable at {API} ({e.__class__.__name__}) — run `make api`")
        health = None
        failed += 1

    if health:
        db = health.get("database", {})
        zones = db.get("zones") or 0
        ok = bool(db.get("connected")) and zones > 0
        line(ok, "Database seeded", f"{zones} zones" if ok else "no zones — run `make seed`")
        failed += not ok

        model = health.get("model", {})
        ok = bool(model.get("loaded"))
        line(ok, "Model loaded", model.get("version") or model.get("error") or "not loaded — run `make train`")
        failed += not ok

        mqtt = health.get("mqtt", {})
        ok = bool(mqtt.get("connected"))
        line(ok, "MQTT broker", f"connected, topic {mqtt.get('topic')}" if ok
             else "not connected — `brew services start mosquitto`")
        failed += not ok

        esc = health.get("escalation", {})
        ok = bool(esc.get("enabled")) and not esc.get("last_error")
        line(ok, "Escalation ladder", f"ticking every {esc.get('interval_s')} s" if ok
             else f"{esc.get('last_error') or 'disabled'}")
        failed += not ok

        try:
            ev = fetch(f"{API}/replay/summary")
            n = ev.get("summary", {}).get("events", 0)
            line(n > 0, "Backtest results", f"{n} held-out events" if n else "missing — run `make backtest`")
            failed += not n
        except Exception:                                    # noqa: BLE001
            line(False, "Backtest results", "missing — run `make backtest`")
            failed += 1

    try:
        fetch("https://api.open-meteo.com/v1/forecast?latitude=26.85&longitude=88.33&hourly=rain&forecast_days=1")
        line(True, "Open-Meteo", "reachable (live weather + ERA5)")
    except Exception as e:                                   # noqa: BLE001
        line(False, "Open-Meteo", f"unreachable ({e.__class__.__name__}) — the cached weather still works")
        failed += 1

    for name, url in (("Map tiles", "https://tiles.openfreemap.org/styles/liberty"),
                      ("Terrain tiles", "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/0/0/0.png")):
        try:
            get(url).close()
            line(True, name, url.split("/")[2])
        except Exception as e:                               # noqa: BLE001
            line(None, name, f"unreachable ({e.__class__.__name__}) — use the 2D / low-data map")

    missing = [k for k, v in (("SMTP_HOST", settings.smtp_host), ("SMTP_USER", settings.smtp_user),
                              ("SMTP_PASSWORD", settings.smtp_password)) if not v.strip()]
    if missing:
        line(None, "SMTP (email)", f"not configured — set {', '.join(missing)} in .env (email shows SIMULATED)")
    else:
        line(True, "SMTP (email)", f"{settings.smtp_host} as {settings.smtp_user} → {settings.e2e_test_email}")

    print()
    if failed:
        print(f"  {RED}{failed} check(s) failed — fix them before judging.{RESET}")
        return 1
    print(f"  {GREEN}Ready for the demo.{RESET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
