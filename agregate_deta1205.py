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
MQTT_TOPIC = "/server/#"  # 全部拾う

CSV_FILE = "smart_home_snapshot.csv"
FLUSH_INTERVAL_SEC = 10  # 何秒ごとに1行書き込むか


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

    # --- PIR (人感) ---
    for pir in PIR_DEVICES:
        cols.append(f"{pir}_motion")

    # --- M5Stack (環境センサ) ---
    m5_metrics = ["co2", "temp", "hum", "pm2_5", "voc"]
    for m5 in M5_DEVICES:
        for m in m5_metrics:
            cols.append(f"{m5}_{m}")

    # --- 空気清浄機 ---
    # 温度, 湿度, PM2.5, ガス, 照度
    air_metrics = ["temp", "hum", "pm25", "gas", "illuminance"]
    for ap in AIR_PURIFIERS:
        for m in air_metrics:
            cols.append(f"{ap}_{m}")

    # --- エアコン (大幅拡張) ---
    ac_metrics = [
        "opStatus",  # 電源
        "mode",  # 運転モード (heating/cooling/auto)
        "setTemp",  # 設定温度
        "roomTemp",  # 室温
        "hum",  # 湿度
        "outsideTemp",  # 外気温
        "blowTemp",  # 吹出温度
        "power",  # 消費電力 (W)
        "totalPower",  # 積算電力量 (kWh)
        "flow",  # 風量
        "human",  # 人検知
        "sunshine",  # 日射
        "co2",  # CO2
    ]
    for ac in AIRCONS:
        for m in ac_metrics:
            cols.append(f"{ac}_{m}")

    return cols


COLUMNS = build_columns()

# 状態を保持する辞書（列名 -> 値）
state = {col: None for col in COLUMNS if col != "timestamp"}
state_lock = threading.Lock()


# ========= CSV ヘッダー作成 =========
def init_csv():
    # カラムが増えたので、既存ファイルがあると列がズレるため注意
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
            # 現在時刻
            row = [datetime.now().isoformat()]
            # 各カラムの最新値を取得
            for col in COLUMNS[1:]:
                row.append(state.get(col))

        # ファイル書き込み
        with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(row)
        print(f"[CSV] snapshot written at {row[0]}")


# ========= MQTT メッセージ処理 =========


def update_pir(device_id, property_name, payload):
    # motion / motion_raw
    if property_name in ("motion", "motion_raw"):
        val = payload.get(property_name)
        col = f"{device_id}_motion"
        with state_lock:
            state[col] = bool(val) if val is not None else None


def update_m5(device_id, property_name, payload):
    # payload は {propertyName: value}
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
    # customF1 に各種データ
    items = payload.items()
    with state_lock:
        for key, val in items:
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


def update_aircon(device_id, property_name, payload):
    # 頂いたJSONプロパティに基づきマッピング
    with state_lock:
        for key, val in payload.items():
            # 電源
            if key == "operationStatus":
                state[f"{device_id}_opStatus"] = bool(val)
            # 運転モード
            elif key == "operationMode":
                state[f"{device_id}_mode"] = val
            # 設定温度 (setTemperature or targetTemperature)
            elif key in ("setTemperature", "targetTemperature"):
                state[f"{device_id}_setTemp"] = val
            # 室温
            elif key == "roomTemperature":
                state[f"{device_id}_roomTemp"] = val
            # 湿度
            elif key == "humidity":
                state[f"{device_id}_hum"] = val
            # 外気温 (outsideTemperature or outdoorTemperature)
            elif key in ("outsideTemperature", "outdoorTemperature"):
                # "unmeasurable" などの文字列が来ることがあるのでそのまま保存
                state[f"{device_id}_outsideTemp"] = val
            # 吹出温度
            elif key == "blowingOutAirTemperature":
                state[f"{device_id}_blowTemp"] = val
            # 消費電力
            elif key == "instantaneousElectricPowerConsumption":
                state[f"{device_id}_power"] = val
            # 積算電力量
            elif key == "consumedCumulativeElectricEnergy":
                state[f"{device_id}_totalPower"] = val
            # 風量
            elif key == "airFlowLevel":
                state[f"{device_id}_flow"] = val
            # 人検知
            elif key == "humanDetected":
                state[f"{device_id}_human"] = bool(val)
            # 日射
            elif key == "sunshineSensorData":
                state[f"{device_id}_sunshine"] = val
            # CO2
            elif key == "co2Concentration":
                state[f"{device_id}_co2"] = val


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
    except Exception as e:
        return

    parts = topic.split("/")
    # /server/{CID}/{deviceId}/properties/{property}
    if len(parts) < 6 or parts[1] != "server":
        return

    device_id = parts[3]
    property_name = parts[5]

    # デバイスID判定
    if device_id in PIR_DEVICES:
        update_pir(device_id, property_name, payload)

    elif device_id in M5_DEVICES:
        update_m5(device_id, property_name, payload)

    elif device_id in AIR_PURIFIERS:
        # customF1 の中身を展開
        update_air_purifier(device_id, property_name, payload)

    elif device_id in AIRCONS:
        # customF6, customFA, その他のプロパティを展開
        update_aircon(device_id, property_name, payload)


# ========= メイン =========


def main():
    init_csv()

    # CSV 書き込みスレッド起動
    t = threading.Thread(target=flush_state_periodically, daemon=True)
    t.start()

    # MQTT クライアント
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
