// ===== ESP32 + PaPIRs (AMN3111x) 1台分 =====
// Vdd->3V3, OUT->GPIO18, GND->GND
// Arduino IDE: ボードは "ESP32 Dev Module" 等

#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// ---------- USER SETTINGS ----------
#define WIFI_SSID "BuffaloAirStationPro"
#define WIFI_PASS "SummerCamp2018"

// Echonet Web API (MQTT Broker)
#define MQTT_BROKER "150.65.179.132"
#define MQTT_PORT   7883
#define CID         "53965d6805152d95"

// ★★ この1行だけ各機で変更（PIR1..PIR6）★★
#define DEV_ID      "PIR1"

// GPIO
static const int PIR_PIN = 18;

// Timing
static const uint32_t STABILIZE_MS = 30000; // 起動安定化
static const uint32_t HOLD_MS      = 1500;  // ON保持（ミリ秒）
static const uint32_t MIN_INTERVAL = 150;   // 最短Publish間隔
static const uint32_t HEARTBEAT_MS = 5000;  // 心拍

// Debounce-ish
static const uint32_t SHORT_PULSE_REJECT_MS = 50; // これ未満の単発は無視

// ---- MQTT Client ----
WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

// ---- State ----
bool     lastMotion     = false;
uint32_t lastChangeMs   = 0;
uint32_t lastPublishMs  = 0;
uint32_t lastHeartbeat  = 0;
bool     inHold         = false;
uint32_t holdUntil      = 0;

// ---------- Helpers ----------
void publishMqtt(const char* topic, const char* payload) {
  if (!mqttClient.publish(topic, payload)) {
    Serial.printf("Publish failed: %s\n", topic);
  } else {
    //Serial.printf("PUB %s\n  %s\n", topic, payload);
  }
}

void registerDevice() {
  char topic[128]; snprintf(topic, sizeof(topic), "/server/%s/register", CID);
  StaticJsonDocument<256> doc;
  doc["id"] = DEV_ID;
  doc["deviceType"] = "pirSensor";
  char payload[256]; serializeJson(doc, payload);
  publishMqtt(topic, payload);
}

void registerProperties() {
  char topic[160]; snprintf(topic, sizeof(topic), "/server/%s/%s/properties", CID, DEV_ID);
  StaticJsonDocument<512> doc;

  // manufacturer / protocol（例）
  JsonObject manufacturer = doc.createNestedObject("manufacturer");
  manufacturer["code"] = "0x000000";
  JsonObject desc = manufacturer.createNestedObject("descriptions");
  desc["ja"] = "JAIST"; desc["en"] = "JAIST";

  JsonObject protocol = doc.createNestedObject("protocol");
  protocol["type"] = "echonet_webapi_like";
  protocol["version"] = "1.0";

  // 初期値（プロパティ定義）
  doc["motion"] = false;               // 人感（true/false）
  doc["last_trigger_ms"] = (uint32_t)0;

  char payload[512]; serializeJson(doc, payload);
  publishMqtt(topic, payload);
}

void ensureWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("WiFi connecting");
  while (WiFi.status() != WL_CONNECTED) { delay(400); Serial.print("."); }
  Serial.printf("\nWiFi OK: %s\n", WiFi.localIP().toString().c_str());
}

void ensureMqtt() {
  if (mqttClient.connected()) return;
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  while (!mqttClient.connected()) {
    Serial.print("MQTT connecting...");
    String cid = String("esp32-") + DEV_ID;
    if (mqttClient.connect(cid.c_str())) {
      Serial.println("connected");
      delay(150);
      registerDevice();
      delay(200);
      registerProperties();
    } else {
      Serial.printf("fail rc=%d, retry in 2s\n", mqttClient.state());
      delay(2000);
    }
  }
}

// 値更新：/properties/motion（true/false）、/properties/last_trigger_ms
void publishMotion(bool motion) {
  const uint32_t now = millis();
  if (now - lastPublishMs < MIN_INTERVAL) return;
  lastPublishMs = now;

  // motion
  {
    char topic[192], payload[64];
    snprintf(topic, sizeof(topic), "/server/%s/%s/properties/motion", CID, DEV_ID);
    StaticJsonDocument<64> j; j["motion"] = motion; serializeJson(j, payload);
    publishMqtt(topic, payload);
  }
  // last_trigger_ms（ON時のみ更新）
  if (motion) {
    char topic[192], payload[64];
    snprintf(topic, sizeof(topic), "/server/%s/%s/properties/last_trigger_ms", CID, DEV_ID);
    StaticJsonDocument<64> j; j["last_trigger_ms"] = now; serializeJson(j, payload);
    publishMqtt(topic, payload);
  }
}

void heartbeat() {
  const uint32_t now = millis();
  if (now - lastHeartbeat < HEARTBEAT_MS) return;
  lastHeartbeat = now;

  char topic[192], payload[64];
  snprintf(topic, sizeof(topic), "/server/%s/%s/properties/heartbeat", CID, DEV_ID);
  StaticJsonDocument<64> j; j["alive"] = true; serializeJson(j, payload);
  publishMqtt(topic, payload);
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n--- PIR -> Echonet Web API (MQTT) ---");

  pinMode(PIR_PIN, INPUT_PULLUP);   // 外付けPUがあれば INPUT でもOK

  ensureWifi();
  ensureMqtt();

  Serial.println("Stabilizing PIR (≈30s)...");
  delay(STABILIZE_MS);
  Serial.println("Ready.");
}

void loop() {
  ensureWifi();
  ensureMqtt();
  mqttClient.loop();
  heartbeat();

  const uint32_t now = millis();
  const int raw = digitalRead(PIR_PIN); // HIGH=検出
  const bool motionRaw = (raw == HIGH);

  // 短パルス弾き（LOW->HIGHの瞬断対策）
  static bool lastRaw = false;
  static uint32_t rawRiseAt = 0;
  if (motionRaw && !lastRaw) rawRiseAt = now;
  lastRaw = motionRaw;

  bool motion = lastMotion;

  if (motionRaw) {
    // 立ち上がりが十分長い or 既に保持中
    if ((now - rawRiseAt) >= SHORT_PULSE_REJECT_MS || inHold) {
      motion = true;
      inHold = true;
      holdUntil = now + HOLD_MS;
    }
  } else {
    // 入力LOWでも、ホールド時間中はtrue維持
    if (inHold && now < holdUntil) {
      motion = true;
    } else {
      inHold = false;
      motion = false;
    }
  }

  if (motion != lastMotion) {
    lastMotion = motion;
    lastChangeMs = now;
    publishMotion(motion);
    Serial.printf("[%10lu ms] motion=%d\n", now, motion);
  }

  delay(5);
}
