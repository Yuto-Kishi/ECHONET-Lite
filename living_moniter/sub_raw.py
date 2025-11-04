# -*- coding: utf-8 -*-
import json, time
import paho.mqtt.client as mqtt

BROKER = "150.65.179.132"
PORT = 7883
CID = "53965d6805152d95"
PIRS = ["PIR1", "PIR2", "PIR3", "PIR4"]
TOPIC_FMT = "/server/{cid}/{dev}/properties/motion_raw"


def on_connect(c, u, f, rc, *_):
    print(f"[connect] rc={rc}")
    if rc == 0:
        for dev in PIRS:
            t = TOPIC_FMT.format(cid=CID, dev=dev)
            print(" SUB", t)
            c.subscribe(t, qos=0)


def on_message(c, u, msg):
    payload = msg.payload.decode("utf-8", "ignore").strip()
    try:
        obj = json.loads(payload)
        motion = obj.get("motion_raw", obj.get("motion"))
    except Exception:
        motion = payload
    print(time.strftime("%H:%M:%S"), msg.topic, "=>", motion)


def on_disconnect(c, u, rc, *_):
    print(f"[disconnect] rc={rc} (will auto-reconnect)")


def on_log(c, u, level, buf):
    # つらい時はコメントアウト解除
    # print("[paho]", buf)
    pass


cli = mqtt.Client(
    client_id=f"sub-{int(time.time())}", clean_session=True, transport="tcp"
)
cli.on_connect = on_connect
cli.on_message = on_message
cli.on_disconnect = on_disconnect
cli.on_log = on_log
cli.connect(BROKER, PORT, keepalive=20)
cli.loop_forever(retry_first_connection=True)
