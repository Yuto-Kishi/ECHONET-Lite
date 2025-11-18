import paho.mqtt.client as mqtt
from datetime import datetime
import sys

# --- 設定 ---
MQTT_BROKER = "150.65.179.132"
MQTT_PORT = 7883
CID = "53965d6805152d95"

# ★★★ ここを確認！ ★★★
# マイコン側で設定したデバイスIDと「完全に同じ」にしてください。
# "PIR18" なのか "pir18" なのか注意してください。
DEVICE_TO_CHECK = "PIR5"

# トピックを作成 (/server/CID/PIR18/#)
TOPIC_TO_SUBSCRIBE = f"/server/{CID}/{DEVICE_TO_CHECK}/#"

# --- コールバック関数 ---


# 接続できた時
def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print("\n[MQTT] 接続成功！")
        print(f"[MQTT] ターゲット: {DEVICE_TO_CHECK}")
        print(f"[MQTT] 監視トピック: {TOPIC_TO_SUBSCRIBE}")
        print("-------------------------------------------")
        print("データ受信待機中... (Ctrl+C で終了)")

        # トピックを購読
        client.subscribe(TOPIC_TO_SUBSCRIBE)
    else:
        print(f"[MQTT] 接続失敗 (コード: {reason_code})")


# メッセージが届いた時
def on_message(client, userdata, msg):
    try:
        time_str = datetime.now().strftime("%H:%M:%S")
        payload_str = msg.payload.decode("utf-8")

        print(f"\n[受信] {time_str}")
        print(f"  トピック: {msg.topic}")
        print(f"  データ: {payload_str}")
        print("-------------------------------------------")
    except Exception as e:
        print(f"[エラー] {e}")


# --- メイン処理 ---
if __name__ == "__main__":
    # クライアント作成
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    client.on_connect = on_connect
    client.on_message = on_message

    print(f"[MQTT] ブローカー ({MQTT_BROKER}) に接続中...")

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_forever()
    except KeyboardInterrupt:
        print("\n[MQTT] 終了します")
        client.disconnect()
    except Exception as e:
        print(f"[エラー] 接続できませんでした: {e}")
