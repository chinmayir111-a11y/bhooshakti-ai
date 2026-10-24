# BHOOSHAKTI AI — 5-minute judge demo

**Before the judges arrive** (two terminals, one browser, optionally one phone on the same Wi-Fi):

```bash
make api        # terminal 1  (:8000)
make web        # terminal 2  (:5173)
```

Open three tabs: `http://localhost:5173/` (citizen app, set the window to phone width or use
a phone), `http://localhost:5173/control` (sign in `authority` / `demo1234`) and
`http://localhost:5173/replay`. In the control room turn **Sound on** (leave **Show data sources** off until a judge asks
where a number comes from). Open the **Demo** menu (right end of the counter strip) and click
**Reset demo** so the map starts calm, then **Warm map cache** once so tiles are local. If you have the ESP32, power it and check
`HW-01` shows LIVE in the DJ-04 drawer.

---

## 0:00 — The problem, in one sentence

> "A landslide warning that only reaches a dashboard in the capital saves nobody on the slope.
> BHOOSHAKTI warns the person on the hill — including the one with a ₹1,200 phone and no data —
> and it never lets a citizen's report sit unseen."

## 0:20 — The citizen app (phone, `/`)

1. Show the home screen: **three buttons, no reading needed**. Tap the speaker on
   *Tell us what you saw* — it speaks. Switch the language pill to **नेपाली** — the buttons and the
   voice change. Point out the *translation under review* line: machine translations are
   labelled as such.
2. Tap **Is it safe near me?** — a traffic-light circle with a pictogram and a spoken line
   (location permission → the nearest monitored zone).
3. Tap **Tell us what you saw**: *photo → location found automatically → pictogram → hold-to-record
   voice → Send*. Submit it. Turn on airplane mode and submit another: it says *Saved. Will send
   when online.* and offers **Send by SMS instead**, which opens the SMS app pre-filled with
   `LS 734223 …`. Turn the network back on: it syncs by itself.

## 1:30 — What happened to that report (control room, `/control`)

4. The ticker reads *New report near Tindharia · score NN*. Open the **Waiting for check** tab in the
   left rail: the score, the plain-language reasons (+30 zone HIGH, +25 sensor anomaly, +5 photo
   …) and two countdowns — **→ next officer in 9m 40s**, **auto "be alert" in 19m 40s**.
   > "If nobody touches this, in ten minutes the next officer on the district roster is paged;
   > in twenty, the public in that zone gets a **Be alert (unconfirmed)** notice (API tier ADVISORY) worded as *unverified*. Score 85 and it
   > goes out at once."
5. **Demo menu → Simulate monsoon event** (speed 4×). Zones turn yellow → orange → red on the 3D terrain,
   the rain columns grow, the counters count up, **Be alert (unconfirmed)** and **Danger (confirmed)** chips
   appear in the feed, the chime sounds, and the **Right now** bar at the top reads *N zones need
   attention · N reports waiting for check* with a button to the most urgent one. Click a Danger — the camera flies to the zone.
6. The drawer shows only risk score, **How sure**, **Why** (top 3) and **What to do**. Open
   **More details → Where this data comes from**: endpoint, ERA5 model, the grid cell used, fetched
   time, and **Verify live** — click it; the Open-Meteo page opens with the same numbers.

## 2:45 — The real sensor (or `make demo-live-sensor`)

7. Tilt the ESP32 (or press **T** three times in the fake-node terminal). Ticker:
   *Sensor HW-01 tilt +1.6° (LIVE hardware)*. The zone recomputes; the top factor is
   *Ground movement measured at sensor HW-01*. Risk climbs; a Danger (confirmed) fires; the siren topic
   `bhooshakti/siren/<zone>` is published (show with `mosquitto_sub -t 'bhooshakti/siren/#'`
   if a laptop is free).

## 3:20 — One click, two outcomes (`/control/moderation`)

8. On the open report: **CONFIRM: danger**. The be-alert notice becomes a confirmed Danger to the same
   recipients, the siren fires. On another: **DISMISS · all clear** — the *false report* follow-up
   goes to exactly the people the advisory reached. Open `/control/audit`: every automatic step
   is logged with the score breakdown.
9. Open `http://localhost:8000/api/cap/alerts.xml`: the same alerts as CAP 1.2, the format
   NDMA SACHET and cell broadcast consume.

## 4:00 — Does the model actually work? (`/replay`)

10. Read the summary card aloud: **"Warned before 16 of 34 held-out real landslides, median 63 h
    ahead; 18 missed; 3 of 6 same-season non-event weeks false-alarmed, 2 of 34 dry weeks."**
11. Pick **★ 2024-05-28 Aizawl** — play at 4×. Rain columns grow in 3D, the risk line crosses
    HIGH, banner: *Alert would have fired on 28 May 02:30 — 3.5 hours before the landslide*;
    then the red shockwave at the event with its source link. Switch to **Dry week**: risk stays low.
12. Pick **★ 2022-06-30 Noney/Tupul** — it is a **miss**, and the page says so.
    > "We show the misses. A system that hides them would get people killed."

## 4:50 — Close

> "Real weather, real past landslides, honest numbers, and a warning that reaches a feature
> phone in Nepali. What's left is integration, not invention: SMS and voice credentials, SACHET
> onboarding for cell broadcast, and sensors on real slopes."

---

## Likely judge questions

**"Isn't 16 of 34 poor?"** It is rainfall-only skill on a news-derived catalogue with 1–50 km
location error and a 25 km reanalysis, with the time of day usually unknown (we count only
warnings that beat the whole day). It is honest and reproducible — `make backtest` — and every
component that would raise it (real sensors, terrain data, SMS reports as corroboration) is
already wired in. We would rather show 16/34 than a 97% accuracy on synthetic data.

**"Why did Noney miss?"** ERA5 shows the rain, but at 25 km resolution the peak at the railway
cut was under the HIGH threshold; the slide was also on a freshly cut slope, which rainfall
cannot see. That is exactly where the tilt sensor and citizen reports come in.

**"What stops false reports from spamming the public?"** Scores, not single reports: an
advisory needs 60 points after 20 unacknowledged minutes or 85 at once, and three *different*
phone numbers are needed for the cluster bonus. Anonymous repeats count once. A second report
of the same slide joins the advisory already out. Dismissal sends an all-clear.

**"Who is liable for an automatic advisory?"** It is a tier below a warning, worded as
unverified, with a plain instruction (avoid the slope, await confirmation), and it exists only
because the alternative — a report nobody reads for an hour — is worse. The design decision,
the thresholds and every issuance are in the audit log for the district authority to own.

**"Is the weather really real?"** Click *Verify live* in any zone drawer: it opens the exact
Open-Meteo API URL for that zone's grid cell. The cache keeps the demo working offline.

**"Does it work with no internet at all?"** Keyword SMS (`LS`, `SAFE`, `JOIN`), missed-call IVR
with a voice report, outbound voice calls in the subscriber's language, CAP for cell broadcast,
and the siren topic for a LoRa/GSM relay. The PWA queues reports offline and sends later.

**"What is stubbed?"** SMS, voice and push gateways (real adapters for Twilio, MSG91, Exotel,
Expo; stubbed without credentials), SMTP email until `SMTP_*` is set, cell broadcast (needs
NDMA/telecom integration — our CAP feed is the input to it), and all but one sensor node.

**"How much does a sensor node cost?"** About ₹1,000 (ESP32 + MPU6050 + soil probe), ₹2,500
with a rain gauge; a LoRa variant for slopes with no Wi-Fi is described in `hardware/`.

**"How fast can this be deployed?"** `make setup` from a clean clone is under ten minutes
including the NASA download; Docker path included. Real deployment needs: provider keys,
a district roster, pincode→zone mapping for the district, and sensor installation.

**"What about Assamese voice?"** No mainstream TTS voice exists yet; we fall back to Bengali
(closest script and sound) and say so in the code and strings file. Recorded human prompts
would replace TTS in production.

## Label glossary (screen word → API value)

| On screen | API / database value |
|---|---|
| Be alert (unconfirmed) | `tier = ADVISORY` |
| Danger (confirmed) | `tier = WARNING` |
| How sure | `confidence` |
| Waiting for check | open escalations (`/reports/escalations`) |
| I'm checking | acknowledge (`POST /reports/{id}/acknowledge`) |
| Where this data comes from | weather provenance (`/zones/{id}/provenance`) |

Demo controls (Simulate monsoon event, speed, Reset demo, Send test alert, Warm map cache) live in
the **Demo** menu at the right end of the counter strip. `make demo-check` prints a green/red
readiness list (API, DB, model, MQTT, Open-Meteo, map tiles, SMTP) before you walk in.
