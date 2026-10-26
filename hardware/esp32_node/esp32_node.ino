/*
 * BHOOSHAKTI AI — slope sensor node (ESP32 + MPU6050 + capacitive soil probe
 * + optional tipping-bucket rain gauge).
 *
 * Publishes the SAME JSON the simulator does (backend/scripts/sensor_simulator.py)
 * to MQTT topic  bhooshakti/sensors/<NODE_ID>  every PUBLISH_MS:
 *
 *   {"node_id":"HW-01","ts":"2026-10-24T11:32:05Z","rainfall_mm":0.28,
 *    "soil_moisture_pct":63.4,"tilt_deg":0.12,"battery_pct":null,"source":"hardware"}
 *
 * tilt_deg is the angle between the board's current "down" and the "down" it
 * measured at power-on, so it reads ~0 where it was installed and grows as
 * the slope (and the stake the board is on) rotates.
 *
 * The backend only shows the green LIVE dot for a node registered as
 * source='hardware' in the database (HW-01 is seeded that way). Wiring,
 * parts and the demo script: README.md, "Demo with a real sensor".
 *
 * Libraries (Arduino Library Manager): PubSubClient by Nick O'Leary.
 * Board: "ESP32 Dev Module" (esp32 core >= 2.0).
 */

#include <WiFi.h>
#include <Wire.h>
#include <PubSubClient.h>
#include <time.h>
#include <math.h>

// ============================== CONFIGURE ME ================================
const char* WIFI_SSID     = "your-wifi";
const char* WIFI_PASSWORD = "your-password";
// The laptop running mosquitto (same Wi-Fi). Find it with `ipconfig getifaddr en0`.
const char* MQTT_HOST     = "192.168.1.50";
const int   MQTT_PORT     = 1883;
const char* NODE_ID       = "HW-01";          // must match a sensor_nodes row
const unsigned long PUBLISH_MS = 5000;

// Capacitive soil probe v1.2/v2.0 on an ADC1 pin (ADC2 is unusable with Wi-Fi).
const int   SOIL_PIN      = 34;
// Calibrate: read the raw value in dry air and in a glass of water.
const int   SOIL_RAW_DRY  = 3200;
const int   SOIL_RAW_WET  = 1350;

// Tipping-bucket rain gauge (reed switch to GND), optional. -1 to disable.
const int   RAIN_PIN      = 27;
const float MM_PER_TIP    = 0.2794;            // typical 0.011" bucket

// Battery through a 100k/100k divider on GPIO35, optional. -1 to disable.
const int   BATTERY_PIN   = -1;
// ============================================================================

const uint8_t MPU_ADDR = 0x68;                  // AD0 low
WiFiClient wifi;
PubSubClient mqtt(wifi);

float baseX = 0, baseY = 0, baseZ = 1;          // gravity direction at power-on
volatile unsigned long rainTips = 0;
volatile unsigned long lastTipMs = 0;
unsigned long lastPublish = 0;

void IRAM_ATTR onRainTip() {
  unsigned long now = millis();
  if (now - lastTipMs > 200) {                  // debounce the reed switch
    rainTips++;
    lastTipMs = now;
  }
}

void mpuWrite(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  Wire.write(val);
  Wire.endTransmission();
}

bool readAccel(float& ax, float& ay, float& az) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x3B);                             // ACCEL_XOUT_H
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(MPU_ADDR, (uint8_t)6) != 6) return false;
  int16_t x = (Wire.read() << 8) | Wire.read();
  int16_t y = (Wire.read() << 8) | Wire.read();
  int16_t z = (Wire.read() << 8) | Wire.read();
  ax = x / 16384.0; ay = y / 16384.0; az = z / 16384.0;   // +-2 g range
  return true;
}

// Average many samples: a single reading jitters by ~0.1 degree.
bool gravity(float& gx, float& gy, float& gz, int n = 50) {
  float sx = 0, sy = 0, sz = 0, ax, ay, az;
  int ok = 0;
  for (int i = 0; i < n; i++) {
    if (readAccel(ax, ay, az)) { sx += ax; sy += ay; sz += az; ok++; }
    delay(2);
  }
  if (!ok) return false;
  float m = sqrt(sx * sx + sy * sy + sz * sz);
  gx = sx / m; gy = sy / m; gz = sz / m;
  return true;
}

float tiltDegrees() {
  float gx, gy, gz;
  if (!gravity(gx, gy, gz)) return NAN;
  float dot = gx * baseX + gy * baseY + gz * baseZ;
  dot = fmaxf(-1.0f, fminf(1.0f, dot));
  return acosf(dot) * 180.0f / PI;
}

float soilPercent() {
  long sum = 0;
  for (int i = 0; i < 16; i++) { sum += analogRead(SOIL_PIN); delay(2); }
  float raw = sum / 16.0;
  float pct = (SOIL_RAW_DRY - raw) * 100.0 / (SOIL_RAW_DRY - SOIL_RAW_WET);
  return fmaxf(0.0f, fminf(100.0f, pct));
}

void connectWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.printf("Wi-Fi: connecting to %s", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  for (int i = 0; i < 60 && WiFi.status() != WL_CONNECTED; i++) { delay(500); Serial.print("."); }
  Serial.println(WiFi.status() == WL_CONNECTED ? " ok" : " FAILED (will retry)");
  if (WiFi.status() == WL_CONNECTED) {
    configTime(0, 0, "pool.ntp.org", "time.google.com");   // UTC timestamps
  }
}

void connectMqtt() {
  while (!mqtt.connected()) {
    String id = String("bhooshakti-") + NODE_ID;
    Serial.printf("MQTT: connecting to %s:%d ... ", MQTT_HOST, MQTT_PORT);
    if (mqtt.connect(id.c_str())) { Serial.println("ok"); return; }
    Serial.printf("failed rc=%d, retry in 3 s\n", mqtt.state());
    delay(3000);
  }
}

String isoNow() {
  time_t now = time(nullptr);
  if (now < 1700000000) return String("");      // NTP not synced: server stamps it
  struct tm t;
  gmtime_r(&now, &t);
  char buf[25];
  strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", &t);
  return String(buf);
}

void setup() {
  Serial.begin(115200);
  delay(200);
  Wire.begin(21, 22);                           // SDA, SCL
  mpuWrite(0x6B, 0x00);                         // wake the MPU6050
  mpuWrite(0x1C, 0x00);                         // accel +-2 g
  mpuWrite(0x1A, 0x04);                         // ~20 Hz low-pass
  delay(100);
  if (!gravity(baseX, baseY, baseZ, 200)) {
    Serial.println("MPU6050 not found — check SDA=21, SCL=22, VCC=3V3");
  } else {
    Serial.printf("Baseline gravity: %.3f %.3f %.3f (tilt is measured from here)\n", baseX, baseY, baseZ);
  }
  analogReadResolution(12);
  if (RAIN_PIN >= 0) {
    pinMode(RAIN_PIN, INPUT_PULLUP);
    attachInterrupt(digitalPinToInterrupt(RAIN_PIN), onRainTip, FALLING);
  }
  connectWifi();
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
}

void loop() {
  connectWifi();
  if (WiFi.status() != WL_CONNECTED) { delay(1000); return; }
  connectMqtt();
  mqtt.loop();

  if (millis() - lastPublish < PUBLISH_MS) return;
  lastPublish = millis();

  noInterrupts();
  unsigned long tips = rainTips;
  rainTips = 0;
  interrupts();

  float tilt = tiltDegrees();
  float soil = soilPercent();
  String ts = isoNow();

  String body = "{\"node_id\":\"" + String(NODE_ID) + "\"";
  if (ts.length()) body += ",\"ts\":\"" + ts + "\"";
  body += ",\"rainfall_mm\":" + (RAIN_PIN >= 0 ? String(tips * MM_PER_TIP, 3) : String("null"));
  body += ",\"soil_moisture_pct\":" + String(soil, 1);
  body += ",\"tilt_deg\":" + (isnan(tilt) ? String("null") : String(tilt, 3));
  if (BATTERY_PIN >= 0) {
    float v = analogReadMilliVolts(BATTERY_PIN) * 2 / 1000.0;           // divider x2
    float pct = fmaxf(0, fminf(100, (v - 3.3) / (4.2 - 3.3) * 100));    // 1S Li-ion
    body += ",\"battery_pct\":" + String(pct, 0);
  } else {
    body += ",\"battery_pct\":null";
  }
  body += ",\"source\":\"hardware\"}";

  String topic = String("bhooshakti/sensors/") + NODE_ID;
  bool ok = mqtt.publish(topic.c_str(), body.c_str());
  Serial.printf("%s %s\n", ok ? "->" : "!!", body.c_str());
}
