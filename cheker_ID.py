import paho.mqtt.client as mqtt
import json
import sys
from datetime import datetime

# --- 設定 ---
MQTT_BROKER = "150.65.179.132"
MQTT_PORT = 7883

# 空気清浄機のEOJ (末尾の識別コード)
TARGET_EOJ = "013501"


def on_connect(client, userdata, flags, reason_code, properties):
    print(f"\n[MQTT] 接続成功。空気清浄機 ({TARGET_EOJ}) を探しています...")
    # 全てのサーバーメッセージを購読
    client.subscribe("/server/#")


def on_message(client, userdata, msg):
    try:
        topic = msg.topic
        # トピックに '013501' が含まれていれば空気清浄機とみなす
        if TARGET_EOJ in topic:
            payload = msg.payload.decode("utf-8")
            data = json.loads(payload)

            # トピックからデバイスID部分を抽出 ( /server/CID/【ここ】/properties/... )
            parts = topic.split("/")
            device_id = parts[3]
            prop = parts[5]

            time_str = datetime.now().strftime("%H:%M:%S")

            # 見やすく表示
            print(f"[{time_str}] 発見! ID: {device_id}")
            print(f"   Prop: {prop}")
            print(f"   Val : {data}")
            print("-" * 30)

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
