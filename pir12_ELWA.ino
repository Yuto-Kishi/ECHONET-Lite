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
#define DEV_ID "PIR1-2"

// --- PIRセンサー設定 ---
const int PIR1_PIN = 26;   // HC-SR501
const int PIR2_PIN = 27;   // Keyestudio PIR

// 起動直後の不安定期間（ms）
const unsigned long WARMUP_IGNORE_MS = 10000;

// --- MQTTクライアント設定 ---
WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

// --- 時間管理 ---
unsigned long t0;
unsigned long lastPrint = 0;

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
  doc["deviceType"] = "pirSensor";

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

  doc["pir1"] = false;
  doc["pir2"] = false;

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
  Serial.println("\n--- PIR Sensor MQTT Setup ---");

  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi Connected!");

  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);

  pinMode(PIR1_PIN, INPUT);
  pinMode(PIR2_PIN, INPUT);

  t0 = millis();
  Serial.println("Setup complete, waiting warmup...");
}

void loop() {
  if (!mqttClient.connected()) {
    reconnectMqtt();
  }
  mqttClient.loop();

  unsigned long now = millis();

  // 起動直後の不安定期間は無視
  if (now - t0 < WARMUP_IGNORE_MS) {
    if (now - lastPrint >= 1000) {
      unsigned long left = (WARMUP_IGNORE_MS - (now - t0)) / 1000;
      Serial.printf("[warmup] wait %lus...\n", left + 1);
      lastPrint = now;
    }
    return;
  }

  // 毎秒ステートを出力 & MQTT送信
  if (now - lastPrint >= 1000) {
    bool s1 = (digitalRead(PIR1_PIN) == HIGH);  // true=motion
    bool s2 = (digitalRead(PIR2_PIN) == HIGH);

    // シリアルにJSON形式で表示
    StaticJsonDocument<128> doc;
    doc["pir1"] = s1;
    doc["pir2"] = s2;
    serializeJson(doc, Serial);
    Serial.println();

    // MQTT送信 (pir1)
    char topic[128], payload[128];
    snprintf(topic, sizeof(topic), "/server/%s/%s/properties/pir1", CID, DEV_ID);
    StaticJsonDocument<64> doc1;
    doc1["pir1"] = s1;
    serializeJson(doc1, payload);
    publishMqttMessage(topic, payload);

    delay(50);

    // MQTT送信 (pir2)
    snprintf(topic, sizeof(topic), "/server/%s/%s/properties/pir2", CID, DEV_ID);
    StaticJsonDocument<64> doc2;
    doc2["pir2"] = s2;
    serializeJson(doc2, payload);
    publishMqttMessage(topic, payload);

    lastPrint = now;
  }
}
