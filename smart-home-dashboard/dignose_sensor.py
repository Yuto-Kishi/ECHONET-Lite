import paho.mqtt.client as mqtt
import json
import sys
from datetime import datetime

# --- 設定 ---
MQTT_BROKER = "150.65.179.132"
MQTT_PORT = 7883

# ★★★ 診断したいデバイスID (画像でデータ待ちになっていたID) ★★★
TARGET_ID = "C0A8033B-013501"


def on_connect(client, userdata, flags, reason_code, properties):
    print(f"\n[診断開始] {MQTT_BROKER} に接続しました。")
    print(f"ターゲットID: {TARGET_ID} の通信を待機しています...")
    print("---------------------------------------------------")
    # 全てのデータを吸い上げて、Python側でフィルタリングします
    client.subscribe("/server/#")


def on_message(client, userdata, msg):
    try:
        topic = msg.topic
        payload = msg.payload.decode("utf-8")

        # トピックの中にターゲットIDが含まれているかチェック
        if TARGET_ID in topic:
            time_str = datetime.now().strftime("%H:%M:%S")
            print(f"✅ [{time_str}] データ受信！")
            print(f"   Topic: {topic}")
            print(f"   Data : {payload}")
            print("---------------------------------------------------")

    except Exception as e:
        print(f"[エラー] {e}")


if __name__ == "__main__":
    # クライアント作成
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_forever()
    except KeyboardInterrupt:
        print("\n診断を終了します")
        client.disconnect()
    except Exception as e:
        print(f"\n接続エラー: {e}")
