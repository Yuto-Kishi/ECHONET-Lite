# --- ここから：接続・サブスク部分のみ差し替え ---

import paho.mqtt.client as mqtt
import threading, time, json

BROKER = "150.65.179.132"
PORT = 7883
KEEPALIVE = 20

TOPIC_FMT = "/server/{cid}/{dev}/properties/motion_raw"


def _on_connect(client, userdata, flags, rc, *_):
    st.session_state.mqtt_ok = rc == 0
    st.session_state.mqtt_rc = rc
    if rc == 0:
        # 再接続時も再サブスク
        for dev in PIRS:
            client.subscribe(TOPIC_FMT.format(cid=CID, dev=dev), qos=0)


def _on_disconnect(client, userdata, rc, *_):
    st.session_state.mqtt_ok = False
    st.session_state.mqtt_rc = rc


def _on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode("utf-8"))
        motion_raw = bool(data.get("motion_raw", False))
    except Exception:
        p = msg.payload.decode("utf-8").strip().lower()
        motion_raw = p in ("1", "true", "on")
    # dev抽出
    parts = msg.topic.split("/")
    dev = parts[3] if len(parts) >= 4 else None
    if dev in st.session_state.last_on and motion_raw:
        st.session_state.last_on[dev] = time.time()


def _start_mqtt():
    # transport="tcp" 明示、固有のclient_id、keepalive短め
    c = mqtt.Client(
        client_id=f"ui-{int(time.time())}", clean_session=True, transport="tcp"
    )
    c.on_connect = _on_connect
    c.on_disconnect = _on_disconnect
    c.on_message = _on_message
    # 認証不要なら username_pw_set は不要。必要なら↓
    # c.username_pw_set("user", "pass")
    c.connect_async(BROKER, PORT, KEEPALIVE)
    t = threading.Thread(
        target=c.loop_forever, kwargs={"retry_first_connection": True}, daemon=True
    )
    t.start()
    return c


if not st.session_state.get("mqtt_started", False):
    st.session_state.mqtt_rc = None
    _start_mqtt()
    st.session_state.mqtt_started = True

# --- ここまで差し替え ---
