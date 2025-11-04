# app_live.py  —— set_page_config を最初に呼ぶ版
import time, json, threading
from pathlib import Path
import paho.mqtt.client as mqtt
import streamlit as st
from PIL import Image, ImageDraw

# 最初の Streamlit コマンドはこれ！
st.set_page_config(layout="wide")

# ====== MQTT / ENV ======
BROKER = "150.65.179.132"
PORT = 7883
CID = "53965d6805152d95"
PIRS = ["PIR1", "PIR2", "PIR3", "PIR4"]

# ====== UI / IMAGE ======
BG_PATH = "living_dining.png"
ACTIVE_WINDOW_SEC = 2.5

SECTIONS = {
    "PIR2": (0.00, 0.00, 0.33, 0.33),
    "PIR2&PIR1": (0.33, 0.00, 0.66, 0.33),
    "PIR1": (0.66, 0.00, 1.00, 0.33),
    "PIR2&PIR4": (0.00, 0.33, 0.33, 0.66),
    "PIR1&PIR3": (0.66, 0.33, 1.00, 0.66),
    "PIR4": (0.00, 0.66, 0.33, 1.00),
    "PIR4&PIR3": (0.33, 0.66, 0.66, 1.00),
    "PIR3": (0.66, 0.66, 1.00, 1.00),
}
COMBO_TO_SECTION = {
    frozenset({"PIR1"}): "PIR1",
    frozenset({"PIR2"}): "PIR2",
    frozenset({"PIR3"}): "PIR3",
    frozenset({"PIR4"}): "PIR4",
    frozenset({"PIR1", "PIR2"}): "PIR2&PIR1",
    frozenset({"PIR3", "PIR4"}): "PIR4&PIR3",
    frozenset({"PIR1", "PIR3"}): "PIR1&PIR3",
    frozenset({"PIR2", "PIR4"}): "PIR2&PIR4",
}


# ====== shared state (thread-safe) ======
@st.cache_resource
def get_shared():
    return {
        "lock": threading.Lock(),
        "connected": False,
        "rc": None,
        "last_on": {p: 0.0 for p in PIRS},
    }


shared = get_shared()


# ====== MQTT callbacks（UIスレッドを触らない） ======
def on_connect(c, u, flags, rc):
    with shared["lock"]:
        shared["connected"] = rc == 0
        shared["rc"] = rc
    if rc == 0:
        for dev in PIRS:
            c.subscribe(f"/server/{CID}/{dev}/properties/motion_raw", qos=0)


def on_disconnect(c, u, rc):
    with shared["lock"]:
        shared["connected"] = False
        shared["rc"] = rc


def on_message(c, u, msg):
    try:
        data = json.loads(msg.payload.decode("utf-8", errors="ignore"))
        val = bool(data.get("motion_raw", False))
    except Exception:
        s = msg.payload.decode("utf-8", errors="ignore").strip().lower()
        val = s in ("1", "true", "on")
    if not val:
        return
    parts = msg.topic.split("/")
    dev = parts[3] if len(parts) > 3 else None
    if dev in PIRS:
        import time as _t

        with shared["lock"]:
            shared["last_on"][dev] = _t.time()


@st.cache_resource
def start_mqtt():
    cli = mqtt.Client(client_id=f"streamlit-{int(time.time())}", protocol=mqtt.MQTTv311)
    cli.on_connect = on_connect
    cli.on_disconnect = on_disconnect
    cli.on_message = on_message
    cli.reconnect_delay_set(1, 10)
    cli.connect(BROKER, PORT, keepalive=30)
    cli.loop_start()
    return cli


start_mqtt()

# ====== UI ======
st.title("Living presence monitor (PIR × 4)")

if "last_on" not in st.session_state:
    st.session_state.last_on = {p: 0.0 for p in PIRS}
if "mqtt_ok" not in st.session_state:
    st.session_state.mqtt_ok = False
if "mqtt_rc" not in st.session_state:
    st.session_state.mqtt_rc = None

with shared["lock"]:
    st.session_state.last_on.update(shared["last_on"])
    st.session_state.mqtt_ok = shared["connected"]
    st.session_state.mqtt_rc = shared["rc"]

now = time.time()
active = {
    p for p, t in st.session_state.last_on.items() if (now - t) <= ACTIVE_WINDOW_SEC
}
sec_name = COMBO_TO_SECTION.get(frozenset(active))

from PIL import Image, ImageDraw
from pathlib import Path

if not Path(BG_PATH).exists():
    st.error(f"背景画像が見つかりません: {BG_PATH}")
else:
    bg = Image.open(BG_PATH).convert("RGBA")
    w, h = bg.size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")

    def rect_from_norm(box):
        x0, y0, x1, y1 = box
        return (int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h))

    if sec_name:
        box = SECTIONS[sec_name]
        draw.rectangle(
            rect_from_norm(box), fill=(255, 0, 0, 80), outline=(255, 0, 0, 180), width=3
        )
    else:
        combos = []
        for k, box in SECTIONS.items():
            need = set(k.split("&"))
            if need.issubset(active):
                combos.append(k)
        for k in combos:
            draw.rectangle(
                rect_from_norm(SECTIONS[k]),
                fill=(255, 0, 0, 60),
                outline=(255, 0, 0, 160),
                width=2,
            )

    composed = Image.alpha_composite(bg, overlay)
    st.image(composed, use_column_width=True)

# ====== 表示部分までそのまま ======

st.subheader("Status (last 2.5s)")
st.write(
    "MQTT:",
    "✅ connected" if st.session_state.mqtt_ok else "❌ disconnected",
    f"(rc={st.session_state.mqtt_rc})",
)
st.json({p: round(now - t, 2) for p, t in st.session_state.last_on.items()})

# ====== ↓ここを置き換える=====
# st.autorefresh(interval=1000, key="refresh") は削除して、
# 以下の自動更新処理を追加
import streamlit.runtime.scriptrunner.script_run_context as stc
import threading


def rerun_later(sec: float):
    """sec 秒後にページを再描画"""

    def _rerun():
        import streamlit as st

        st.experimental_rerun()

    threading.Timer(sec, _rerun).start()


# 1秒ごとに自動更新
rerun_later(1.0)
