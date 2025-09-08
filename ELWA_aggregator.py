# elwa_aggregate_csv.py
import os
import csv
import json
import time
import threading
from datetime import datetime

import requests
import paho.mqtt.client as mqtt

# ============================
# コンフィグ
# ============================
MQTT_BROKER = "150.65.179.132"
MQTT_PORT   = 7883
CID         = "53965d6805152d95"

CSV_FILE    = "elwa_all_sensors.csv"
WRITE_EVERY_SEC = 1.0        # 何秒ごとに1行書くか（スナップショット）
HTTP_PIR_ENABLED = True      # HTTP PIRも入れるなら True
PIR_URL = "http://150.65.179.132:7000/elapi/v1/devices/1921682116000702/properties/detection"
HTTP_PIR_FIELD = "pir_http"  # CSV列名

# 旧「multi-sensors」群も集約する場合のデバイスID
MULTI_DEV_IDS = ["multi-sensors1", "multi-sensors2", "multi-sensors3", "multi-sensors4"]
MULTI_KEYS    = ["co2", "temperature", "humidity", "lux"]

# ============================
# トピック→JSONキー→CSV列 の対応
# 受け取るトピックをここで宣言
# ============================
TOPIC_MAP = [
    # ---- pir-amp1 ----
    (f"/server/{CID}/pir-amp1/properties/pir2",          "pir2",          "pir2"),
    (f"/server/{CID}/pir-amp1/properties/sound_amp",     "sound_amp",     "sound_amp_pir"),
    (f"/server/{CID}/pir-amp1/properties/sound_trig",    "sound_trig",    "sound_trig_pir"),
    (f"/server/{CID}/pir-amp1/properties/mic_occupied",  "mic_occupied",  "mic_occupied"),

    # ---- door-amp1 ----
    (f"/server/{CID}/door-amp1/properties/door",         "door",          "door"),
    # トピックは sound_amp1 だが payload のキーは "sound_amp"
    (f"/server/{CID}/door-amp1/properties/sound_amp1",   "sound_amp",     "sound_amp_door"),
    (f"/server/{CID}/door-amp1/properties/sound_trig",   "sound_trig",    "sound_trig_door"),

    # ---- M5Stack1 (SCD40 & SEN55) ----
    (f"/server/{CID}/M5Stack1/properties/scd40_co2",     "scd40_co2",     "scd40_co2"),
    (f"/server/{CID}/M5Stack1/properties/scd40_temp",    "scd40_temp",    "scd40_temp"),
    (f"/server/{CID}/M5Stack1/properties/scd40_hum",     "scd40_hum",     "scd40_hum"),

    (f"/server/{CID}/M5Stack1/properties/sen55_pm1",     "sen55_pm1",     "sen55_pm1"),
    (f"/server/{CID}/M5Stack1/properties/sen55_pm2_5",   "sen55_pm2_5",   "sen55_pm2_5"),
    (f"/server/{CID}/M5Stack1/properties/sen55_pm4",     "sen55_pm4",     "sen55_pm4"),
    (f"/server/{CID}/M5Stack1/properties/sen55_pm10",    "sen55_pm10",    "sen55_pm10"),
    (f"/server/{CID}/M5Stack1/properties/sen55_temp",    "sen55_temp",    "sen55_temp"),
    (f"/server/{CID}/M5Stack1/properties/sen55_hum",     "sen55_hum",     "sen55_hum"),
    (f"/server/{CID}/M5Stack1/properties/sen55_voc",     "sen55_voc",     "sen55_voc"),
    (f"/server/{CID}/M5Stack1/properties/sen55_nox",     "sen55_nox",     "sen55_nox"),
]

# multi-sensors 系のトピックを追加
for dev_id in MULTI_DEV_IDS:
    suffix = dev_id.split("-")[-1]
    for key in MULTI_KEYS:
        topic = f"/server/{CID}/{dev_id}/properties/{key}"
        field = f"{key}(sensors_{suffix})"
        TOPIC_MAP.append((topic, key, field))

# ============================
# CSV ヘッダー
# ============================
FIELDNAMES = ["timestamp"]

if HTTP_PIR_ENABLED:
    FIELDNAMES.append(HTTP_PIR_FIELD)

# 宣言した全フィールドを列にする（重複排除）
for _, _, field in TOPIC_MAP:
    if field not in FIELDNAMES:
        FIELDNAMES.append(field)

# ============================
# 共有状態
# ============================
latest_values = {k: None for k in FIELDNAMES if k != "timestamp"}
latest_values_lock = threading.Lock()
latest_pir_http = None

# ============================
# ユーティリティ
# ============================
def ensure_csv_header():
    if not os.path.exists(CSV_FILE) or os.path.getsize(CSV_FILE) == 0:
        with open(CSV_FILE, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()

def set_value(field, value):
    with latest_values_lock:
        latest_values[field] = value

def http_pir_loop():
    global latest_pir_http
    while True:
        try:
            r = requests.get(PIR_URL, timeout=1.5)
            r.raise_for_status()
            js = r.json()
            latest_pir_http = bool(js.get("detection", False))
        except Exception as e:
            # エラー時は None に（前回値を残したいならコメントアウト）
            latest_pir_http = None
            print(f"HTTP PIR error: {e}")
        time.sleep(1)

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
        set_value(field, val)
        # 簡易ログ
        print(f"[{field}] <- {val}  ({msg.topic})")

# ============================
# ライターループ（毎秒）
# ============================
def writer_loop():
    ensure_csv_header()
    last_write = 0.0
    while True:
        now = time.time()
        if now - last_write >= WRITE_EVERY_SEC:
            with latest_values_lock:
                row = {"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                # PIR(HTTP)
                if HTTP_PIR_ENABLED:
                    row[HTTP_PIR_FIELD] = latest_pir_http
                # MQTTで集めた各値
                for k in FIELDNAMES:
                    if k in ("timestamp", HTTP_PIR_FIELD):
                        continue
                    row[k] = latest_values.get(k, None)

            # 追記
            try:
                with open(CSV_FILE, "a", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
                    writer.writerow(row)
                print("💾 CSV:", row)
            except Exception as e:
                print("⚠️ CSV write error:", e)

            last_write = now
        time.sleep(0.05)

# ============================
# メイン
# ============================
def main():
    # HTTP PIR
    if HTTP_PIR_ENABLED:
        th = threading.Thread(target=http_pir_loop, daemon=True)
        th.start()

    # MQTT
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    client.loop_start()

    # Writer
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
