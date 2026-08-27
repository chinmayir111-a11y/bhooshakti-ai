"""BHOOSHAKTI AI — API entrypoint.

    uvicorn app.main:app --reload

Startup binds the event loop for thread-safe WebSocket fan-out, loads the
trained susceptibility model, and connects the MQTT ingest subscriber.

    OpenAPI docs: http://localhost:8000/docs
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import session_scope
from .mqtt_client import ingest
from .routers import (
    alerts,
    audit,
    auth,
    demo,
    field,
    infrastructure,
    reports,
    risk,
    weather,
    zones,
)
from .services import risk_service, spatial
from .ws import manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)-22s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bhooshakti")

DESCRIPTION = """
AI-powered landslide early warning and risk monitoring for North-East India.

**Smart India Hackathon 2026 · Problem Statement 26001 (MDoNER) · Team DEADLINE SURVIVORS**

> ### ⚠ WHAT IS REAL HERE, AND WHAT IS NOT
> **Rainfall and soil moisture are real observed data** — hourly ERA5 reanalysis
> and forecast per zone from Open-Meteo, cached locally so the system runs with
> no network. Place names and approximate coordinates are real.
>
> **Everything hazard-related is simulated**: the 120 historical landslide
> events, the 40 sensor nodes, the zone boundaries, and the monsoon event the
> demo plays. No physical sensor exists and no government hazard feed is
> connected.
>
> Weather data by Open-Meteo.com (CC BY 4.0); ERA5 reanalysis via ECMWF.

**What the system does:** `PREDICT → MONITOR → VERIFY → ALERT → RESPOND`

**What it is not:** a guaranteed prediction. Every risk output is decision
support carrying a confidence score and a ranked, plain-language explanation of
the factors behind it. Model performance figures are deliberately not exposed
through this API — accuracy measured on synthetic data would misrepresent
real-world skill.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    manager.bind_loop(asyncio.get_running_loop())

    log.info("loading susceptibility model …")
    risk_service.registry.load()

    log.info("starting MQTT ingest …")
    ingest.start()

    try:
        with session_scope() as db:
            summary = spatial.dashboard_summary(db)
        log.info("ready — %s zones scored, %s active alerts, %s sensors (%s failed)",
                 sum(v for k, v in summary["severity_counts"].items() if k != "UNSCORED"),
                 summary["active_alerts"], summary["sensors_total"], summary["sensors_failed"])
    except Exception as exc:
        log.warning("database not ready (%s) — run scripts/seed.py --reset", exc)

    yield

    ingest.stop()
    log.info("shutdown complete")


app = FastAPI(
    title="BHOOSHAKTI AI",
    version="1.0.0-prototype",
    description=DESCRIPTION,
    lifespan=lifespan,
    contact={"name": "Team DEADLINE SURVIVORS — SIH 2026 PS 26001"},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory=str(settings.upload_dir)), name="uploads")

for router in (auth.router, zones.router, risk.router, alerts.router, reports.router,
               field.router, infrastructure.router, demo.router, audit.router,
               weather.router):
    app.include_router(router)


@app.get("/", tags=["meta"], summary="Service banner")
def root() -> dict:
    return {
        "service": "BHOOSHAKTI AI",
        "subtitle": "AI landslide early warning & risk monitoring — North-East India",
        "problem_statement": "SIH 2026 · PS 26001 · MDoNER · Disaster Management",
        "team": "DEADLINE SURVIVORS",
        "pipeline": ["PREDICT", "MONITOR", "VERIFY", "ALERT", "RESPOND"],
        "docs": "/docs",
        "websocket": "/ws/live",
        "demo_data": True,
        "data_notice": ("Rainfall and soil moisture are REAL observed data (Open-Meteo "
                        "ERA5 + forecast, cached locally). Historical landslide events, "
                        "sensor nodes, zone boundaries and the demo storm are SIMULATED."),
        "weather_attribution": ("Weather data by Open-Meteo.com (CC BY 4.0). "
                               "ERA5 reanalysis via ECMWF."),
        "ai_notice": ("Risk output is decision support, not a guaranteed prediction. Every "
                      "estimate carries a confidence score and ranked contributing factors."),
    }


@app.get("/health", tags=["meta"], summary="Liveness and dependency status")
def health() -> dict:
    db_ok, zone_count = True, 0
    try:
        with session_scope() as db:
            zone_count = int(db.execute(
                __import__("sqlalchemy").text("SELECT COUNT(*) FROM zones")).scalar_one())
    except Exception:
        db_ok = False

    return {
        "status": "ok" if db_ok else "degraded",
        "database": {"connected": db_ok, "zones": zone_count},
        "mqtt": {
            "enabled": settings.mqtt_enabled,
            "connected": ingest.connected,
            "messages_ingested": ingest.messages_seen,
            "rollups_done": ingest.rollups_done,
            "rollups_pending": ingest.pending_rollups,
            "topic": f"{settings.mqtt_topic_prefix}/+",
        },
        "model": {
            "loaded": risk_service.registry.loaded,
            "version": risk_service.registry.version,
            "error": risk_service.registry.load_error,
        },
        "websocket_clients": manager.client_count,
        "email": {
            "configured": settings.email_configured,
            "test_recipient": settings.alert_test_email,
            "mode": "live SMTP" if settings.email_configured else "SIMULATED (SMTP_HOST unset)",
        },
        "weather": {
            "provider": settings.weather_provider,
            "using_real_weather": settings.use_real_weather,
        },
        "notify_channels": settings.channel_list,
        "demo_data": True,
    }


@app.websocket("/ws/live")
async def live(websocket: WebSocket) -> None:
    """Single live channel for the dashboard: risk updates, alerts, reports,
    infrastructure changes and demo-timeline steps. No polling anywhere."""
    await manager.connect(websocket)
    try:
        while True:
            # Client messages are only keep-alives; everything flows server->client.
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception:
        await manager.disconnect(websocket)
