#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// ===== Wi-Fi =====
#define WIFI_SSID "BuffaloAirStationPro"
#define WIFI_PASS "SummerCamp2018"

// ===== Echonet Web API (MQTT Broker) =====
#define MQTT_BROKER "150.65.179.132"
#define MQTT_PORT   7883
#define CID         "53965d6805152d95"
#define DEV_ID      "door-amp1"   // 必要に応じて変更

// ===== Pins =====
const int HALL_PIN   = 27;  // ホールセンサー（アクティブLow=磁石あり=閉）
const int MIC_A_PIN  = 34;  // マイク A0（ADC1 専用入力）
const int MIC_D_PIN  = 26;  // マイク D0（デジタル出力）

// ===== Publish intervals =====
const uint32_t MIC_PUBLISH_MS  = 1000; // sound_amp 毎秒
const uint32_t DOOR_PUBLISH_MS = 1000; // door 毎秒

// ===== MQTT Client =====
WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

// ===== State =====
unsigned long lastMicMs  = 0;
unsigned long lastDoorMs = 0;
bool lastDoorClosed = false;
bool lastSoundTrig  = false;

// ---------- MQTT helpers ----------
void publishMqtt(const char* topic, const char* payload) {
  Serial.printf("PUB %s\n  %s\n", topic, payload);
  if (!mqttClient.publish(topic, payload)) {
    Serial.println("  -> publish failed");
  }
}

void registerDevice() {
  char topic[128]; snprintf(topic, sizeof(topic), "/server/%s/register", CID);
  StaticJsonDocument<256> doc;
  doc["id"] = DEV_ID;
  doc["deviceType"] = "doorSoundSensor";
  char payload[256]; serializeJson(doc, payload);
  publishMqtt(topic, payload);
}

void registerProperties() {
  char topic[128]; snprintf(topic, sizeof(topic), "/server/%s/%s/properties", CID, DEV_ID);
  StaticJsonDocument<512> doc;

  JsonObject manufacturer = doc.createNestedObject("manufacturer");
  manufacturer["code"] = "0x000000";
  JsonObject desc = manufacturer.createNestedObject("descriptions");
  desc["ja"] = "JAIST"; desc["en"] = "JAIST";
  JsonObject protocol = doc.createNestedObject("protocol");
  protocol["type"] = "custom_mqtt"; protocol["version"] = "1.0";

  // 初期値
  doc["door"]        = "OPEN";
  doc["sound_amp"]   = 0;
  doc["sound_trig"]  = false;

  char payload[512]; serializeJson(doc, payload);
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

static float  dcMean2   = 2048.0f, env2 = 0.0f, noiseFlr2 = 0.0f;
static bool   trig2     = false;
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
  Serial.println("\n--- Door + Mic (auto-threshold) to ELWA/MQTT ---");

  // Wi-Fi
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("WiFi connecting");
  while (WiFi.status() != WL_CONNECTED) { delay(400); Serial.print("."); }
  Serial.printf("\nWiFi OK: %s\n", WiFi.localIP().toString().c_str());

  // MQTT
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);

  // Pins
  pinMode(HALL_PIN, INPUT);
  pinMode(MIC_D_PIN, INPUT);
  analogReadResolution(12);                   // 0..4095
  analogSetPinAttenuation(MIC_A_PIN, ADC_11db); // ~0..3.3V

  // 初期状態
  lastDoorClosed = (digitalRead(HALL_PIN) == LOW);
  lastSoundTrig  = false;
}

void loop() {
  // MQTT keep-alive
  if (!mqttClient.connected()) reconnectMqtt();
  mqttClient.loop();

  const unsigned long now = millis();

  // ---- Mic: every 1s send sound_amp, and sound_trig only on change ----
  if (now - lastMicMs >= MIC_PUBLISH_MS) {
    lastMicMs = now;

    uint16_t amp; bool trig;
    readMicTuned(amp, trig);

    // sound_amp（毎秒）
    {
      char topic[160], payload[160];
      snprintf(topic, sizeof(topic), "/server/%s/%s/properties/sound_amp1", CID, DEV_ID);
      StaticJsonDocument<64> j; j["sound_amp"] = amp; serializeJson(j, payload);
      publishMqtt(topic, payload);
    }
    Serial.printf("sound_amp=%u\n", amp);

    // sound_trig（変化時のみ）
    if (trig != lastSoundTrig) {
      lastSoundTrig = trig;
      char topic[160], payload[160];
      snprintf(topic, sizeof(topic), "/server/%s/%s/properties/sound_trig", CID, DEV_ID);
      StaticJsonDocument<64> j; j["sound_trig"] = trig; serializeJson(j, payload);
      publishMqtt(topic, payload);
      Serial.printf("sound_trig=%s\n", trig ? "true" : "false");
    }
  }

  // ---- Door: every 1s always send OPEN/CLOSED ----
  if (now - lastDoorMs >= DOOR_PUBLISH_MS) {
    lastDoorMs = now;

    bool doorClosed = (digitalRead(HALL_PIN) == LOW); // アクティブLow
    char topic[160], payload[160];
    snprintf(topic, sizeof(topic), "/server/%s/%s/properties/door", CID, DEV_ID);
    StaticJsonDocument<64> d; d["door"] = doorClosed ? "CLOSED" : "OPEN";
    serializeJson(d, payload);
    publishMqtt(topic, payload);

    if (doorClosed != lastDoorClosed) {
      lastDoorClosed = doorClosed;
      Serial.printf("Door changed: %s\n", doorClosed ? "CLOSED" : "OPEN");
    }
    Serial.printf("door=%s\n", doorClosed ? "CLOSED" : "OPEN");
  }
}
