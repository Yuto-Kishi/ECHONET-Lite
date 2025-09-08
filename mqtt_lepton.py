# check_thermal_mqtt.py
import json
import time
import paho.mqtt.client as mqtt

MQTT_BROKER = "150.65.179.132"
MQTT_PORT   = 7883
CID         = "53965d6805152d95"
DEV_ID      = "thermal_1"  # Lepton側スクリプトの DEV_ID と一致させる

# 2つ購読して確実に拾う：占有フラグ単体 & その配下全部
TOPIC_OCC   = f"/server/{CID}/{DEV_ID}/properties/lepton_occupied"
TOPIC_ALL   = f"/server/{CID}/{DEV_ID}/properties/#"

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("✅ MQTT connected")
        client.subscribe([(TOPIC_OCC, 0), (TOPIC_ALL, 0)])
        print(f"📡 Subscribed to: {TOPIC_OCC} and {TOPIC_ALL}")
        print("…waiting for messages (Ctrl+C to quit)")
    else:
        print("❌ MQTT connect failed:", rc)

def on_message(client, userdata, msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    payload = msg.payload.decode(errors="ignore")
    print(f"[{ts}] MSG {msg.topic}  {payload}")
    try:
        data = json.loads(payload)
    except Exception:
        return

    # lepton_occupied が来たら抜き出して表示
    if msg.topic == TOPIC_OCC or "lepton_occupied" in data:
        val = data.get("lepton_occupied")
        print(f"   ↳ lepton_occupied = {val}")

def main():
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\nbye")

if __name__ == "__main__":
    main()
