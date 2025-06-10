#include <SensirionI2cScd4x.h>

#include <WiFi.h>
#include "EL.h"
#include <Adafruit_NeoPixel.h>
#include <Wire.h>              // I2C通信用




//--------------WIFI
#define WIFI_SSID "Buffalo-G-4970" // ご自身の2.4GHz帯のSSIDを入力
#define WIFI_PASS "cfn6v438t3rkb" // ご自身のパスワードを入力

WiFiUDP elUDP;
IPAddress myip;

//--------------EL
#define OBJ_NUM 3
EL echo(elUDP, { { 0x00, 0x12, 0x01 }, { 0x00, 0x11, 0x01 }, { 0x00, 0x13, 0x01 } });

//--------------SCD41
SensirionI2cScd4x scd4x;
float currentCo2 = 0.0;
float currentTemp = 0.0;
float currentHumidity = 0.0;
unsigned long lastSCD41ReadTime = 0;
const long scd41ReadInterval = 5000;

//====================================================================
// Echonet Lite コールバック関数
//====================================================================
bool callback(byte tid[], byte seoj[], byte deoj[], byte esv, byte opc, byte epc, byte pdc, byte edt[]) {
  bool ret = false;

  if (deoj[2] != 0x00 && deoj[2] != 0x01) { return false; } 

  // CO2濃度センサー (deoj[0]=0x00, deoj[1]=0x12)
  if (deoj[0] == 0x00 && deoj[1] == 0x12) {
    if (esv == EL_GET && epc == 0xE0) {
      uint16_t co2_ppm = (uint16_t)currentCo2;
      echo.update(0, epc, {(byte)(co2_ppm >> 8), (byte)(co2_ppm & 0xFF)}); // ★ 修正
      ret = true;
    }
  }
  // 温度センサー (deoj[0]=0x00, deoj[1]=0x11)
  else if (deoj[0] == 0x00 && deoj[1] == 0x11) {
    if (esv == EL_GET && epc == 0xE0) {
      int16_t temp_centi_c = (int16_t)(currentTemp * 10.0);
      echo.update(1, epc, {(byte)(temp_centi_c >> 8), (byte)(temp_centi_c & 0xFF)}); // ★ 修正
      ret = true;
    }
  }
  // 湿度センサー (deoj[0]=0x00, deoj[1]=0x13)
  else if (deoj[0] == 0x00 && deoj[1] == 0x13) {
    if (esv == EL_GET && epc == 0xE0) {
      byte humidity_percent = (byte)currentHumidity;
      echo.update(2, epc, {humidity_percent}); // ★ 修正
      ret = true;
    }
  }

  return ret;
}

//====================================================================
// setup
//====================================================================
void setup() {
  Serial.begin(115200);
  delay(2000);
  Serial.println("\n\n--- Starting Setup ---");

  // Wi-Fi接続
  Serial.println("Connecting to WiFi...");
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi Connected!");
  myip = WiFi.localIP();
  Serial.print("IP Address: ");
  Serial.println(myip);

  // SCD41センサーの初期化
  Serial.println("Initializing I2C and SCD41 Sensor...");
  Wire.begin(21, 19); // SDAピンが21番、SCLピンが19番であることを明示的に指定
  scd4x.begin(Wire, 0x62);

  uint16_t error;
  scd4x.stopPeriodicMeasurement();
  error = scd4x.startPeriodicMeasurement();
  if (error) {
    Serial.println("ERROR starting periodic measurement!");
    char errorMessage[256];
    errorToString(error, errorMessage, 256);
    Serial.print("Error message: ");
    Serial.println(errorMessage);
    Serial.println("Halting due to sensor error.");
    while (1);
  }
  Serial.println("SCD41 Initialized Successfully.");

  // Echonet Lite 起動シーケンス
  Serial.println("Starting ECHONET Lite...");
  echo.begin(callback);

  // --- ECHONET Lite オブジェクトごとの初期プロパティ設定 ---
  const byte SPEC_VER[] = { 0x00, 0x00, 0x52, 0x01 };
  const byte MAKER_CODE[] = { 0x00, 0x00, 0x77 };

  // ★★★ setup内のupdateもすべて修正 ★★★
  echo.update(0, 0x80, {0x30});
  echo.update(0, 0x82, {SPEC_VER[0], SPEC_VER[1], SPEC_VER[2], SPEC_VER[3]});
  echo.update(0, 0x8A, {MAKER_CODE[0], MAKER_CODE[1], MAKER_CODE[2]});
  echo.update(0, 0x9D, {4, 0x80, 0x82, 0x8A, 0xE0});
  echo.update(0, 0x9E, {0});
  echo.update(0, 0x9F, {5, 0x80, 0x82, 0x8A, 0xE0, 0x9F});

  echo.update(1, 0x80, {0x30});
  echo.update(1, 0x82, {SPEC_VER[0], SPEC_VER[1], SPEC_VER[2], SPEC_VER[3]});
  echo.update(1, 0x8A, {MAKER_CODE[0], MAKER_CODE[1], MAKER_CODE[2]});
  echo.update(1, 0x9D, {4, 0x80, 0x82, 0x8A, 0xE0});
  echo.update(1, 0x9E, {0});
  echo.update(1, 0x9F, {5, 0x80, 0x82, 0x8A, 0xE0, 0x9F});

  echo.update(2, 0x80, {0x30});
  echo.update(2, 0x82, {SPEC_VER[0], SPEC_VER[1], SPEC_VER[2], SPEC_VER[3]});
  echo.update(2, 0x8A, {MAKER_CODE[0], MAKER_CODE[1], MAKER_CODE[2]});
  echo.update(2, 0x9D, {4, 0x80, 0x82, 0x8A, 0xE0});
  echo.update(2, 0x9E, {0});
  echo.update(2, 0x9F, {5, 0x80, 0x82, 0x8A, 0xE0, 0x9F});
  
  Serial.println("--- Setup Complete! ---");
}

//====================================================================
// loop
//====================================================================
void loop() {
  echo.recvProcess();

  if (millis() - lastSCD41ReadTime >= scd41ReadInterval) {
    uint16_t co2;
    float temperature;
    float humidity;
    uint16_t error = scd4x.readMeasurement(co2, temperature, humidity);
    
    if (error) {
      Serial.println("Error reading SCD41 measurements.");
    } else if (co2 == 0) {
      Serial.println("Invalid sensor data detected, skipping update.");
    } else {
      currentCo2 = co2;
      currentTemp = temperature;
      currentHumidity = humidity;
      Serial.printf("CO2: %d ppm, Temp: %.2f C, Humid: %.2f %%RH\n", co2, temperature, humidity);

      // ECHONET Liteのプロパティを更新
      uint16_t co2_val = (uint16_t)currentCo2;
      echo.update(0, 0xE0, {(byte)(co2_val >> 8), (byte)(co2_val & 0xFF)}); // ★ 修正

      int16_t temp_val = (int16_t)(currentTemp * 10.0);
      echo.update(1, 0xE0, {(byte)(temp_val >> 8), (byte)(temp_val & 0xFF)}); // ★ 修正

      byte humidity_val = (byte)currentHumidity;
      echo.update(2, 0xE0, {humidity_val}); // ★ 修正
    }
    lastSCD41ReadTime = millis();
  }
}