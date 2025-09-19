# monitor_esp32_pub.py
import argparse
import json
import time
from datetime import datetime, timedelta
import paho.mqtt.client as mqtt

EXPECTED_PROPS = ["co2", "temperature", "humidity", "lux"]


def parse_args():
    ap = argparse.ArgumentParser(description="ESP32 MQTT publish monitor")
    ap.add_argument("--broker", required=True)
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--cid", required=True)
    ap.add_argument("--dev-id", required=True, dest="devid")
    ap.add_argument("--duration", type=int, default=30, help="監視時間 (秒)")
    ap.add_argument(
        "--expect-interval",
        type=float,
        default=5.0,
        help="期待送信周期(秒)の目安。2倍を超えて未着なら遅延警告。",
    )
    ap.add_argument("--transport", choices=["tcp", "websockets"], default="tcp")
    ap.add_argument("--qos", type=int, choices=[0, 1, 2], default=0)
    return ap.parse_args()


def now_ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def is_plausible(prop, val):
    try:
        v = float(val)
    except Exception:
        return False, "非数値"
    if prop == "co2":
        return (350 <= v <= 10000), "350..10000ppm 推奨"
    if prop == "temperature":
        return (-20 <= v <= 60), "-20..60℃ 推奨"
    if prop == "humidity":
        return (0 <= v <= 100), "0..100% 推奨"
    if prop == "lux":
        return (v >= 0), "0以上 推奨"
    return True, ""  # 未知キー


def main():
    args = parse_args()

    base = f"/server/{args.cid}/{args.devid}"
    topics = [
        (f"/server/{args.cid}/register", args.qos),
        (f"{base}/properties", args.qos),  # 初期登録
        (f"{base}/properties/#", args.qos),  # 個別プロパティ
    ]

    last_seen = {k: None for k in EXPECTED_PROPS}
    counts = {k: 0 for k in EXPECTED_PROPS}
    suspicious = []

    def on_connect(client, userdata, flags, rc, properties=None):
        print(f"[{now_ts()}] Connected rc={rc}")
        for t, qos in topics:
            client.subscribe(t, qos=qos)
            print(f"  subscribed: {t} (qos={qos})")

    def on_message(client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode("utf-8", errors="replace")
        print(f"[{now_ts()}] <{topic}> {payload}")

        # どのプロパティかを推定
        prop = None
        if topic.endswith("/properties"):
            # 初回登録メッセージ（複数キー）
            try:
                data = json.loads(payload)
                for k in EXPECTED_PROPS:
                    if k in data:
                        last_seen[k] = time.time()
                        counts[k] += 1
                        ok, note = is_plausible(k, data[k])
                        if not ok:
                            suspicious.append((k, data[k], note, topic))
            except Exception as e:
                suspicious.append(("payload", payload, f"JSONエラー: {e}", topic))
            return
        else:
            # /properties/<prop> 形式
            parts = topic.split("/")
            if len(parts) >= 5 and parts[-2] == "properties":
                prop = parts[-1]

        # JSON から値を取り出す
        try:
            data = json.loads(payload)
        except Exception as e:
            suspicious.append(("payload", payload, f"JSONエラー: {e}", topic))
            return

        # prop がトピックから取れた場合はそれ優先、なければJSONのキーから推測
        if prop and prop in data:
            val = data[prop]
            last_seen[prop] = time.time()
            counts[prop] += 1
            ok, note = is_plausible(prop, val)
            if not ok:
                suspicious.append((prop, val, note, topic))
        else:
            # JSONの中から既知キーを拾う（保険）
            hit = False
            for k in EXPECTED_PROPS:
                if k in data:
                    last_seen[k] = time.time()
                    counts[k] += 1
                    ok, note = is_plausible(k, data[k])
                    if not ok:
                        suspicious.append((k, data[k], note, topic))
                    hit = True
            if not hit:
                suspicious.append(
                    ("unknown_keys", list(data.keys()), "既知キーなし", topic)
                )

    client = mqtt.Client(client_id=f"monitor-{args.devid}", transport=args.transport)
    client.on_connect = on_connect
    client.on_message = on_message

    # （必要なら）認証やTLSをここで設定
    # client.username_pw_set("user","pass")
    # client.tls_set(...)

    print(
        f"[{now_ts()}] Connecting to {args.broker}:{args.port} transport={args.transport}"
    )
    client.connect(args.broker, args.port, keepalive=30)

    t_end = time.time() + args.duration
    client.loop_start()
    try:
        while time.time() < t_end:
            time.sleep(0.2)
    finally:
        client.loop_stop()
        client.disconnect()

    print("\n==== Summary ====")
    ok_all = True
    for k in EXPECTED_PROPS:
        seen = last_seen[k]
        c = counts[k]
        if seen is None:
            print(f"NG: {k:<12} 未受信")
            ok_all = False
        else:
            ago = time.time() - seen
            lag_warn = ago > args.expect_interval * 2
            print(
                f"OK: {k:<12} {c}件  最終 {ago:4.1f}s 前"
                + ("  (遅延気味)" if lag_warn else "")
            )
            if lag_warn:
                ok_all = False

    if suspicious:
        ok_all = False
        print("\n[注意: 値の妥当性/形式に問題の可能性]")
        for item in suspicious[:20]:
            k, v, note, topic = item
            print(f" - {k}={v} ({note}) @ {topic}")
        if len(suspicious) > 20:
            print(f"  …ほか {len(suspicious)-20} 件")

    print(
        "\n判定:",
        (
            "✅ 正常にpublishされています"
            if ok_all
            else "⚠️ 問題の可能性あり（上のログを確認）"
        ),
    )


if __name__ == "__main__":
    main()
