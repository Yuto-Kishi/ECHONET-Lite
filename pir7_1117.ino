#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <NTPClient.h>
#include <WiFiUdp.h>

// ===== Wi-Fi =====
#define WIFI_SSID "Kissinger"
#define WIFI_PASS "chkishilish1119"

// ===== MQTT (ECHONET Web API broker) =====
#define MQTT_BROKER "150.65.179.132"
#define MQTT_PORT   7883
#define CID         "53965d6805152d95"

// ===== Device ID =====
#define DEV_ID "PIR8"   // PIR1〜PIR6で個別設定

// ===== Pins =====
const int PIR_PIN = 18;

// ===== Timing =====
const unsigned long STABILIZE_MS   = 30000;   // 起動安定化
const unsigned long HOLD_MS        = 1500;    // 検出後の保持
const unsigned long PRINT_INTERVAL = 1000;    // 表示周期
const unsigned long HEALTH_INTERVAL = 60000;  // 健全性チェック（毎分）
const unsigned long PUBLISH_INTERVAL = 1000;  // ★ 追加: 毎秒publishする間隔

// ★★★ ノイズ除去設定 (ここから追加) ★★★
// この数値を大きくするとノイズに強くなります (例: 200 -> 500)
const unsigned long DEBOUNCE_MS = 200;    // ノイズ除去: この時間(ms)以上続いたら検知とみなす
// ★★★ (ここまで) ★★★

// ===== MQTT Client =====
WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

// ===== NTP (現在時刻表示用) =====
WiFiUDP ntpUDP;
NTPClient timeClient(ntpUDP, "ntp.nict.jp", 9 * 3600, 60000); // JST (+9h)

// ===== State =====
bool lastMotion = false;
unsigned long holdUntil = 0;
unsigned long lastPrint = 0;
unsigned long lastHealth = 0;
unsigned long lastPublish = 0; // ★ 追加: 定期publish用

// ★★★ ノイズ除去用の状態変数 (ここから追加) ★★★
unsigned long motionHighStart = 0; // ノイズ除去: 検知開始時間
bool motionState = false;          // ノイズ除去: デバウンス後の状態
// ★★★ (ここまで) ★★★

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
void setup() {
  Serial.begin(115200);
  pinMode(PIR_PIN, INPUT);

  Serial.println("\n=== PIR (motion_raw + state + timestamp) ===");

  // Wi-Fi
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("WiFi connecting");
  while (WiFi.status() != WL_CONNECTED) { delay(400); Serial.print("."); }
  Serial.printf("\nWiFi OK: %s\n", WiFi.localIP().toString().c_str());

  // NTP
  timeClient.begin();
  timeClient.update();
  Serial.printf("Time: %s\n", timeClient.getFormattedTime().c_str());

  // MQTT
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  reconnectMqtt();

  // PIR安定化
  Serial.println("Stabilizing PIR (≈30s)...");
  delay(STABILIZE_MS);
  Serial.println("Ready.\n");
}

// ============================================================
// ★★★ loop()関数をノイズ除去ロジック入りに置き換え ★★★
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

  // --- 1. PIR読み取り（瞬間値） ---
  bool motionRaw = (digitalRead(PIR_PIN) == HIGH);

  // --- 2. ソフトウェアデバウンス（ノイズ除去） ---
  if (motionRaw) {
    // 'HIGH' を検出
    if (motionHighStart == 0) {
      // 'HIGH' になり始めた瞬間、開始時刻を記録
      motionHighStart = nowMs;
    } else if (nowMs - motionHighStart >= DEBOUNCE_MS) {
      // 'HIGH' の状態が DEBOUNCE_MS (例: 200ms) 以上続いた
      // これを「真の検出」とみなし、motionState を true にする
      motionState = true;
    }
  } else {
    // 'LOW' を検出
    motionHighStart = 0; // 'HIGH' 継続タイマーをリセット
    motionState = false; // デバウンス後の状態も 'LOW' にする
  }
  
  // --- 3. ホールドで安定化（= state） ---
  // 'motion' は最終的な publish 用の状態
  bool motion;
  if (motionState) {
    // 'motionState' (デバウンス済み) が true なら、ホールド開始
    holdUntil = nowMs + HOLD_MS;
    motion = true; // すぐに 'motion' を true に
  } else {
    // デバウンス後の状態が false の場合
    if (nowMs < holdUntil) {
      motion = true; // ホールド期間中なら 'motion' を true に維持
    } else {
      motion = false; // ホールド期間が終わったら 'motion' を false に
    }
  }
  
  // --- 4. 状態変化があった場合のみPublish (motion) ---
  if (motion != lastMotion) {
    lastMotion = motion;
    char topic[200], payload[96];
    snprintf(topic, sizeof(topic), "/server/%s/%s/properties/motion", CID, DEV_ID);
    StaticJsonDocument<96> j;
    j["motion"] = motion;
    j["timestamp"] = nowTime;
    serializeJson(j, payload);
    publishMqtt(topic, payload);
  }

  // --- 5. 毎秒publish (motion_raw) ---
  if (nowMs - lastPublish >= PUBLISH_INTERVAL) {
    lastPublish = nowMs;
    char topic[200], payload[96];
    snprintf(topic, sizeof(topic), "/server/%s/%s/properties/motion_raw", CID, DEV_ID);
    StaticJsonDocument<96> j;
    
    // ★★★ アプリ側を変更しないよう、ノイズ除去済みの 'motion' にすり替える ★★★
    j["motion_raw"] = motion; 
    
    j["timestamp"] = nowTime;
    serializeJson(j, payload);
    publishMqtt(topic, payload);
  }

  // --- 6. 表示（rawとstateを両方出力） ---
  if (nowMs - lastPrint >= PRINT_INTERVAL) {
    lastPrint = nowMs;
    Serial.printf("[%s] motion_raw=%d, state=%d (debounced_state=%d)\n",
                  nowTime.c_str(), motionRaw ? 1 : 0, motion ? 1 : 0, motionState ? 1 : 0);
  }

  // --- 7. 健全性（毎分） → ★ 元のコードの通り、Publishなし ★
  if (nowMs - lastHealth >= HEALTH_INTERVAL) {
    lastHealth = nowMs;
    // WiFiとMQTTの状態チェックのみ（Publishなし）
    Serial.printf("[Health] Time=%s WiFi=%s MQTT=%s\n",
                  nowTime.c_str(),
                  WiFi.isConnected() ? "OK" : "NG",
                  mqttClient.connected() ? "OK" : "NG");
  }

  delay(5);
}