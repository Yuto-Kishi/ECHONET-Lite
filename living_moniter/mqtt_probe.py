# -*- coding: utf-8 -*-
import socket, sys, time
import paho.mqtt.client as mqtt

BROKER = "150.65.179.132"
PORT = 7883
KEEPALIVE = 20

print(f"TCP reachability test: {BROKER}:{PORT}")
s = socket.socket()
s.settimeout(3.0)
try:
    s.connect((BROKER, PORT))
    print("✅ TCP reachable")
except Exception as e:
    print(f"❌ TCP connect failed: {e}")
    sys.exit(1)
finally:
    try:
        s.close()
    except:
        pass


def on_connect(c, u, f, rc, *_):
    print(f"[on_connect] rc={rc} (0=success)")


def on_disconnect(c, u, rc, *_):
    print(f"[on_disconnect] rc={rc}")


def on_log(c, u, level, buf):
    print(f"[paho] {buf}")


client = mqtt.Client(
    client_id=f"probe-{int(time.time())}", clean_session=True, transport="tcp"
)
client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.enable_logger()  # paho内部ログ
# 認証が不要なら username_pw_set は不要
print("Connecting...")
client.connect(BROKER, PORT, KEEPALIVE)
client.loop_start()
time.sleep(5)
client.loop_stop()
client.disconnect()
print("Done.")
