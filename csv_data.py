import json
import csv
import os
import time
import threading
import requests
from datetime import datetime
import paho.mqtt.client as mqtt

# --- PIRセンサー設定 ---
PIR_URL = "http://150.65.179.132:7000/elapi/v1/devices/1921682116000702/properties/detection"
latest_pir_value = False

def update_pir_loop():
    global latest_pir_value
    while True:
        try:
            response = requests.get(PIR_URL, timeout=1)
            response.raise_for_status()
            data = response.json()
            latest_pir_value = data.get("detection", False)
        except Exception as e:
            print(f"⚠️ PIR取得エラー: {e}")
            latest_pir_value = False
        time.sleep(1)

# --- MQTT設定 ---
MQTT_BROKER = "150.65.179.132"
MQTT_PORT = 7883
CID = "53965d6805152d95"
DEVICE_IDS = ["multi-sensors1", "multi-sensors2", "multi-sensors3","multi-sensors4"]
SENSORS = ["co2", "temperature", "humidity", "lux"]

# --- トピック辞書作成 ---
TOPICS = {}
for dev_id in DEVICE_IDS:
    suffix = dev_id.split("-")[-1]
    for sensor in SENSORS:
        topic = f"/server/{CID}/{dev_id}/properties/{sensor}"
        TOPICS[topic] = (sensor, f"sensors_{suffix}")

# --- CSVファイル設定 ---
CSV_FILE = "multi_sensors_data.csv"

# --- CSVカラム定義（並び順：timestamp, PIR, 各センサー）---
FIELDNAMES = ["timestamp", "PIR"]
for dev_id in DEVICE_IDS:
    suffix = dev_id.split("-")[-1]
    FIELDNAMES.extend([f"{sensor}(sensors_{suffix})" for sensor in SENSORS])

# --- カラム名の書き込み（空ファイル or ヘッダーなしの場合に書く） ---
def ensure_csv_has_header():
    if not os.path.exists(CSV_FILE) or os.path.getsize(CSV_FILE) == 0:
        with open(CSV_FILE, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()
    else:
        # すでにヘッダーが書かれているか確認
        with open(CSV_FILE, "r", newline="") as f:
            first_line = f.readline()
            if "timestamp" not in first_line or "PIR" not in first_line:
                with open(CSV_FILE, "w", newline="") as f_out:
                    writer = csv.DictWriter(f_out, fieldnames=FIELDNAMES)
                    writer.writeheader()

# --- データバッファ初期化 ---
data_buffer = {
    f"sensors_{dev_id.split('-')[-1]}": {sensor: None for sensor in SENSORS}
    for dev_id in DEVICE_IDS
}

# --- MQTT接続時処理 ---
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("✅ Connected to MQTT Broker")
        for topic in TOPICS:
            client.subscribe(topic)
            print(f"📡 Subscribed to: {topic}")
    else:
        print(f"❌ MQTT接続失敗: {rc}")

# --- メッセージ受信時処理 ---
def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode()
        json_data = json.loads(payload)
        topic = msg.topic

        if topic in TOPICS:
            sensor, suffix = TOPICS[topic]
            value = json_data.get(sensor)
            if value is not None:
                data_buffer[suffix][sensor] = value
                print(f"[{suffix}] {sensor}: {value}")

            # センサーデータが揃ったら保存
            if all(data_buffer[suffix].values()):
                ensure_csv_has_header()  # ★ 必ずCSVのヘッダーがあるようにする

                row = {
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "PIR": latest_pir_value
                }
                for s in SENSORS:
                    row[f"{s}({suffix})"] = data_buffer[suffix][s]

                with open(CSV_FILE, "a", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
                    writer.writerow(row)

                print(f"💾 CSV保存: {row}")
                data_buffer[suffix] = {s: None for s in SENSORS}
    except Exception as e:
        print(f"⚠️ 処理エラー: {e}")

# --- メイン処理 ---
if __name__ == "__main__":
    ensure_csv_has_header()  # 起動時にも一応ヘッダー確認

    # PIRセンサーの取得を別スレッドで開始
    pir_thread = threading.Thread(target=update_pir_loop, daemon=True)
    pir_thread.start()

    # MQTTクライアント起動
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)

    print("📡 統合記録開始 (Ctrl+Cで終了)")
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("🛑 終了します。")
