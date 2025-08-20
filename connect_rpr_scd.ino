#include <WiFi.h>
#include <Wire.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <SensirionI2cScd4x.h>

// --- I2Cピン設定 ---
#define PIN_SDA 21
#define PIN_SCL 19
#define I2C_FREQ 100000

// --- RPR-0521RS定義 ---
#define RPR_ADDR            0x38
#define REG_MANUFACT_ID     0x92
#define REG_ALS_PS_CONTROL  0x42
#define REG_PS_CONTROL      0x44
#define REG_MODE_CONTROL    0x41
#define REG_DATA_START      0x44
#define ALS_GAIN_BITS       0x05
#define PS_CONTROL_BITS     0x20
#define MODE_CONTROL_BITS   0xC6

// --- Wi-Fi設定 ---
#define WIFI_SSID "Buffalo-G-4970"
#define WIFI_PASS "cfn6v438t3rkb"

// --- MQTT設定 ---
#define MQTT_BROKER "150.65.179.132"
#define MQTT_PORT 7883
#define CID "53965d6805152d95"
#define DEV_ID "multi-sensors8"

SensirionI2cScd4x scd4x;
WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);
unsigned long lastSensorReadTime = 0;
const long sensorReadInterval = 5000;

float lux_from_raw(uint16_t d0, uint16_t d1) {
  float f0 = d0 / 2.0f;
  float f1 = d1 / 2.0f;
  if (f0 < 1e-3) return 0;
  float r = f1 / f0;
  if (r < 0.595f)  return 1.682f * f0 - 1.877f * f1;
  if (r < 1.015f)  return 0.644f * f0 - 0.132f * f1;
  if (r < 1.352f)  return 0.756f * f0 - 0.243f * f1;
  if (r < 3.053f)  return 0.766f * f0 - 0.250f * f1;
  return 0;
}

void i2c_write(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(RPR_ADDR);
  Wire.write(reg);
  Wire.write(val);
  Wire.endTransmission();
}

bool i2c_read(uint8_t reg, uint8_t* buf, uint8_t len) {
  Wire.beginTransmission(RPR_ADDR);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  uint8_t read = Wire.requestFrom(RPR_ADDR, len);
  if (read != len) return false;
  for (int i = 0; i < len; ++i) buf[i] = Wire.read();
  return true;
}

void initRPR0521() {
  delay(100);
  uint8_t id;
  if (!i2c_read(REG_MANUFACT_ID, &id, 1) || id != 0xE0) {
    Serial.println("RPR-0521RS not detected.");
    while (1);
  }
  i2c_write(REG_ALS_PS_CONTROL, ALS_GAIN_BITS);
  i2c_write(REG_PS_CONTROL, PS_CONTROL_BITS);
  i2c_write(REG_MODE_CONTROL, MODE_CONTROL_BITS);
  delay(100);
  Serial.println("RPR-0521RS Initialized.");
}

bool readRPR0521(float &lux, uint16_t &prox) {
  uint8_t buf[6];
  if (!i2c_read(REG_DATA_START, buf, 6)) return false;
  prox = (buf[1] << 8) | buf[0];
  uint16_t als0 = (buf[3] << 8) | buf[2];
  uint16_t als1 = (buf[5] << 8) | buf[4];
  lux = lux_from_raw(als0, als1);
  return true;
}

void publishMqttMessage(const char* topic, const char* payload) {
  Serial.printf("Publishing to topic: %s\nPayload: %s\n", topic, payload);
  mqttClient.publish(topic, payload) ? Serial.println("Publish successful.") : Serial.println("Publish failed.");
}

void registerDevice() {
  char topic[128], payload[256];
  snprintf(topic, sizeof(topic), "/server/%s/register", CID);
  StaticJsonDocument<256> doc;
  doc["id"] = DEV_ID;
  doc["deviceType"] = "temperatureSensor";
  serializeJson(doc, payload);
  publishMqttMessage(topic, payload);
}

void registerProperties() {
  char topic[128], payload[512];
  snprintf(topic, sizeof(topic), "/server/%s/%s/properties", CID, DEV_ID);
  StaticJsonDocument<512> doc;
  JsonObject manufacturer = doc.createNestedObject("manufacturer");
  manufacturer["code"] = "0x000000";
  manufacturer["descriptions"]["ja"] = "JAIST";
  manufacturer["descriptions"]["en"] = "JAIST";
  doc["protocol"]["type"] = "custom_mqtt";
  doc["protocol"]["version"] = "1.0";
  doc["co2"] = 0;
  doc["temperature"] = 0.0;
  doc["humidity"] = 0.0;
  doc["lux"] = 0.0;
  doc["proximity"] = 0;
  serializeJson(doc, payload);
  publishMqttMessage(topic, payload);
}

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
      Serial.printf("failed, rc=%d. Retrying...\n", mqttClient.state());
      delay(5000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(2000);
  Serial.println("--- Setup Start ---");
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.println("\nWiFi Connected!");
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  Wire.begin(PIN_SDA, PIN_SCL, I2C_FREQ);
  initRPR0521();
  scd4x.begin(Wire, 0x62);
  scd4x.stopPeriodicMeasurement();
  if (scd4x.startPeriodicMeasurement()) {
    Serial.println("SCD41 measurement start failed!");
    while (1);
  }
  Serial.println("SCD41 Initialized.");
  Serial.println("--- Setup Complete ---");
}

void loop() {
  if (!mqttClient.connected()) reconnectMqtt();
  mqttClient.loop();
  char topic[128], payload[128];
  if (millis() - lastSensorReadTime >= sensorReadInterval) {
    lastSensorReadTime = millis();

    uint16_t co2 = 0;
    float temp = 0.0f, humid = 0.0f;
    if (!scd4x.readMeasurement(co2, temp, humid) && co2 >= 400 && co2 <= 10000) {
      snprintf(topic, sizeof(topic), "/server/%s/%s/properties/co2", CID, DEV_ID);
      StaticJsonDocument<64> doc1; doc1["co2"] = co2;
      serializeJson(doc1, payload); publishMqttMessage(topic, payload); delay(100);

      snprintf(topic, sizeof(topic), "/server/%s/%s/properties/temperature", CID, DEV_ID);
      StaticJsonDocument<64> doc2; doc2["temperature"] = temp;
      serializeJson(doc2, payload); publishMqttMessage(topic, payload); delay(100);

      snprintf(topic, sizeof(topic), "/server/%s/%s/properties/humidity", CID, DEV_ID);
      StaticJsonDocument<64> doc3; doc3["humidity"] = humid;
      serializeJson(doc3, payload); publishMqttMessage(topic, payload); delay(100);
    } else {
      Serial.println("SCD41 sensor read error or invalid CO2.");
    }

    float lux = 0.0; uint16_t prox = 0;
    if (readRPR0521(lux, prox)) {
      Serial.printf("RPR-0521RS: lux = %.2f, proximity = %u\n", lux, prox);
      snprintf(topic, sizeof(topic), "/server/%s/%s/properties/lux", CID, DEV_ID);
      StaticJsonDocument<64> lux_doc; lux_doc["lux"] = lux;
      serializeJson(lux_doc, payload); publishMqttMessage(topic, payload); delay(100);
      snprintf(topic, sizeof(topic), "/server/%s/%s/properties/proximity", CID, DEV_ID);
      StaticJsonDocument<64> prox_doc; prox_doc["proximity"] = prox;
      serializeJson(prox_doc, payload); publishMqttMessage(topic, payload); delay(100);
    } else {
      Serial.println("Failed to read RPR-0521RS sensor.");
    }
  }
}