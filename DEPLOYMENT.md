# Deployment architecture

**Nothing in this repository is deployed.** Everything runs locally with
`docker compose up` or `make setup`. This document describes what a real
deployment would look like, so the team can speak to it credibly.

Reference target below is **AWS**, with Azure and GCP equivalents in the last
section. Nothing in the codebase is AWS-specific: every managed service below
replaces a component that already runs behind an interface.

---

## Target architecture

```
                          ┌──────────────┐
   Citizens (web/PWA) ───▶│  CloudFront  │
   Officers (Expo/APK) ──▶│      +       │──▶ S3   static dashboard bundle
                          │     WAF      │
                          └──────┬───────┘
                                 │ /api  /ws
                          ┌──────▼────────────────┐
                          │  Application Load     │  TLS termination,
                          │  Balancer (sticky WS) │  WebSocket upgrade
                          └──────┬────────────────┘
                                 │
                   ┌─────────────▼──────────────┐
                   │  ECS Fargate — API service │  2+ tasks, autoscaled
                   │  FastAPI + uvicorn         │  on CPU and WS count
                   └──┬────────┬────────┬───────┘
                      │        │        │
        ┌─────────────▼──┐  ┌──▼─────┐ ┌▼────────────────┐
        │ RDS PostgreSQL │  │ Elasti │ │ SQS alert queue │
        │ + PostGIS      │  │ Cache  │ │  ──▶ Lambda     │
        │ Multi-AZ       │  │ Redis  │ │  dispatch workers│
        └────────────────┘  └────────┘ └─┬───────────────┘
                                          │
   Field sensors ──MQTT/TLS──▶ AWS IoT ───┤   SES (email)
   (LoRaWAN gateway)           Core       │   SNS / Twilio / MSG91 (SMS)
                                │         │   Expo Push (mobile)
                                ▼         │
                          IoT Rule ──▶ Kinesis ──▶ ingest task
                                          │
        S3 (report photos) ◀──────────────┘
        SageMaker / ECS batch — scheduled model retraining
```

---

## Component mapping

| Local (this repo) | AWS | Why |
|---|---|---|
| Postgres 18 + PostGIS container | **RDS for PostgreSQL, Multi-AZ, PostGIS extension** | Spatial queries stay identical. Managed backups, PITR, read replica for analytics. |
| Mosquitto container | **AWS IoT Core** | Per-device X.509 certificates, TLS, fleet provisioning, and an IoT Rule that forwards to Kinesis. Replaces `allow_anonymous`, which must never ship. |
| `sensor_simulator.py` | **Real LoRaWAN / NB-IoT field nodes** | Same JSON payload on the same topic shape (`bhooshakti/sensors/{node_id}`), so the ingest code is unchanged. |
| Uvicorn on a laptop | **ECS Fargate behind an ALB** | Stateless API tasks. The ALB must have sticky sessions and an idle timeout above the WebSocket keep-alive (25 s in `web/src/api/ws.ts`). |
| In-process `ConnectionManager` | **ElastiCache Redis pub/sub** | The WebSocket hub is in-memory today, which is correct for one process and wrong for two. With more than one task, fan-out has to go through Redis so a client on task A sees an event raised on task B. **This is the single change required to scale past one API task.** |
| Synchronous `notify.dispatch` | **SQS + Lambda workers** | Alert dispatch currently runs inline in the request. At real volume it must be enqueued so a slow SMS gateway cannot hold a request open. The channel interface already isolates this. |
| `backend/uploads/` on disk | **S3 + CloudFront**, presigned PUT | Photos must not live on an ephemeral container filesystem. `app/services/media.py` is the only module that touches storage. |
| `joblib` file next to the app | **S3-versioned artefact, loaded at task start** | Plus **SageMaker** or a scheduled ECS task for retraining as real inventory data accumulates. Pin the model version in `zone_risk.model_version` — the column already exists. |
| `.env` | **Secrets Manager / SSM Parameter Store** | SMTP credentials, JWT secret, SMS keys. Rotate the JWT secret on a schedule. |
| `print`/`logging` | **CloudWatch Logs + OpenTelemetry** | Alert on: model load failure, MQTT disconnection, dispatch failure rate, and any zone whose confidence drops below 0.4. |

---

## Sensor ingest

The local broker runs `allow_anonymous true`. **That must not reach production.**

1. Each node gets an X.509 certificate via IoT Core fleet provisioning.
2. An IoT Topic Rule on `bhooshakti/sensors/+` writes to Kinesis Data Streams.
3. An ingest task consumes the stream and performs the same hourly roll-up that
   `app/mqtt_client.py::_rollup_hour` does today (an upsert keyed on
   `(zone_id, hour)` — the unique constraint already exists).
4. A node that stops reporting is marked `FAILED` by a heartbeat monitor, which
   is what drives the confidence reduction the UI already surfaces.

Sensor telemetry is append-only and cheap to store: Kinesis Firehose to S3 in
Parquet gives a training corpus for free.

---

## Data protection

- **Citizen reports contain a location and an optional phone number.** Both are
  personal data. Retain moderated reports for a bounded period, drop the phone
  number once the report is closed, and never expose it on a public endpoint.
  The audit log already records every read of the report table.
- **Photos may show homes and people.** Presigned, short-lived URLs only; never
  a public bucket.
- **The audit log is the compliance artefact.** Ship it to a write-once store
  (S3 Object Lock) so it cannot be edited after the fact.
- **JWT secret rotation** invalidates live sessions by design. Field officers
  should be able to re-authenticate offline against a cached token until it
  expires — `JWT_EXPIRE_MINUTES` defaults to 720 for exactly this reason.

---

## Scaling notes, in the order they will actually bite

1. **WebSocket fan-out is in-process.** Two API tasks means two disjoint sets of
   connected clients. Move `ws.py` onto Redis pub/sub *before* scaling out.
2. **Alert dispatch is synchronous.** One slow SMTP handshake blocks a request.
   Move to SQS before real alert volume.
3. **`recompute_all` is a serial loop over zones.** Fine at 25 zones, wrong at
   2,500. Partition by district and fan out; the computation is embarrassingly
   parallel per zone.
4. **Rainfall series are read in full on every risk computation.** At 25 zones ×
   30 days that is trivial; at national scale, keep a materialised rolling-window
   table or use TimescaleDB.
5. **The model loads at task startup.** Cold starts get slower as the artefact
   grows. Bake it into the image or warm from EFS.

---

## Extension point: satellite change detection

Deliberately **not** built in v1. When added:

- A PyTorch or TensorFlow change-detection model over Sentinel-1 InSAR
  coherence loss or Sentinel-2 optical pairs, run as a scheduled batch job
  (not in the request path — imagery is slow and the risk API must stay fast).
- It writes a per-zone `change_score` with an observation timestamp.
- `ml/fusion.py` gains a fifth weighted component and a matching plain-language
  contributing factor. The weights renormalise; nothing else changes.
- Because it is a batch signal it should **raise confidence when fresh and decay
  when stale**, exactly as the field-verification term already does.

---

## Azure and GCP equivalents

| AWS | Azure | GCP |
|---|---|---|
| RDS PostgreSQL + PostGIS | Azure Database for PostgreSQL Flexible Server | Cloud SQL for PostgreSQL |
| ECS Fargate | Container Apps | Cloud Run |
| IoT Core | Azure IoT Hub | Cloud IoT alternative / self-managed EMQX |
| SQS + Lambda | Service Bus + Functions | Pub/Sub + Cloud Functions |
| S3 + CloudFront | Blob Storage + Front Door | Cloud Storage + Cloud CDN |
| ElastiCache Redis | Azure Cache for Redis | Memorystore |
| SES | Communication Services Email | SendGrid on GCP Marketplace |
| Secrets Manager | Key Vault | Secret Manager |
| SageMaker | Azure ML | Vertex AI |

Cloud Run and Container Apps both support WebSockets, but check the idle-timeout
default against the client keep-alive interval before assuming it works.

---

## Cost sketch (indicative, one state, ~250 zones, ~400 nodes)

| | Monthly |
|---|---|
| RDS `db.t4g.medium` Multi-AZ | ~$140 |
| ECS Fargate, 2 × 0.5 vCPU | ~$35 |
| IoT Core, 400 nodes @ 12 msg/hour | ~$15 |
| S3 + CloudFront | ~$10 |
| SES + SNS SMS (alert volume dependent) | ~$25 |
| **Total** | **~$225/month** |

SMS dominates at scale and is the line item to negotiate — a state disaster
authority will typically have an existing bulk-SMS arrangement, which is exactly
why the SMS gateway sits behind a swappable adapter interface.
