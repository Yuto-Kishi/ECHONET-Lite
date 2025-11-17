import paho.mqtt.client as mqtt
from datetime import datetime
import sys

# --- 設定 ---
MQTT_BROKER = "150.65.179.132"
MQTT_PORT = 7883
CID = "53965d6805152d95"

# ★★★ 確認したいPicoのDEV_ID ★★★
DEVICE_TO_CHECK = "PIR7"

# ★★★ ここが正しいトピックの指定方法です ★★★
# (# は、PIR7以下の全トピックを意味します)
TOPIC_TO_SUBSCRIBE = f"/server/{CID}/{DEVICE_TO_CHECK}/#"
# ---


# 接続に成功した時のコールバック関数
def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print("[MQTT] 接続に成功しました。")
        print(f"[MQTT] 以下のトピックの監視を開始します:")
        print(f"  {TOPIC_TO_SUBSCRIBE}")
        print("-------------------------------------------")
        print("Picoからのデータ受信を待っています...")
        # 接続に成功したらトピックを購読
        client.subscribe(TOPIC_TO_SUBSCRIBE)
    else:
        print(f"[MQTT] 接続に失敗しました (コード: {reason_code})")


# メッセージを受信した時のコールバック関数
def on_message(client, userdata, msg):
    try:
        time_str = datetime.now().strftime("%H:%M:%S")
        payload_str = msg.payload.decode("utf-8")

        print(f"\n[受信] {time_str}")
        print(f"  トピック: {msg.topic}")
        print(f"  データ: {payload_str}")
        print("-------------------------------------------")
    except Exception as e:
        print(f"[エラー] メッセージの処理に失敗: {e}")


# --- メイン処理 ---
if __name__ == "__main__":
    # ★ 警告(Warning)を消すための書き方
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    client.on_connect = on_connect
    client.on_message = on_message

    print(f"[MQTT] ブローカーに接続中... {MQTT_BROKER}:{MQTT_PORT}")
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
    except Exception as e:
        print(f"[MQTT] 接続エラー: {e}")
        sys.exit()

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\n[MQTT] 監視を終了します。")
        client.disconnect()
