# collect_all_to_csv.py
# 指定のセンサー(M5Stack/door-amp1/pir-amp1/thermal_1 + HTTP PIR×2)のみを集約してCSV化

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

CSV_FILE = "washitsu0915.csv"
WRITE_EVERY_SEC = 1.0  # 何秒ごとに1行書くか
THERMAL_DEV_ID = "thermal_1"  # thermal 側の DEV_ID に合わせる
FORCE_THERMAL_EACH_WRITE = True  # その秒に未受信でも False を書く

# ---- HTTP PIR（0/1で出力）----
HTTP_PIR_ENDPOINTS = {
    "pir_http_0702": "http://150.65.179.132:7000/elapi/v1/devices/1921682116000702/properties/detection",
    "pir_http_0701": "http://150.65.179.132:7000/elapi/v1/devices/1921682116000701/properties/detection",
}

# ============================
# MQTT: トピック -> (payloadキー, CSV列名)
# ============================
TOPIC_MAP = [
    # ---- pir-amp1 ----
    (f"/server/{CID}/pir-amp1/properties/pir2", "pir2", "pir2"),
    (f"/server/{CID}/pir-amp1/properties/sound_amp", "sound_amp", "sound_amp_pir"),
    (f"/server/{CID}/pir-amp1/properties/sound_trig", "sound_trig", "sound_trig_pir"),
    (f"/server/{CID}/pir-amp1/properties/mic_occupied", "mic_occupied", "mic_occupied"),
    # ---- door-amp1 ----
    (f"/server/{CID}/door-amp1/properties/door", "door", "door"),
    # topicは sound_amp1 だが payload のキーは "sound_amp"
    (f"/server/{CID}/door-amp1/properties/sound_amp1", "sound_amp", "sound_amp_door"),
    (f"/server/{CID}/door-amp1/properties/sound_trig", "sound_trig", "sound_trig_door"),
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
    # ---- Lepton / thermal-1 ----
    (
        f"/server/{CID}/{THERMAL_DEV_ID}/properties/lepton_occupied",
        "lepton_occupied",
        "thermal-1",
    ),
]

# ============================
# CSV ヘッダー
# ============================
FIELDNAMES = ["timestamp"] + list(HTTP_PIR_ENDPOINTS.keys())
for _, _, field in TOPIC_MAP:
    if field not in FIELDNAMES:
        FIELDNAMES.append(field)

# ============================
# 共有状態
# ============================
latest_values = {k: None for k in FIELDNAMES if k != "timestamp"}
latest_lock = threading.Lock()


# HTTP PIR 取得
def poll_http_pir(name: str, url: str):
    """1秒ごとにHTTP PIRを取得（0/1）"""
    while True:
        val = None
        try:
            r = requests.get(url, timeout=1.5)
            r.raise_for_status()
            js = r.json()
            det = bool(js.get("detection", False))
            val = 1 if det else 0
        except Exception as e:
            # エラー時は val=None（CSVは空欄）
            print(f"[HTTP PIR] {name} error: {e}")
        with latest_lock:
            latest_values[name] = val
        time.sleep(1)


# 値の正規化（CSVへ入れる直前）
def normalize_value(field: str, value):
    if value is None:
        return None
    # thermal-1 / pir2 / sound_trig / mic_occupied は 0/1 で統一
    if field in (
        "thermal-1",
        "pir2",
        "sound_trig_pir",
        "sound_trig_door",
        "mic_occupied",
    ):
        try:
            return 1 if bool(value) else 0
        except Exception:
            return None
    # door は OPEN/CLOSED のまま（必要なら 0/1 に変換可）
    if field == "door":
        return str(value)
    # 数値はそのまま
    return value


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
        with latest_lock:
            latest_values[field] = val
        # ログ（うるさければコメントアウト可）
        print(f"[{field}] <- {val}  ({msg.topic})")


# ============================
# ライターループ（毎秒）
# ============================
def writer_loop():
    # ヘッダー作成
    need_header = (not os.path.exists(CSV_FILE)) or (os.path.getsize(CSV_FILE) == 0)
    if need_header:
        with open(CSV_FILE, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=FIELDNAMES).writeheader()

    last_write = 0.0
    while True:
        now = time.time()
        if now - last_write >= WRITE_EVERY_SEC:
            with latest_lock:
                row = {"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                # HTTP PIR（すでに 0/1 に正規化済み）
                for name in HTTP_PIR_ENDPOINTS.keys():
                    row[name] = latest_values.get(name, None)

                # MQTT 系
                for k in FIELDNAMES:
                    if k in ("timestamp", *HTTP_PIR_ENDPOINTS.keys()):
                        continue
                    v = latest_values.get(k, None)

                    # thermal-1 は未受信でも False=0 を入れる
                    if FORCE_THERMAL_EACH_WRITE and k == "thermal-1" and v is None:
                        v = 0

                    row[k] = normalize_value(k, v)

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
    # HTTP PIR スレッド起動
    for name, url in HTTP_PIR_ENDPOINTS.items():
        threading.Thread(target=poll_http_pir, args=(name, url), daemon=True).start()

    # MQTT
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    client.loop_start()

    # Writer
    threading.Thread(target=writer_loop, daemon=True).start()

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
