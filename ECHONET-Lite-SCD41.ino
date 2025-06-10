#include <SensirionI2cScd4x.h>

#include <WiFi.h>
#include "EL.h"
#include <Adafruit_NeoPixel.h>
#include <Wire.h>              // I2C通信用


//--------------WIFI
#define WIFI_SSID "Buffalo-A-5660" // ここにSSIDを入力
#define WIFI_PASS "k7cx3s37e6b6k" // ここにKEYを入力

WiFiUDP elUDP;
IPAddress myip;

//--------------EL
// ECHONET Lite オブジェクトの定義:
// インデックス0: 一般照明 (0x02, 0x90, 0x01)
// インデックス1: CO2濃度センサー (0x00, 0x12, 0x01)
// インデックス2: 温度センサー (0x00, 0x11, 0x01)
// インデックス3: 湿度センサー (0x00, 0x13, 0x01)
#define OBJ_NUM 4
EL echo(elUDP, { { 0x02, 0x90, 0x01 }, { 0x00, 0x12, 0x01 }, { 0x00, 0x11, 0x01 }, { 0x00, 0x13, 0x01 } });

//--------------LED
#define LED_PIN 6     // NeoPixelの出力ピン番号
#define LED_NUM 7     // LEDの連結数(素子の個数)
#define LUMINANCE 255 // 輝度の制限(最大値 : 255)

Adafruit_NeoPixel strip(LED_NUM, LED_PIN, NEO_GRB + NEO_KHZ800);

//--------------SCD41
SensirionI2cScd4x scd4x; // 
float currentCo2 = 0.0;
float currentTemp = 0.0;
float currentHumidity = 0.0;
unsigned long lastSCD41ReadTime = 0;
const long scd41ReadInterval = 5000; // 5秒ごとにSCD41を読み取る

//--------------VARIABLES (LED用)
uint8_t LED_R = 255, LED_G = 255, LED_B = 255, BRIGHTNESS = LUMINANCE;
bool isLedOn = false; // LEDの現在の状態を保持

//====================================================================
// Echonet Lite コールバック関数
//====================================================================
bool callback(byte tid[], byte seoj[], byte deoj[], byte esv, byte opc, byte epc, byte pdc, byte edt[]) {
  bool ret = false; // デフォルトで失敗としておく

  // deoj[2] != 0x01 は、インスタンスコード1番のみを対象とするフィルタ
  if (deoj[2] != 0x00 && deoj[2] != 0x01) { return false; } 

  // **オブジェクト分岐**

  // **一般照明 (deoj[0]=0x02, deoj[1]=0x90)**
  if (deoj[0] == 0x02 && deoj[1] == 0x90) {
    switch (esv) {
      case EL_SETI:
      case EL_SETC:
        switch (epc) {
          // 電源 (0x80)
          case 0x80:
            if (edt[0] == 0x30) { // ON
              Serial.println("Light Power ON 80:30");
              isLedOn = true;
              strip.clear();
              strip.setBrightness(BRIGHTNESS);
              for (int i = 0; i < LED_NUM; i++)
                strip.setPixelColor(i, strip.Color(LED_R, LED_G, LED_B));
              strip.show();
              echo.update(0, epc, { 0x30 });
              ret = true;
            } else if (edt[0] == 0x31) { // OFF
              Serial.println("Light Power OFF 80:31");
              isLedOn = false;
              strip.clear();
              strip.show();
              echo.update(0, epc, { 0x31 });
              ret = true;
            }
            break;
          // 照度の設定 (0xB0)
          case 0xB0:
            if (edt[0] >= 0 && edt[0] <= 100) {
              Serial.printf("Brightness Level B0: %d\n", edt[0]);
              BRIGHTNESS = map(edt[0], 0, 100, 0, LUMINANCE);
              if (isLedOn) { strip.setBrightness(BRIGHTNESS); strip.show(); }
              echo.update(0, epc, { edt[0] });
              ret = true;
            }
            break;
          // (他の照明関連のSET処理は省略... 元のコードと同様に実装)
        }
        break; // SETI, SETC 終了
      
      case EL_GET:
        // (照明関連のGET処理... 元のコードと同様に実装)
        break;
    }
  }
  // **CO2濃度センサー (deoj[0]=0x00, deoj[1]=0x12)**
  else if (deoj[0] == 0x00 && deoj[1] == 0x12) {
    switch (esv) {
      case EL_GET:
        switch (epc) {
          case 0x80: // 動作状態
            echo.update(1, epc, { 0x30 }); // 常にON
            ret = true;
            break;
          case 0xE0: // CO2濃度測定値
            {
              uint16_t co2_ppm = (uint16_t)currentCo2;
              byte co2_h = (byte)(co2_ppm >> 8);
              byte co2_l = (byte)(co2_ppm & 0xFF);
              echo.update(1, epc, { co2_h, co2_l });
              Serial.printf("GET CO2(E0): %d ppm\n", co2_ppm);
              ret = true;
            }
            break;
        }
        break;
    }
  }
  // **温度センサー (deoj[0]=0x00, deoj[1]=0x11)**
  else if (deoj[0] == 0x00 && deoj[1] == 0x11) {
    switch (esv) {
      case EL_GET:
        switch (epc) {
          case 0x80: // 動作状態
            echo.update(2, epc, { 0x30 }); // 常にON
            ret = true;
            break;
          case 0xE0: // 温度測定値
            {
              int16_t temp_centi_c = (int16_t)(currentTemp * 10.0); // 0.1℃単位
              byte temp_h = (byte)(temp_centi_c >> 8);
              byte temp_l = (byte)(temp_centi_c & 0xFF);
              echo.update(2, epc, { temp_h, temp_l });
              Serial.printf("GET Temp(E0): %.1f C\n", currentTemp);
              ret = true;
            }
            break;
        }
        break;
    }
  }
  // **湿度センサー (deoj[0]=0x00, deoj[1]=0x13)**
  else if (deoj[0] == 0x00 && deoj[1] == 0x13) {
    switch (esv) {
      case EL_GET:
        switch (epc) {
          case 0x80: // 動作状態
            echo.update(3, epc, { 0x30 }); // 常にON
            ret = true;
            break;
          case 0xE0: // 湿度測定値
            {
              byte humidity_percent = (byte)currentHumidity; // 1%単位
              echo.update(3, epc, { humidity_percent });
              Serial.printf("GET Humid(E0): %.0f %%RH\n", currentHumidity);
              ret = true;
            }
            break;
        }
        break;
    }
  }

  if (ret) {
    return true;
  } else {
    // 該当する処理がない場合、基本的にはtrueを返して正常応答とする
    return true;
  }
}

//====================================================================
// setup
//====================================================================
void setup() {
  Serial.begin(115200);

  // LED制御開始
  strip.begin();
  strip.clear();
  strip.setBrightness(0);
  strip.show();

  // Wi-Fi接続
  Serial.print("Connecting to WiFi: ");
  Serial.println(WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) {
    delay(1000);
    Serial.print(".");
  }
  Serial.println("\nWiFi connected.");
  myip = WiFi.localIP();
  Serial.print("IP Address: ");
  Serial.println(myip);

  // SCD41センサーの初期化
  Wire.begin();
  scd4x.begin(Wire, 0x62); // 第2引数にI2Cアドレスを追加

  uint16_t error;
  char errorMessage[256];
  scd4x.stopPeriodicMeasurement(); // 念のため一度停止
  error = scd4x.startPeriodicMeasurement();
  if (error) {
    Serial.println("Error starting SCD41 periodic measurement.");
    errorToString(error, errorMessage, 256);
    Serial.println(errorMessage);
    while (1); // センサーが動かないと困るので停止
  }
  Serial.println("SCD41 sensor initialized.");

  // Echonet Lite 起動シーケンス
  echo.begin(callback);

  // --- Echonet Lite オブジェクトごとの初期プロパティ設定 ---
  const byte SPEC_VER[] = { 0x00, 0x00, 0x52, 0x01 }; // Release R rev.1
  const byte MAKER_CODE[] = { 0x00, 0x00, 0x77 };     // メーカーコード (仮: 神奈川工科大学)

  // オブジェクト0: 一般照明 (0x02, 0x90, 0x01)
  echo.update(0, 0x80, { 0x31 }); // 電源OFF
  echo.update(0, 0x81, { 0xFF }); // 場所不定
  echo.update(0, 0x82, SPEC_VER);
  echo.update(0, 0x88, { 0x42 }); // 異常なし
  echo.update(0, 0x8A, MAKER_CODE);
  echo.update(0, 0xB0, { 100 });  // 照度100%
  // プロパティマップ
  echo.update(0, 0x9D, { 6, 0x80, 0x81, 0x82, 0x88, 0x8A, 0x9D, 0x9E, 0x9F });
  echo.update(0, 0x9E, { 2, 0x80, 0xB0 });
  echo.update(0, 0x9F, { 9, 0x80, 0x81, 0x82, 0x88, 0x8A, 0xB0, 0x9D, 0x9E, 0x9F });

  // オブジェクト1: CO2濃度センサー (0x00, 0x12, 0x01)
  echo.update(1, 0x80, { 0x30 }); // 電源ON
  echo.update(1, 0x81, { 0xFF }); // 場所不定
  echo.update(1, 0x82, SPEC_VER);
  echo.update(1, 0x8A, MAKER_CODE);
  echo.update(1, 0xE0, { 0x00, 0x00 }); // CO2濃度 (初期値0ppm)
  // プロパティマップ
  echo.update(1, 0x9D, { 5, 0x80, 0x81, 0x82, 0x8A, 0xE0 });
  echo.update(1, 0x9E, { 0 });
  echo.update(1, 0x9F, { 6, 0x80, 0x81, 0x82, 0x8A, 0xE0, 0x9F });

  // オブジェクト2: 温度センサー (0x00, 0x11, 0x01)
  echo.update(2, 0x80, { 0x30 }); // 電源ON
  echo.update(2, 0x81, { 0xFF }); // 場所不定
  echo.update(2, 0x82, SPEC_VER);
  echo.update(2, 0x8A, MAKER_CODE);
  echo.update(2, 0xE0, { 0x80, 0x01 }); // 温度 (初期値-3276.7℃:無効値)
  // プロパティマップ
  echo.update(2, 0x9D, { 5, 0x80, 0x81, 0x82, 0x8A, 0xE0 });
  echo.update(2, 0x9E, { 0 });
  echo.update(2, 0x9F, { 6, 0x80, 0x81, 0x82, 0x8A, 0xE0, 0x9F });

  // オブジェクト3: 湿度センサー (0x00, 0x13, 0x01)
  echo.update(3, 0x80, { 0x30 }); // 電源ON
  echo.update(3, 0x81, { 0xFF }); // 場所不定
  echo.update(3, 0x82, SPEC_VER);
  echo.update(3, 0x8A, MAKER_CODE);
  echo.update(3, 0xE0, { 0x00 }); // 湿度 (初期値0%)
  // プロパティマップ
  echo.update(3, 0x9D, { 5, 0x80, 0x81, 0x82, 0x8A, 0xE0 });
  echo.update(3, 0x9E, { 0 });
  echo.update(3, 0x9F, { 6, 0x80, 0x81, 0x82, 0x8A, 0xE0, 0x9F });

  echo.printAll(); // 全設定値の確認

  // 起動時に自ノードのインスタンスリストを通知 (必須)
  // ノードプロファイル(0x0E,0xF0,0x01)宛に通知
  const byte deoj[] = { 0x0E, 0xF0, 0x01 };

}

//====================================================================
// loop
//====================================================================
//====================================================================
// loop
//====================================================================
void loop() {
  echo.recvProcess(); // Echonet Lite通信処理は常に呼び出す

  // 5秒ごとにセンサーを読み取る
  if (millis() - lastSCD41ReadTime >= scd41ReadInterval) {
    // 【ここからが修正箇所】
    uint16_t co2;
    float temperature;
    float humidity;
    uint16_t error; // ★ error変数をここで宣言する

    error = scd4x.readMeasurement(co2, temperature, humidity); // ★ ここで値を入れる
    
    if (error) {
      Serial.println("Error reading SCD41 measurements.");
    } else if (co2 == 0) {
      Serial.println("Invalid SCD41 sensor data detected!");
    } else {
      currentCo2 = co2;
      currentTemp = temperature;
      currentHumidity = humidity;
      Serial.printf("CO2: %d ppm, Temp: %.2f C, Humid: %.2f %%RH\n", co2, temperature, humidity);

      // --- Echonet Liteのプロパティを更新 ---
      // CO2濃度 (インデックス1, EPC 0xE0)
      uint16_t co2_ppm_el = (uint16_t)currentCo2;
      echo.update(1, 0xE0, { (byte)(co2_ppm_el >> 8), (byte)(co2_ppm_el & 0xFF) });

      // 温度 (インデックス2, EPC 0xE0)
      int16_t temp_centi_c_el = (int16_t)(currentTemp * 10.0);
      echo.update(2, 0xE0, { (byte)(temp_centi_c_el >> 8), (byte)(temp_centi_c_el & 0xFF) });

      // 湿度 (インデックス3, EPC 0xE0)
      byte humidity_val_el = (byte)currentHumidity;
      echo.update(3, 0xE0, { humidity_val_el });
    }
    lastSCD41ReadTime = millis();
    // 【ここまでを置き換える】
  }
}