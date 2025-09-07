#include <M5Unified.h>
#include <WiFi.h>
#include <Wire.h>
#include <SensirionI2cScd4x.h>
#include <SensirionI2CSen5x.h>

// ======== ★ Wi-Fi 設定（ここを書き換え） ========
#define WIFI_SSID "Kissinger"
#define WIFI_PASS "chkishilish1119"
// ===============================================

// ===== Instances =====
SensirionI2cScd4x scd4x;   // SCD40/41: CO2 / Temp / Hum
SensirionI2CSen5x sen5x;   // SEN55   : PM / VOC / NOx / Temp / Hum

// ===== AirQ pins =====
constexpr int PIN_I2C_SDA = 11;
constexpr int PIN_I2C_SCL = 12;
constexpr int PIN_EXT_SENSOR_EN = 10;  // 外部センサ電源制御: LOWで有効

// ===== Timers =====
unsigned long lastSen55ReadMs = 0;
unsigned long lastScd40PollMs = 0;
constexpr uint32_t SEN55_INTERVAL_MS      = 1000; // 1s
constexpr uint32_t SCD40_POLL_INTERVAL_MS = 500;  // 0.5s で readiness 確認

// 最新値保持
struct { bool valid=false; uint16_t co2=0; float temp=NAN, hum=NAN; } scd;
struct { bool valid=false; float pm1=NAN, pm25=NAN, pm4=NAN, pm10=NAN, temp=NAN, hum=NAN, voc=NAN, nox=NAN; } sen;

// ---- Wi-Fi 接続（成功ならIP表示、失敗時は周辺スキャンを表示） ----
void connectWiFiOrScan() {
  M5.Display.fillScreen(TFT_BLACK);
  M5.Display.setCursor(0, 0);
  M5.Display.setTextSize(1);
  M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);

  WiFi.mode(WIFI_STA);
  WiFi.disconnect(true, true);
  delay(200);

  M5.Display.printf("Connecting to:\n%s\n\n", WIFI_SSID);
  Serial.printf("Connecting to %s ...\n", WIFI_SSID);

  WiFi.begin(WIFI_SSID, WIFI_PASS);

  const uint32_t timeoutMs = 20000;  // 20秒待つ
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < timeoutMs) {
    M5.Display.print(".");
    Serial.print(".");
    delay(300);
    M5.update();
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    IPAddress ip = WiFi.localIP();
    M5.Display.printf("\nConnected!\nIP: %s\n\n", ip.toString().c_str());
    Serial.printf("Connected. IP: %s\n", ip.toString().c_str());
    return;
  }

  // 失敗したらスキャンで見えるAPを表示
  M5.Display.println("\nFailed. Scanning Wi-Fi...");
  Serial.println("Failed to connect. Scanning Wi-Fi...");

  WiFi.disconnect();
  delay(150);
  int n = WiFi.scanNetworks(false, true);
  M5.Display.printf("Found %d networks\n\n", n);
  Serial.printf("Found %d networks\n", n);

  for (int i = 0; i < n; i++) {
    String ssid = WiFi.SSID(i);
    int rssi = WiFi.RSSI(i);
    bool enc = (WiFi.encryptionType(i) != WIFI_AUTH_OPEN);
    M5.Display.printf("%2d: %s\n    (%d dBm, %s)\n\n", i+1, ssid.c_str(), rssi, enc ? "secure" : "open");
    Serial.printf("%2d: %-32s  %4d dBm  %s\n", i+1, ssid.c_str(), rssi, enc ? "secure" : "open");
    delay(20);
  }
}

void setup() {
  Serial.begin(115200);
  delay(200);

  // --- M5 init（画面を使う） ---
  auto cfg = M5.config();
  M5.begin(cfg);
  M5.Display.clear(TFT_BLACK);
  M5.Display.setTextSize(1);
  M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);

  // --- I2C開始（AirQ: SDA=11, SCL=12） ---
  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);

  // --- 外部センサー電源制御（LOWで有効） ---
  pinMode(PIN_EXT_SENSOR_EN, OUTPUT);
  digitalWrite(PIN_EXT_SENSOR_EN, LOW);

  // --- Wi-Fiへ接続（またはスキャン表示） ---
  connectWiFiOrScan();

  // --- SCD40 ---
  scd4x.begin(Wire, 0x62);
  scd4x.stopPeriodicMeasurement();
  scd4x.reinit();
  delay(20);
  uint16_t err = scd4x.startPeriodicMeasurement();  // ≈5s周期
  if (err) {
    char msg[64]; errorToString(err, msg, sizeof(msg));
    Serial.print("SCD40 start error: "); Serial.println(msg);
    M5.Display.setTextColor(TFT_RED, TFT_BLACK);
    M5.Display.printf("SCD40 start error:\n%s\n", msg);
  } else {
    Serial.println("SCD40 started. Wait ~5s for first data...");
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
    M5.Display.setTextColor(TFT_RED, TFT_BLACK);
    M5.Display.printf("SEN55 start error:\n%s\n", msg);
  } else {
    Serial.println("SEN55 started.");
  }

  Serial.println("--- AirQ text output mode ---");
}

void loop() {
  const unsigned long now = millis();

  // ---- SEN55: 毎秒読む & テキストで1行出力 ----
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
      sen.temp = tC; sen.hum  = rH;   sen.voc = voc; sen.nox  = nox;

      Serial.printf(
        "PM1.0=%.1f ug/m3  PM2.5=%.1f ug/m3  PM4.0=%.1f ug/m3  PM10=%.1f ug/m3  Temp=%.2fC  Hum=%.2f%%RH  VOC=%.1f  NOx=%.1f\n",
        sen.pm1, sen.pm25, sen.pm4, sen.pm10, sen.temp, sen.hum, sen.voc, sen.nox
      );
    }
  }

  // ---- SCD40: 0.5秒ごとにready確認→readyなら読み & テキストで1行出力 ----
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
      }
    }
  }

  M5.update();
}
