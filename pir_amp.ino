#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// ===== Wi-Fi =====  ※必要に応じて書き換え
#define WIFI_SSID "BuffaloStationPro"
#define WIFI_PASS "SummerCamp2018"

// ===== Echonet Web API (MQTT Broker) =====
#define MQTT_BROKER "150.65.179.132"
#define MQTT_PORT   7883
#define CID         "53965d6805152d95"
#define DEV_ID      "pir-amp1"    // ←重複しないIDに

// ===== Pins =====
const int PIR1_PIN  = 26;   // HC-SR501
const int PIR2_PIN  = 27;   // Keyestudio等
const int MIC_A_PIN = 34;   // AMP A0 (ADC1)
const int MIC_D_PIN = 25;   // AMP D0 (digital)

// ===== Intervals =====
const uint32_t PUBLISH_EVERY_MS = 1000;   // 毎秒送信
const uint32_t PIR_WARMUP_MS    = 10000;  // PIR安定化待ち

// ===== MQTT =====
WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

// ===== State =====
unsigned long t0 = 0, lastTick = 0;
bool lastPir1=false, lastPir2=false;
bool lastSoundTrig=false;

// ---------- MQTT helpers ----------
void publishMqtt(const char* topic, const char* payload) {
  Serial.printf("PUB %s\n  %s\n", topic, payload);
  if (!mqttClient.publish(topic, payload)) Serial.println("  -> publish failed");
}

void registerDevice() {
  char topic[128]; snprintf(topic, sizeof(topic), "/server/%s/register", CID);
  StaticJsonDocument<256> doc;
  doc["id"] = DEV_ID;
  doc["deviceType"] = "pirSoundSensor";
  char payload[256]; serializeJson(doc, payload);
  publishMqtt(topic, payload);
}

void registerProperties() {
  char topic[128]; snprintf(topic, sizeof(topic), "/server/%s/%s/properties", CID, DEV_ID);
  StaticJsonDocument<1024> doc;

  JsonObject manufacturer = doc.createNestedObject("manufacturer");
  manufacturer["code"] = "0x000000";
  JsonObject desc = manufacturer.createNestedObject("descriptions");
  desc["ja"] = "JAIST"; desc["en"] = "JAIST";
  JsonObject protocol = doc.createNestedObject("protocol");
  protocol["type"] = "custom_mqtt"; protocol["version"] = "1.0";

  // 初期プロパティ
  doc["pir1"] = false;
  doc["pir2"] = false;
  doc["sound_amp"]  = 0;
  doc["sound_trig"] = false;

  char payload[1024]; serializeJson(doc, payload);
  publishMqtt(topic, payload);
}

void reconnectMqtt() {
  while (!mqttClient.connected()) {
    Serial.print("MQTT connecting...");
    String cid = String("esp32-") + DEV_ID;
    if (mqttClient.connect(cid.c_str())) {
      Serial.println("connected");
      registerDevice();
      delay(200);
      registerProperties();
    } else {
      Serial.printf("fail rc=%d, retry in 3s\n", mqttClient.state());
      delay(3000);
    }
  }
}

// ----------（任意）Wi-Fi簡易再接続 ----------
unsigned long lastWifiTry = 0;
bool ensureWiFi() {
  if (WiFi.status() == WL_CONNECTED) return true;
  if (millis() - lastWifiTry > 5000) {
    lastWifiTry = millis();
    Serial.println("WiFi reconnect...");
    WiFi.disconnect(true, true);
    delay(20);
    WiFi.begin(WIFI_SSID, WIFI_PASS);
  }
  return false;
}

// ===================================================================
// ==== drop-in: mic measurement with auto threshold & hysteresis ====
// （キャリブで決めたパラメータをそのまま使用）
const uint16_t FS_HZ2       = 4000;
const uint16_t WIN_MS2      = 20;
const uint16_t N_SAMPLES2   = FS_HZ2 * WIN_MS2 / 1000;
const float    DC_ALPHA2    = 0.02f;
const float    ENV_ALPHA2   = 0.20f;
const float    FLOOR_ALPHA2 = 0.01f;
const float    THR_GAIN2    = 4.0f;
const float    MIN_THR2     = 30.0f;
const float    HYST_FALL2   = 0.5f;
const uint16_t HOLD_MS2     = 250;

static float  dcMean2 = 2048.0f, env2 = 0.0f, noiseFlr2 = 0.0f;
static bool   trig2 = false;
static unsigned long trigUntil2 = 0;

// 1ウィンドウ分の計測と判定
// 返り値: amp(=env2のint) と trig2（true/false）
void readMicTuned(uint16_t &ampOut, bool &trigOut) {
  for (uint16_t i=0; i<N_SAMPLES2; ++i) {
    uint16_t x = analogRead(MIC_A_PIN);
    dcMean2 = (1.0f - DC_ALPHA2) * dcMean2 + DC_ALPHA2 * x;
    float ac = fabsf((float)x - dcMean2);
    env2 = (1.0f - ENV_ALPHA2) * env2 + ENV_ALPHA2 * ac;
    delayMicroseconds(1000000UL / FS_HZ2);
  }

  float thr = noiseFlr2 * THR_GAIN2 + MIN_THR2;
  if (env2 < thr) {
    noiseFlr2 = (1.0f - FLOOR_ALPHA2) * noiseFlr2 + FLOOR_ALPHA2 * env2;
  }
  thr = noiseFlr2 * THR_GAIN2 + MIN_THR2;

  bool d0   = (digitalRead(MIC_D_PIN) == HIGH);
  bool cand = (env2 >= thr) || d0;

  unsigned long now = millis();
  if (trig2) {
    if (now >= trigUntil2 && env2 < thr * HYST_FALL2 && !d0) trig2 = false;
  } else {
    if (cand) { trig2 = true; trigUntil2 = now + HOLD_MS2; }
  }

  ampOut  = (uint16_t)env2;
  trigOut = trig2;
}
// ===================================================================

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n--- PIR x2 + AMP x1 to ELWA/MQTT ---");

  // Wi-Fi
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("WiFi connecting");
  while (WiFi.status() != WL_CONNECTED) { delay(400); Serial.print("."); }
  Serial.printf("\nWiFi OK: %s\n", WiFi.localIP().toString().c_str());

  // MQTT
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);

  // Pins
  pinMode(PIR1_PIN, INPUT);
  pinMode(PIR2_PIN, INPUT);
  pinMode(MIC_D_PIN, INPUT);
  analogReadResolution(12);                     // 0..4095
  analogSetPinAttenuation(MIC_A_PIN, ADC_11db); // ~0..3.3V

  t0 = millis();
}

void loop() {
  // ネットワーク維持
  if (ensureWiFi()) {
    if (!mqttClient.connected()) reconnectMqtt();
    mqttClient.loop();
  }

  const unsigned long now = millis();
  if (now - lastTick < PUBLISH_EVERY_MS) return;
  lastTick = now;

  // --- PIR（ウォームアップ） ---
  bool warm = (now - t0 < PIR_WARMUP_MS);
  bool pir1=false, pir2=false;
  if (!warm) {
    pir1 = (digitalRead(PIR1_PIN) == HIGH);
    pir2 = (digitalRead(PIR2_PIN) == HIGH);
  } else {
    uint32_t left = (PIR_WARMUP_MS - (now - t0) + 999) / 1000;
    Serial.printf("[warmup] PIR stabilize... %lus\n", left);
  }

  // --- AMP計測 ---
  uint16_t amp; bool trig;
  readMicTuned(amp, trig);

  // ===== Serial debug =====
  if (!warm) {
    Serial.printf("{\"pir1\":%s,\"pir2\":%s}  ", pir1 ? "true":"false", pir2 ? "true":"false");
  }
  Serial.printf("sound_amp=%u trig=%s\n", amp, trig ? "true":"false");

  // ===== MQTT Publish =====
  // PIRは毎秒（ウォームアップ中は送らない）
  if (!warm) {
    { // pir1
      char topic[160], payload[128];
      snprintf(topic, sizeof(topic), "/server/%s/%s/properties/pir1", CID, DEV_ID);
      StaticJsonDocument<64> j; j["pir1"] = pir1;
      serializeJson(j, payload); publishMqtt(topic, payload);
    }
    { // pir2
      char topic[160], payload[128];
      snprintf(topic, sizeof(topic), "/server/%s/%s/properties/pir2", CID, DEV_ID);
      StaticJsonDocument<64> j; j["pir2"] = pir2;
      serializeJson(j, payload); publishMqtt(topic, payload);
    }
  }

  // AMP: 毎秒 amp、変化時のみ trig
  { // sound_amp
    char topic[160], payload[128];
    snprintf(topic, sizeof(topic), "/server/%s/%s/properties/sound_amp", CID, DEV_ID);
    StaticJsonDocument<64> j; j["sound_amp"] = amp;
    serializeJson(j, payload); publishMqtt(topic, payload);
  }
  if (trig != lastSoundTrig) {
    lastSoundTrig = trig;
    char topic[160], payload[128];
    snprintf(topic, sizeof(topic), "/server/%s/%s/properties/sound_trig", CID, DEV_ID);
    StaticJsonDocument<64> j; j["sound_trig"] = trig;
    serializeJson(j, payload); publishMqtt(topic, payload);
  }
}
