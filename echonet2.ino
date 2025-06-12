#include <WiFi.h>
#include "EL.h"
#include <Adafruit_NeoPixel.h>

//--------------WIFI
#define WIFI_SSID "ここにSSID"
#define WIFI_PASS "ここにKEY"

WiFiUDP elUDP;
IPAddress myip;

//--------------EL
#define OBJ_NUM 1

EL echo(elUDP, { { 0x02, 0x90, 0x01 } } );
//クラスグループコード 住宅・設備関連機器:0x02, クラスコード 一般照明 : 0x90, インスタンスコード 01

//--------------LED
#define LED_PIN 6      // NeoPixelの出力ピン番号
#define LED_NUM 7      // LEDの連結数(素子の個数)
#define LUMINANCE 255  // 輝度の制限(最大値 : 255)

Adafruit_NeoPixel strip(LED_NUM, LED_PIN, NEO_GRB + NEO_KHZ800);

//--------------VARIABLES
uint8_t LED_R = 255, LED_G = 255, LED_B = 255, BRIGHTNESS = LUMINANCE;

//====================================================================
bool callback(byte tid[], byte seoj[], byte deoj[], byte esv, byte opc, byte epc, byte pdc, byte edt[]) {
  bool ret = false;                                          // デフォルトで失敗としておく
  if (deoj[0] != 0x02 || deoj[1] != 0x90) { return false; }  // 一般照明以外を除外
  if (deoj[2] != 0x00 && deoj[2] != 0x01) { return false; }  // 該当インスタンス以外を除外

  // -----------------------------------
  // ESVがSETとかGETとかで動作をかえる、基本的にはSETのみ対応すればよい
  switch (esv) {
    // -----------------------------------
    // 動作状態の変更 Set対応
    case EL_SETI:
    case EL_SETC:
      switch (epc) {
        // 電源
        case 0x80:
          if (edt[0] == 0x30) {
            Serial.println("電源ON 80 : 30");
            strip.clear();
            strip.setBrightness(BRIGHTNESS);
            for (int i = 0; i < LED_NUM; i++)
              strip.setPixelColor(i, strip.Color(LED_R, LED_G, LED_B));
            strip.show();
            echo.update(0, epc, { 0x30 });
            echo.update(0, 0xB6, { 0x42 });
            ret = true;
          }
          else if (edt[0] == 0x31) {
            Serial.println("電源OFF 80 : 31");
            strip.clear();
            strip.show();
            echo.update(0, epc, { 0x31 });
            ret = true;
          }
          else {
            ret = false;
          }
          break;

        // 照度の設定 edtを[0x00-0x64]で指定することで明るさに反映
        case 0xB0:
          if (0 <= edt[0] && edt[0] <= 100) {
            Serial.printf("照度レベル B0 : %d\n", edt[0]);
            strip.clear();
            BRIGHTNESS = int(edt[0]) * (LUMINANCE / 100);
            strip.setBrightness(BRIGHTNESS);
            for (int i = 0; i < LED_NUM; i++)
              strip.setPixelColor(i, strip.Color(LED_R, LED_G, LED_B));
            strip.show();
            echo.update(0, epc, { edt[0] });
            ret = true;
          }
          else {
            ret = false;
          }
          break;

        // LED点灯モードの設定　edtを[0x41-0x45]で指定してモードの変更
        case 0xB6:
          switch (edt[0]) {
            case 0x41:
              Serial.println("点灯モード 自動 B6 : 41");
              LED_R = LED_G = LED_B = 255;  // 白
              strip.clear();
              strip.setBrightness(LUMINANCE * 0.7);
              for (int i = 0; i < LED_NUM; i++)
                strip.setPixelColor(i, strip.Color(LED_R, LED_G, LED_B));
              strip.show();
              echo.update(0, epc, { edt[0] });
              echo.update(0, 0xC0, { LED_R, LED_G, LED_B });
              ret = true;
              break;

            case 0x42:
              Serial.println("点灯モード 通常灯 B6 : 42");
              LED_R = LED_G = LED_B = 255;  // 白
              strip.clear();
              strip.setBrightness(LUMINANCE);
              for (int i = 0; i < LED_NUM; i++)
                strip.setPixelColor(i, strip.Color(LED_R, LED_G, LED_B));
              strip.show();
              echo.update(0, epc, { edt[0] });
              echo.update(0, 0xC0, { LED_R, LED_G, LED_B });
              ret = true;
              break;

            case 0x43:
              Serial.println("点灯モード 常夜灯 B6 : 43");
              LED_R = 255, LED_G = 48, LED_G = 0;
              strip.clear();
              strip.setBrightness(LUMINANCE * 0.2);
              for (int i = 0; i < LED_NUM; i++)
                strip.setPixelColor(i, strip.Color(LED_R, LED_G, LED_B));
              strip.show();
              echo.update(0, epc, { edt[0] });
              echo.update(0, 0xC0, { LED_R, LED_G, LED_B });
              ret = true;
              break;

            case 0x45:
              Serial.println("点灯モード カラー灯 B6 : 45");
              LED_R = 0, LED_G = 0, LED_B = 255;
              strip.clear();
              strip.setBrightness(LUMINANCE * 0.5);
              for (int i = 0; i < LED_NUM; i++)
                strip.setPixelColor(i, strip.Color(LED_R, LED_G, LED_B));
              strip.show();
              echo.update(0, epc, { edt[0] });
              echo.update(0, 0xC0, { LED_R, LED_G, LED_B });
              ret = true;
              break;

            default:
              ret = false;
              break;
          }
          break;

        // カラー灯モード時RGB設定 edtの6桁でカラーコード指定
        case 0xC0:
          if (0 <= edt[0] && edt[0] <= 255) {
            if(0 <= edt[1] && edt[1] <= 255) {
              if(0 <= edt[2] && edt[2] <= 255) {
                LED_R = edt[0], LED_G = edt[1], LED_B = edt[2];
                Serial.printf("C0 : %d, %d, %d\n", LED_R, LED_G, LED_B);
                  strip.clear();
                for (int i = 0; i < LED_NUM; i++)
                  strip.setPixelColor(i, strip.Color(LED_R, LED_G, LED_B));
                strip.show();
                echo.update(0, epc, { LED_R, LED_G, LED_B });
                echo.update(0, 0xB6, { 0x45 });
                ret = true;
              }
            }
          }
          break;
      }
      // SETI, SETCここまで
      break;
    
    case EL_GET:
      break;

    // 基本はtrueを返却
    default:
      ret = true;
      break;
  }

  return ret;
}


//====================================================================
// main loop
void setup() {

  // シリアル開始
  Serial.begin(115200);

  // LED制御開始
  strip.begin();
  strip.clear();
  strip.setBrightness(0);
  strip.show();

  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) {
    Serial.print(".");
    delay(1000);
  }

  // print your WiFi IP address:
  myip = WiFi.localIP();

  echo.begin(callback);  // EL 起動シーケンス

  // 初期値設定
  echo.update(0, 0x80, { 0x31 });                                                                          // off
  echo.update(0, 0x81, { 0xFF });                                                                          // 場所不定
  echo.update(0, 0x82, { 0x00, 0x00, 0x52, 0x01 });                                                        // Release R rev.1
  //echo.update(0, 0x83, { 0x00 });                                                                        // 識別番号未設定
  // ライブラリによる初期設定が[0xfe + メーカーコード6桁 + macアドレス12桁 + 0x0e, 0xf0, 0x01, 0x00, 0x00, 0x00, 0x00]
  echo.update(0, 0x88, { 0x42 });                                                                          // 異常なし
  echo.update(0, 0x8A, { 0x00, 0x00, 0x77 });                                                              // 神奈川工科大学(000077)
  echo.update(0, 0x8E, { 0x07, 0xE8, 0x01, 0x01 });                                                        // 製造年月日(2023/01/01)
  echo.update(0, 0xB0, { BRIGHTNESS });                                                                    // 照度
  echo.update(0, 0xB6, { 0x42 });                                                                          // 通常灯
  echo.update(0, 0xC0, { LED_R, LED_G, LED_B });                                                           // 色設定(白)
  echo.update(0, 0x9D, { 0x80, 0xD6 });                                                                    // INFプロパティマップ
  echo.update(0, 0x9E, { 0x80, 0xB0, 0xB6, 0xC0 });                                                        // Setプロパティマップ
  echo.update(0, 0x9F, { 0x80, 0x81, 0x82, 0x83, 0x88, 0x8A, 0x8E, 0xB0, 0xB6, 0xC0, 0x9D, 0x9E, 0x9F });  // Getプロパティマップ

  echo.printAll();  // 全設定値の確認

  // 一般照明の状態，繋がった宣言として立ち上がったことをコントローラに知らせるINFを飛ばす
  const byte deoj[] = { 0x05, 0xFF, 0x01 };
  const byte edt[] = { 0x01, 0x31 };
  echo.sendMultiOPC1(deoj, EL_INF, 0x80, edt);
}

//====================================================================
// main loop
void loop() {

  echo.recvProcess();

  delay(300);
}
