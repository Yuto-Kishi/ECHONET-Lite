import json
import csv
import os
from datetime import datetime
import paho.mqtt.client as mqtt

# --- MQTT設定 ---
MQTT_BROKER = "150.65.179.132"
MQTT_PORT = 7883
CID = "53965d6805152d95"

# --- 複数デバイス対応 ---
DEVICE_IDS = ["multi-sensors1", "multi-sensors2", "multi-sensors3","multi-sensors4"]  # 必要に応じて追加

# --- センサ名 ---
SENSORS = ["co2", "temperature", "humidity", "lux"]

# --- トピック辞書（topic → (sensor, suffix)）---
TOPICS = {}
for dev_id in DEVICE_IDS:
    suffix = dev_id.split("-")[-1]  # 例: "1"
    for sensor in SENSORS:
        topic = f"/server/{CID}/{dev_id}/properties/{sensor}"
        TOPICS[topic] = (sensor, f"sensors_{suffix}")

# --- CSV設定 ---
CSV_FILE = "multi_sensors_data.csv"

# カラム名（timestamp + 各デバイスごとのセンサ名）
FIELDNAMES = ["timestamp"]
for dev_id in DEVICE_IDS:
    suffix = dev_id.split("multi-")[-1]
    FIELDNAMES.extend([f"{sensor}(sensors_{suffix})" for sensor in SENSORS])

# 初回だけヘッダーを書く
if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()

# --- バッファ：デバイスごとに値保持 ---
data_buffer = {
    f"sensors_{dev_id.split('-')[-1]}": {sensor: None for sensor in SENSORS}
    for dev_id in DEVICE_IDS
}

# --- 接続時処理 ---
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("✅ Connected to MQTT Broker")
        for topic in TOPICS:
            client.subscribe(topic)
            print(f"📡 Subscribed to: {topic}")
    else:
        print(f"❌ Failed to connect: {rc}")

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

            # 全て揃ったらCSVに保存
            if all(data_buffer[suffix].values()):
                row = {"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                for s in SENSORS:
                    row[f"{s}({suffix})"] = data_buffer[suffix][s]
                with open(CSV_FILE, "a", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
                    writer.writerow(row)
                print(f"💾 Saved row: {row}")
                # バッファクリア
                data_buffer[suffix] = {s: None for s in SENSORS}

    except Exception as e:
        print(f"⚠️ Error: {e}")

# --- MQTTクライアント開始 ---
client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message
client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)

print("📡 Listening for MQTT messages... (Ctrl+C to stop)")
try:
    client.loop_forever()
except KeyboardInterrupt:
    print("🛑 Stopped.")
