#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
指定デバイスの MQTT publish を購読し、毎秒スナップショットを CSV に追記します。
対象デバイスとプロパティ（Arduino側スケッチに合わせています）:

- /server/{CID}/Living_West/properties/{co2, temperature, humidity, lux}
- /server/{CID}/M5Stack1/properties/{scd40_co2, scd40_temp, scd40_hum,
                                     sen55_pm1, sen55_pm2_5, sen55_pm4, sen55_pm10,
                                     sen55_temp, sen55_hum, sen55_voc, sen55_nox}
- /server/{CID}/door-sensor1/properties/{door, sound_amp, sound_trig}
- /server/{CID}/Kitchen/properties/{co2, temperature, humidity, lux}

CSVは毎秒「その時点の最新値」を1行として記録します。未受信の値は None になります。
"""

import argparse
import csv
import json
import os
import signal
import sys
import time
from datetime import datetime
from threading import Lock, Thread

import paho.mqtt.client as mqtt


# ---------- 引数 ----------
def parse_args():
    p = argparse.ArgumentParser(
        description="Collect selected MQTT sensors to CSV (Living_West / M5Stack1 / door-sensor1 / Kitchen)"
    )
    p.add_argument("--broker", default="150.65.179.132")
    p.add_argument("--port", type=int, default=7883)
    p.add_argument("--cid", default="53965d6805152d95", help="CID (server/<CID>/...)")
    p.add_argument("--out", default="elwa_selected.csv", help="output CSV path")
    p.add_argument(
        "--interval", type=float, default=1.0, help="snapshot write interval (sec)"
    )
    p.add_argument("--qos", type=int, default=0, choices=[0, 1, 2])
    p.add_argument("--transport", choices=["tcp", "websockets"], default="tcp")
    p.add_argument("--keepalive", type=int, default=60)
    return p.parse_args()


# ---------- トピック→JSONキー→CSV列名 ----------
def build_topic_map(cid: str):
    m = []

    # Living_West
    for k in ["co2", "temperature", "humidity", "lux"]:
        topic = f"/server/{cid}/Living_West/properties/{k}"
        m.append((topic, k, f"Living_West__{k}"))

    # M5Stack1
    for k in [
        "scd40_co2",
        "scd40_temp",
        "scd40_hum",
        "sen55_pm1",
        "sen55_pm2_5",
        "sen55_pm4",
        "sen55_pm10",
        "sen55_temp",
        "sen55_hum",
        "sen55_voc",
        "sen55_nox",
    ]:
        topic = f"/server/{cid}/M5Stack1/properties/{k}"
        m.append((topic, k, f"M5Stack1__{k}"))

    # door-sensor1（CSV列名はハイフン無しにします）
    for k in ["door", "sound_amp", "sound_trig"]:
        topic = f"/server/{cid}/door-sensor1/properties/{k}"
        m.append((topic, k, f"door_sensor1__{k}"))

    # Kitchen
    for k in ["co2", "temperature", "humidity", "lux"]:
        topic = f"/server/{cid}/Kitchen/properties/{k}"
        m.append((topic, k, f"Kitchen__{k}"))

    return m


# ---------- 共有状態 ----------
class State:
    def __init__(self, fieldnames):
        self.lock = Lock()
        self.values = {k: None for k in fieldnames if k != "timestamp"}

    def set_value(self, field, value):
        with self.lock:
            self.values[field] = value

    def snapshot_row(self):
        with self.lock:
            row = {"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            row.update(self.values)
            return row


# ---------- CSV ----------
def ensure_csv_header(csv_path, fieldnames):
    need_header = (not os.path.exists(csv_path)) or (os.path.getsize(csv_path) == 0)
    if need_header:
        os.makedirs(os.path.dirname(csv_path) or ".", exist_ok=True)
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()


# ---------- MQTT コールバック ----------
def make_on_connect(topics, qos):
    def _on_connect(client, userdata, flags, rc):
        if rc == 0:
            print("✅ MQTT connected")
            for t in topics:
                client.subscribe(t, qos=qos)
                print("  subscribed:", t)
        else:
            print(f"❌ MQTT connect failed: rc={rc}")

    return _on_connect


def make_on_message(topic_to_key_field, state: State):
    def _on_message(client, userdata, msg):
        try:
            payload = msg.payload.decode(errors="ignore")
            data = json.loads(payload)
        except Exception as e:
            print(
                f"⚠️ JSON parse error on {msg.topic}: {e} / payload={msg.payload[:80]!r}"
            )
            return

        tup = topic_to_key_field.get(msg.topic)
        if not tup:
            return
        json_key, field = tup

        val = data.get(json_key, None)
        # 軽い型整形（数値らしきものは数値化、"OPEN"/"CLOSED"はそのまま）
        if isinstance(val, str):
            s = val.strip().lower()
            if s in ("true", "false"):
                val = s == "true"
            else:
                try:
                    # int/float への変換を試みる（失敗したら文字列のまま）
                    if "." in s or "e" in s:
                        val = float(val)
                    else:
                        val = int(val)
                except Exception:
                    pass

        state.set_value(field, val)
        print(f"[{field}] <- {val}  ({msg.topic})")

    return _on_message


# ---------- ライタースレッド ----------
def writer_loop(csv_path, fieldnames, state: State, interval_sec: float, stop_flag):
    ensure_csv_header(csv_path, fieldnames)
    print(f"📡 集約開始（Ctrl+C で終了） -> CSV: {os.path.abspath(csv_path)}")
    while not stop_flag["stop"]:
        row = state.snapshot_row()
        try:
            with open(csv_path, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writerow(row)
            # 進行ログ（うるさい場合はコメントアウト）
            print("💾 CSV:", row)
        except Exception as e:
            print("⚠️ CSV write error:", e)
        time.sleep(interval_sec)


# ---------- メイン ----------
def main():
    args = parse_args()

    topic_map = build_topic_map(args.cid)
    topics = [t for (t, _, _) in topic_map]
    topic_to_key_field = {t: (k, field) for (t, k, field) in topic_map}

    # CSVヘッダ（timestamp + 全列）
    fieldnames = ["timestamp"]
    for _, _, field in topic_map:
        if field not in fieldnames:
            fieldnames.append(field)

    state = State(fieldnames)

    client = mqtt.Client(transport=args.transport)
    client.on_connect = make_on_connect(topics, qos=args.qos)
    client.on_message = make_on_message(topic_to_key_field, state)

    # 接続
    client.connect(args.broker, args.port, keepalive=args.keepalive)
    client.loop_start()

    # Writer thread
    stop_flag = {"stop": False}
    wt = Thread(
        target=writer_loop,
        args=(args.out, fieldnames, state, args.interval, stop_flag),
        daemon=True,
    )
    wt.start()

    # Ctrl+C ハンドリング
    def handle_sigint(signum, frame):
        print("\n🛑 終了処理中...")
        stop_flag["stop"] = True
        client.loop_stop()
        client.disconnect()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sigint)
    signal.signal(signal.SIGTERM, handle_sigint)

    # メインスレッドは待機
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        handle_sigint(None, None)


if __name__ == "__main__":
    main()
