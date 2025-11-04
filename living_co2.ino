#include <WiFi.h>
#include <Wire.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

#include <SensirionI2cScd4x.h>
#include <BH1750.h>

// --- Wi-Fi設定 ---
#define WIFI_SSID "BuffaloAirStationPro"
#define WIFI_PASS "SummerCamp2018"

// --- Elwaサーバ設定 ---
#define MQTT_BROKER "150.65.179.132"
#define MQTT_PORT 7883

#define CID "53965d6805152d95"
#define DEV_ID "Living_West"

// --- I2Cピン/アドレス ---
#define I2C_SDA 21
#define I2C_SCL 19
#define SCD4X_ADDR 0x62

// --- インスタンス ---
SensirionI2cScd4x scd4x;
BH1750 lightMeter;

WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

// --- タイミング ---
unsigned long lastSensorReadTime = 0;
const unsigned long sensorReadInterval = 5000;

unsigned long notReadyStart = 0;
const unsigned long notReadyTimeout = 10000; // 10s

// ===== Utils =====
void ensureWifiConnected() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.println("[WiFi] reconnecting...");
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  unsigned long t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 15000) {
    delay(500);
    Serial.print(".");
  }
  Serial.println(WiFi.status() == WL_CONNECTED ? "\n[WiFi] Connected" : "\n[WiFi] FAILED");
}

void publishMqttMessage(const char* topic, const char* payload) {
  Serial.printf("Publishing to topic: %s\nPayload: %s\n", topic, payload);
  if (mqttClient.publish(topic, payload)) Serial.println("Publish successful.");
  else Serial.println("Publish failed.");
}

// ===== 登録系 =====
void registerDevice() {
  char topic[128];
  snprintf(topic, sizeof(topic), "/server/%s/register", CID);

  StaticJsonDocument<256> doc;
  doc["id"] = DEV_ID;
  doc["deviceType"] = "temperatureSensor";

  char payload[256];
  serializeJson(doc, payload);
  publishMqttMessage(topic, payload);
}

void registerProperties() {
  char topic[128];
  snprintf(topic, sizeof(topic), "/server/%s/%s/properties", CID, DEV_ID);

  StaticJsonDocument<512> doc;
  JsonObject manufacturer = doc.createNestedObject("manufacturer");
  manufacturer["code"] = "0x000000";
  JsonObject desc = manufacturer.createNestedObject("descriptions");
  desc["ja"] = "JAIST"; desc["en"] = "JAIST";

  JsonObject protocol = doc.createNestedObject("protocol");
  protocol["type"] = "custom_mqtt"; protocol["version"] = "1.0";

  doc["co2"] = 0;
  doc["temperature"] = 0.0;
  doc["humidity"] = 0.0;
  doc["lux"] = 0.0;

  char payload[512];
  serializeJson(doc, payload);
  publishMqttMessage(topic, payload);
}

// ===== MQTT =====
void reconnectMqtt() {
  ensureWifiConnected();
  if (mqttClient.connected()) return;

  while (!mqttClient.connected()) {
    Serial.print("[MQTT] Attempting connection...");
    String clientId = "esp32-client-" + String(DEV_ID);
    if (mqttClient.connect(clientId.c_str())) {
      Serial.println("connected");
      registerDevice(); delay(300);
      registerProperties();
    } else {
      Serial.print("failed, rc=");
      Serial.print(mqttClient.state());
      Serial.println(" retry in 3s");
      delay(3000);
    }
  }
}

// ===== センサー初期化 =====
bool initBH1750() {
  bool ok = lightMeter.begin(BH1750::CONTINUOUS_HIGH_RES_MODE);
  Serial.println(ok ? "[BH1750] ready." : "[BH1750] init failed.");
  return ok;
}

bool initSCD4x() {
  Serial.println("[SCD4x] initializing...");
  scd4x.begin(Wire, SCD4X_ADDR);

  scd4x.stopPeriodicMeasurement();
  delay(5);
  int16_t err = scd4x.reinit();
  if (err) Serial.printf("[SCD4x] reinit error: %d\n", err);
  delay(1000);

  err = scd4x.startPeriodicMeasurement();
  if (err) {
    Serial.printf("[SCD4x] startPeriodicMeasurement error: %d\n", err);
    return false;
  }
  Serial.println("[SCD4x] ready.");
  return true;
}

void reinitSensorsAndMqtt() {
  Serial.println("=== Data not ready for >10s: reinitializing sensors & MQTT ===");

  if (mqttClient.connected()) { mqttClient.disconnect(); delay(100); }
  ensureWifiConnected();

  Wire.end(); delay(10);
  Wire.begin(I2C_SDA, I2C_SCL); delay(10);

  initBH1750();
  initSCD4x();
  reconnectMqtt();

  notReadyStart = 0;
}

// ===== Arduino lifecycle =====
void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("\n--- Starting Setup ---");

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.println("\nWiFi Connected!");

  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);

  Serial.println("Initializing I2C & sensors...");
  Wire.begin(I2C_SDA, I2C_SCL);

  initBH1750();
  initSCD4x();

  Serial.println("--- Setup Complete! ---");
}

void loop() {
  if (!mqttClient.connected()) reconnectMqtt();
  mqttClient.loop();

  const unsigned long now = millis();
  if (now - lastSensorReadTime < sensorReadInterval) return;
  lastSensorReadTime = now;

  // --- SCD4x: データready確認（bool& 版） ---
  bool isReady = false;
  int16_t error = scd4x.getDataReadyStatus(isReady);
  if (error) {
    Serial.printf("[SCD4x] getDataReadyStatus error: %d\n", error);
    if (notReadyStart == 0) notReadyStart = now;
    if (now - notReadyStart >= notReadyTimeout) reinitSensorsAndMqtt();
    return;
  }

  if (!isReady) {
    Serial.println("Data not ready yet");
    if (notReadyStart == 0) notReadyStart = now;
    if (now - notReadyStart >= notReadyTimeout) reinitSensorsAndMqtt();
    return;
  }
  notReadyStart = 0;

  // --- 測定 ---
  uint16_t co2 = 0;
  float temperature = 0.0f, humidity = 0.0f;
  error = scd4x.readMeasurement(co2, temperature, humidity);

  if (error || co2 < 350 || co2 > 10000) {
    Serial.printf("Sensor read error or invalid CO2 data: %u ppm\n", co2);
    return;
  }

  Serial.printf("CO2: %u ppm, Temp: %.2f C, Humid: %.2f %%\n", co2, temperature, humidity);

  char topic[128], payload[160];

  // CO2
  snprintf(topic, sizeof(topic), "/server/%s/%s/properties/co2", CID, DEV_ID);
  { StaticJsonDocument<64> doc; doc["co2"] = co2;
    serializeJson(doc, payload, sizeof(payload));
    publishMqttMessage(topic, payload); delay(60); }

  // 温度
  snprintf(topic, sizeof(topic), "/server/%s/%s/properties/temperature", CID, DEV_ID);
  { StaticJsonDocument<64> doc; doc["temperature"] = temperature;
    serializeJson(doc, payload, sizeof(payload));
    publishMqttMessage(topic, payload); delay(60); }

  // 湿度
  snprintf(topic, sizeof(topic), "/server/%s/%s/properties/humidity", CID, DEV_ID);
  { StaticJsonDocument<64> doc; doc["humidity"] = humidity;
    serializeJson(doc, payload, sizeof(payload));
    publishMqttMessage(topic, payload); delay(60); }

  // 照度
  float lux = lightMeter.readLightLevel();
  if (lux >= 0) {
    snprintf(topic, sizeof(topic), "/server/%s/%s/properties/lux", CID, DEV_ID);
    StaticJsonDocument<64> doc; doc["lux"] = lux;
    serializeJson(doc, payload, sizeof(payload));
    publishMqttMessage(topic, payload); delay(60);
  }
}
