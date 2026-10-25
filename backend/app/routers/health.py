"""System health for officers: every dependency, green / amber / red, with the
last time it worked. The control room shows a banner when a critical one is red."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import Principal, require_roles

router = APIRouter(prefix="/health", tags=["meta"])
CHECKS: list = []        # extra checks other modules register (e.g. the earthquake feed)


def _age(ts: datetime | None, now: datetime) -> float | None:
    return (now - ts).total_seconds() / 3600.0 if ts else None


def _iso(ts: datetime | None) -> str | None:
    return ts.isoformat() if ts else None


def checks(db: Session) -> list[dict[str, Any]]:
    from ..mqtt_client import ingest
    from ..services import escalation, risk_service, weather_job

    now = datetime.now(timezone.utc)
    out: list[dict[str, Any]] = [{"key": "api", "label": "API", "status": "green", "critical": True,
                                  "detail": "Responding", "last_ok": _iso(now)}]
    try:
        zones = db.execute(text("SELECT COUNT(*) FROM zones")).scalar_one()
        out.append({"key": "database", "label": "Database (PostGIS)", "critical": True,
                    "status": "green" if zones else "red",
                    "detail": f"{zones} zones" if zones else "No zones — run make seed", "last_ok": _iso(now)})
    except Exception as exc:
        db.rollback()
        out.append({"key": "database", "label": "Database (PostGIS)", "critical": True, "status": "red",
                    "detail": f"{type(exc).__name__}", "last_ok": None})

    out.append({"key": "mqtt", "label": "MQTT broker (sensors, siren)", "critical": False,
                "status": "green" if ingest.connected else ("amber" if not settings.mqtt_enabled else "red"),
                "detail": f"{ingest.messages_seen} messages" if ingest.connected
                          else ("Disabled" if not settings.mqtt_enabled else "Not connected — sirens cannot sound"),
                "last_ok": None})

    last = db.execute(text("SELECT MAX(fetched_at) FROM weather_fetches WHERE ok")).scalar()
    age = _age(last, now)
    out.append({"key": "weather", "label": "Weather (Open-Meteo)", "critical": True,
                "status": "green" if age is not None and age < 1 else "amber" if age is not None and age < 3 else "red",
                "detail": (f"Last fetch {age:.1f} h ago" if age is not None else "Never fetched")
                          + (f" · job error: {weather_job.scheduler.last_error}" if weather_job.scheduler.last_error else ""),
                "last_ok": _iso(last)})

    sched = escalation.scheduler
    alive = bool(sched._thread and sched._thread.is_alive()) if settings.escalation_enabled else False
    out.append({"key": "escalation", "label": "Escalation ladder", "critical": True,
                "status": "red" if settings.escalation_enabled and not alive else ("amber" if sched.last_error else "green"),
                "detail": f"{sched.ticks} ticks" + (f" · {sched.last_error}" if sched.last_error else ""), "last_ok": None})

    out.append({"key": "model", "label": "Risk model", "critical": False,
                "status": "green" if risk_service.registry.loaded else "amber",
                "detail": risk_service.registry.version if risk_service.registry.loaded
                          else "Not loaded — rule-based fallback is scoring", "last_ok": None})

    for ch, label, live, sim_note in (
        ("email", "Email (SMTP)", settings.email_configured, "Simulated — SMTP_HOST not set"),
        ("sms", "SMS gateway", settings.sms_provider.lower() not in ("", "stub"), "Simulated — SMS_PROVIDER=stub"),
        ("voice", "Voice calls", settings.voice_provider.lower() not in ("", "stub"), "Simulated — no voice provider"),
    ):
        row = db.execute(text("""
            SELECT MAX(sent_at) FILTER (WHERE status = 'SENT') AS ok, MAX(sent_at) FILTER (WHERE status = 'FAILED') AS bad
            FROM alert_deliveries WHERE channel = :c
        """), {"c": ch}).mappings().first()
        failing = row["bad"] is not None and (row["ok"] is None or row["bad"] > row["ok"])
        out.append({"key": ch, "label": label, "critical": False,
                    "status": "red" if failing else ("green" if live else "amber"),
                    "detail": "Last delivery FAILED — use Retry on the alert" if failing else ("Live" if live else sim_note),
                    "last_ok": _iso(row["ok"])})

    nasa = bool(getattr(settings, "earthdata_user", "")) or _env_has("EARTHDATA_USER")
    out.append({"key": "nasa", "label": "NASA Earthdata (IMERG)", "critical": False, "status": "amber",
                "detail": "Login set; satellite rain not used live yet" if nasa else "No login set", "last_ok": None})
    for extra in CHECKS:
        try:
            out.append(extra(db))
        except Exception as exc:
            out.append({"key": getattr(extra, "__name__", "check"), "label": "check", "status": "red",
                        "critical": False, "detail": str(exc), "last_ok": None})
    return out


def _env_has(name: str) -> bool:
    try:
        from pathlib import Path
        env = Path(__file__).resolve().parents[3] / ".env"
        return any(line.startswith(f"{name}=") and line.strip() != f"{name}=" for line in env.read_text().splitlines())
    except OSError:
        return False


@router.get("/status", summary="Every dependency, green / amber / red (officers)")
def status(db: Session = Depends(get_db), _: Principal = Depends(require_roles("authority", "field_officer"))) -> dict:
    rows = checks(db)
    red = [r["label"] for r in rows if r["critical"] and r["status"] == "red"]
    return {"checked_at": datetime.now(timezone.utc).isoformat(), "checks": rows, "critical_red": red}


@router.get("/quakes", summary="Recent M4.5+ earthquakes around the North-East (USGS)")
def recent_quakes(days: int = 7, db: Session = Depends(get_db)) -> dict:
    from ..services import quakes
    return {"quakes": quakes.recent(db, min(max(days, 1), 30)), "feed": quakes.health_check(db), "source": "USGS"}


def _register() -> None:
    from ..services import quakes
    CHECKS.append(quakes.health_check)


_register()
