// ESP32 + ホールセンサー ドア開閉検知テスト
// センサーOUT → ESP32 GPIO27
// センサーVCC → 3.3V
// センサーGND → GND

const int HALL_PIN = 27;  // センサーの出力ピンをつなぐGPIO番号
bool lastState = HIGH;    // 初期状態（磁å石が離れている＝ドア開）

void setup() {
  Serial.begin(115200);     // シリアルモニタ用
  pinMode(HALL_PIN, INPUT); // ホールセンサーはプッシュプル出力なのでINPUTでOK
  Serial.println("Door sensor ready. Bring a magnet close!");
}

void loop() {
  int state = digitalRead(HALL_PIN); 
  bool doorClosed = (state == LOW);  // アクティブLowなのでLOW=磁石あり=ドア閉

  // 状態が変化したときだけ出力
  if (doorClosed != (lastState == LOW)) {
    if (doorClosed) {
      Serial.println("🚪 Door CLOSED");
    } else {
      Serial.println("🚪 Door OPEN");
    }
    lastState = state;
  }

  delay(50); // センサー応答が約50ms周期なので十分
}
