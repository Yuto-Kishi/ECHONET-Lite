// === ESP32 + Two PIR sensors: print state every second ===
// Wiring example:
//   PIR1 (HC-SR501): VCC->5V,  GND->GND, OUT->GPIO26
//   PIR2 (Keyestudio): VCC->3V3(or 5V), GND->GND, SIG->GPIO27

const int PIR1_PIN = 26;   // HC-SR501
const int PIR2_PIN = 27;   // Keyestudio PIR

// 起動直後の不安定期間をスキップ（必要なければ 0 に）
const unsigned long WARMUP_IGNORE_MS = 10000;

unsigned long t0;
unsigned long lastPrint = 0;

void setup() {
  Serial.begin(115200);
  pinMode(PIR1_PIN, INPUT);  // モジュール側がプッシュプル出力のため INPUT でOK
  pinMode(PIR2_PIN, INPUT);

  t0 = millis();
  Serial.println("\n=== Two PIR: print state every 1s ===");
  Serial.println("PIR1(HC-SR501)=GPIO26, PIR2(Keyestudio)=GPIO27");
}

void loop() {
  unsigned long now = millis();

  // 起動直後の不安定期間は読みを無視（HC-SR501対策）
  if (now - t0 < WARMUP_IGNORE_MS) {
    // 簡易カウントダウン表示（1秒間隔）
    if (now - lastPrint >= 1000) {
      unsigned long left = (WARMUP_IGNORE_MS - (now - t0)) / 1000;
      Serial.printf("[warmup] wait %lus...\n", left + 1);
      lastPrint = now;
    }
    return;
  }

  // 毎秒ステートを出力
  if (now - lastPrint >= 1000) {
    int s1 = digitalRead(PIR1_PIN);  // 1: motion, 0: no motion
    int s2 = digitalRead(PIR2_PIN);

    // 見やすいように1行でJSON風に
    Serial.printf("{\"pir1\":%d,\"pir2\":%d}\n", s1, s2);

    // もし文字で見たいならこちらでもOK（上のprintfをコメントアウトして使う）
    // Serial.printf("PIR1:%s  PIR2:%s\n", s1 ? "MOTION" : "no", s2 ? "MOTION" : "no");

    lastPrint = now;
  }

  // ループを軽く
  delay(5);
}
