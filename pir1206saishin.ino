#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <NTPClient.h>
#include <WiFiUdp.h>
//アナログ用
// ===== Wi-Fi =====
#define WIFI_SSID "BuffaloAirStationPro"
#define WIFI_PASS "SummerCamp2018"

// ===== MQTT =====
#define MQTT_BROKER "150.65.179.132"
#define MQTT_PORT   7883
#define CID         "53965d6805152d95"

// ===== Device ID =====
#define DEV_ID "PIR15"   // 洋室1

// ===== Pins =====
const int PIR_PIN = 32; 

// ===== Settings =====
// 感度調整の閾値 (シリアルモニタでDiffを見て調整してください)
const int THRESHOLD = 800; 

// ノイズ対策: 平均化の回数
const int SAMPLE_COUNT = 20; 

// 検出後の保持時間
const unsigned long HOLD_MS = 2000;

const unsigned long PRINT_INTERVAL = 1000;    // 表示周期
const unsigned long HEALTH_INTERVAL = 60000;  // 健全性チェック周期
const unsigned long PUBLISH_INTERVAL = 1000;  // Publish周期

// ===== Global Vars =====
int baselineValue = 0;
unsigned long motionEnd = 0;
bool lastMotion = false;
unsigned long lastPrint = 0;
unsigned long lastHealth = 0;
unsigned long lastPublish = 0;

// Clients
WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);
WiFiUDP ntpUDP;
NTPClient timeClient(ntpUDP, "ntp.nict.jp", 9 * 3600, 60000);

// ---------- Helper Functions ----------

// 平均化読み取り（ノイズ除去）
int getStableAnalogRead(int pin) {
  long sum = 0;
  for (int i = 0; i < SAMPLE_COUNT; i++) {
    sum += analogRead(pin);
    delay(2);
  }
  return (int)(sum / SAMPLE_COUNT);
}

void publishMqtt(const char* topic, const char* payload) {
  if (mqttClient.connected()) mqttClient.publish(topic, payload);
}

void registerDevice() {
  char topic[128]; snprintf(topic, sizeof(topic), "/server/%s/register", CID);
  StaticJsonDocument<128> doc;
  doc["id"] = DEV_ID; doc["deviceType"] = "pirSensor";
  char payload[128]; serializeJson(doc, payload);
  publishMqtt(topic, payload);
}

void registerProperties() {
  char topic[160]; snprintf(topic, sizeof(topic), "/server/%s/%s/properties", CID, DEV_ID);
  StaticJsonDocument<256> doc;
  doc["motion"] = false; doc["description"] = "PIR (Analog/Debug)";
  char payload[256]; serializeJson(doc, payload);
  publishMqtt(topic, payload);
}

void reconnectMqtt() {
  while (!mqttClient.connected()) {
    Serial.print("MQTT connecting...");
    String cid = String("esp32-") + DEV_ID;
    if (mqttClient.connect(cid.c_str())) {
      Serial.println("connected");
      registerDevice(); delay(200); registerProperties();
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

  Serial.println("\n=== PIR15 Analog Debug Mode ===");

  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("WiFi connecting");
  while (WiFi.status() != WL_CONNECTED) { delay(400); Serial.print("."); }
  Serial.printf("\nWiFi OK: %s\n", WiFi.localIP().toString().c_str());

  timeClient.begin();
  timeClient.update();

  // 安定化待機
  Serial.println("Stabilizing Sensor (30s)...");
  for(int i = 0; i < 30; i++) {
    if(i%5==0) Serial.print(".");
    delay(1000);
  }
  Serial.println("\nCalibrating...");

  // ベースライン取得
  long sum = 0;
  for(int i=0; i<50; i++) {
    sum += getStableAnalogRead(PIR_PIN);
    delay(10);
  }
  baselineValue = sum / 50;
  
  Serial.printf("Baseline Value: %d (Approx. %.2fV)\n", baselineValue, (baselineValue * 3.3 / 4095.0));
  Serial.println("Ready.");

  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  reconnectMqtt();
}

// ============================================================
void loop() {
  if (WiFi.status() != WL_CONNECTED) { WiFi.begin(WIFI_SSID, WIFI_PASS); delay(1000); return; }
  if (!mqttClient.connected()) reconnectMqtt();
  mqttClient.loop();
  timeClient.update();

  unsigned long nowMs = millis();
  String nowTime = timeClient.getFormattedTime();

  // 1. 読み取り
  int sensorValue = getStableAnalogRead(PIR_PIN);
  int diff = abs(sensorValue - baselineValue);
  
  // 2. 判定
  if (diff > THRESHOLD) {
    motionEnd = nowMs + HOLD_MS;
  }
  bool isMotion = nowMs < motionEnd;

  // 3. Publish
  if (isMotion != lastMotion) {
    lastMotion = isMotion;
    char topic[200], payload[96];
    snprintf(topic, sizeof(topic), "/server/%s/%s/properties/motion", CID, DEV_ID);
    StaticJsonDocument<96> j;
    j["motion"] = isMotion; j["timestamp"] = nowTime;
    serializeJson(j, payload);
    publishMqtt(topic, payload);
  }

  if (nowMs - lastPublish >= PUBLISH_INTERVAL) {
    lastPublish = nowMs;
    char topic[200], payload[96];
    snprintf(topic, sizeof(topic), "/server/%s/%s/properties/motion_raw", CID, DEV_ID);
    StaticJsonDocument<96> j;
    j["motion_raw"] = isMotion; j["timestamp"] = nowTime;
    serializeJson(j, payload);
    publishMqtt(topic, payload);
  }

  // 4. デバッグ表示
  if (nowMs - lastPrint >= PRINT_INTERVAL) {
    lastPrint = nowMs;
    Serial.printf("[%s] Val:%d | Base:%d | Diff:%d | Motion:%s\n",
                  nowTime.c_str(), sensorValue, baselineValue, diff, isMotion ? "ON" : "OFF");
  }

  if (nowMs - lastHealth >= HEALTH_INTERVAL) {
    lastHealth = nowMs;
    Serial.println("[Health] OK");
  }
  
  delay(10);
}