# elwa_aggregate_csv_living_kitchen.py
# 集約対象:
#  - Living_Space1_SCD / Living_Space2_SCD / Living_Space3_SCD: co2, temperature, humidity, lux
#  - Kitchen_Space: co2, temperature, humidity, lux
#  - M5Stack1: scd40_(co2,temp,hum) / sen55_(pm1,pm2_5,pm4,pm10,temp,hum,voc,nox)
#  - door-amp1: door, sound_amp1(topic)/sound_amp(key), sound_trig
#  - pir-amp1: pir2, sound_amp, sound_trig, mic_occupied
#  - thermal_1: lepton_occupied -> CSV列名 "thermal-1"（未受信でも 0 を記録）
#  - HTTP PIR x6: detection を 0/1 で記録

import os
import csv
import json
import time
import threading
from datetime import datetime

import requests
import paho.mqtt.client as mqtt

# ============================
# ブローカ設定
# ============================
MQTT_BROKER = "150.65.179.132"
MQTT_PORT = 7883
CID = "53965d6805152d95"

# ============================
# CSV 設定
# ============================
CSV_FILE = "living_kitchen0916.csv"
WRITE_EVERY_SEC = 1.0

# ============================
# HTTP PIR（0/1で格納）
# ============================
HTTP_PIRS = [
    # 例: detection(bool) を 0/1 で保存。列名はID付きで一意に。
    (
        "http://150.65.179.132:7000/elapi/v1/devices/1921682115000702/properties/detection",
        "pir_http_1921682115000702",
    ),
    (
        "http://150.65.179.132:7000/elapi/v1/devices/1921682115000701/properties/detection",
        "pir_http_1921682115000701",
    ),
    (
        "http://150.65.179.132:7000/elapi/v1/devices/1921682114000701/properties/detection",
        "pir_http_1921682114000701",
    ),
    (
        "http://150.65.179.132:7000/elapi/v1/devices/1921682114000702/properties/detection",
        "pir_http_1921682114000702",
    ),
    (
        "http://150.65.179.132:7000/elapi/v1/devices/1921682113000701/properties/detection",
        "pir_http_1921682113000701",
    ),
    (
        "http://150.65.179.132:7000/elapi/v1/devices/1921682113000702/properties/detection",
        "pir_http_1921682113000702",
    ),
]

# ============================
# MQTT トピック → (JSONキー, CSV列名)
# ============================
TOPIC_MAP = []


def add_living_module(dev_id: str, label: str):
    TOPIC_MAP.extend(
        [
            (f"/server/{CID}/{dev_id}/properties/co2", "co2", f"co2({label})"),
            (
                f"/server/{CID}/{dev_id}/properties/temperature",
                "temperature",
                f"temperature({label})",
            ),
            (
                f"/server/{CID}/{dev_id}/properties/humidity",
                "humidity",
                f"humidity({label})",
            ),
            (f"/server/{CID}/{dev_id}/properties/lux", "lux", f"lux({label})"),
        ]
    )


# Living 1..3
add_living_module("Living_Space1_SCD", "Living1")
add_living_module("Living_Space2_SCD", "Living2")
add_living_module("Living_Space3_SCD", "Living3")

# Kitchen
add_living_module("Kitchen_Space", "Kitchen")

# M5Stack1
TOPIC_MAP.extend(
    [
        (f"/server/{CID}/M5Stack1/properties/scd40_co2", "scd40_co2", "scd40_co2"),
        (f"/server/{CID}/M5Stack1/properties/scd40_temp", "scd40_temp", "scd40_temp"),
        (f"/server/{CID}/M5Stack1/properties/scd40_hum", "scd40_hum", "scd40_hum"),
        (f"/server/{CID}/M5Stack1/properties/sen55_pm1", "sen55_pm1", "sen55_pm1"),
        (
            f"/server/{CID}/M5Stack1/properties/sen55_pm2_5",
            "sen55_pm2_5",
            "sen55_pm2_5",
        ),
        (f"/server/{CID}/M5Stack1/properties/sen55_pm4", "sen55_pm4", "sen55_pm4"),
        (f"/server/{CID}/M5Stack1/properties/sen55_pm10", "sen55_pm10", "sen55_pm10"),
        (f"/server/{CID}/M5Stack1/properties/sen55_temp", "sen55_temp", "sen55_temp"),
        (f"/server/{CID}/M5Stack1/properties/sen55_hum", "sen55_hum", "sen55_hum"),
        (f"/server/{CID}/M5Stack1/properties/sen55_voc", "sen55_voc", "sen55_voc"),
        (f"/server/{CID}/M5Stack1/properties/sen55_nox", "sen55_nox", "sen55_nox"),
    ]
)

# door-amp1（sound_ampはトピック名が sound_amp1、中のキーは "sound_amp"）
TOPIC_MAP.extend(
    [
        (f"/server/{CID}/door-amp1/properties/door", "door", "door"),
        (
            f"/server/{CID}/door-amp1/properties/sound_amp1",
            "sound_amp",
            "sound_amp_door",
        ),
        (
            f"/server/{CID}/door-amp1/properties/sound_trig",
            "sound_trig",
            "sound_trig_door",
        ),
    ]
)

# pir-amp1
TOPIC_MAP.extend(
    [
        (f"/server/{CID}/pir-amp1/properties/pir2", "pir2", "pir2"),
        (f"/server/{CID}/pir-amp1/properties/sound_amp", "sound_amp", "sound_amp_pir"),
        (
            f"/server/{CID}/pir-amp1/properties/sound_trig",
            "sound_trig",
            "sound_trig_pir",
        ),
        (
            f"/server/{CID}/pir-amp1/properties/mic_occupied",
            "mic_occupied",
            "mic_occupied",
        ),
    ]
)

# thermal_1 → thermal-1 列（未受信の秒は 0 を記録）
TOPIC_MAP.append(
    (
        f"/server/{CID}/thermal_1/properties/lepton_occupied",
        "lepton_occupied",
        "thermal-1",
    )
)

# ============================
# CSV ヘッダ構成
# ============================
FIELDNAMES = ["timestamp"]
# MQTT列
for _, _, field in TOPIC_MAP:
    if field not in FIELDNAMES:
        FIELDNAMES.append(field)
# HTTP PIR列
for _, field in HTTP_PIRS:
    if field not in FIELDNAMES:
        FIELDNAMES.append(field)

# ============================
# 共有状態
# ============================
latest_values = {k: None for k in FIELDNAMES if k != "timestamp"}
latest_lock = threading.Lock()


# ============================
# 補助
# ============================
def ensure_csv_header():
    need = (not os.path.exists(CSV_FILE)) or (os.path.getsize(CSV_FILE) == 0)
    if need:
        with open(CSV_FILE, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=FIELDNAMES).writeheader()


def set_value(field, value):
    with latest_lock:
        latest_values[field] = value


def coerce_bool_like_to_01(v):
    # bool/“true”/“false” などを 0/1 に
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, (int, float)) and v in (0, 1):
        return int(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "t", "yes", "y", "on"):
            return 1
        if s in ("false", "f", "no", "n", "off"):
            return 0
    return v  # 変換不可はそのまま


# ============================
# HTTP PIR ポーリング（巡回）
# ============================
def http_pir_loop():
    while True:
        for url, field in HTTP_PIRS:
            try:
                r = requests.get(url, timeout=1.5)
                r.raise_for_status()
                js = r.json()
                det = 1 if bool(js.get("detection", False)) else 0
                set_value(field, det)
            except Exception as e:
                # エラー時は値更新せず（前回値を保持）
                print(f"HTTP PIR error: {field}: {e}")
            time.sleep(0.05)  # 叩き過ぎ防止
        time.sleep(0.5)


# ============================
# MQTT コールバック
# ============================
TOPICS = [t[0] for t in TOPIC_MAP]
TOPIC_TO_KEY = {t[0]: (t[1], t[2]) for t in TOPIC_MAP}  # topic -> (json_key, field)


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("✅ MQTT connected")
        for t in TOPICS:
            client.subscribe(t)
            print("  subscribed:", t)
    else:
        print("❌ MQTT connect failed:", rc)


def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode(errors="ignore")
        data = json.loads(payload)
    except Exception as e:
        print(f"⚠️ JSON parse error on {msg.topic}: {e} / payload={msg.payload[:80]!r}")
        return

    if msg.topic in TOPIC_TO_KEY:
        json_key, field = TOPIC_TO_KEY[msg.topic]
        val = data.get(json_key, None)

        # 可能なら 0/1 に正規化（pir/occupied類）
        if field in (
            "pir2",
            "mic_occupied",
            "sound_trig_pir",
            "sound_trig_door",
            "thermal-1",
        ):
            val = coerce_bool_like_to_01(val)

        set_value(field, val)
        print(f"[{field}] <- {val}  ({msg.topic})")


# ============================
# ライタースレッド（毎秒）
# ============================
def writer_loop():
    ensure_csv_header()
    last_write = 0.0
    while True:
        now = time.time()
        if now - last_write >= WRITE_EVERY_SEC:
            with latest_lock:
                row = {"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

                for col in FIELDNAMES:
                    if col == "timestamp":
                        continue
                    v = latest_values.get(col, None)

                    # thermal-1 は未受信の秒でも 0 を強制
                    if col == "thermal-1" and v is None:
                        v = 0

                    # HTTP PIR は常に 0/1 で出したい（未受信は None のまま）
                    if col.startswith("pir_http_") and v is not None:
                        v = 1 if int(v) == 1 else 0

                    # その他のbooleanっぽい値も 0/1 化（可能なら）
                    if col in ("pir2", "mic_occupied"):
                        v = coerce_bool_like_to_01(v)

                    row[col] = v

            try:
                with open(CSV_FILE, "a", newline="") as f:
                    csv.DictWriter(f, fieldnames=FIELDNAMES).writerow(row)
                print("💾 CSV:", row)
            except Exception as e:
                print("⚠️ CSV write error:", e)

            last_write = now
        time.sleep(0.05)


# ============================
# メイン
# ============================
def main():
    # HTTP PIR ポーラ
    th = threading.Thread(target=http_pir_loop, daemon=True)
    th.start()

    # MQTT
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    client.loop_start()

    # CSVライタ
    writer_thread = threading.Thread(target=writer_loop, daemon=True)
    writer_thread.start()

    print("📡 集約開始（Ctrl+Cで終了） -> CSV:", os.path.abspath(CSV_FILE))
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 終了します。")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
