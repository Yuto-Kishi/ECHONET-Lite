import streamlit as st
import paho.mqtt.client as mqtt
import json
from collections import deque
import time

# MQTT設定
BROKER = "150.65.179.132"
PORT = 7883
TOPIC = "/server/53965d6805152d95/multi-sensors4/properties/#"

# リアルタイムデータ保存用バッファ
MAX_LEN = 100
data_buffers = {
    "co2": deque(maxlen=MAX_LEN),
    "temperature": deque(maxlen=MAX_LEN),
    "humidity": deque(maxlen=MAX_LEN),
    "lux": deque(maxlen=MAX_LEN),
    "pressure": deque(maxlen=MAX_LEN),
    "timestamp": deque(maxlen=MAX_LEN),
}

# MQTTメッセージ受信時の処理
def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        now = time.strftime("%H:%M:%S")
        for key in payload:
            if key in data_buffers:
                data_buffers[key].append(payload[key])
                data_buffers["timestamp"].append(now)
    except Exception as e:
        print("JSON decode error:", e)

# MQTTクライアント初期化
client = mqtt.Client()
client.on_message = on_message
client.connect(BROKER, PORT, 60)
client.subscribe(TOPIC)
client.loop_start()

# Streamlit UI
st.title("📊 Realtime Sensor Dashboard")

placeholder = st.empty()

while True:
    with placeholder.container():
        st.line_chart({
            "CO2": list(data_buffers["co2"]),
            "Temp": list(data_buffers["temperature"]),
            "Humid": list(data_buffers["humidity"]),
            "Lux": list(data_buffers["lux"]),
            "Press": list(data_buffers["pressure"]),
        })
    time.sleep(1)