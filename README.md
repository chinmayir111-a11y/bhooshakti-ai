
# BHOOSHAKTI AI

**AI-powered landslide early warning and risk monitoring for North-East India.**


> ### ⚠ WHAT IS REAL HERE, AND WHAT IS NOT
> **Rainfall and soil moisture are real observed data** — hourly ERA5 reanalysis and
> forecast pulled per zone from [Open-Meteo](https://open-meteo.com) and cached locally.
> Place names and approximate coordinates are real North-East India locations.
>
> **Everything hazard-related is simulated**: the 120 historical landslide events, the 40
> sensor nodes, the zone boundaries, and the monsoon event the demo plays. No physical
> sensor exists and no government hazard feed is connected. Every data screen carries a
> permanent `DEMO DATA` badge and names its weather source on screen.

---

## What it does

    PREDICT  →  MONITOR  →  VERIFY  →  ALERT  →  RESPOND

| Stage | What happens | Where to see it |
|---|---|---|
| **PREDICT** | XGBoost susceptibility model + 24h rainfall outlook, fused into a risk score | Zone drawer on the dashboard |
| **MONITOR** | Simulated IoT nodes publish rainfall / soil moisture / tilt over MQTT | Sensor layer + `/sensors` |
| **VERIFY** | Field officers confirm or deny on site — offline-first, syncs later | Expo field app |
| **ALERT** | Zones crossing HIGH or CRITICAL fire automatically on every channel | Left rail + `/alerts` |
| **RESPOND** | PostGIS works out which roads and settlements are cut off, and what to do first | Map + response plan |

**AI here is risk forecasting and early-warning decision support — never a guaranteed
prediction.** Every risk output carries a **confidence score** and **ranked contributing
factors in plain language**. Confidence falls when the evidence is thin: failed sensors,
stale telemetry, or the model disagreeing with what the rain gauges say. Model accuracy
figures are deliberately never shown in the UI or served by the API — accuracy measured
on synthetic data would misrepresent real-world skill.

---

## Running it

Pick **one** of the two paths below. Docker works identically on Windows, macOS and
Linux and needs nothing else installed. The native path is faster and is what the
project was developed on.

### Path A — Docker (any OS, nothing else to install)

Requires [Docker Desktop](https://docs.docker.com/get-started/get-docker/).

```bash
git clone https://github.com/chinmayir111-a11y/bhooshakti-ai.git
cd bhooshakti-ai
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

## Demo walkthrough

Sign in as **`authority`**. Press **Simulate Monsoon Event** (leave speed at 1× for a
~60-second run). Each step toasts on screen.

1. **The Sikkim–Darjeeling corridor.** 25 monitored zones, live over WebSocket — nothing
   here polls. The map is a risk choropleth; the left rail is the live alert feed; the top
   strip counts zones by severity.

2. **Step 1–2 — rainfall ramps across three zones, and soil moisture follows with a lag.**
   These are genuine MQTT messages published to Mosquitto and ingested back through the
   API's own subscriber. The sensor layer updates live.

3. **Step 3 — risk recomputes. Two zones go HIGH, one goes CRITICAL.** Click
   **Tindharia–Paglajhora**. The drawer shows the risk score, the **confidence**, and the
   **ranked contributing factors in plain language** — "72h rainfall 215 mm, 2.7× the
   seasonal normal for this zone".

4. **Step 4 — alerts fire automatically and dispatch on every channel.** Email, SMS,
   push, WebSocket and console, each with its delivery status. Channels marked `sim` are
   honestly labelled as simulated.

5. **Step 5 — a field officer confirms slope movement on site.** Note what happens:
   **the confirmation escalates the zone and raises confidence**. Ground truth outranks
   telemetry — that is what the VERIFY stage is for, and it is visible in the factor list.

6. **Step 6 — a citizen report arrives.** It is geo-validated by PostGIS `ST_Contains`
   against the monitored zones before a human ever sees it, and lands in **/moderation**.

7. **Step 7 — NH-110 is blocked, and four settlements lose road access.** `ST_Intersects`
   picks the lifeline road crossing the zone; `ST_DWithin` finds every settlement inside
   the cut-off radius. Tindharia, Sonada, Ghum and Paglajhora — 13,500 residents.

8. **Step 8 — the prioritised response list.** Close the road, evacuate, move SDRF, open a
   relief point, broadcast in three languages, fix the failed sensors.

**Then press `Reset Demo`** — it restores the seeded baseline so you can run it again.

**Also worth trying:**

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
| The monsoon event in the demo | Simulated on top of the real baseline weather — you cannot wait for an actual landslide during a two-minute demo. |
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
ALERT_TEST_EMAIL=you@gmail.com
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
