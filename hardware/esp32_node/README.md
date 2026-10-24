# ESP32 slope sensor node

`esp32_node.ino` turns an ESP32, an MPU6050 and a capacitive soil probe (plus an
optional tipping-bucket rain gauge) into a BHOOSHAKTI sensor node. It publishes
the same JSON as the simulator to `bhooshakti/sensors/HW-01` every 5 s.

Full wiring table, parts list with prices and the demo script are in the main
[README → Demo with a real sensor](../../README.md#demo-with-a-real-sensor).

## Flash it

1. Arduino IDE → Boards Manager → install **esp32 by Espressif** (2.x or 3.x).
2. Library Manager → install **PubSubClient** (Nick O'Leary).
3. Open `esp32_node.ino`, set `WIFI_SSID`, `WIFI_PASSWORD` and `MQTT_HOST`
   (the laptop running mosquitto: `ipconfig getifaddr en0` on macOS).
4. Board: *ESP32 Dev Module*. Upload, open Serial Monitor at 115200.
5. Keep the board still for the first second after power-on — that reading is
   the zero for tilt.

Mosquitto must accept LAN connections: `infra/mosquitto/mosquitto.conf` already
listens on `0.0.0.0:1883` with anonymous access for the demo.

> The sketch was written against the documented ESP32 Arduino and PubSubClient
> APIs but has not been compiled on this machine (no Arduino toolchain was
> installed). Expect to fix at most trivial build issues on first upload.

## Calibrating the soil probe

Print `analogRead(34)` with the probe in dry air (≈3200) and in a glass of
water (≈1350), and put those into `SOIL_RAW_DRY` / `SOIL_RAW_WET`.

## LoRa variant (no Wi-Fi on the slope)

Real slopes rarely have Wi-Fi. Swap the ESP32 for a **Heltec WiFi LoRa 32 (V3)**
or a **TTGO LoRa32** (both ESP32 + SX1262/SX1276) and send the same JSON as a
LoRa packet instead of MQTT. A second LoRa board at the panchayat office (with
Wi-Fi or a GSM modem) receives it and republishes to MQTT — a single-channel
gateway is ~40 lines with the `RadioLib` library. Range in hill terrain is
typically 2–5 km line of sight at SF9/125 kHz. Keep the payload under ~120
bytes (drop `ts` and let the gateway stamp it) and publish every 60 s, not 5 s,
to respect duty-cycle limits on IN865 (865–867 MHz). The same gateway can drive
the siren relay subscribed to `bhooshakti/siren/<zone_id>`.
