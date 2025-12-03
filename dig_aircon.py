import paho.mqtt.client as mqtt
import json
from datetime import datetime

# --- 設定 ---
MQTT_BROKER = "150.65.179.132"
MQTT_PORT = 7883

# ★ 監視ターゲット: リビングのエアコン
TARGET_ID = "C0A8033D-013501"

def on_connect(client, userdata, flags, reason_code, properties):
    print(f"\n[診断開始] エアコン ({TARGET_ID}) を監視中...")
    print("★ ヒント: エアコンのリモコンで「ON/OFF」や「温度変更」をしてみてください。")
    print("---------------------------------------------------")
    client.subscribe("/server/#")

def on_message(client, userdata, msg):
    try:
        topic = msg.topic
        if TARGET_ID in topic:
            payload = msg.payload.decode('utf-8')
            time_str = datetime.now().strftime('%H:%M:%S')
            print(f"✅ [{time_str}] データ受信！")
            print(f"   Topic: {topic}")
            print(f"   Data : {payload}")
            print("---------------------------------------------------")
    except Exception as e:
        pass

if __name__ == "__main__":
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_forever()
    except KeyboardInterrupt:
        print("終了")
