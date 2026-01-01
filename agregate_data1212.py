import paho.mqtt.client as mqtt
import json
import os
import csv
import time
import threading
from datetime import datetime
from flask import Flask, request, render_template_string
import logging

# Flaskのログを抑制
log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)

# ========= 設定 =========
MQTT_BROKER = "150.65.179.132"
MQTT_PORT = 7883
MQTT_TOPIC = "/server/#"

CSV_FILE = "./smart-home-dashboard/smart_home_0101.csv"
FLUSH_INTERVAL_SEC = 10
WEB_PORT = 5001

# ========= 部屋とラベルの定義 =========
ROOM_MAPPING = {
    "Living": "リビング",
    "Kitchen": "キッチン",
    "Entrance": "玄関",
    "Toilet1F": "1Fトイレ",
    "Washroom": "洗面所",
    "Japanese": "和室",
    "Master": "主寝室",
    "Toilet2F": "2Fトイレ",
    "West1": "洋室1",
    "West2": "洋室2",
    "Spare": "予備室",
    "Hall": "2Fホール",
}

# ========= デバイス一覧 =========
PIR_DEVICES = [
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
    "C0A8033B-013501",
    "C0A8033E-013501",
    "C0A80341-013501",
    "C0A8033D-013501",
    "C0A8033C-013501",
    "C0A80342-013501",
    "C0A80343-013501",
    "C0A80344-013501",
]
AIRCONS = ["C0A80367-013001", "C0A80368-013001"]

# ========= Flask アプリケーション =========
app = Flask(__name__)

# UIテンプレート (ボタンデザインなどはそのまま)
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>リモコン記録</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; padding: 10px; background: #f2f2f7; color: #333; }
        .control-panel { background: white; padding: 10px; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.05); }
        .room-row { display: flex; flex-direction: column; padding: 12px 0; border-bottom: 1px solid #eee; }
        .room-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
        .room-name { font-weight: bold; font-size: 1.1rem; color: #1c1c1e; }
        .stepper { display: flex; align-items: center; background: #f2f2f7; border-radius: 8px; padding: 2px; }
        .btn-step { 
            width: 44px; height: 44px; border: none; background: white; border-radius: 6px; 
            font-size: 24px; color: #007aff; font-weight: bold; cursor: pointer;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1); touch-action: manipulation;
        }
        .btn-step:active { background: #e5e5ea; }
        .count-display { 
            width: 40px; text-align: center; font-size: 18px; font-weight: bold; border: none; background: transparent; 
        }
        .action-input { width: 100%; box-sizing: border-box; padding: 10px; font-size: 16px; border: 1px solid #ddd; border-radius: 8px; margin-top: 5px; -webkit-appearance: none; }
        .total-row { background: #e8f4ff; padding: 15px; border-radius: 8px; margin-bottom: 15px; display: flex; justify-content: space-between; align-items: center; font-weight: bold; }
        .submit-area { position: sticky; bottom: 10px; margin-top: 20px; }
        .btn-update { 
            width: 100%; padding: 16px; background: #007aff; color: white; border: none; border-radius: 12px; 
            font-size: 18px; font-weight: bold; cursor: pointer; box-shadow: 0 4px 12px rgba(0,122,255,0.3); 
        }
        .btn-update:active { background: #0056b3; transform: scale(0.98); }
    </style>
    <script>
        function updateCount(key, delta) {
            var input = document.getElementById(key + '_Count');
            var val = parseInt(input.value) || 0;
            val += delta;
            if (val < 0) val = 0;
            input.value = val;
        }
    </script>
</head>
<body>
    <form method="POST" class="control-panel">
        <div class="total-row">
            <span>🏠 家全体の人数</span>
            <div class="stepper">
                <button type="button" class="btn-step" onclick="updateCount('Total_People', -1)">－</button>
                <input type="number" id="Total_People_Count" name="Total_People" value="{{ state.get('Label_Total_People', 0) }}" class="count-display" readonly>
                <button type="button" class="btn-step" onclick="updateCount('Total_People', 1)">＋</button>
            </div>
        </div>
        
        {% for key, name in rooms.items() %}
        <div class="room-row">
            <div class="room-header">
                <span class="room-name">{{ name }}</span>
                <div class="stepper">
                    <button type="button" class="btn-step" onclick="updateCount('{{ key }}', -1)">－</button>
                    <input type="number" id="{{ key }}_Count" name="{{ key }}_Count" value="{{ state.get('Label_' + key + '_Count', 0) }}" class="count-display" readonly>
                    <button type="button" class="btn-step" onclick="updateCount('{{ key }}', 1)">＋</button>
                </div>
            </div>
            <input type="text" name="{{ key }}_Action" value="{{ state.get('Label_' + key + '_Action', '') }}" class="action-input" placeholder="行動..." list="action-list">
        </div>
        {% endfor %}
        
        <datalist id="action-list">
            <option value="就寝"></option>
            <option value="TV視聴"></option>
            <option value="食事"></option>
            <option value="調理"></option>
            <option value="仕事"></option>
            <option value="勉強"></option>
            <option value="スマホ"></option>
            <option value="家事"></option>
            <option value="入浴"></option>
            <option value="外出"></option>
        </datalist>

        <div class="submit-area">
            <button type="submit" class="btn-update">状況を更新 (Update)</button>
        </div>
    </form>
</body>
</html>
"""


# ========= カラム設計 =========
def build_columns():
    cols = ["timestamp"]
    cols.append("Label_Total_People")
    for key in ROOM_MAPPING.keys():
        cols.append(f"Label_{key}_Count")
        cols.append(f"Label_{key}_Action")

    for pir in PIR_DEVICES:
        cols.append(f"{pir}_motion")
    for m5 in M5_DEVICES:
        for m in ["co2", "temp", "hum", "pm2_5", "voc"]:
            cols.append(f"{m5}_{m}")

    air_metrics = [
        "opStatus",
        "temp",
        "hum",
        "pm25",
        "gas",
        "illuminance",
        "dust",
        "power",
        "flow",
        "odor",
        "dirt",
    ]
    for ap in AIR_PURIFIERS:
        for m in air_metrics:
            cols.append(f"{ap}_{m}")

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
# 初期値を必ず数値の0にする
state = {col: None for col in COLUMNS if col != "timestamp"}
state["Label_Total_People"] = 0
for key in ROOM_MAPPING.keys():
    state[f"Label_{key}_Count"] = 0
    state[f"Label_{key}_Action"] = ""

state_lock = threading.Lock()


# ========= サーバーの通信処理 (★ここを修正しました) =========
@app.route("/", methods=["GET", "POST"])
def index():
    global state
    if request.method == "POST":
        with state_lock:
            # ★修正点: データを受け取る際に、強制的に数値(int)に変換する

            # 家全体の人数
            raw_total = request.form.get("Total_People", "0")
            state["Label_Total_People"] = int(raw_total) if raw_total.isdigit() else 0

            # 各部屋の人数と行動
            for key in ROOM_MAPPING.keys():
                # 人数: 空文字なら0、それ以外は数値化
                raw_count = request.form.get(f"{key}_Count", "0")
                state[f"Label_{key}_Count"] = (
                    int(raw_count) if raw_count.isdigit() else 0
                )

                # 行動: そのまま受け取る
                state[f"Label_{key}_Action"] = request.form.get(f"{key}_Action", "")

        print(f"[UI] ラベル更新: Total={state['Label_Total_People']}")
    return render_template_string(HTML_TEMPLATE, state=state, rooms=ROOM_MAPPING)


def run_web_server():
    app.run(host="0.0.0.0", port=WEB_PORT, debug=False, use_reloader=False)


# ========= CSV/MQTT処理 (変更なし) =========
def init_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(COLUMNS)
        print(f"[CSV] 新規作成: {CSV_FILE}")
    else:
        print(f"[CSV] 既存ファイルに追記: {CSV_FILE}")


def flush_state_periodically():
    while True:
        time.sleep(FLUSH_INTERVAL_SEC)
        with state_lock:
            row = [datetime.now().isoformat()]
            for col in COLUMNS[1:]:
                # 値がない(None)場合は空文字にするが、stateには0が入っているはず
                val = state.get(col)
                row.append(val if val is not None else "")

        with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(row)
        print(f"[CSV] 記録完了 (Total: {state.get('Label_Total_People')})")


def update_pir(d, p, val):
    v = val.get(p)
    if v is not None:
        with state_lock:
            state[f"{d}_motion"] = bool(v)


def update_m5(d, p, val):
    with state_lock:
        for k, v in val.items():
            k = k.lower()
            if "co2" in k:
                state[f"{d}_co2"] = v
            if ("temp" in k) and ("scd40" in k or "sen55" in k):
                state[f"{d}_temp"] = v
            if "hum" in k:
                state[f"{d}_hum"] = v
            if "pm2_5" in k or "pm2.5" in k:
                state[f"{d}_pm2_5"] = v
            if "voc" in k:
                state[f"{d}_voc"] = v


def update_air_purifier(d, p, val):
    data = val if isinstance(val, dict) else {p: val}
    with state_lock:
        for k, v in data.items():
            if k == "temperature":
                state[f"{d}_temp"] = v
            elif k == "humidity":
                state[f"{d}_hum"] = v
            elif k == "pm25":
                state[f"{d}_pm25"] = v
            elif k == "gasContaminationValue":
                state[f"{d}_gas"] = v
            elif k == "illuminanceValue":
                state[f"{d}_illuminance"] = v
            elif k == "dustValue":
                state[f"{d}_dust"] = v
            elif k == "operationStatus":
                state[f"{d}_opStatus"] = bool(v)
            elif k == "instantaneousElectricPowerConsumption":
                state[f"{d}_power"] = v
            elif k == "airFlowLevel":
                state[f"{d}_flow"] = v
            elif k == "odorStainEvaluationLevel":
                state[f"{d}_odor"] = v
            elif k == "overallDirtinessLevel":
                state[f"{d}_dirt"] = v


def update_aircon(d, p, val):
    with state_lock:
        for k, v in val.items():
            if k == "outsideTemperature":
                state[f"{d}_outsideTemp"] = v
            elif k == "roomTemperature":
                state[f"{d}_roomTemp"] = v
            elif k in ("targetTemperature", "setTemperature"):
                state[f"{d}_setTemp"] = v
            elif k == "humanDetected":
                state[f"{d}_human"] = bool(v)
            elif k == "sunshineSensorData":
                state[f"{d}_sunshine"] = v
            elif k == "blowingOutAirTemperature":
                state[f"{d}_blowTemp"] = v
            elif k == "co2Concentration":
                state[f"{d}_co2"] = v
            elif k == "operationStatus":
                state[f"{d}_opStatus"] = bool(v)
            elif k == "instantaneousElectricPowerConsumption":
                state[f"{d}_power"] = v
            elif k == "consumedCumulativeElectricEnergy":
                state[f"{d}_totalPower"] = v
            elif k == "airFlowLevel":
                state[f"{d}_flow"] = v
            elif k == "humidity":
                state[f"{d}_hum"] = v


def on_connect(c, u, f, rc):
    print("[MQTT] 接続成功: コード", rc)
    c.subscribe(MQTT_TOPIC)


def on_message(c, u, msg):
    try:
        topic = msg.topic
        payload = json.loads(msg.payload.decode("utf-8"))
        parts = topic.split("/")
        if len(parts) >= 6 and parts[1] == "server":
            d, p = parts[3], parts[5]
            if d in PIR_DEVICES:
                update_pir(d, p, payload)
            elif d in M5_DEVICES:
                update_m5(d, p, payload)
            elif d in AIR_PURIFIERS:
                update_air_purifier(d, p, payload)
            elif d in AIRCONS:
                update_aircon(d, p, payload)
    except:
        pass


def main():
    init_csv()
    threading.Thread(target=flush_state_periodically, daemon=True).start()
    threading.Thread(target=run_web_server, daemon=True).start()
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    print("-" * 50)
    print(f"[INFO] スマホからここにアクセスしてください: http://<PCのIPアドレス>:5001")
    print("-" * 50)
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("終了")


if __name__ == "__main__":
    main()
