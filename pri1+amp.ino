#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <math.h>

// ===== Wi-Fi =====  ※必要に応じて書き換え
#define WIFI_SSID "BuffaloStationPro"
#define WIFI_PASS "SummerCamp2018"

// ===== Echonet Web API (MQTT Broker) =====
#define MQTT_BROKER "150.65.179.132"
#define MQTT_PORT   7883
#define CID         "53965d6805152d95"
#define DEV_ID      "pir-amp1"    // ←重複しないIDに

// ===== Pins =====
const int PIR2_PIN  = 27;   // PIR（Keyestudio 等）
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
bool lastPir2=false;
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
  doc["pir2"]         = false;
  doc["sound_amp"]    = 0;
  doc["sound_trig"]   = false;
  doc["mic_occupied"] = false;
  // （必要ならデバッグ用）doc["mic_score"] = 0;

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

// ---------- Wi-Fi簡易再接続 ----------
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
// == Mic Presence Detection (Noise-Hardened) for room occupancy    ==
// Pins: MIC_A_PIN (ADC1=34), MIC_D_PIN (25)
// 1秒周期くらいで readMicPresence(...) を呼び出してください。
// 出力：amp / trig / occupied / score
// ===================================================================

// ---- サンプリング設定 ----
static const uint16_t FS_HZ     = 4000;   // 4 kHz
static const uint16_t WIN_MS    = 30;     // 30ms/窓
static const uint16_t N_SAMP    = (FS_HZ * WIN_MS) / 1000; // =120

// ---- フィルタ係数 ----
static const float  DC_A        = 0.02f;  // DCトラッキング
static const float  ENV_FAST_A  = 0.25f;  // 窓内エンベロープ
static const float  ENV_SLOW_A  = 0.10f;  // 窓間エンベロープ

// ---- 可変ノイズ床（上昇は遅く・下降は速く）----
static const float  FLR_UP_A    = 0.002f; // ↑ゆっくり
static const float  FLR_DN_A    = 0.02f;  // ↓速い

// ---- 閾値・瞬時イベント判定 ----
static const float  THR_GAIN    = 4.5f;   // 4.5〜6.0で部屋に合わせ調整
static const float  MIN_THR     = 35.0f;  // 25〜80で調整
static const float  HYST_FALL   = 0.55f;
static const uint16_t HOLD_MS   = 300;

// ---- スパイク除去/揺らぎ抑制 ----
static const uint8_t  ON_STREAK   = 2;
static const uint8_t  OFF_STREAK  = 2;
static const float    MOD_MIN     = 0.08f; // 0.10〜0.15でさらに厳しく

// ---- 在室スコア ----
static const uint8_t  SCORE_MAX   = 20;
static const uint8_t  SCORE_ON    = 8;    // 在室ON閾
static const uint8_t  SCORE_OFF   = 3;    // 在室OFF閾
static const uint8_t  INC_EVENT   = 2;    // イベントで +2
static const uint8_t  INC_D0BONUS = 1;    // D0 High でさらに +1
static const uint8_t  DEC_IDLE    = 1;    // イベントなしで -1/秒

// ---- 内部状態 ----
static float  dcMean   = 2048.0f;
static float  envFast  = 0.0f;
static float  envSlow  = 0.0f;
static float  noiseFlr = 0.0f;

static bool   eventTrig   = false;
static unsigned long trigUntil = 0;
static uint8_t onStreak = 0, offStreak = 0, d0Streak = 0;

static uint8_t occScore = 0;
static bool    occupied = false;

// メディアン（5窓）
static float median5(float a, float b, float c, float d, float e) {
  float x[5] = {a,b,c,d,e};
  for (int i=0;i<4;i++) for (int j=i+1;j<5;j++) if (x[j]<x[i]) { float t=x[i]; x[i]=x[j]; x[j]=t; }
  return x[2];
}
static float winBuf[5] = {0,0,0,0,0};
static uint8_t winIdx = 0;

void readMicPresence(uint16_t &ampOut, bool &trigOut, bool &occupiedOut, uint8_t &scoreOut) {
  float deltaSum = 0.0f;

  for (uint16_t i=0; i<N_SAMP; ++i) {
    uint16_t x = analogRead(MIC_A_PIN);
    dcMean  = (1.0f - DC_A) * dcMean + DC_A * x;
    float ac = fabsf((float)x - dcMean);
    float envFastOld = envFast;
    envFast = (1.0f - ENV_FAST_A) * envFast + ENV_FAST_A * ac;
    deltaSum += fabsf(envFast - envFastOld);
    delayMicroseconds(1000000UL / FS_HZ);
  }

  // 窓間エンベロープ
  envSlow = (1.0f - ENV_SLOW_A) * envSlow + ENV_SLOW_A * envFast;

  // メディアン（5窓）
  winBuf[winIdx] = envSlow; winIdx = (winIdx + 1) % 5;
  float envMed = median5(winBuf[0], winBuf[1], winBuf[2], winBuf[3], winBuf[4]);

  // ノイズ床（上昇遅・下降速）
  if (envMed < noiseFlr) noiseFlr = (1.0f - FLR_DN_A) * noiseFlr + FLR_DN_A * envMed;
  else                   noiseFlr = (1.0f - FLR_UP_A) * noiseFlr + FLR_UP_A * envMed;

  float thr = noiseFlr * THR_GAIN + MIN_THR;

  // 変調度（定常騒音の弾き）
  float mod = (envMed > 1.0f) ? (deltaSum / (float)N_SAMP) / envMed : 0.0f;

  // D0（デジタル）窓デバウンス
  bool d0 = (digitalRead(MIC_D_PIN) == HIGH);
  d0Streak = d0 ? (uint8_t)min<int>(255, d0Streak+1) : 0;

  // イベント候補
  bool cand = ((envMed >= thr) && (mod >= MOD_MIN)) || (d0Streak >= 1);

  // 瞬時イベント：ヒステリシス＋保持
  unsigned long now = millis();
  if (eventTrig) {
    bool offCond = (envMed < thr*HYST_FALL) && !d0 && (mod < MOD_MIN);
    offStreak = offCond ? (uint8_t)min<int>(255, offStreak+1) : 0;
    if (now >= trigUntil && offStreak >= OFF_STREAK) {
      eventTrig = false; onStreak = 0;
    }
  } else {
    onStreak = cand ? (uint8_t)min<int>(255, onStreak+1) : 0;
    if (onStreak >= ON_STREAK) {
      eventTrig = true; trigUntil = now + HOLD_MS; offStreak = 0;
    }
  }

  // 在室スコア（ゆっくり上下）
  if (eventTrig) {
    uint8_t inc = INC_EVENT + (d0 ? INC_D0BONUS : 0);
    occScore = (uint8_t)min<int>(SCORE_MAX, occScore + inc);
  } else {
    occScore = (occScore > DEC_IDLE) ? (occScore - DEC_IDLE) : 0;
  }

  // 在室ヒステリシス
  if (!occupied && occScore >= SCORE_ON)  occupied = true;
  if ( occupied && occScore <= SCORE_OFF) occupied = false;

  // 出力
  ampOut      = (uint16_t)envMed;
  trigOut     = eventTrig;
  occupiedOut = occupied;
  scoreOut    = occScore;
}
// ===================================================================

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n--- PIR(27) + AMP presence to ELWA/MQTT ---");

  // Wi-Fi
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("WiFi connecting");
  while (WiFi.status() != WL_CONNECTED) { delay(400); Serial.print("."); }
  Serial.printf("\nWiFi OK: %s\n", WiFi.localIP().toString().c_str());

  // MQTT
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);

  // Pins
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

  // --- PIR（GPIO27 / ウォームアップ） ---
  bool warm = (now - t0 < PIR_WARMUP_MS);
  bool pir2=false;
  if (!warm) {
    pir2 = (digitalRead(PIR2_PIN) == HIGH);
  } else {
    uint32_t left = (PIR_WARMUP_MS - (now - t0) + 999) / 1000;
    Serial.printf("[warmup] PIR stabilize... %lus\n", left);
  }

  // --- AMP 在室版 ---
  uint16_t amp; bool trig, occupied; uint8_t score;
  readMicPresence(amp, trig, occupied, score);

  // ===== Serial debug =====
  if (!warm) Serial.printf("{\"pir2\":%s}  ", pir2 ? "true":"false");
  Serial.printf("amp=%u trig=%s occ=%s score=%u\n",
                amp, trig ? "true":"false", occupied ? "true":"false", score);

  // ===== MQTT Publish =====
  // PIRは毎秒（ウォームアップ中は送らない）
  if (!warm) {
    char topic[160], payload[128];
    snprintf(topic, sizeof(topic), "/server/%s/%s/properties/pir2", CID, DEV_ID);
    StaticJsonDocument<64> j; j["pir2"] = pir2;
    serializeJson(j, payload); publishMqtt(topic, payload);
  }

  // AMP: 毎秒 amp / occupied、trig は変化時のみ
  { // sound_amp
    char topic[160], payload[128];
    snprintf(topic, sizeof(topic), "/server/%s/%s/properties/sound_amp", CID, DEV_ID);
    StaticJsonDocument<64> j; j["sound_amp"] = amp;
    serializeJson(j, payload); publishMqtt(topic, payload);
  }
  { // mic_occupied
    char topic[160], payload[128];
    snprintf(topic, sizeof(topic), "/server/%s/%s/properties/mic_occupied", CID, DEV_ID);
    StaticJsonDocument<64> j; j["mic_occupied"] = occupied;
    serializeJson(j, payload); publishMqtt(topic, payload);
  }
  if (trig != lastSoundTrig) {
    lastSoundTrig = trig;
    char topic[160], payload[128];
    snprintf(topic, sizeof(topic), "/server/%s/%s/properties/sound_trig", CID, DEV_ID);
    StaticJsonDocument<64> j; j["sound_trig"] = trig;
    serializeJson(j, payload); publishMqtt(topic, payload);
  }

  // （必要ならデバッグ用スコア出力を追加でPublish可能）
  // char topic[160], payload[128];
  // snprintf(topic, sizeof(topic), "/server/%s/%s/properties/mic_score", CID, DEV_ID);
  // StaticJsonDocument<64> js; js["mic_score"] = score;
  // serializeJson(js, payload); publishMqtt(topic, payload);
}
