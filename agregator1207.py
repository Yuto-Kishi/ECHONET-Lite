import paho.mqtt.client as mqtt
import json
import os
import csv
import time
import threading
from datetime import datetime

# ========= 設定 =========
MQTT_BROKER = "150.65.179.132"
MQTT_PORT = 7883
MQTT_TOPIC = "/server/#"

CSV_FILE = "smart_home_snapshot.csv"
FLUSH_INTERVAL_SEC = 10


# ========= デバイス一覧 =========
PIR_DEVICES = [
    # 1F
    "PIR1",
    "PIR2",
    "PIR3",
    "PIR4",
    "PIR18",
    "PIR13",
    "PIR11",
    "PIR5",
    "PIR21",
    "PIR17",
    # 2F
    "PIR6",
    "PIR8",
    "PIR9",
    "PIR10",
    "PIR15",
    "PIR19",
    "PIR20",
    "PIR22",
    "PIR24",
]

M5_DEVICES = [
    "M5Stack1",
    "M5Stack2",
    "M5Stack3",
    "M5Stack4",
    "M5Stack5",
    "M5Stack6",
    "M5Stack8",
    "M5Stack10",
]

AIR_PURIFIERS = [
    "C0A8033B-013501",  # 1F リビング
    "C0A8033E-013501",  # 1F 浴室洗面台
    "C0A80341-013501",  # 1F 和室
    "C0A8033D-013501",  # 2F 予備室
    "C0A8033C-013501",  # 2F ホール
    "C0A80342-013501",  # 2F 洋室2
    "C0A80343-013501",  # 2F 主寝室
    "C0A80344-013501",  # 2F 洋室1
]

AIRCONS = [
    "C0A80367-013001",  # リビング
    "C0A80368-013001",  # 和室
]


# ========= カラム設計 =========


def build_columns():
    cols = ["timestamp"]

    # PIR
    for pir in PIR_DEVICES:
        cols.append(f"{pir}_motion")

    # M5Stack
    m5_metrics = ["co2", "temp", "hum", "pm2_5", "voc"]
    for m5 in M5_DEVICES:
        for m in m5_metrics:
            cols.append(f"{m5}_{m}")

    # 空気清浄機 (★ 項目を追加しました)
    air_metrics = [
        "opStatus",  # 電源
        "temp",  # 温度
        "hum",  # 湿度
        "pm25",  # PM2.5
        "gas",  # ガス
        "illuminance",  # 照度
        "dust",  # ホコリ
        "power",  # 消費電力
        "flow",  # 風量
        "odor",  # ニオイレベル
        "dirt",  # 汚れレベル
    ]
    for ap in AIR_PURIFIERS:
        for m in air_metrics:
            cols.append(f"{ap}_{m}")

    # エアコン
    ac_metrics = [
        "opStatus",
        "mode",
        "setTemp",
        "roomTemp",
        "hum",
        "outsideTemp",
        "blowTemp",
        "power",
        "totalPower",
        "flow",
        "human",
        "sunshine",
        "co2",
    ]
    for ac in AIRCONS:
        for m in ac_metrics:
            cols.append(f"{ac}_{m}")

    return cols


COLUMNS = build_columns()
state = {col: None for col in COLUMNS if col != "timestamp"}
state_lock = threading.Lock()


# ========= CSV ヘッダー作成 =========
def init_csv():
    # カラムが変わったので、既存ファイルがある場合は別名にするか削除推奨
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(COLUMNS)
        print(f"[CSV] 新規作成: {CSV_FILE}")
    else:
        print(f"[CSV] 既存ファイルに追記します: {CSV_FILE}")


# ========= 定期フラッシュ =========
def flush_state_periodically():
    while True:
        time.sleep(FLUSH_INTERVAL_SEC)
        with state_lock:
            row = [datetime.now().isoformat()]
            for col in COLUMNS[1:]:
                row.append(state.get(col))

        with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(row)
        print(f"[CSV] snapshot written at {row[0]}")


# ========= MQTT メッセージ処理 =========


def update_pir(device_id, property_name, payload):
    if property_name in ("motion", "motion_raw"):
        val = payload.get(property_name)
        col = f"{device_id}_motion"
        with state_lock:
            state[col] = bool(val) if val is not None else None


def update_m5(device_id, property_name, payload):
    items = payload.items()
    with state_lock:
        for key, val in items:
            k = key.lower()
            if "co2" in k:
                state[f"{device_id}_co2"] = val
            if ("temp" in k) and ("scd40" in k or "sen55" in k):
                state[f"{device_id}_temp"] = val
            if "hum" in k:
                state[f"{device_id}_hum"] = val
            if "pm2_5" in k or "pm2.5" in k:
                state[f"{device_id}_pm2_5"] = val
            if "voc" in k:
                state[f"{device_id}_voc"] = val


def update_air_purifier(device_id, property_name, payload):
    # payloadは customF1 (dict) または 個別のプロパティ (value)
    # customF1の場合: {"temperature": 18, ...}
    # 個別の場合: {"operationStatus": true} など

    # データを統合して処理しやすくする
    data_map = {}
    if isinstance(payload, dict):
        data_map = payload
    else:
        # 単一の値が来た場合 (property_name がキーになる)
        data_map = {property_name: payload}

    with state_lock:
        for key, val in data_map.items():
            # customF1 の中身
            if key == "temperature":
                state[f"{device_id}_temp"] = val
            elif key == "humidity":
                state[f"{device_id}_hum"] = val
            elif key == "pm25":
                state[f"{device_id}_pm25"] = val
            elif key == "gasContaminationValue":
                state[f"{device_id}_gas"] = val
            elif key == "illuminanceValue":
                state[f"{device_id}_illuminance"] = val
            elif key == "dustValue":
                state[f"{device_id}_dust"] = val

            # 通常プロパティ
            elif key == "operationStatus":
                state[f"{device_id}_opStatus"] = bool(val)
            elif key == "instantaneousElectricPowerConsumption":
                state[f"{device_id}_power"] = val
            elif key == "airFlowLevel":
                state[f"{device_id}_flow"] = val
            elif key == "odorStainEvaluationLevel":
                state[f"{device_id}_odor"] = val
            elif key == "overallDirtinessLevel":
                state[f"{device_id}_dirt"] = val


def update_aircon(device_id, property_name, payload):
    with state_lock:
        for key, val in payload.items():
            if key == "outsideTemperature":
                state[f"{device_id}_outsideTemp"] = val
            elif key == "roomTemperature":
                state[f"{device_id}_roomTemp"] = val
            elif key in ("targetTemperature", "setTemperature"):
                state[f"{device_id}_setTemp"] = val
            elif key == "humanDetected":
                state[f"{device_id}_human"] = bool(val)
            elif key == "sunshineSensorData":
                state[f"{device_id}_sunshine"] = val
            elif key == "blowingOutAirTemperature":
                state[f"{device_id}_blowTemp"] = val
            elif key == "co2Concentration":
                state[f"{device_id}_co2"] = val
            elif key == "operationStatus":
                state[f"{device_id}_opStatus"] = bool(val)
            elif key == "instantaneousElectricPowerConsumption":
                state[f"{device_id}_power"] = val
            elif key == "consumedCumulativeElectricEnergy":
                state[f"{device_id}_totalPower"] = val
            elif key == "airFlowLevel":
                state[f"{device_id}_flow"] = val
            elif key == "humidity":
                state[f"{device_id}_hum"] = val


# ========= MQTT コールバック =========


def on_connect(client, userdata, flags, rc):
    print("[MQTT] Connected with result code", rc)
    client.subscribe(MQTT_TOPIC)
    print(f"[MQTT] Subscribed: {MQTT_TOPIC}")


def on_message(client, userdata, msg):
    try:
        topic = msg.topic
        payload_str = msg.payload.decode("utf-8")
        payload = json.loads(payload_str)
    except Exception:
        return

    parts = topic.split("/")
    if len(parts) < 6 or parts[1] != "server":
        return

    device_id = parts[3]
    property_name = parts[5]

    if device_id in PIR_DEVICES:
        update_pir(device_id, property_name, payload)
    elif device_id in M5_DEVICES:
        update_m5(device_id, property_name, payload)
    elif device_id in AIR_PURIFIERS:
        update_air_purifier(device_id, property_name, payload)
    elif device_id in AIRCONS:
        update_aircon(device_id, property_name, payload)


# ========= メイン =========


def main():
    init_csv()
    t = threading.Thread(target=flush_state_periodically, daemon=True)
    t.start()

    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    print("[MAIN] logging to", CSV_FILE)

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\n[END] 終了します")


if __name__ == "__main__":
    main()
