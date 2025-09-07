#include <WiFi.h>
#include <Wire.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// --- Wi-Fi設定 ---
#define WIFI_SSID "Kissinger"
#define WIFI_PASS "chkishilish1119"

// --- Elwaサーバ設定 ---
#define MQTT_BROKER "150.65.179.132"
#define MQTT_PORT 7883

#define CID "53965d6805152d95"
#define DEV_ID "door-sensor1"   // ★デバイスIDを適宜変更

// --- Hall Sensor ---
const int HALL_PIN = 27;        // 磁石あり=LOW（アクティブLow）
bool lastDoorClosed = false;    // 変化検出用（ログに使うだけ）

// --- Mic module (KY-038系) ---
const int MIC_A_PIN = 34;       // A0 → ADC1(GPIO34)
const int MIC_D_PIN = 26;       // D0 → 任意のデジタル入力
const uint16_t SAMPLE_RATE_HZ  = 2000;   // 2 kHz
const uint16_t WINDOW_MS       = 25;     // 25ms 窓
const uint16_t SAMPLES_PER_WIN = SAMPLE_RATE_HZ * WINDOW_MS / 1000; // 50 samples
const uint16_t AMP_THRESHOLD   = 200;    // しきい値（環境に合わせ調整）
bool lastSoundTrig = false;

// --- MQTTクライアント ---
WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

// --- タイミング ---
unsigned long lastMicPublishTime  = 0;
const long    micPublishInterval  = 1000;  // 1s
unsigned long lastDoorPublishTime = 0;
const long    doorPublishInterval = 1000;  // ★ドアも毎秒

// ========== MQTTユーティリティ ==========
void publishMqttMessage(const char* topic, const char* payload) {
  Serial.printf("Publishing to topic: %s\nPayload: %s\n", topic, payload);
  if (mqttClient.publish(topic, payload)) {
    Serial.println("Publish successful.");
  } else {
    Serial.println("Publish failed.");
  }
}

void registerDevice() {
  char topic[128];
  snprintf(topic, sizeof(topic), "/server/%s/register", CID);

  StaticJsonDocument<256> doc;
  doc["id"] = DEV_ID;
  doc["deviceType"] = "doorSoundSensor";

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

  // 初期値
  doc["door"] = "OPEN";
  doc["sound_amp"] = 0;          // 数値
  doc["sound_trig"] = false;     // 真偽値

  char payload[512];
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
      delay(300);
      registerProperties();
    } else {
      Serial.print("failed, rc="); Serial.print(mqttClient.state());
      Serial.println(" try again in 5 seconds");
      delay(5000);
    }
  }
}

// --- Mic: A0 振幅（ピークtoピーク）を測る ---
uint16_t readMicAmplitude() {
  uint16_t vmin = 4095, vmax = 0;
  for (uint16_t i = 0; i < SAMPLES_PER_WIN; ++i) {
    uint16_t v = analogRead(MIC_A_PIN);
    if (v < vmin) vmin = v;
    if (v > vmax) vmax = v;
    delayMicroseconds(1000000UL / SAMPLE_RATE_HZ);
  }
  return (vmax >= vmin) ? (vmax - vmin) : 0;
}

// ========== setup ==========
void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n--- Starting Setup ---");

  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.println("\nWiFi Connected!");

  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);

  pinMode(HALL_PIN, INPUT);      // Hall
  pinMode(MIC_D_PIN, INPUT);     // Mic D0
  analogReadResolution(12);                  // 0..4095
  analogSetPinAttenuation(MIC_A_PIN, ADC_11db); // 0〜3.3Vレンジ相当

  Serial.println("--- Setup Complete! ---");
}

// ========== loop ==========
void loop() {
  if (!mqttClient.connected()) reconnectMqtt();
  mqttClient.loop();

  const unsigned long now = millis();

  // ---- マイク: 毎秒 sound_amp、変化時のみ sound_trig ----
  if (now - lastMicPublishTime >= micPublishInterval) {
    lastMicPublishTime = now;

    uint16_t amp = readMicAmplitude();

    // sound_amp（定期送信）
    {
      char topic[128], payload[128];
      snprintf(topic, sizeof(topic), "/server/%s/%s/properties/sound_amp", CID, DEV_ID);
      StaticJsonDocument<64> j; j["sound_amp"] = amp;
      serializeJson(j, payload);
      publishMqttMessage(topic, payload);
    }
    Serial.printf("sound_amp=%u\n", amp);

    // sound_trig（D0 または 振幅しきい超え）：変化時のみ
    bool trigNow = (digitalRead(MIC_D_PIN) == HIGH) || (amp > AMP_THRESHOLD);
    if (trigNow != lastSoundTrig) {
      char topic[128], payload[128];
      snprintf(topic, sizeof(topic), "/server/%s/%s/properties/sound_trig", CID, DEV_ID);
      StaticJsonDocument<64> j; j["sound_trig"] = trigNow;
      serializeJson(j, payload);
      publishMqttMessage(topic, payload);
      Serial.printf("sound_trig changed: %s\n", trigNow ? "true" : "false");
      lastSoundTrig = trigNow;
    }
  }

  // ---- ドア: 毎秒 door を送信（OPEN/CLOSED） ----
  if (now - lastDoorPublishTime >= doorPublishInterval) {
    lastDoorPublishTime = now;

    bool doorClosed = (digitalRead(HALL_PIN) == LOW); // アクティブLow
    char topic[128], payload[128];
    snprintf(topic, sizeof(topic), "/server/%s/%s/properties/door", CID, DEV_ID);

    StaticJsonDocument<64> d;
    d["door"] = doorClosed ? "CLOSED" : "OPEN";
    serializeJson(d, payload);
    publishMqttMessage(topic, payload);

    // ログ（変化時にだけ差分メッセージも出す）
    if (doorClosed != lastDoorClosed) {
      Serial.printf("Door state changed: %s\n", doorClosed ? "CLOSED" : "OPEN");
      lastDoorClosed = doorClosed;
    }
    // 毎秒の現在値も表示
    Serial.printf("door=%s\n", doorClosed ? "CLOSED" : "OPEN");
  }
}
