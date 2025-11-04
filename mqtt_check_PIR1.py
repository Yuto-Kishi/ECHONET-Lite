# mqtt_check_PIR1.py
import paho.mqtt.client as mqtt

BROKER = "150.65.179.132"
PORT = 7883
CID = "53965d6805152d95"
TOPIC = f"/server/{CID}/PIR1/properties/#"


def on_connect(client, userdata, flags, rc):
    print("Connected ✅")
    client.subscribe(TOPIC)
    print(f"Listening: {TOPIC}")


def on_message(client, userdata, msg):
    print(f"[PIR1] {msg.payload.decode('utf-8')}")


client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message
client.connect(BROKER, PORT, 60)
client.loop_forever()
