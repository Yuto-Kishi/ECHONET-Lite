#include <WiFi.h>
#include <Wire.h>
#include <PubSubClient.h>      // MQTT通信用ライブラリ
#include <ArduinoJson.h>       // JSONデータ作成用ライブラリ
#include <SensirionI2cScd4x.h> // SCD41センサー用ライブラリ

// --- Wi-Fi設定 ---
#define WIFI_SSID "Buffalo-G-4970" // ご自身の2.4GHz帯のSSIDを入力
#define WIFI_PASS "cfn6v438t3rkb" // ご自身のパスワードを入力

// --- MQTTブローカー設定 ---
#define MQTT_BROKER "150.65.179.132" // MQTTブローカーのIPアドレス
#define MQTT_PORT 7883               // MQTTブローカーのポート
#define MQTT_TOPIC "sensor/scd41/data" // データ送信先のトピック

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

// MQTTブローカーへの再接続処理
void reconnectMqtt() {
  while (!mqttClient.connected()) {
    Serial.print("Attempting MQTT connection...");
    // クライアントIDはユニークである必要があります
    String clientId = "esp32-scd41-client-";
    clientId += String(random(0xffff), HEX);

    if (mqttClient.connect(clientId.c_str())) {
      Serial.println("connected");
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

      // センサーデータをJSON形式で一つのペイロードにまとめる
      StaticJsonDocument<256> doc;
      doc["co2"] = co2;
      doc["temperature"] = temperature;
      doc["humidity"] = humidity;

      char payload[256];
      serializeJson(doc, payload);

      // まとめたデータをMQTTブローカーに送信
      publishMqttMessage(MQTT_TOPIC, payload);
    }
    lastSensorReadTime = millis();
  }
}
