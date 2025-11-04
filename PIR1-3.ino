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
#define DEV_ID "PIR1"   // PIR1〜PIR6で個別設定

// ===== Pins =====
const int PIR_PIN = 18;

// ===== Timing =====
const unsigned long STABILIZE_MS   = 30000;   // 起動安定化
const unsigned long HOLD_MS        = 1500;    // 検出後の保持
const unsigned long PRINT_INTERVAL = 1000;    // 表示周期
const unsigned long HEALTH_INTERVAL = 60000;  // 健全性チェック（毎分）

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

void setup() {
  Serial.begin(115200);
  pinMode(PIR_PIN, INPUT);

  Serial.println("\n=== PIR (motion + timestamp only) ===");

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

  // --- PIR読み取り（raw） ---
  bool motionRaw = (digitalRead(PIR_PIN) == HIGH);

  // --- ホールドで安定化（= state） ---
  bool motion = motionRaw;
  if (motionRaw) holdUntil = nowMs + HOLD_MS;
  if (nowMs < holdUntil) motion = true;

  // --- 変化時のみPublish ---
  if (motion != lastMotion) {
    lastMotion = motion;
    char topic[200], payload[96];
    snprintf(topic, sizeof(topic), "/server/%s/%s/properties/motion", CID, DEV_ID);
    StaticJsonDocument<96> j;
    j["motion"] = motion;
    j["timestamp"] = nowTime;  // ★ ついでにMQTTペイロードにも時刻を入れておくと便利
    serializeJson(j, payload);
    publishMqtt(topic, payload);
  }

  // --- 表示は「モーション」と「時刻」だけ ---
  if (nowMs - lastPrint >= PRINT_INTERVAL) {
    lastPrint = nowMs;
    Serial.printf("[%s] motion=%d\n", nowTime.c_str(), motion ? 1 : 0);
  }

  // 健全性（毎分）
  if (nowMs - lastHealth >= HEALTH_INTERVAL) {
    lastHealth = nowMs;
    char topic[200], payload[128];
    snprintf(topic, sizeof(topic), "/server/%s/%s/properties/health", CID, DEV_ID);
    StaticJsonDocument<128> h;
    h["wifi"] = WiFi.isConnected();
    h["mqtt"] = mqttClient.connected();
    h["timestamp"] = nowTime;
    serializeJson(h, payload);
    publishMqtt(topic, payload);
  }

  delay(5);
}
