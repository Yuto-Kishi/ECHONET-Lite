# mqtt_probe.py
# ESP32(AirQ: SCD40+SEN55) が Echonet Web API (MQTT) へ publish しているかを検証するツール
# - 対象トピック:
#   /server/{CID}/register
#   /server/{CID}/{DEV_ID}/properties
#   /server/{CID}/{DEV_ID}/properties/...
# - JSON payload を解析して、キー一致/型/レンジを簡易チェックします。

import argparse
import json
import time
import signal
import sys
from collections import defaultdict

import paho.mqtt.client as mqtt

def parse_args():
    ap = argparse.ArgumentParser(description="Probe Echonet Web API MQTT publishes from ESP32 (AirQ).")
    ap.add_argument("--host", default="150.65.179.132")
    ap.add_argument("--port", type=int, default=7883)
    ap.add_argument("--cid",  default="53965d6805152d95")
    ap.add_argument("--dev-id", default="M5Stack1")
    ap.add_argument("--username", default=None, help="MQTT username (not used in your current setup)")
    ap.add_argument("--password", default=None, help="MQTT password (not used in your current setup)")
    ap.add_argument("--timeout", type=int, default=120, help="Seconds to run before summarizing")
    return ap.parse_args()

class Validator:
    def __init__(self, cid, dev_id):
        self.cid = cid
        self.dev_id = dev_id

        # 統計
        self.counts = defaultdict(int)
        self.last_payload = {}
        self.errors = []
        self.start_ts = time.time()

        # 受信確認フラグ
        self.saw_register   = False
        self.saw_schema     = False
        self.saw_scd40_any  = False
        self.saw_sen55_any  = False

        # プロパティの期待一覧（キー名）
        self.expected_props = {
            "scd40_co2":  ("number", (250, 10000)),   # ppm 想定レンジ
            "scd40_temp": ("number", (-20.0, 80.0)),  # °C 想定レンジ（環境に合わせて調整可）
            "scd40_hum":  ("number", (0.0, 100.0)),   # %RH
            "sen55_pm1":   ("number", (0.0, 2000.0)),
            "sen55_pm2_5": ("number", (0.0, 2000.0)),
            "sen55_pm4":   ("number", (0.0, 2000.0)),
            "sen55_pm10":  ("number", (0.0, 2000.0)),
            "sen55_temp":  ("number", (-20.0, 80.0)),
            "sen55_hum":   ("number", (0.0, 100.0)),
            "sen55_voc":   ("number", (-1000.0, 10000.0)),  # 指標/指数のため広め
            "sen55_nox":   ("number", (-1000.0, 10000.0)),
        }

    def log(self, s):
        dt = time.time() - self.start_ts
        print(f"[{dt:6.1f}s] {s}")

    def check_payload(self, topic: str, payload: bytes):
        self.counts[topic] += 1
        text = payload.decode("utf-8", errors="replace").strip()
        self.last_payload[topic] = text

        # JSONでない場合は注意喚起
        try:
            data = json.loads(text)
        except Exception as e:
            self.errors.append(f"JSON parse error on {topic}: {e}; payload={text!r}")
            self.log(f"⚠️  Non-JSON or invalid JSON on {topic}: {text}")
            return

        # register（デバイス登録）
        if topic == f"/server/{self.cid}/register":
            dev_id = data.get("id")
            if dev_id != self.dev_id:
                self.errors.append(f"register id mismatch: expected {self.dev_id}, got {dev_id}")
                self.log(f"❌ register id mismatch: {dev_id}")
            else:
                self.saw_register = True
                self.log(f"✅ register received: id={dev_id}")
            return

        # properties スキーマ登録
        if topic == f"/server/{self.cid}/{self.dev_id}/properties":
            # 期待キーの存在をざっくり確認
            missing = [k for k in self.expected_props.keys() if k not in data]
            if missing:
                self.errors.append(f"properties schema missing keys: {missing}")
                self.log(f"⚠️ properties schema missing keys: {missing}")
            else:
                self.saw_schema = True
                self.log("✅ properties schema received (looks good)")
            return

        # 各プロパティ
        prefix = f"/server/{self.cid}/{self.dev_id}/properties/"
        if topic.startswith(prefix):
            prop = topic[len(prefix):]  # 例: scd40_co2
            if prop not in self.expected_props:
                self.log(f"ℹ️  {prop} (unexpected property key) payload={data}")
                return

            # JSON のキー名がトピックと一致しているか
            if prop not in data:
                self.errors.append(f"{prop}: key not found in payload keys={list(data.keys())}")
                self.log(f"❌ {prop}: key missing in payload: {data}")
                return

            value = data[prop]
            expected_type, (lo, hi) = self.expected_props[prop]

            # 型チェック
            if expected_type == "number":
                if not isinstance(value, (int, float)):
                    self.errors.append(f"{prop}: expected number, got {type(value).__name__}")
                    self.log(f"❌ {prop}: non-number value={value!r}")
                    return

                # レンジチェック（広め）
                if value < lo or value > hi:
                    self.log(f"⚠️  {prop}: value {value} out of expected range [{lo}, {hi}]")

            # グループ到達フラグ
            if prop.startswith("scd40_"):
                self.saw_scd40_any = True
            if prop.startswith("sen55_"):
                self.saw_sen55_any = True

            self.log(f"✅ {prop} = {value}")

def main():
    args = parse_args()
    v = Validator(args.cid, args.dev_id)

    client = mqtt.Client(client_id=f"probe-{int(time.time())}")
    if args.username:
        client.username_pw_set(args.username, args.password)

    # コールバック
    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            v.log(f"Connected to MQTT {args.host}:{args.port}")
            # 監視トピックに一括サブスクライブ
            topics = [
                (f"/server/{args.cid}/register", 0),
                (f"/server/{args.cid}/{args.dev_id}/properties", 0),
                (f"/server/{args.cid}/{args.dev_id}/properties/#", 0),
            ]
            for t, q in topics:
                client.subscribe(t, qos=q)
                v.log(f"SUB {t}")
        else:
            v.log(f"MQTT connect failed rc={rc}")

    def on_message(client, userdata, msg):
        v.log(f"MSG {msg.topic}  {msg.payload!r}")
        v.check_payload(msg.topic, msg.payload)

    def on_disconnect(client, userdata, rc):
        v.log(f"Disconnected rc={rc}")

    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    # 接続
    client.connect(args.host, args.port, keepalive=30)

    # Ctrl+C でサマリ表示して終了
    stopping = False
    def handle_sigint(sig, frame):
        nonlocal stopping
        if not stopping:
            stopping = True
            print("\n\n=== SUMMARY ===")
            duration = time.time() - v.start_ts
            print(f"Duration: {duration:.1f}s")
            print(f"Messages per topic:")
            for t, c in sorted(v.counts.items()):
                print(f"  {t}: {c}")
            print(f"\nSeen:")
            print(f"  register: {'YES' if v.saw_register else 'no'}")
            print(f"  properties schema: {'YES' if v.saw_schema else 'no'}")
            print(f"  any scd40_*: {'YES' if v.saw_scd40_any else 'no'}")
            print(f"  any sen55_*: {'YES' if v.saw_sen55_any else 'no'}")
            if v.errors:
                print("\nErrors / Warnings:")
                for e in v.errors:
                    print(f"  - {e}")
            else:
                print("\nNo errors recorded.")
            print("\nBye.")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sigint)

    # タイムアウトで自動サマリ
    deadline = time.time() + args.timeout
    client.loop_start()
    try:
        while time.time() < deadline:
            time.sleep(0.1)
        handle_sigint(None, None)
    finally:
        client.loop_stop()
        client.disconnect()

if __name__ == "__main__":
    main()
