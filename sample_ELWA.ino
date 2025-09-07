#include <WiFi.h>
#include <Wire.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

#include <SensirionI2cScd4x.h>
#include <BH1750.h>

// --- Wi-Fi設定 ---å
#define WIFI_SSID "BuffaloAirStationPro"
#define WIFI_PASS "SummerCamp2018"

// --- Elwaサーバ設定 ---
#define MQTT_BROKER "150.65.179.132"
#define MQTT_PORT 7883

#define CID "53965d6805152d95"
#define DEV_ID "multi-sensors4"

// --- センサーインスタンス ---
SensirionI2cScd4x scd4x;
BH1750 lightMeter;

// --- MQTTクライアント設定 ---
WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

// --- 測定間隔 ---
unsigned long lastSensorReadTime = 0;
const long sensorReadInterval = 5000;

// --- MQTT Publish ---
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
  doc["deviceType"] = "temperatureSensor";

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
  scd4x.begin(Wire, 0x62);

  scd4x.stopPeriodicMeasurement();
  uint16_t error = scd4x.startPeriodicMeasurement();
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
    bool isDataReady = false;
    int16_t error = scd4x.getDataReadyStatus(isDataReady);
    if (error) {
      Serial.println("Error reading data ready status");
      return;
    }

    if (!isDataReady) {
      Serial.println("Data not ready yet");
      return;
    }

    uint16_t co2 = 0;
    float temperature = 0.0f, humidity = 0.0f;
    error = scd4x.readMeasurement(co2, temperature, humidity);

    if (error || co2 < 400 || co2 > 10000) {
      Serial.printf("Sensor read error or invalid CO2 data: %u ppm\n", co2);
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
    }

    lastSensorReadTime = millis();
  }
}
