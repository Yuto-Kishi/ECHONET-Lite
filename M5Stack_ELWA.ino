#include <M5Unified.h>
#include <WiFi.h>
#include <Wire.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <SensirionI2cScd4x.h>
#include <SensirionI2CSen5x.h>

// ========= Wi-Fi =========
#define WIFI_SSID "BuffaloAirStationPro"
#define WIFI_PASS "SummerCamp2018"

// ========= Echonet Web API（MQTTブローカ） =========
#define MQTT_BROKER "150.65.179.132"
#define MQTT_PORT   7883
#define CID         "53965d6805152d95"
#define DEV_ID      "M5Stack1"

// ========= AirQ I2C & GPIO =========
constexpr int PIN_I2C_SDA        = 11;
constexpr int PIN_I2C_SCL        = 12;
constexpr int PIN_EXT_SENSOR_EN  = 10;  // LOW = 外部センサ有効

// ========= センサー周期 =========
constexpr uint32_t SEN55_INTERVAL_MS      = 1000; // 1s
constexpr uint32_t SCD40_POLL_INTERVAL_MS = 500;  // 0.5s（≈5sごとにready）

// ========= 再接続ウォッチドッグ =========
constexpr uint32_t WIFI_CHECK_INTERVAL_MS = 5000; // Wi-Fi再接続試行間隔
constexpr uint32_t MQTT_RETRY_INTERVAL_MS = 3000; // MQTT再接続試行間隔

// ========= インスタンス =========
SensirionI2cScd4x scd4x;     // SCD40/41: CO2 / Temp / Hum
SensirionI2CSen5x sen5x;     // SEN55   : PM / VOC / NOx / Temp / Hum
WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

// ========= 状態保持 =========
unsigned long lastSen55ReadMs   = 0;
unsigned long lastScd40PollMs   = 0;
unsigned long lastWifiCheckMs   = 0;
unsigned long lastMqttAttemptMs = 0;

struct { bool valid=false; uint16_t co2=0; float temp=NAN, hum=NAN; } scd;
struct { bool valid=false; float pm1=NAN, pm25=NAN, pm4=NAN, pm10=NAN, temp=NAN, hum=NAN, voc=NAN, nox=NAN; } sen;

// ---------- MQTTユーティリティ ----------
void publishMqttMessage(const char* topic, const char* payload) {
  if (!mqttClient.connected()) {
    Serial.printf("MQTT offline, skip publish to %s\n", topic);
    return;
  }
  Serial.printf("Publishing to %s\n  %s\n", topic, payload);
  if (!mqttClient.publish(topic, payload)) {
    Serial.println("  -> Publish failed.");
  }
}

void registerDevice() {
  char topic[128];  snprintf(topic, sizeof(topic), "/server/%s/register", CID);
  StaticJsonDocument<256> doc;
  doc["id"] = DEV_ID;
  doc["deviceType"] = "airQualitySensor";
  char payload[256]; serializeJson(doc, payload);
  publishMqttMessage(topic, payload);
}

void registerProperties() {
  char topic[128];  snprintf(topic, sizeof(topic), "/server/%s/%s/properties", CID, DEV_ID);
  StaticJsonDocument<1024> doc;

  JsonObject manufacturer = doc.createNestedObject("manufacturer");
  manufacturer["code"] = "0x000000";
  JsonObject desc = manufacturer.createNestedObject("descriptions");
  desc["ja"] = "JAIST"; desc["en"] = "JAIST";
  JsonObject protocol = doc.createNestedObject("protocol");
  protocol["type"] = "custom_mqtt"; protocol["version"] = "1.0";

  // SCD40 & SEN55 のプロパティ名
  doc["scd40_co2"]  = 0;
  doc["scd40_temp"] = 0.0;
  doc["scd40_hum"]  = 0.0;
  doc["sen55_pm1"]   = 0.0;
  doc["sen55_pm2_5"] = 0.0;
  doc["sen55_pm4"]   = 0.0;
  doc["sen55_pm10"]  = 0.0;
  doc["sen55_temp"]  = 0.0;
  doc["sen55_hum"]   = 0.0;
  doc["sen55_voc"]   = 0.0;
  doc["sen55_nox"]   = 0.0;

  char payload[1024]; serializeJson(doc, payload);
  publishMqttMessage(topic, payload);
}

// ---------- 値の publish（プロパティ別トピック） ----------
void publish_scd40(uint16_t co2, float temp, float hum) {
  char topic[160], payload[160];
  snprintf(topic, sizeof(topic), "/server/%s/%s/properties/scd40_co2", CID, DEV_ID);
  { StaticJsonDocument<64> d; d["scd40_co2"] = co2; serializeJson(d, payload); publishMqttMessage(topic, payload); }
  snprintf(topic, sizeof(topic), "/server/%s/%s/properties/scd40_temp", CID, DEV_ID);
  { StaticJsonDocument<64> d; d["scd40_temp"] = temp; serializeJson(d, payload); publishMqttMessage(topic, payload); }
  snprintf(topic, sizeof(topic), "/server/%s/%s/properties/scd40_hum", CID, DEV_ID);
  { StaticJsonDocument<64> d; d["scd40_hum"]  = hum;  serializeJson(d, payload); publishMqttMessage(topic, payload); }
}

void publish_sen55(const decltype(sen)& s) {
  char topic[160], payload[160];
  snprintf(topic, sizeof(topic), "/server/%s/%s/properties/sen55_pm1", CID, DEV_ID);
  { StaticJsonDocument<64> d; d["sen55_pm1"] = s.pm1; serializeJson(d, payload); publishMqttMessage(topic, payload); }
  snprintf(topic, sizeof(topic), "/server/%s/%s/properties/sen55_pm2_5", CID, DEV_ID);
  { StaticJsonDocument<64> d; d["sen55_pm2_5"] = s.pm25; serializeJson(d, payload); publishMqttMessage(topic, payload); }
  snprintf(topic, sizeof(topic), "/server/%s/%s/properties/sen55_pm4", CID, DEV_ID);
  { StaticJsonDocument<64> d; d["sen55_pm4"] = s.pm4; serializeJson(d, payload); publishMqttMessage(topic, payload); }
  snprintf(topic, sizeof(topic), "/server/%s/%s/properties/sen55_pm10", CID, DEV_ID);
  { StaticJsonDocument<64> d; d["sen55_pm10"] = s.pm10; serializeJson(d, payload); publishMqttMessage(topic, payload); }
  snprintf(topic, sizeof(topic), "/server/%s/%s/properties/sen55_temp", CID, DEV_ID);
  { StaticJsonDocument<64> d; d["sen55_temp"] = s.temp; serializeJson(d, payload); publishMqttMessage(topic, payload); }
  snprintf(topic, sizeof(topic), "/server/%s/%s/properties/sen55_hum", CID, DEV_ID);
  { StaticJsonDocument<64> d; d["sen55_hum"]  = s.hum;  serializeJson(d, payload); publishMqttMessage(topic, payload); }
  snprintf(topic, sizeof(topic), "/server/%s/%s/properties/sen55_voc", CID, DEV_ID);
  { StaticJsonDocument<64> d; d["sen55_voc"] = s.voc; serializeJson(d, payload); publishMqttMessage(topic, payload); }
  snprintf(topic, sizeof(topic), "/server/%s/%s/properties/sen55_nox", CID, DEV_ID);
  { StaticJsonDocument<64> d; d["sen55_nox"] = s.nox; serializeJson(d, payload); publishMqttMessage(topic, payload); }
}

// ---------- ネットワーク・ウォッチドッグ（非ブロッキング） ----------
bool ensureWiFi() {
  if (WiFi.status() == WL_CONNECTED) return true;
  if (millis() - lastWifiCheckMs >= WIFI_CHECK_INTERVAL_MS) {
    lastWifiCheckMs = millis();
    Serial.println("WiFi disconnected. Reconnecting...");
    WiFi.disconnect(true, true);
    delay(20);
    WiFi.begin(WIFI_SSID, WIFI_PASS);
  }
  return false;
}

void tryReconnectMqtt() {
  if (mqttClient.connected()) return;
  if (WiFi.status() != WL_CONNECTED) return; // まずはWiFiを復旧
  if (millis() - lastMqttAttemptMs < MQTT_RETRY_INTERVAL_MS) return;

  lastMqttAttemptMs = millis();
  String clientId = String("esp32-client-") + DEV_ID;
  Serial.print("MQTT reconnect...");
  if (mqttClient.connect(clientId.c_str())) {
    Serial.println("OK");
    registerDevice();
    delay(200);
    registerProperties();
  } else {
    Serial.print("fail rc="); Serial.println(mqttClient.state());
  }
}

void networkWatchdog() {
  bool wifiOK = ensureWiFi();
  if (wifiOK) tryReconnectMqtt();
  if (mqttClient.connected()) mqttClient.loop();
}

// ---------- 初期化 ----------
void initSensors() {
  // I2C開始
  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);

  // 外部センサー電源制御（LOWで有効）
  pinMode(PIN_EXT_SENSOR_EN, OUTPUT);
  digitalWrite(PIN_EXT_SENSOR_EN, LOW);

  // --- SCD40 ---
  scd4x.begin(Wire, 0x62);
  scd4x.stopPeriodicMeasurement();
  scd4x.reinit();
  delay(20);
  uint16_t err = scd4x.startPeriodicMeasurement(); // ≈5s周期
  if (err) {
    char msg[64]; errorToString(err, msg, sizeof(msg));
    Serial.print("SCD40 start error: "); Serial.println(msg);
  } else {
    Serial.println("SCD40 started (≈5s/update).");
  }

  // --- SEN55 ---
  sen5x.begin(Wire);
  err = sen5x.deviceReset();
  if (err) { char msg[64]; errorToString(err, msg, sizeof(msg));
    Serial.print("SEN55 reset error: "); Serial.println(msg);
  }
  err = sen5x.startMeasurement(); // ≈1s更新
  if (err) { char msg[64]; errorToString(err, msg, sizeof(msg));
    Serial.print("SEN55 start error: "); Serial.println(msg);
  } else {
    Serial.println("SEN55 started (1s/update).");
  }
}

// =====================================================

void setup() {
  Serial.begin(115200);
  delay(200);

  // 画面（必要なら表示追加）
  auto cfg = M5.config();
  M5.begin(cfg);
  M5.Display.clear(TFT_BLACK);
  M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
  M5.Display.setTextSize(1);

  // Wi-Fiはここでは「開始」だけ（実接続はwatchdogに任せる）
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  // MQTTサーバ設定
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  mqttClient.setKeepAlive(30);

  // I2C & センサー
  initSensors();

  Serial.println("--- AirQ with auto-reconnect (Wi-Fi & MQTT) ---");
}

void loop() {
  // 1) ネットワークの自動復旧（Wi-Fi→MQTT の順）
  networkWatchdog();

  const unsigned long now = millis();

  // 2) SEN55: 1秒ごとに読み取り & テキスト表示 & MQTT
  if (now - lastSen55ReadMs >= SEN55_INTERVAL_MS) {
    lastSen55ReadMs = now;

    float pm1, pm25, pm4, pm10, rH, tC, voc, nox;
    uint16_t err = sen5x.readMeasuredValues(pm1, pm25, pm4, pm10, rH, tC, voc, nox);
    if (err) {
      char em[64]; errorToString(err, em, sizeof(em));
      Serial.print("SEN55 read error: "); Serial.println(em);
      sen.valid = false;
    } else {
      sen.valid = true;
      sen.pm1 = pm1; sen.pm25 = pm25; sen.pm4 = pm4; sen.pm10 = pm10;
      sen.temp = tC; sen.hum  = rH;   sen.voc = voc;  sen.nox = nox;

      // シリアル（テキスト）
      Serial.printf("PM1.0=%.1f ug/m3  PM2.5=%.1f ug/m3  PM4.0=%.1f ug/m3  PM10=%.1f ug/m3  Temp=%.2fC  Hum=%.2f%%RH  VOC=%.1f  NOx=%.1f\n",
                    sen.pm1, sen.pm25, sen.pm4, sen.pm10, sen.temp, sen.hum, sen.voc, sen.nox);

      // MQTT publish（オンライン時のみ）
      if (mqttClient.connected()) publish_sen55(sen);
    }
  }

  // 3) SCD40: 0.5秒ごとにready確認→readyなら読み & テキスト表示 & MQTT
  if (now - lastScd40PollMs >= SCD40_POLL_INTERVAL_MS) {
    lastScd40PollMs = now;

    bool ready = false;
    uint16_t err = scd4x.getDataReadyStatus(ready);
    if (!err && ready) {
      uint16_t co2; float tC, rH;
      err = scd4x.readMeasurement(co2, tC, rH);
      if (err) {
        char em[64]; errorToString(err, em, sizeof(em));
        Serial.print("SCD40 read error: "); Serial.println(em);
        scd.valid = false;
      } else if (co2 != 0) {
        scd.valid = true;
        scd.co2 = co2; scd.temp = tC; scd.hum = rH;

        Serial.printf("CO2=%uppm  Temp=%.2fC  Hum=%.2f%%RH\n", scd.co2, scd.temp, scd.hum);

        if (mqttClient.connected()) publish_scd40(scd.co2, scd.temp, scd.hum);
      }
    }
  }

  M5.update();
}
