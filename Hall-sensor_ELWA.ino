#include <WiFi.h>
#include <Wire.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// --- Wi-Fi設定 ---
#define WIFI_SSID "BuffaloAirStationPro"
#define WIFI_PASS "SummerCamp2018"

// --- Elwaサーバ設定 ---
#define MQTT_BROKER "150.65.179.132"
#define MQTT_PORT 7883

#define CID "53965d6805152d95"
#define DEV_ID "door-sensor1"   // ★デバイスIDを適宜変更

// --- Hall Sensor設定 ---
const int HALL_PIN = 27;   // センサーOUTを接続するGPIO
bool lastDoorClosed = false;

// --- MQTTクライアント設定 ---
WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

// --- 測定間隔 ---
unsigned long lastSensorReadTime = 0;
const long sensorReadInterval = 2000; // 2秒ごとにチェック

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
  doc["deviceType"] = "doorSensor";   // ★ドアセンサーとして登録

  char payload[256];
  serializeJson(doc, payload);
  publishMqttMessage(topic, payload);
}

// --- プロパティ登録 ---
void registerProperties() {
  char topic[128];
  snprintf(topic, sizeof(topic), "/server/%s/%s/properties", CID, DEV_ID);

  StaticJsonDocument<256> doc;

  JsonObject manufacturer = doc.createNestedObject("manufacturer");
  manufacturer["code"] = "0x000000";
  JsonObject desc = manufacturer.createNestedObject("descriptions");
  desc["ja"] = "JAIST";
  desc["en"] = "JAIST";

  JsonObject protocol = doc.createNestedObject("protocol");
  protocol["type"] = "custom_mqtt";
  protocol["version"] = "1.0";

  // ドアの状態プロパティを登録
  doc["door"] = "OPEN";  // 初期値

  char payload[256];
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
      delay(500);
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

  // Wi-Fi接続
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi Connected!");

  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);

  pinMode(HALL_PIN, INPUT); // プッシュプル出力なのでINPUTでOK

  Serial.println("--- Setup Complete! ---");
}

void loop() {
  if (!mqttClient.connected()) {
    reconnectMqtt();
  }
  mqttClient.loop();

  if (millis() - lastSensorReadTime >= sensorReadInterval) {
    int state = digitalRead(HALL_PIN);
    bool doorClosed = (state == LOW); // アクティブLow: 磁石あり=閉

    if (doorClosed != lastDoorClosed) {
      // 状態が変化したらMQTTに送信
      char topic[128], payload[128];
      snprintf(topic, sizeof(topic), "/server/%s/%s/properties/door", CID, DEV_ID);

      StaticJsonDocument<64> doc;
      doc["door"] = doorClosed ? "CLOSED" : "OPEN";
      serializeJson(doc, payload);

      publishMqttMessage(topic, payload);

      Serial.printf("Door state changed: %s\n", doorClosed ? "CLOSED" : "OPEN");

      lastDoorClosed = doorClosed;
    }

    lastSensorReadTime = millis();
  }
}
