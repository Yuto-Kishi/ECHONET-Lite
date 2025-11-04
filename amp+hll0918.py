#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ESP32 の MQTT Publish を監視するサブスクライバ
- /server/{CID}/register
- /server/{CID}/{DEV_ID}/properties
- /server/{CID}/{DEV_ID}/properties/#
を購読して内容を表示し、想定間隔より途切れたら WARN を出します。
"""

import argparse
import json
import time
import sys
from datetime import datetime
from collections import defaultdict

import paho.mqtt.client as mqtt


def parse_args():
    p = argparse.ArgumentParser(description="ESP32 MQTT publisher monitor (subscriber)")
    p.add_argument("--broker", default="150.65.179.132", help="MQTT broker host/IP")
    p.add_argument("--port", type=int, default=7883, help="MQTT port")
    p.add_argument("--cid", default="53965d6805152d95", help="CID")
    p.add_argument("--dev-id", default="living_door", help="Device ID")
    p.add_argument(
        "--duration", type=int, default=120, help="Run time in seconds (0=forever)"
    )
    p.add_argument(
        "--expect-interval",
        type=float,
        default=2.5,
        help="Expected publish interval seconds (WARN if no message for > interval)",
    )
    p.add_argument(
        "--transport",
        choices=["tcp", "websockets"],
        default="tcp",
        help="MQTT transport",
    )
    p.add_argument(
        "--qos", type=int, choices=[0, 1, 2], default=0, help="Subscribe QoS"
    )
    return p.parse_args()


def pretty_json(payload: bytes):
    try:
        obj = json.loads(payload.decode("utf-8"))
        return True, json.dumps(obj, ensure_ascii=False)
    except Exception:
        try:
            return False, payload.decode("utf-8", errors="replace")
        except Exception:
            return False, repr(payload)


def main():
    args = parse_args()

    cid = args.cid
    dev = args.dev_id

    topics = [
        f"/server/{cid}/register",
        f"/server/{cid}/{dev}/properties",
        f"/server/{cid}/{dev}/properties/#",
    ]

    # 計測用
    counts = defaultdict(int)
    last_seen = {}  # topic -> ts
    last_prop_seen = defaultdict(float)  # "door"/"sound_amp"/"sound_trig" 別に時刻記録

    start_ts = time.time()

    def on_connect(client, userdata, flags, rc, properties=None):
        if rc == 0:
            print(
                f"[{datetime.now().isoformat(timespec='seconds')}] Connected to {args.broker}:{args.port} ({args.transport})"
            )
            for t in topics:
                client.subscribe(t, qos=args.qos)
                print(f"  - Subscribed: {t} (QoS {args.qos})")
        else:
            print(f"Connect failed: rc={rc}")
            # rc!=0 の時は自動で再接続が走る

    # 受信
    def on_message(client, userdata, msg):
        now = time.time()
        ok, body = pretty_json(msg.payload)
        counts[msg.topic] += 1
        last_seen[msg.topic] = now

        # どのプロパティか推定
        prop_name = None
        if msg.topic.endswith("/properties/door"):
            prop_name = "door"
        elif msg.topic.endswith("/properties/sound_amp"):
            prop_name = "sound_amp"
        elif msg.topic.endswith("/properties/sound_trig"):
            prop_name = "sound_trig"
        elif msg.topic.endswith("/properties"):
            prop_name = "properties_root"
        elif msg.topic.endswith("/register"):
            prop_name = "register"

        if prop_name:
            last_prop_seen[prop_name] = now

        ts = datetime.now().isoformat(timespec="seconds")
        print(f"\n[{ts}] {msg.topic}")
        print(f"  payload: {body}")

        # 軽いバリデーション
        if prop_name == "door":
            try:
                j = json.loads(msg.payload.decode("utf-8"))
                v = str(j.get("door", "")).upper()
                if v not in ("OPEN", "CLOSED"):
                    print("  WARN: door should be 'OPEN' or 'CLOSED'")
            except Exception:
                print("  WARN: door payload is not JSON")
        elif prop_name == "sound_amp":
            try:
                j = json.loads(msg.payload.decode("utf-8"))
                amp = j.get("sound_amp", None)
                if not isinstance(amp, (int, float)):
                    print("  WARN: sound_amp should be number")
            except Exception:
                print("  WARN: sound_amp payload is not JSON")
        elif prop_name == "sound_trig":
            try:
                j = json.loads(msg.payload.decode("utf-8"))
                trig = j.get("sound_trig", None)
                if not isinstance(trig, (bool, int)):
                    print("  WARN: sound_trig should be boolean-like")
            except Exception:
                print("  WARN: sound_trig payload is not JSON")

    def on_disconnect(client, userdata, rc, properties=None):
        print(
            f"[{datetime.now().isoformat(timespec='seconds')}] Disconnected (rc={rc}). Auto-reconnect will try..."
        )

    client = mqtt.Client(
        client_id=f"monitor-{dev}", transport=args.transport, protocol=mqtt.MQTTv311
    )
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect
    client.reconnect_delay_set(min_delay=1, max_delay=5)
    client.keepalive = 30

    try:
        client.connect(args.broker, args.port, keepalive=30)
    except Exception as e:
        print(f"ERROR: cannot connect to {args.broker}:{args.port} -> {e}")
        sys.exit(2)

    client.loop_start()

    try:
        while True:
            time.sleep(0.5)

            # 監視: 期待間隔を超えて来ていないプロパティがあればWARN
            now = time.time()
            for prop in ("door", "sound_amp", "sound_trig"):
                last = last_prop_seen.get(prop, 0.0)
                if last == 0.0:
                    # 未受信
                    continue
                if now - last > args.expect_interval:
                    print(
                        f"[WARN] {prop} last message {now - last:.1f}s ago (> {args.expect_interval}s)."
                    )

            if args.duration and (now - start_ts) >= args.duration:
                break
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()

        # サマリ
        print("\n=== SUMMARY ===")
        all_cnt = 0
        for t in sorted(counts.keys()):
            c = counts[t]
            all_cnt += c
            age = "-"
            if t in last_seen:
                age = f"{time.time() - last_seen[t]:.1f}s ago"
            print(f"{t:60s}  count={c:4d}  last={age}")
        print(f"TOTAL messages: {all_cnt}")

        # 主要プロパティの最新受信からの経過
        for prop in ("register", "properties_root", "door", "sound_amp", "sound_trig"):
            last = last_prop_seen.get(prop, 0.0)
            if last:
                print(f"last {prop:16s}: {time.time() - last:.1f}s ago")
            else:
                print(f"last {prop:16s}: (no message)")
        print("===============")


if __name__ == "__main__":
    main()
