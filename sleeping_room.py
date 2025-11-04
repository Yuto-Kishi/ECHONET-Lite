# elwa_sleepingroom_aggregate.py
# 対象：sleeping_room, M5Stack1, door-amp1, pir-amp1, HTTP PIR(2台)
# 出力：elwa_sleepingroom_sensors.csv を毎秒1行で追記
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
MQTT_PORT = 7883
CID = "53965d6805152d95"

CSV_FILE = "sleepingroom0916.csv"
WRITE_EVERY_SEC = 1.0  # 何秒ごとに1行書くか（スナップショット）

# ---- HTTP PIR (寝室の固定2台) ----
HTTP_PIRS = {
    # 列名 : URL
    "pir_http_1921682121000702": "http://150.65.179.132:7000/elapi/v1/devices/1921682121000702/properties/detection",
    "pir_http_1921682121000701": "http://150.65.179.132:7000/elapi/v1/devices/1921682121000701/properties/detection",
}

# ============================
# トピック→JSONキー→CSV列 の対応
# ============================
TOPIC_MAP = [
    # ---- sleeping_room (SCD + BH1750) ----
    (f"/server/{CID}/sleeping_room/properties/co2", "co2", "co2(sleeping)"),
    (
        f"/server/{CID}/sleeping_room/properties/temperature",
        "temperature",
        "temperature(sleeping)",
    ),
    (
        f"/server/{CID}/sleeping_room/properties/humidity",
        "humidity",
        "humidity(sleeping)",
    ),
    (f"/server/{CID}/sleeping_room/properties/lux", "lux", "lux(sleeping)"),
    # ---- M5Stack1 (SCD40 & SEN55) ----
    (f"/server/{CID}/M5Stack1/properties/scd40_co2", "scd40_co2", "scd40_co2"),
    (f"/server/{CID}/M5Stack1/properties/scd40_temp", "scd40_temp", "scd40_temp"),
    (f"/server/{CID}/M5Stack1/properties/scd40_hum", "scd40_hum", "scd40_hum"),
    (f"/server/{CID}/M5Stack1/properties/sen55_pm1", "sen55_pm1", "sen55_pm1"),
    (f"/server/{CID}/M5Stack1/properties/sen55_pm2_5", "sen55_pm2_5", "sen55_pm2_5"),
    (f"/server/{CID}/M5Stack1/properties/sen55_pm4", "sen55_pm4", "sen55_pm4"),
    (f"/server/{CID}/M5Stack1/properties/sen55_pm10", "sen55_pm10", "sen55_pm10"),
    (f"/server/{CID}/M5Stack1/properties/sen55_temp", "sen55_temp", "sen55_temp"),
    (f"/server/{CID}/M5Stack1/properties/sen55_hum", "sen55_hum", "sen55_hum"),
    (f"/server/{CID}/M5Stack1/properties/sen55_voc", "sen55_voc", "sen55_voc"),
    (f"/server/{CID}/M5Stack1/properties/sen55_nox", "sen55_nox", "sen55_nox"),
    # ---- door-amp1 ----
    (f"/server/{CID}/door-amp1/properties/door", "door", "door"),
    # トピックは sound_amp1 だが payload のキーは "sound_amp"
    (f"/server/{CID}/door-amp1/properties/sound_amp1", "sound_amp", "sound_amp_door"),
    (f"/server/{CID}/door-amp1/properties/sound_trig", "sound_trig", "sound_trig_door"),
    # ---- pir-amp1 ----
    (f"/server/{CID}/pir-amp1/properties/pir2", "pir2", "pir2"),
    (f"/server/{CID}/pir-amp1/properties/sound_amp", "sound_amp", "sound_amp_pir"),
    (f"/server/{CID}/pir-amp1/properties/sound_trig", "sound_trig", "sound_trig_pir"),
    (f"/server/{CID}/pir-amp1/properties/mic_occupied", "mic_occupied", "mic_occupied"),
]

# 0/1へ正規化したい列（bool想定）
BOOL_FIELDS = {
    "pir2",
    "mic_occupied",
    "sound_trig_pir",
    "sound_trig_door",
    # HTTP PIR も 0/1 で保存
    *HTTP_PIRS.keys(),
}

# ============================
# CSV ヘッダー
# ============================
FIELDNAMES = ["timestamp"]
# HTTP PIR列
FIELDNAMES.extend(HTTP_PIRS.keys())
# MQTT列
for _, _, field in TOPIC_MAP:
    if field not in FIELDNAMES:
        FIELDNAMES.append(field)

# ============================
# 共有状態
# ============================
latest_values = {k: None for k in FIELDNAMES if k != "timestamp"}
latest_values_lock = threading.Lock()


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


def bool_like_to_int(v):
    """True/Falseや'true'/'false'を0/1に。数値やNoneはそのまま。"""
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "t", "1", "on", "yes"):
            return 1
        if s in ("false", "f", "0", "off", "no"):
            return 0
    return v  # その他はそのまま


# ============================
# HTTP PIR ポーリング
# ============================
def http_pir_loop(name: str, url: str):
    while True:
        try:
            r = requests.get(url, timeout=1.5)
            r.raise_for_status()
            js = r.json()
            det = js.get("detection", None)
            val = bool_like_to_int(det) if det is not None else None
            set_value(name, val)
        except Exception as e:
            # 失敗時は None を入れる（ネットワーク断など）
            set_value(name, None)
            print(f"[HTTP PIR] {name} error: {e}")
        time.sleep(1.0)


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
                for k in FIELDNAMES:
                    if k == "timestamp":
                        continue
                    v = latest_values.get(k, None)
                    # bool想定列は0/1正規化
                    if k in BOOL_FIELDS and v is not None:
                        v = bool_like_to_int(v)
                    row[k] = v
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
    # HTTP PIR threads
    for name, url in HTTP_PIRS.items():
        th = threading.Thread(target=http_pir_loop, args=(name, url), daemon=True)
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
