import paho.mqtt.client as mqtt
import json
import sys
from datetime import datetime
from elasticsearch import Elasticsearch
import warnings
from elasticsearch.exceptions import ElasticsearchWarning

# セキュリティ警告を無視 (ローカル環境用)
warnings.simplefilter("ignore", ElasticsearchWarning)

# --- 設定 ---
MQTT_BROKER = "150.65.179.132"
MQTT_PORT = 7883
ES_HOST = "http://localhost:9200"
INDEX_NAME = "smarthome_logs"

# Elasticsearch接続
es = Elasticsearch(hosts=[ES_HOST])


# --- 接続時 ---
def on_connect(client, userdata, flags, reason_code, properties):
    print(f"\n[システム] MQTT接続成功。全デバイスのデータ保存を開始します...")
    print(f"-------------------------------------------------------")
    # すべてのトピックを購読
    client.subscribe("/server/#")


# --- メッセージ受信時 ---
def on_message(client, userdata, msg):
    try:
        # トピック解析: /server/CID/DeviceID/properties/PropName
        topic_parts = msg.topic.split("/")
        if len(topic_parts) < 6:
            return

        device_id = topic_parts[3]
        prop_name = topic_parts[5]

        payload_str = msg.payload.decode("utf-8")

        # --- 保存するデータの作成 ---
        doc = {
            "@timestamp": datetime.now().isoformat(),
            "device_id": device_id,
            "property_name": prop_name,
            "topic": msg.topic,
        }

        # --- 値の解析と展開 ---
        try:
            # JSONとして読み込みを試みる
            value = json.loads(payload_str)

            if isinstance(value, dict):
                # ★★★ 重要: 辞書型なら中身を展開してトップレベルに保存 ★★★
                # これにより Kibana で "temperature" や "pm25" を直接グラフ化できます
                doc.update(value)

                # 念のため元のJSONも文字列として残しておく（デバッグ用）
                doc["raw_json"] = payload_str
            else:
                # 単純な値なら "value" フィールドに入れる
                doc["value"] = value

        except json.JSONDecodeError:
            # JSONでない場合（単純な数値や文字列）
            if payload_str.replace(".", "", 1).isdigit():
                doc["value"] = float(payload_str)
            elif payload_str.lower() == "true":
                doc["value"] = True
            elif payload_str.lower() == "false":
                doc["value"] = False
            else:
                doc["value"] = payload_str

        # --- データベース(Elasticsearch)に保存 ---
        # 注: ライブラリのバージョンに合わせて body 引数を使用
        res = es.index(index=INDEX_NAME, body=doc)

        # --- ターミナルへのログ表示 ---
        time_str = datetime.now().strftime("%H:%M:%S")

        # 家電 (エアコン0130, 空気清浄機0135)
        if "013001" in device_id:
            print(f"[{time_str}] 🟢 エアコン保存: {device_id} ({prop_name})")
        elif "013501" in device_id:
            print(f"[{time_str}] 🔵 空清保存: {device_id} ({prop_name})")
        # センサー
        elif "PIR" in device_id:
            print(f"[{time_str}] 🟡 PIR保存: {device_id}")
        elif "M5" in device_id:
            print(f"[{time_str}] 🟠 M5Stack保存: {device_id} ({prop_name})")
        else:
            print(f"[{time_str}] ⚪️ その他保存: {device_id}")

    except Exception as e:
        print(f"[エラー] {e}")


# --- メイン処理 ---
if __name__ == "__main__":
    # インデックス作成（なければ）
    try:
        if not es.indices.exists(index=INDEX_NAME):
            es.indices.create(index=INDEX_NAME)
            print(f"[システム] 新しいインデックス '{INDEX_NAME}' を作成しました。")
    except Exception:
        pass

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_forever()
    except KeyboardInterrupt:
        print("\n終了します")
