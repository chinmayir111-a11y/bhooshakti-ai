"""WebSocket fan-out for the live dashboard.

One hub, many topics. The dashboard subscribes once and receives risk updates,
new alerts, field reports, moderation items and demo-timeline steps as they
happen — there is no polling anywhere in the frontend.

`publish_threadsafe` exists because MQTT telemetry arrives on paho's own
thread, which has no event loop of its own.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime
from typing import Any

from fastapi import WebSocket

log = logging.getLogger("bhooshakti.ws")

# Event names the frontend switches on. Keep in sync with web/src/api/ws.ts.
EVENT_RISK_UPDATE = "risk.update"
EVENT_ALERT_NEW = "alert.new"
EVENT_ALERT_DELIVERY = "alert.delivery"
EVENT_SENSOR_READING = "sensor.reading"
EVENT_SENSOR_STATUS = "sensor.status"
EVENT_REPORT_NEW = "report.new"
EVENT_REPORT_MODERATED = "report.moderated"
EVENT_FIELD_REPORT = "field.report"
EVENT_INFRA_UPDATE = "infra.update"
EVENT_DEMO_STEP = "demo.step"
EVENT_DEMO_STATE = "demo.state"
EVENT_SUMMARY = "summary.update"
EVENT_RESPONSE_PLAN = "response.plan"


def _default(obj: Any) -> Any:
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if hasattr(obj, "value"):        # enums
        return obj.value
    return str(obj)


class ConnectionManager:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = asyncio.Lock()
        self._recent: list[dict[str, Any]] = []   # small replay buffer

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Called once at startup so background threads can reach the loop."""
        self._loop = loop

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)
        log.info("ws client connected (%d total)", len(self._clients))
        await ws.send_text(json.dumps({
            "event": "hello",
            "payload": {
                "message": "BHOOSHAKTI AI live channel",
                "demo_data": True,
                "recent": self._recent[-20:],
            },
        }, default=_default))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)
        log.info("ws client disconnected (%d total)", len(self._clients))

    async def broadcast(self, event: str, payload: Any) -> None:
        message = {"event": event, "payload": payload,
                   "ts": datetime.now().astimezone().isoformat()}
        if event in (EVENT_ALERT_NEW, EVENT_DEMO_STEP):
            self._recent.append(message)
            self._recent = self._recent[-50:]

        text = json.dumps(message, default=_default)
        dead: list[WebSocket] = []
        for ws in list(self._clients):
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.discard(ws)

    def publish_threadsafe(self, event: str, payload: Any) -> None:
        """Broadcast from a non-async context (MQTT callback thread, scripts)."""
        if self._loop is None or self._loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(self.broadcast(event, payload), self._loop)
        except RuntimeError:  # pragma: no cover - loop shutting down
            pass

    def clear_replay(self) -> None:
        self._recent.clear()


manager = ConnectionManager()
