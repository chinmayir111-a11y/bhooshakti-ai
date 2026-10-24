# BHOOSHAKTI AI

**AI-powered landslide early warning and risk monitoring for North-East India.**

Smart India Hackathon 2026 · Problem Statement **26001** (MDoNER — Disaster Management, Software)
Team **DEADLINE SURVIVORS**

> ### ⚠ WHAT IS REAL HERE, AND WHAT IS NOT
> **Real:** rainfall and soil moisture (hourly ERA5 reanalysis + forecast from
> [Open-Meteo](https://open-meteo.com), cached per zone with the grid cell recorded);
> the historical landslide record (351 [NASA Global Landslide Catalog](https://catalog.data.gov/dataset/global-landslide-catalog-export-75464)
> events in North-East India, 2007–2016, plus two documented 2022/2024 events with their
> sources); the model, which is trained on those events; the backtest counts; citizen
> reports and the escalation that follows them; terrain in the 3D map (AWS Terrain Tiles).
>
> **Simulated:** the zone boundaries and their terrain attributes, the sensor nodes
> (except `HW-01` when a real ESP32 is plugged in — see *Demo with a real sensor*), the
> scripted monsoon storm, the escalation roster and the demo subscriber numbers. Turn on
> **Show data sources** in the control room and every number says which it is.
> See [Real vs simulated data](#real-vs-simulated-data) for the full table.

---

## What it does

    PREDICT  →  MONITOR  →  VERIFY  →  ALERT  →  RESPOND

| Stage | What happens | Where to see it |
|---|---|---|
| **PREDICT** | XGBoost trained on real NASA GLC landslides + 24h outlook, fused into a risk score | Zone drawer in `/control` |
| **MONITOR** | IoT nodes (simulated, or a real ESP32) publish rainfall / soil moisture / tilt over MQTT; measured tilt raises risk directly | Sensor layer, LIVE dot |
| **VERIFY** | Citizens report by app, PWA, SMS or missed call; reports are scored, escalated and never left unseen; field officers confirm on site | `/`, `/control/moderation` |
| **ALERT** | ADVISORY (machine) and WARNING (human-confirmed / CRITICAL) on websocket, email, SMS, voice call, push, CAP 1.2 feed and a siren MQTT topic | `/control/alerts`, `/api/cap/alerts.xml` |
| **RESPOND** | PostGIS works out which roads and settlements are cut off, and what to do first | Map + response plan |

**AI here is risk forecasting and early-warning decision support — never a guaranteed
prediction.** Every risk output carries a **confidence score** and **ranked contributing
factors in plain language**. Confidence falls when the evidence is thin: failed sensors,
stale telemetry, or the model disagreeing with what the rain gauges say. Model skill is
reported only one way: as counts from a backtest on real held-out landslides
(*warned before 16 of 34*), never as an accuracy percentage — see
[Backtest on real landslides](#backtest-on-real-landslides).

---

## Running it

Pick **one** of the two paths below. Docker works identically on Windows, macOS and
Linux and needs nothing else installed. The native path is faster and is what the
prototype was developed on.

### Path A — Docker (any OS, nothing else to install)

Requires [Docker Desktop](https://docs.docker.com/get-started/get-docker/).

```bash
git clone https://github.com/chinmayir111-a11y/bhooshakti.git
cd bhooshakti
cp .env.example .env

docker compose up --build                                # starts db, mqtt, api, web
docker compose exec api python scripts/seed.py --reset   # loads data + real weather
docker compose exec api python scripts/train.py          # trains the model
```

On Windows use PowerShell and `copy .env.example .env` instead of `cp`.

> **Note:** the container path is written and reviewed but has **not been executed** —
> Docker was not installed on the development machine. If you hit a problem here, the
> native path below is the one that is proven.

### Path B — Native

**Check what you have first.** This tells you exactly what is missing:

```bash
make doctor
```

<details open>
<summary><strong>macOS</strong> (Intel and Apple Silicon)</summary>

```bash
brew install postgresql@18 postgis mosquitto python@3.12 node
cp infra/mosquitto/mosquitto.conf "$(brew --prefix)/etc/mosquitto/mosquitto.conf"
make setup
```
</details>

<details>
<summary><strong>Linux</strong> (Debian / Ubuntu)</summary>

```bash
sudo apt update
sudo apt install -y postgresql postgresql-16-postgis-3 mosquitto \
                    python3.12 python3.12-venv nodejs npm
sudo cp infra/mosquitto/mosquitto.conf /etc/mosquitto/conf.d/bhooshakti.conf
sudo systemctl restart mosquitto
make setup
```

Adjust the PostGIS package to match your PostgreSQL version
(`postgresql-15-postgis-3`, etc.).
</details>

<details>
<summary><strong>Windows</strong></summary>

`make` is not standard on Windows. Two options:

**Easiest — use Docker (Path A above).**

**Or use WSL2**, which gives you a real Linux environment:

```powershell
wsl --install -d Ubuntu
```

Then open Ubuntu and follow the Linux instructions exactly.

**Or run the steps by hand in PowerShell**, if you would rather not use either.
Install [PostgreSQL + PostGIS](https://www.postgresql.org/download/windows/) (tick
PostGIS in Stack Builder), [Python 3.12](https://www.python.org/downloads/) and
[Node.js](https://nodejs.org/), then:

```powershell
copy .env.example .env
python -m venv backend\.venv
backend\.venv\Scripts\pip install -r backend\requirements.txt

psql -U postgres -c "CREATE ROLE bhooshakti WITH LOGIN PASSWORD 'bhooshakti' SUPERUSER"
psql -U postgres -c "CREATE DATABASE bhooshakti OWNER bhooshakti"
psql -U postgres -d bhooshakti -c "CREATE EXTENSION IF NOT EXISTS postgis"

cd backend
.venv\Scripts\python scripts\seed.py --reset
.venv\Scripts\python scripts\train.py
cd ..
cd web && npm install && cd ..
```
</details>

### Start it

Two terminals (three if you want the phone app):

| Terminal | macOS / Linux | Windows (PowerShell) |
|---|---|---|
| 1 | `make api` | `backend\.venv\Scripts\python -m uvicorn app.main:app --port 8000` *(from `backend\`)* |
| 2 | `make web` | `npm run dev` *(from `web\`)* |
| 3 | `make mobile` | `npx expo start --web --port 8081` *(from `mobile\`)* |

From a clean clone, setup completes in **under 5 minutes** (about 25 seconds of that is
seed + train; the rest is downloading dependencies).

| Surface | URL |
|---|---|
| Authority dashboard | http://localhost:5173 |
| Citizen reporting (no login) | http://localhost:5173/report |
| Field officer app | http://localhost:8081 |
| API docs (OpenAPI) | http://localhost:8000/docs |
| Live WebSocket channel | ws://localhost:8000/ws/live |

### Everyday commands

```bash
make doctor    # what is installed, what is missing, what still needs doing
make test      # all 74 tests
make weather   # refresh the cached Open-Meteo data
make reset     # rebuild data and retrain from scratch
make help      # every available command
```

### Demo logins

The login screen lists all three. Password for every account: `demo1234`.

| Username | Role | Sees |
|---|---|---|
| `authority` | authority | Everything: dashboard, moderation, alerts, audit, demo controls |
| `field.officer` | field officer | Assigned zones and the verification form |
| `citizen` | citizen | Public reporting (which needs no account at all) |

---

## Where the weather comes from

Two Open-Meteo endpoints, because neither covers the whole window alone:

| Endpoint | Covers | Why |
|---|---|---|
| `archive-api.open-meteo.com/v1/archive` | 30 days ago → ~3 days ago | ERA5 reanalysis — the best available estimate of what actually happened. Lags real time by ~2 days. |
| `api.open-meteo.com/v1/forecast` | last ~5 days → +5 days | Operational model. `past_days` covers the archive's lag; the rest is the genuine forecast. |

They are stitched with the archive winning on overlap. Two details that are easy to get
wrong, both handled in `backend/app/services/openmeteo.py`:

- **The endpoints serve different soil layers.** The forecast has
  `soil_moisture_0_to_1cm` and `soil_moisture_1_to_3cm`; ERA5 has neither, offering
  `soil_moisture_0_to_7cm`. Mixing them puts a step change into the series exactly at the
  join — at Darjeeling the 0–1 cm layer reads ~0.28 m³/m³ while 0–7 cm reads ~0.38 at the
  same instant, which would look like a drying event that never happened. **0–7 cm is the
  canonical layer** (the only one both endpoints share, and the depth that actually governs
  shallow slope failure). The two thin layers are still stored where available.
- **Units are m³/m³, not percent.** Multiplying by 100 caps the series near 50% and the
  saturation term in fusion never engages. It is converted to a *degree of saturation*
  against anchors measured from the real regional distribution (`VWC_DRY = 0.25`,
  `VWC_SATURATED = 0.53`), which puts the regional median near 60% and the 95th percentile
  near 91% — right across the 55% and 90% thresholds fusion already used.

```bash
python scripts/fetch_weather.py             # refresh the cache
python scripts/fetch_weather.py --status    # what is cached, and how fresh
python scripts/fetch_weather.py --calibrate # re-derive the VWC anchors from data
```

Or `POST /weather/refresh` from the API. **Real sensor telemetry is never overwritten by a
refresh** — an hour already carrying a sensor reading is left alone, which is also what
keeps a running demo storm intact.

### Working offline

The cache *is* the database. Once seeded, pull the network cable and everything still
works: risk computes, the demo runs, the scores are identical. `POST /weather/refresh`
returns `ok: false` with a plain explanation instead of failing. This is tested — see
*Verified offline* in the test table.

### Observation vs forecast

Forecast rows live in the same tables as observations, flagged with `is_forecast`. Every
trailing-window query filters them out. Without that flag a "trailing 24 hours of
rainfall" would quietly include tomorrow's forecast and every risk score in the system
would run hot; two tests exist purely to keep that from regressing.

The 24-hour outlook in fusion now uses the **real forecast** when it is cached, falling
back to the statistical nowcast (`ml/rainfall_trend.py`) when it is not.

---

## The 2-minute demo — read this aloud while presenting

Sign in as **`authority`**. Press **Simulate Monsoon Event** (leave speed at 1× for a
~60-second run; 4× if you are short of time). Each step toasts on screen.

1. **"This is the Sikkim–Darjeeling corridor. 25 monitored zones, live over WebSocket —
   nothing here polls."** The map is a risk choropleth; the left rail is the live alert
   feed; the top strip counts zones by severity.

2. **Step 1–2 — "Rainfall is ramping across three zones, and soil moisture follows with a
   lag."** These are genuine MQTT messages published to Mosquitto and ingested back
   through the API's own subscriber. The sensor layer updates live.

3. **Step 3 — "Risk recomputes. Two zones go HIGH, one goes CRITICAL."** Click
   **Tindharia–Paglajhora**. The drawer shows the risk score, the **confidence**, and the
   **ranked contributing factors in plain language** — "72h rainfall 215 mm, 2.7× the
   seasonal normal for this zone". *This is the slide to linger on.*

4. **Step 4 — "Alerts fire automatically and dispatch on every channel."** Email, SMS,
   push, WebSocket and console, each with its delivery status. Channels marked `sim` are
   honestly labelled as simulated.

5. **Step 5 — "A field officer confirms slope movement on site."** Note what happens:
   **the confirmation escalates the zone and raises confidence**. Ground truth outranks
   telemetry — that is what the VERIFY stage is for, and it is visible in the factor list.

6. **Step 6 — "A citizen report arrives."** It is geo-validated by PostGIS `ST_Contains`
   against the monitored zones before a human ever sees it, and lands in
   **/moderation**.

7. **Step 7 — "NH-110 is blocked, and four settlements lose road access."** `ST_Intersects`
   picks the lifeline road crossing the zone; `ST_DWithin` finds every settlement inside
   the cut-off radius. Tindharia, Sonada, Ghum and Paglajhora — 13,500 residents.

8. **Step 8 — "And here is the prioritised response list."** Close the road, evacuate,
   move SDRF, open a relief point, broadcast in three languages, fix the failed sensors.

**Then press `Reset Demo`** — it restores the seeded baseline so you can run it again for
the next judge.

**Two more things worth showing if you have 30 seconds:**

- **`/report`** on a phone — the citizen form in **English / हिन्दी / অসমীয়া**, no login.
- **The field app with the network off** — queue a verification, watch the banner say
  *"1 report pending sync"*, turn the network back on, watch it clear by itself.

---

## What is real vs simulated

**Real — genuinely working software:**

| | |
|---|---|
| PostgreSQL 18 + **PostGIS 3.6** | Real geometry columns and real spatial queries — `ST_Contains` for zone lookup and report geo-validation, `ST_Intersects` for road/zone exposure, `ST_DWithin` (on `geography`, in metres) for cut-off analysis. No spatial logic is faked in Python. |
| **XGBoost** susceptibility model | Really trained by `scripts/train.py`, persisted, and loaded by the API at startup. Platt-calibrated so the output is usable as a probability. |
| **MQTT** ingest | Real Mosquitto broker. `sensor_simulator.py` publishes to `bhooshakti/sensors/{node_id}`; the API subscribes and rolls readings into each zone's hourly series. The demo timeline publishes through this same path. |
| **WebSockets** | Real push on `/ws/live`. The dashboard never polls. |
| **JWT auth + RBAC** | Real tokens, three roles, enforced per endpoint. |
| **Audit log** | Every data access, moderation decision and dispatch is written to `audit_log` and surfaced at `/audit`. |
| **Offline sync queue** | Really works. Writes to AsyncStorage, survives an app restart, replays idempotently on `client_uuid`, and is covered by 9 unit tests. |
| **Email dispatch** | Real SMTP code path. Sends for real the moment credentials are set — see below. |
| **Alembic migrations** | Real two-revision chain. `alembic check` reports no drift from the models, and upgrade → downgrade → upgrade round-trips cleanly. |
| **Rainfall and soil moisture** | **Real observed data.** Hourly ERA5 reanalysis and forecast per zone from Open-Meteo, cached in PostgreSQL. |

> Attribution: weather data by [Open-Meteo.com](https://open-meteo.com) (CC BY 4.0),
> ERA5 reanalysis via ECMWF. Free for non-commercial use, no API key.

**Simulated — clearly labelled everywhere:**

| | |
|---|---|
| Sensor telemetry | `sensor_simulator.py` and the demo timeline. No physical node exists. |
| The monsoon event in the demo | Simulated on top of the real baseline weather — we cannot wait for an actual landslide during a two-minute demo. |
| The 120 historical landslide events | Synthetic, with plausible feature values. **Not** an official GSI/NRSC inventory. |
| Zone polygons | Generated shapes around real centroids. **Not** surveyed administrative or geological boundaries. |
| Terrain attributes (slope, aspect, elevation, lithology, land cover) | Plausible values chosen for the demo, not survey measurements. |
| Populations and infrastructure | Indicative figures. Road and settlement *names* are real; the geometries are approximate. |
| **SMS** | Real Twilio and MSG91 adapters are implemented behind the channel interface, but the default provider is a **stub** that logs and displays as `SIMULATED`, so the demo needs no paid account. |
| **Push** | Real Expo push adapter; stub when no device is paired. |

### Email: the one thing you must configure to see it end-to-end

Email is **fully implemented and genuinely sends**, but it is inert until SMTP credentials
exist. Out of the box it reports `SIMULATED` and logs the rendered message — the honest
state, not a silent failure.

To turn it on, put a Gmail **App Password** (needs 2FA:
<https://myaccount.google.com/apppasswords>) in `.env`:

```dotenv
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=xxxxxxxxxxxxxxxx
ALERT_TEST_EMAIL=abjgd108@gmail.com
```

Then:

```bash
cd backend && .venv/bin/python scripts/test_alert_email.py
```

It prints the zone, severity, score, confidence, every contributing factor, the exposed
roads and settlements, the deep link, and the delivery result. The dashboard's
**Send test alert** button does the same thing through `POST /alerts/test`.

> **Status in this build:** the email pipeline is complete and verified end-to-end up to
> the SMTP handshake, but **no credentials were configured**, so no message has actually
> been delivered to an inbox yet. `scripts/test_alert_email.py` currently exits with
> `RESULT: SIMULATED`. Add the four `SMTP_*` values above and re-run to send for real —
> no code change is needed.

---

## Architecture

```
                    ┌──────────────────────────┐
   MQTT             │  React + Vite dashboard  │  Expo field app
   sensor_simulator │  Leaflet · WebSocket     │  offline-first queue
        │           └────────────┬─────────────┘         │
        │  bhooshakti/sensors/+  │  REST + WS            │ REST (batch replay)
        ▼                        ▼                       ▼
   ┌────────────────────────────────────────────────────────────┐
   │                    FastAPI  ·  /docs  ·  /ws/live          │
   │  auth · zones · risk · alerts · reports · field · demo     │
   ├────────────────────────────────────────────────────────────┤
   │  ml/  features → XGBoost → rainfall trend → RISK FUSION    │
   │       score 0-100 · severity · confidence · factors[]      │
   ├────────────────────────────────────────────────────────────┤
   │  notify/  console · websocket · email(SMTP) · sms · push   │
   └───────────────────────────┬────────────────────────────────┘
                               ▼
              PostgreSQL 18 + PostGIS 3.6
              ST_Contains · ST_Intersects · ST_DWithin
```

### Risk fusion

`backend/ml/fusion.py` — pure, no I/O, and the most heavily tested module in the project.

```
hazard = 0.55·model_probability          (XGBoost susceptibility)
       + 0.18·rainfall_pressure          (72h total ÷ this zone's own seasonal normal)
       + 0.14·saturation_pressure        (soil moisture vs the saturation threshold)
       + 0.13·forecast_pressure          (24h outlook)
       ± field_verification              (a confirmed on-site check outranks telemetry)

risk_score = 100 · clamp(hazard)
severity   = LOW <25 ≤ MODERATE <50 ≤ HIGH <75 ≤ CRITICAL
```

Confidence starts at 0.90 and is reduced by failed sensors, stale telemetry, model /
environment disagreement, and rainfall far outside the training range. It is raised when
a field officer has actually been on the slope. **It can never reach 1.0** — there is a
test asserting exactly that.

### Layout

```
backend/
  app/          FastAPI app, routers, auth, audit, WebSocket hub, MQTT ingest
    services/   spatial.py (all PostGIS SQL) · risk_service.py · demo_engine.py
    notify/     dispatcher, channel adapters, trilingual alert templates
  ml/           features.py · fusion.py · rainfall_trend.py
  scripts/      seed.py · train.py · sensor_simulator.py · test_alert_email.py
                calibrate_demo.py · geodata.py
  tests/        test_fusion.py (32) · test_spatial.py (19)
web/            React + Vite + TypeScript, Leaflet, one WebSocket
mobile/         Expo (Android + web), offline queue + 9 tests
infra/          Mosquitto config
```

---

## Tests

```bash
make test
```

| Suite | Covers | Count |
|---|---|---|
| `backend/tests/test_fusion.py` | Severity bands, monotonicity, confidence behaviour, verification uplift, explanation quality | 32 |
| `backend/tests/test_spatial.py` | Real `ST_Contains` / `ST_Intersects` / `ST_DWithin` against PostGIS, the blocking cascade, GeoJSON validity | 19 |
| `backend/tests/test_weather.py` | Open-Meteo unit conversion, forecast/observation separation, sensor precedence, raw-value audit trail | 14 |
| `mobile/src/offline/queue.test.ts` | Offline retention, restart survival, idempotent replay, partial settlement, retry limits, concurrent-flush collapse, corrupt storage | 9 |

The spatial tests run against a real seeded PostGIS database on purpose — mocking the
database would test nothing about the claim being made. They skip cleanly if none is
reachable.

**Verified offline:** with Open-Meteo pointed at an unreachable host, the risk engine still
scores all 25 zones and the demo timeline produces byte-identical results from cache.

Several of these tests caught real bugs. The offline queue was double-sending under
concurrent flush (the guard was claimed after an `await`). The MQTT ingest ran a full
aggregate query per message on paho's single callback thread, so a 150-message demo burst
took longer to drain than the demo ran — one zone silently kept its pre-storm soil
moisture and never escalated. And the first migration baseline called
`metadata.create_all()`, which meant it tracked whatever the models looked like *today*,
so the next migration tried to add columns the baseline had already created.

---

## API

`GET /docs` for the full interactive spec.

| | |
|---|---|
| `GET /zones` · `/zones/{id}` · `/zones/{id}/risk` | Zones as GeoJSON with live risk |
| `POST /risk/recompute` | Recompute every zone (or a subset) |
| `GET /alerts` · `POST /alerts/test` | Alert history; send a real test alert |
| `GET /reports` · `POST /reports` · `POST /reports/{id}/moderate` | Citizen reporting and moderation |
| `POST /field/verify` · `/field/verify/batch` | Verification, single and offline-batch |
| `GET /infrastructure` · `/sensors` · `/historical` | Map layers |
| `POST /demo/simulate` · `POST /demo/reset` | The scripted timeline |
| `GET /weather/status` · `POST /weather/refresh` | Cached weather provenance and freshness; re-pull Open-Meteo |
| `GET /audit` | The audit trail |
| `WS /ws/live` | Everything, pushed |

---

## Known limits

Honest list, because a judge will ask.

- **The model is trained on real weather but synthetic landslide labels.** The rainfall
  and soil moisture going in are genuine observations; the 120 events it learns from are
  not. So it has learned a plausible rainfall–failure relationship, not the actual one.
  Retraining the labels on the **GSI Bhukosh** landslide inventory is the first real-world
  step — and because the weather side is already real, that is now the *only* substitution
  the model needs.
- **No email has actually been delivered** in this build — credentials were never
  configured. The code path is complete and tested up to the SMTP handshake.
- **Satellite change detection is not implemented.** The extension point is documented in
  `DEPLOYMENT.md`; a PyTorch/TensorFlow model would slot in beside the XGBoost one as an
  additional fusion input, not a replacement.
- **The demo storm is simulated on top of real weather.** The baseline is genuine; the
  monsoon event is not. `scripts/calibrate_demo.py` measures which rainfall totals land
  each zone in which band and the timeline uses those measured numbers, so the scripted
  story survives a reseed. Against real ERA5 normals (25–80 mm/72h here) the storm targets
  are 26–45 mm/24h — far smaller than the synthetic-weather era needed, and far more
  realistic.
- **Zone polygons are generated shapes**, not surveyed boundaries. Terrain attributes
  (slope, aspect, lithology, land cover) are plausible values, not survey measurements —
  these are the next thing to replace with SRTM/CartoDEM and GSI geology.
- **Nothing is deployed.** `DEPLOYMENT.md` describes the target cloud architecture.

---

## Extension points

- **Satellite change detection** — `backend/ml/` alongside `fusion.py`; feed a
  before/after InSAR or optical change score in as an additional fusion component.
- **Mapbox GL JS** — `web/src/components/MapView.tsx`, `createBaseLayer()`. Set
  `VITE_MAPBOX_TOKEN` and the layer swaps; no overlay code changes.
- **Real SMS** — set `SMS_PROVIDER=twilio` or `msg91` plus credentials. Adapters are
  already written against the plain REST APIs, so no vendor SDK is needed.
- **More languages** — `web/src/i18n/strings.json` and
  `backend/app/notify/templates.py`.
- **Real terrain** — `scripts/geodata.py` holds hand-entered slope/lithology values.
  Open-Meteo already returns a grid `elevation` per zone, which is the easiest first
  substitution; SRTM or CartoDEM gives the rest.

---

*Prototype built for SIH 2026 PS 26001. Not for operational use.*

## Contributing

Contributions are welcome. To keep development consistent across the backend,
web dashboard, and mobile field app, use the workflow below.

For a quick demonstration of the complete BHOOSHAKTI AI workflow:

1. Start PostgreSQL/PostGIS and Mosquitto.
2. Start the FastAPI backend on port `8000`.
3. Start the Vite web application on port `5173`.
4. Open `http://localhost:5173`.
5. Sign in using the `authority` demo account.
6. Select **Simulate Monsoon Event** to demonstrate the prediction, monitoring, verification, alert, and response workflow.

### Demo Credentials

All demo accounts use the password `demo1234`.

| Username | Role | Access |
|---|---|---|
| `authority` | Authority | Full dashboard, alerts, moderation, audit and demo controls |
| `field.officer` | Field Officer | Assigned zones and field verification |
| `citizen` | Citizen | Citizen reporting functionality |

> **Note:** BHOOSHAKTI AI clearly distinguishes real weather observations from simulated sensor telemetry, historical landslide events, terrain attributes, infrastructure data and the demonstration monsoon event. See **What is real vs simulated** for the complete data provenance.

*Prototype built for SIH 2026 PS 26001. Not for operational use.*

---

## Two apps in one

| URL | Who | What |
|---|---|---|
| `/` | Public | Citizen app: three giant buttons with audio labels — **Report landslide**, **Am I safe?**, **Emergency help**. Installable PWA, works offline, five languages. No map libraries are loaded here; the whole citizen bundle is ~80 KB gzipped. |
| `/control` | Officers (login) | Control room: live counters, activity ticker, 3D terrain map (MapLibre + deck.gl, with a 2D / low-data toggle), alert feed, escalation panel, moderation, audit. Full dark mode. |
| `/replay` | Public | Replay real past landslides hour by hour through the live risk pipeline. |

Languages: English, Hindi, Assamese, Bengali, Nepali. The Bengali and Nepali strings, and
every new Hindi/Assamese string since the first prototype, are **machine translations
awaiting review by a native speaker** — the app says so on screen
(`web/src/i18n/strings.json` → `_meta.needs_native_review`).

---

## Rural / offline access

Most people on these slopes have a feature phone and patchy 2G. Every channel below works
with no smartphone or no data; the ones that need a paid gateway run as clearly labelled
stubs until credentials are set in `.env`.

| Channel | How it works | Status in the demo |
|---|---|---|
| **SMS in** | `POST /api/inbound/sms` accepts Twilio or MSG91 webhooks. Keywords, case-insensitive: `LS <pincode or village> <what you see>` files a landslide report; `SAFE <pincode>` replies with the current risk; `JOIN <pincode> [HI]` registers the number for that zone's alerts; `STOP` ends them. Pincodes are resolved through a seeded `pincodes` table for the demo districts (`backend/scripts/geodata.py`). | Endpoint and parser are real and tested. Replies go through the SMS stub (logged) until `SMS_PROVIDER` is set. |
| **Missed call / IVR** | `POST /api/inbound/ivr` (Exotel-style). A missed call from a registered number triggers a call-back that reads the zone's risk aloud; *press 1* records a 20 s voice note that is stored like a photo and filed as a report. | Flow is real and tested; the outbound call is stubbed until `VOICE_PROVIDER` is set. |
| **Outbound voice** | New `voice` notify channel: a text-to-speech call in the subscriber's language (Exotel or Twilio adapters). Public ADVISORY/WARNING recipients get SMS **and** a call. | Stub unless configured. |
| **CAP 1.2 feed** | `GET /api/cap/alerts.xml` — every alert as Common Alerting Protocol 1.2, the format NDMA's SACHET and cell-broadcast systems consume. Validated in tests against the OASIS schema. Messages carry `status=Exercise`. | Real. **Actual cell broadcast requires government integration** (SACHET onboarding, telecom gateways); this feed is what that integration would consume. |
| **Siren hook** | Every WARNING is published on MQTT `bhooshakti/siren/<zone_id>` so a GSM/LoRa relay at a panchayat office can sound a siren. | Real (needs a relay on the wire). |
| **PWA offline** | `/` is installable. Offline, a report is queued in IndexedDB (same pattern as the field app's queue) and sent when the network returns; a **Send by SMS instead** button opens the phone's SMS app pre-filled with `LS <pincode> <description>`. | Real. |

Demo numbers (`+9198000000xx`) are reserved test ranges; nothing ever rings a real phone
unless you configure a provider.

---

## What happens when no officer is online

A citizen report is never allowed to sit unseen.

1. **On arrival** the report gets a **corroboration score (0–100)** with plain-language reasons:
   inside a zone currently HIGH/CRITICAL **+30** · 24 h observed rainfall above the zone's
   own threshold **+20** · a sensor within 2 km with a tilt or saturation anomaly in the last
   6 h **+25** · ≥3 independent reports (different phone numbers) within 1.5 km and 60 min
   **+25** · photo **+5** · location outside every monitored zone **−30**.
2. **T+0** — the district's on-duty moderator is paged by websocket, SMS and email.
3. **T+10 min unacknowledged** — the next officer in `escalation_contacts` (an ordered
   roster per district) is paged; again every 10 minutes until the roster runs out.
4. **T+20 min unacknowledged and score ≥ 60** — an **ADVISORY** goes automatically to
   everyone registered in that zone: *“Unverified public reports of a landslide near X. Stay
   alert, avoid the slope/road, await official confirmation.”*
5. **Score ≥ 85 at any time** — the ADVISORY goes out immediately, still awaiting a human.

Two alert tiers are shown everywhere: **ADVISORY** (machine-issued, unconfirmed) and
**WARNING** (human-confirmed, or the model at CRITICAL). A model HIGH is an advisory, not a
warning. A moderator's one click **CONFIRM** upgrades the advisory to a WARNING (and sounds
the siren); **DISMISS** sends an *all clear / false report* follow-up to exactly the people
the advisory reached. A second report of the same slide joins the advisory already out
rather than texting the public twice. Every automatic action is written to the audit log
with the full score breakdown. The ladder runs as a background job every minute
(`app/services/escalation.py`); its timings are tested with frozen time.

---

## Real vs simulated data

| Item | Status | Source / how to verify |
|---|---|---|
| Rainfall, soil moisture | **REAL** | Open-Meteo ERA5 archive + forecast. Zone drawer → *Weather provenance* shows the endpoint, model, grid cell actually used, fetch time and a **Verify live** link that opens the exact Open-Meteo URL so you can compare numbers yourself. |
| Past landslides | **REAL** | NASA Global Landslide Catalog (CSV cached in `backend/data/raw/`), filtered to the eight NE states; plus `backend/data/curated_events.csv` with source URLs. `source` column says which. |
| Model | **REAL training data** | Trained only on hydro-meteorological features of pre-2016 events; terrain attributes are not learned because catalogue points carry no terrain survey. |
| Terrain in the 3D map | **REAL** | AWS Terrain Tiles (Mapzen terrarium DEM), hillshade from the same source. |
| Citizen reports, escalation, audit | **REAL** | Whatever you submit. |
| Zone polygons and their slope / lithology / land cover | SIMULATED | `backend/scripts/geodata.py`. Real place names and approximate coordinates. |
| Sensor nodes | SIMULATED, except `HW-01` | `sensor_nodes.source` = `simulated` or `hardware`. Only a hardware node can show the green LIVE dot. The keyboard demo node `KB-01` is registered as simulated. |
| The monsoon storm the demo plays | SIMULATED | `app/services/demo_engine.py`; its strength is re-measured after every retrain (`scripts/calibrate_demo.py`). |
| Escalation roster, subscribers, pincode→zone map | SIMULATED / seeded | Reserved phone ranges; real pincodes for the demo towns. |

The control room's **Show data sources** toggle puts a `REAL · Open-Meteo`, `REAL · live sensor`
or `SIMULATED` badge beside every number.

---

## Backtest on real landslides

```bash
make import-landslides   # NASA GLC + curated events, then 30 days of ERA5 before each (cached)
make train               # train on pre-2016 events only
make backtest            # replay the held-out events -> ml/artifacts/backtest_results.json
```

**Method.** 353 real events are imported; those from the test year (2016) onward plus the two
curated events — 34 in all — are held out and never trained on. For each held-out event the
week before it is replayed hour by hour through the same pipeline the live system uses
(`risk_service.assess_series`), with a statistical nowcast in place of the Open-Meteo forecast
(no archived forecast exists for past events, and nothing from the future is used). The
alert threshold is HIGH (risk ≥ 50), where the live system alerts. The reference time is the
recorded time, or — since the GLC records dates only — the **start** of the local event day,
so a warning only counts if it beat the whole day. For every event the same place is also
replayed in a year with no catalogued landslide nearby (same calendar window) and in a dry
February week, to count false alarms.

**Result (model `v2.0-xgb-real`, 24 Oct 2026):**

> Warned before **16 of 34** held-out landslides (median **63 h** ahead); 0 more on the same day;
> **18 missed**. False alarms: **3 of 6** same-season non-event windows, **2 of 34** dry-season windows.

Of the two demo events, **Aizawl 28 May 2024** was warned 3.5 h ahead; **Noney/Tupul 30 June
2022** was **missed** (peak risk 42.5, under the threshold). Both are shown as-is on `/replay`.
Caveats worth saying out loud: the GLC is a news-derived, incomplete catalogue, so some
"non-event" windows may hide unreported slides; event locations carry 1–50 km uncertainty;
ERA5 is a ~25 km reanalysis, not a rain gauge on the slope; and rainfall alone cannot see
road-cutting or quarrying triggers. The numbers are counts, not an accuracy claim.

`/replay` lets a judge pick any held-out event, play the week at 1–16×, watch the rainfall
bars and the risk line cross the HIGH threshold (banner: *Alert would have fired on … — N hours
before the landslide*), see the real event marker with a link to its source record, and then
play the dry week at the same place. The 3D camera orbits the site while the rain column grows.

---

## Demo with a real sensor

`hardware/esp32_node/esp32_node.ino` turns an ESP32 into a slope sensor publishing the same
MQTT JSON as the simulator to `bhooshakti/sensors/HW-01`. The board measures tilt against the
orientation it had at power-on, so it reads ~0° where installed and climbs as the slope moves.

**Parts (approx. INR, Oct 2026 street prices):**

| Part | Approx. cost |
|---|---|
| ESP32 DevKit v1 (Wi-Fi + Bluetooth) | ₹350–450 |
| MPU6050 accelerometer/gyro breakout | ₹120–180 |
| Capacitive soil moisture sensor v1.2/v2.0 | ₹90–150 |
| Tipping-bucket rain gauge (optional) | ₹900–1,500 |
| 18650 cell + TP4056 charger + holder (optional) | ₹250–350 |
| Jumper wires, enclosure, stake | ₹150 |
| **Total** | **≈ ₹1,000 without rain gauge; ≈ ₹2,500 with** |

**Wiring:**

| ESP32 pin | Connects to |
|---|---|
| 3V3 | MPU6050 VCC, soil sensor VCC |
| GND | MPU6050 GND, soil sensor GND, rain gauge one side |
| GPIO 21 (SDA) | MPU6050 SDA |
| GPIO 22 (SCL) | MPU6050 SCL |
| GPIO 34 (ADC1) | soil sensor AOUT |
| GPIO 27 | rain gauge reed switch (other side), internal pull-up |
| GPIO 35 (optional) | battery through a 100 k / 100 k divider |

Flash with the Arduino IDE (board *ESP32 Dev Module*, library *PubSubClient*), set `WIFI_SSID`,
`WIFI_PASSWORD` and `MQTT_HOST` (the laptop running mosquitto; `ipconfig getifaddr en0`).
`infra/mosquitto/mosquitto.conf` already listens on the LAN. Details, calibration and a
LoRa variant: `hardware/esp32_node/README.md`.

**Demo script (the "wow" minute):**

1. Open `/control`, click zone **DJ-04 Tindharia–Paglajhora**. In the drawer, `HW-01` shows a
   green **LIVE** dot and *n s ago*.
2. Tilt the board slowly past ~1.5°. Within seconds the ticker reads *Sensor HW-01 tilt +1.6°
   (LIVE hardware)*, the zone is recomputed, and *Ground movement measured at sensor HW-01*
   appears as the top contributing factor.
3. Keep tilting towards 3° — the zone crosses into HIGH (ADVISORY) and, with the storm running,
   CRITICAL (WARNING). The alert feed, chime and siren topic fire; the configured inbox and
   test phone get the email/SMS (SMS as a stub unless a provider is set).

**No hardware to hand?** `make demo-live-sensor` runs a keyboard-driven fake node (`KB-01`):
press **T** to tilt +1.5°, **W** to wet the soil, **R** for a rain burst, **0** to reset. It is
registered as *simulated* and labelled so everywhere — it can never show the LIVE dot.

> The Arduino sketch was written against the documented ESP32 Arduino core and PubSubClient
> APIs but was not compiled on the development machine (no Arduino toolchain installed).
