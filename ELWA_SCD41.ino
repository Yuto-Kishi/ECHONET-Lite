#include <WiFi.h>
#include <Wire.h>
#include <PubSubClient.h>      // MQTT通信用ライブラリ
#include <ArduinoJson.h>       // JSONデータ作成用ライブラリ
#include <SensirionI2cScd4x.h> // SCD41センサー用ライブラリ

// --- Wi-Fi設定 ---
#define WIFI_SSID "Buffalo-G-4970" // ご自身の2.4GHz帯のSSIDを入力
#define WIFI_PASS "cfn6v438t3rkb" // ご自身のパスワードを入力

// --- MQTTブローカー & ELWAサーバー設定 ---
#define MQTT_BROKER "150.65.179.132" // ELWAサーバーのIPアドレス
#define MQTT_PORT 7883               // ELWAサーバーのMQTTポート

// !!! 注意: この2つの値はご自身の環境に合わせて設定してください !!!
#define CLIENT_TOKEN "7032a35b07c467a4" // ELWAサーバーのWebUIから取得したClient Token
#define DEVICE_ID "scd41-device-01"      // このデバイスを識別するためのユニークなID

// --- SCD41センサー設定 ---
SensirionI2cScd4x scd4x;
unsigned long lastSensorReadTime = 0;
const long sensorReadInterval = 5000; // 5秒ごとにセンサーを読み取る

// --- MQTTクライアント設定 ---
WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

// MQTTメッセージをPublish（送信）するヘルパー関数
void publishMqttMessage(const char* topic, const char* payload) {
  Serial.printf("Publishing to topic: %s\n", topic);
  Serial.printf("Payload: %s\n", payload);
  if (mqttClient.publish(topic, payload)) {
    Serial.println("Publish successful.");
  } else {
    Serial.println("Publish failed.");
  }
}

// ELWAサーバーへデバイスを登録する関数
void registerDevice() {
  char topic[128];
  snprintf(topic, sizeof(topic), "/server/%s/register", CLIENT_TOKEN);

  // ペイロードをJSON形式で作成
  StaticJsonDocument<256> doc;
  doc["id"] = DEVICE_ID;
  // deviceTypeはELWAサーバーの仕様で定義されているものを使用します。
  // 今回は一般的なセンサーなので "homeAirConditioner" を仮で使いますが、
  // 適切なものがあれば変更してください。
  doc["deviceType"] = "temperatureSensor"; // "airConditioner" や "generalLighting" など

  char payload[256];
  serializeJson(doc, payload);

  publishMqttMessage(topic, payload);
}

// ELWAサーバーへプロパティを登録する関数
void registerProperties() {
  char topic[128];
  snprintf(topic, sizeof(topic), "/server/%s/%s/properties", CLIENT_TOKEN, DEVICE_ID);

  // ペイロードをJSON形式で作成
  StaticJsonDocument<512> doc;
  // ELWAサーバー仕様書(P.14)にある必須プロパティ
  JsonObject manufacturer = doc.createNestedObject("manufacturer");
  manufacturer["code"] = "0x000000"; // 仮のメーカーコード
  JsonObject manufacturer_desc = manufacturer.createNestedObject("descriptions");
  manufacturer_desc["ja"] = "KAIT";
  manufacturer_desc["en"] = "Kanagawa Institute of Technology";

  JsonObject protocol = doc.createNestedObject("protocol");
  protocol["type"] = "custom_mqtt";
  protocol["version"] = "1.0";

  // このデバイスが持つプロパティを定義
  doc["co2"] = 0;
  doc["temperature"] = 0.0;
  doc["humidity"] = 0.0;

  char payload[512];
  serializeJson(doc, payload);

  publishMqttMessage(topic, payload);
}

// MQTTブローカーへの再接続処理
void reconnectMqtt() {
  while (!mqttClient.connected()) {
    Serial.print("Attempting MQTT connection...");
    // クライアントIDはユニークである必要があります
    String clientId = "esp32-client-" + String(DEVICE_ID);
    if (mqttClient.connect(clientId.c_str())) {
      Serial.println("connected");
      // 接続が成功したら、デバイスとプロパティを登録
      registerDevice();
      delay(1000); // サーバー側の処理を待つ
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

  // --- Wi-Fi接続 ---
  Serial.print("Connecting to WiFi: ");
  Serial.println(WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi Connected!");
  Serial.print("IP Address: ");
  Serial.println(WiFi.localIP());

  // --- MQTTクライアント設定 ---
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);

  // --- SCD41センサー初期化 ---
  Serial.println("Initializing I2C and SCD41 Sensor...");
  Wire.begin(21, 19); // SDA=GPIO21, SCL=GPIO19
  scd4x.begin(Wire, 0x62);

  uint16_t error;
  error = scd4x.stopPeriodicMeasurement();
  if (error) {
    Serial.println("Error stopping periodic measurement");
  }

  error = scd4x.startPeriodicMeasurement();
  if (error) {
    Serial.println("ERROR starting periodic measurement!");
    while (1); // センサーエラー時は停止
  }
  Serial.println("SCD41 Initialized Successfully.");
  Serial.println("--- Setup Complete! ---");
}

void loop() {
  // MQTT接続を維持
  if (!mqttClient.connected()) {
    reconnectMqtt();
  }
  mqttClient.loop();

  // --- センサーデータ読み取りとMQTT送信 ---
  if (millis() - lastSensorReadTime >= sensorReadInterval) {
    uint16_t co2 = 0;
    float temperature = 0.0f;
    float humidity = 0.0f;
    uint16_t error = scd4x.readMeasurement(co2, temperature, humidity);

    if (error) {
      Serial.println("Error reading SCD41 measurements.");
    } else if (co2 == 0) {
      Serial.println("Invalid sensor data (CO2=0), skipping.");
    } else {
      Serial.printf("Read values -> CO2: %u ppm, Temp: %.2f C, Humid: %.2f %%RH\n", co2, temperature, humidity);

      // 各センサーデータをそれぞれのトピックに送信
      char topic[128];
      char payload[128];

      // CO2
      snprintf(topic, sizeof(topic), "/server/%s/%s/properties/co2", CLIENT_TOKEN, DEVICE_ID);
      StaticJsonDocument<64> co2_doc;
      co2_doc["co2"] = co2;
      serializeJson(co2_doc, payload);
      publishMqttMessage(topic, payload);
      delay(100);

      // 温度
      snprintf(topic, sizeof(topic), "/server/%s/%s/properties/temperature", CLIENT_TOKEN, DEVICE_ID);
      StaticJsonDocument<64> temp_doc;
      temp_doc["temperature"] = temperature;
      serializeJson(temp_doc, payload);
      publishMqttMessage(topic, payload);
      delay(100);

      // 湿度
      snprintf(topic, sizeof(topic), "/server/%s/%s/properties/humidity", CLIENT_TOKEN, DEVICE_ID);
      StaticJsonDocument<64> humid_doc;
      humid_doc["humidity"] = humidity;
      serializeJson(humid_doc, payload);
      publishMqttMessage(topic, payload);
    }
    lastSensorReadTime = millis();
  }
}

