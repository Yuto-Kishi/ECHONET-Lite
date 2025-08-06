import json
import time
import paho.mqtt.client as mqtt

# --- MQTT設定 ---
MQTT_BROKER = "150.65.179.132"
MQTT_PORT = 7883
CID = "53965d6805152d95"
DEV_ID = "multi-sensors2"

# --- 購読するトピック一覧 ---
TOPICS = [
    f"/server/{CID}/{DEV_ID}/properties/co2",
    f"/server/{CID}/{DEV_ID}/properties/temperature",
    f"/server/{CID}/{DEV_ID}/properties/humidity",
    f"/server/{CID}/{DEV_ID}/properties/lux"
]

# --- メッセージ受信時の処理 ---
def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode('utf-8')
        data = json.loads(payload)
        print(f"[{msg.topic}] {json.dumps(data, indent=2)}")
    except Exception as e:
        print(f"Error decoding message: {e}")

# --- 接続時の処理 ---
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("✅ Connected to MQTT Broker")
        for topic in TOPICS:
            client.subscribe(topic)
            print(f"📡 Subscribed to: {topic}")
    else:
        print(f"❌ Failed to connect, return code {rc}")

# --- MQTTクライアント設定 ---
client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message

client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)

# --- ループ開始 ---
try:
    print("🔍 Listening for MQTT messages...")
    client.loop_forever()
except KeyboardInterrupt:
    print("🛑 Disconnected")
    client.disconnect()