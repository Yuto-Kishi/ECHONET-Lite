import json

import paho.mqtt.client as mqtt

# --- 設定 (Publisherと合わせる) ---
MQTT_BROKER = "150.65.179.250"
MQTT_PORT = 1883

# --- 購読するトピック ---
# Publisherは /akehi/sensor/data/885 や /akehi/sensor/data/884 というトピックに送信します。
# '+' は「シングルレベルワイルドカード」で、この階層の任意の文字列に一致します。
# これにより、両方のデバイスからのデータを1つのSubscriberで受信できます。
SUBSCRIBE_TOPIC = "/akehi/sensor/data/+"


# MQTTブローカーに接続したときに呼び出されるコールバック関数
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"MQTTブローカー ({MQTT_BROKER}) に接続しました。")
        # 接続に成功したら、指定したトピックを購読(subscribe)する
        client.subscribe(SUBSCRIBE_TOPIC)
        print(f"トピック '{SUBSCRIBE_TOPIC}' の購読を開始しました。")
    else:
        print(f"接続に失敗しました。リターンコード: {rc}")
        print("ブローカーが起動しているか、ネットワーク設定を確認してください。")


# メッセージを受信したときに呼び出されるコールバック関数
def on_message(client, userdata, msg):
    """
    メッセージを受信した際に、そのトピックと内容を画面に表示する
    """
    try:
        # 受信したペイロード(msg.payload)はバイナリ形式なので、UTF-8でデコードして文字列に変換
        payload_str = msg.payload.decode("utf-8")
        # JSON文字列をPythonの辞書オブジェクトに変換
        data = json.loads(payload_str)
        
        print("=" * 40)
        print(f"受信時刻: {data.get('Date', '')} {data.get('Time', '')}")
        print(f"受信トピック: {msg.topic}")
        print("-" * 40)
        
        # 受信したデータをきれいに表示
        print("受信データ:")
        for key, value in data.items():
            print(f"  - {key:<20}: {value}")
        print("=" * 40 + "\n")
        
    except json.JSONDecodeError:
        print(f"エラー: トピック '{msg.topic}' から受信したデータが有効なJSON形式ではありません。")
        print(f"受信した生データ: {msg.payload}")
    except Exception as e:
        print(f"メッセージ処理中に予期せぬエラーが発生しました: {e}")


# メインの処理
def main():
    # MQTTクライアントのインスタンスを作成
    # client_idは指定しない場合、自動で生成されます
    client = mqtt.Client()

    # 各コールバック関数をクライアントに設定
    client.on_connect = on_connect
    client.on_message = on_message

    print(f"MQTTブローカー ({MQTT_BROKER}:{MQTT_PORT}) に接続を試みます...")
    
    try:
        # ブローカーに接続
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
    except Exception as e:
        print(f"MQTTブローカーへの接続に失敗しました: {e}")
        return

    # メッセージループを開始します。
    # この関数はプログラムをブロックし、バックグラウンドでブローカーとの通信を処理し続けます。
    # プログラムを終了するには Ctrl+C を押してください。
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\nプログラムを終了します。")
        client.disconnect()
        print("ブローカーから切断しました。")


if __name__ == "__main__":
    main()
