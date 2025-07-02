#include <WiFi.h>
#include <Wire.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

#include <SensirionI2cScd4x.h>
#include <BH1750.h>
#include <Dps310.h>

// --- Wi-Fi設定 ---
#define WIFI_SSID "Buffalo-G-4970"
#define WIFI_PASS "cfn6v438t3rkb"

// --- Elwaサーバ設定 ---
#define MQTT_BROKER "150.65.179.132"
#define MQTT_PORT 7883

#define CID "53965d6805152d95"           // あなたのCID
#define DEV_ID "scd41-device-01"         // 任意のユニークID

// --- SCD41センサー設定 ---
SensirionI2cScd4x scd4x;
unsigned long lastSensorReadTime = 0;
const long sensorReadInterval = 5000;

// --- MQTTクライアント設定 ---
WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);


BH1750 lightMeter;
Dps310 DpsSensor;

// --- MQTT Publish処理 ---
void publishMqttMessage(const char* topic, const char* payload) {
  Serial.printf("Publishing to topic: %s\nPayload: %s\n", topic, payload);
  if (mqttClient.publish(topic, payload)) {
    Serial.println("Publish successful.");
  } else {
    Serial.println("Publish failed.");
  }
}

// --- デバイス登録 ---
void registerDevice() {
  char topic[128];
  snprintf(topic, sizeof(topic), "/server/%s/register", CID);

  StaticJsonDocument<256> doc;
  doc["id"] = DEV_ID;
  doc["deviceType"] = "temperatureSensor"; // 必要なら他に変更可能

  char payload[256];
  serializeJson(doc, payload);
  publishMqttMessage(topic, payload);
}

// --- プロパティ登録 ---
void registerProperties() {
  char topic[128];
  snprintf(topic, sizeof(topic), "/server/%s/%s/properties", CID, DEV_ID);

  StaticJsonDocument<512> doc;

  JsonObject manufacturer = doc.createNestedObject("manufacturer");
  manufacturer["code"] = "0x000000";
  JsonObject desc = manufacturer.createNestedObject("descriptions");
  desc["ja"] = "JAIST";
  desc["en"] = "JAIST";

  JsonObject protocol = doc.createNestedObject("protocol");
  protocol["type"] = "custom_mqtt";
  protocol["version"] = "1.0";

  doc["co2"] = 0;
  doc["temperature"] = 0.0;
  doc["humidity"] = 0.0;
  doc["lux"] = 0.0;
  doc["pressure"] = 0.0;

  char payload[512];
  serializeJson(doc, payload);
  publishMqttMessage(topic, payload);
}

// --- MQTT再接続 ---
void reconnectMqtt() {
  while (!mqttClient.connected()) {
    Serial.print("Attempting MQTT connection...");
    String clientId = "esp32-client-" + String(DEV_ID);
    if (mqttClient.connect(clientId.c_str())) {
      Serial.println("connected");
      registerDevice();
      delay(1000);
      registerProperties();
    } else {
      Serial.print("failed, rc=");
      Serial.print(mqttClient.state());
      Serial.println(" try again in 5 seconds");
      delay(5000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(2000);
  Serial.println("\n--- Starting Setup ---");

  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi Connected!");

  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);

  Serial.println("Initializing I2C and SCD41 Sensor...");
  Wire.begin(21, 19);  // SDA, SCL

  lightMeter.begin(BH1750::CONTINUOUS_HIGH_RES_MODE);
  DpsSensor.begin(Wire, 0x77);
  scd4x.begin(Wire, 0x62);

  uint16_t error;
  error = scd4x.stopPeriodicMeasurement();
  error = scd4x.startPeriodicMeasurement();
  if (error) {
    Serial.println("Error starting periodic measurement");
    while (1);
  }
  Serial.println("SCD41 Initialized Successfully.");
  Serial.println("--- Setup Complete! ---");
}

void loop() {
  if (!mqttClient.connected()) {
    reconnectMqtt();
  }
  mqttClient.loop();

  if (millis() - lastSensorReadTime >= sensorReadInterval) {
    uint16_t co2 = 0;
    float temperature = 0.0f, humidity = 0.0f;
    uint16_t error = scd4x.readMeasurement(co2, temperature, humidity);

    if (error || co2 == 0) {
      Serial.println("Sensor read error or invalid data.");
    } else {
      Serial.printf("CO2: %u ppm, Temp: %.2f C, Humid: %.2f %%\n", co2, temperature, humidity);

      char topic[128], payload[128];

      // CO2
      snprintf(topic, sizeof(topic), "/server/%s/%s/properties/co2", CID, DEV_ID);
      StaticJsonDocument<64> co2_doc;
      co2_doc["co2"] = co2;
      serializeJson(co2_doc, payload);
      publishMqttMessage(topic, payload);
      delay(100);

      // 温度
      snprintf(topic, sizeof(topic), "/server/%s/%s/properties/temperature", CID, DEV_ID);
      StaticJsonDocument<64> temp_doc;
      temp_doc["temperature"] = temperature;
      serializeJson(temp_doc, payload);
      publishMqttMessage(topic, payload);
      delay(100);

      // 湿度
      snprintf(topic, sizeof(topic), "/server/%s/%s/properties/humidity", CID, DEV_ID);
      StaticJsonDocument<64> humid_doc;
      humid_doc["humidity"] = humidity;
      serializeJson(humid_doc, payload);
      publishMqttMessage(topic, payload);
      delay(100);

      // 照度
      float lux = lightMeter.readLightLevel();
      if (lux >= 0) {
        snprintf(topic, sizeof(topic), "/server/%s/%s/properties/lux", CID, DEV_ID);
        StaticJsonDocument<64> lux_doc;
        lux_doc["lux"] = lux;
        serializeJson(lux_doc, payload);
        publishMqttMessage(topic, payload);
        delay(100);
      }

      // 気圧
      float pressure, temperature_dps;
      if (DpsSensor.measurePressureOnce(pressure) == 0) {
        snprintf(topic, sizeof(topic), "/server/%s/%s/properties/pressure", CID, DEV_ID);
        StaticJsonDocument<64> pressure_doc;
        pressure_doc["pressure"] = pressure;
        serializeJson(pressure_doc, payload);
        publishMqttMessage(topic, payload);
        delay(100);
      }
    }

    lastSensorReadTime = millis();
  }
}
