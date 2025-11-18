#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <NTPClient.h>
#include <WiFiUdp.h>

// ===== Wi-Fi =====
#define WIFI_SSID "BuffaloAirStationPro"
#define WIFI_PASS "SummerCamp2018"

// ===== MQTT (ECHONET Web API broker) =====
#define MQTT_BROKER "150.65.179.132"
#define MQTT_PORT   7883
#define CID         "53965d6805152d95"

// ===== Device ID =====
#define DEV_ID "PIR11"   // ★★★ DEV_ID を "PIR5" に設定 ★★★

// ===== Pins =====
const int PIR_PIN = 32; // ★★★ PaPIRs OUTピンをGPIO 32 (アナログ入力) に接続 ★★★

// ===== Timing =====
const unsigned long STABILIZE_MS   = 30000;   // 起動安定化
const unsigned long HOLD_MS        = 2000;    // ★★★ 検出後の保持時間を 2000ms (2秒) に設定 ★★★
const unsigned long PRINT_INTERVAL = 1000;    // 表示周期
const unsigned long HEALTH_INTERVAL = 60000;  // 健全性チェック（毎分）
const unsigned long PUBLISH_INTERVAL = 1000;  // 毎秒publishする間隔

// ===== Analog PaPIRs Detection Variables =====
const int THRESHOLD = 550; // ★★★ 調整済みの閾値 500 を適用 ★★★
int baselineValue = 0;
unsigned long motionEnd = 0; // 動き検知の保持終了時刻

// ===== MQTT Client =====
WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

// ===== NTP (現在時刻表示用) =====
WiFiUDP ntpUDP;
NTPClient timeClient(ntpUDP, "ntp.nict.jp", 9 * 3600, 60000); // JST (+9h)

// ===== State =====
bool lastMotion = false; // 状態変化チェック用
unsigned long lastPrint = 0;
unsigned long lastHealth = 0;
unsigned long lastPublish = 0; 

// ---------- Helper ----------
void publishMqtt(const char* topic, const char* payload) {
  bool ok = mqttClient.publish(topic, payload);
  Serial.printf("[MQTT] %s (%s)\n", topic, ok ? "OK" : "FAILED");
}

void registerDevice() {
  char topic[128]; snprintf(topic, sizeof(topic), "/server/%s/register", CID);
  StaticJsonDocument<128> doc;
  doc["id"] = DEV_ID;
  doc["deviceType"] = "pirSensor";
  char payload[128]; serializeJson(doc, payload);
  publishMqtt(topic, payload);
}

void registerProperties() {
  char topic[160]; snprintf(topic, sizeof(topic), "/server/%s/%s/properties", CID, DEV_ID);
  StaticJsonDocument<256> doc;
  doc["motion"] = false;
  doc["description"] = "Human presence sensor (PIR)";
  char payload[256]; serializeJson(doc, payload);
  publishMqtt(topic, payload);
}

void reconnectMqtt() {
  while (!mqttClient.connected()) {
    Serial.print("MQTT connecting...");
    // ESP32用クライアントID
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

// ============================================================
// ★★★ SETUP: アナログセンサの安定化とキャリブレーションを追加 ★★★
// ============================================================
void setup() {
  Serial.begin(115200);
  pinMode(PIR_PIN, INPUT); // アナログピンとして設定

  Serial.println("\n=== PaPIRs Analog Sensor Init and MQTT Start ===");

  // Wi-Fi接続
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("WiFi connecting");
  while (WiFi.status() != WL_CONNECTED) { delay(400); Serial.print("."); }
  Serial.printf("\nWiFi OK: %s\n", WiFi.localIP().toString().c_str());

  // NTP
  timeClient.begin();
  timeClient.update();
  Serial.printf("Time: %s\n", timeClient.getFormattedTime().c_str());

  // --- センサ安定化とキャリブレーション ---
  Serial.println("Stabilizing PaPIRs (≈30s)...");
  // 回路安定時間（Twu: 30秒）待機
  for(int i = STABILIZE_MS / 1000; i > 0; i--) {
    Serial.printf("Stabilizing... %d\n", i);
    delay(1000);
  }
  
  // 安定状態の電圧を基準値として取得（キャリブレーション）
  long sum = 0;
  for(int i=0; i<100; i++) {
    sum += analogRead(PIR_PIN);
    delay(10);
  }
  baselineValue = sum / 100;
  
  Serial.printf("Baseline Value: %d (Approx. %.2fV)\n", baselineValue, (baselineValue * 3.3 / 4095.0));
  Serial.printf("Detection THRESHOLD set to: %d\n", THRESHOLD);
  Serial.println("Ready to detect.");

  // MQTT
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  reconnectMqtt();
}

// ============================================================
// ★★★ LOOP: アナログ検知ロジックとMQTT Publishの統合 ★★★
// ============================================================
void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    delay(1000);
    return;
  }
  if (!mqttClient.connected()) reconnectMqtt();
  mqttClient.loop();
  timeClient.update();

  unsigned long nowMs = millis();
  String nowTime = timeClient.getFormattedTime();

  // --- 1. アナログ値の読み取り ---
  int sensorValue = analogRead(PIR_PIN);
  
  // 基準値との差分（絶対値）を計算
  int diff = abs(sensorValue - baselineValue);
  
  // ------------------------------------
  // 2. 検出ロジック (イベント発生時)
  // ------------------------------------
  // 閾値を超えたら、保持タイマーを更新
  if (diff > THRESHOLD) {
    motionEnd = nowMs + HOLD_MS;
  }

  // ------------------------------------
  // 3. 状態出力ロジック (True/False & ホールド)
  // ------------------------------------
  bool isMotion = nowMs < motionEnd;
  
  // --- 状態変化があった場合のみPublish (properties/motion) ---
  if (isMotion != lastMotion) {
    lastMotion = isMotion;
    char topic[200], payload[96];
    snprintf(topic, sizeof(topic), "/server/%s/%s/properties/motion", CID, DEV_ID);
    StaticJsonDocument<96> j;
    j["motion"] = isMotion; // True/False を送信
    j["timestamp"] = nowTime;
    serializeJson(j, payload);
    publishMqtt(topic, payload);
  }

  // ★ 4. 毎秒publishする処理 (properties/motion_raw)
  if (nowMs - lastPublish >= PUBLISH_INTERVAL) {
    lastPublish = nowMs;
    char topic[200], payload[96];
    snprintf(topic, sizeof(topic), "/server/%s/%s/properties/motion_raw", CID, DEV_ID);
    StaticJsonDocument<96> j;
    // motion_raw トピックにも、ノイズ除去済みの最終状態 (isMotion) を送る
    j["motion_raw"] = isMotion;
    j["timestamp"] = nowTime;
    serializeJson(j, payload);
    publishMqtt(topic, payload);
  }

  // --- 5. 表示（状態と差分を出力） ---
  if (nowMs - lastPrint >= PRINT_INTERVAL) {
    lastPrint = nowMs;
    Serial.printf("[%s] Motion: %s, Diff: %d\n",
                  nowTime.c_str(), isMotion ? "True" : "False", diff);
  }

  // 6. 健全性（毎分）
  if (nowMs - lastHealth >= HEALTH_INTERVAL) {
    lastHealth = nowMs;
    Serial.printf("[Health] Time=%s WiFi=%s MQTT=%s\n",
                  nowTime.c_str(),
                  WiFi.isConnected() ? "OK" : "NG",
                  mqttClient.connected() ? "OK" : "NG");
  }

  delay(5);
}