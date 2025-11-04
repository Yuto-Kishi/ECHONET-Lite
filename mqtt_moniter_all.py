# mqtt_monitor_all.py
import paho.mqtt.client as mqtt

BROKER = "150.65.179.132"
PORT = 7883
CID = "53965d6805152d95"
TOPIC = f"/server/{CID}/+/properties/#"  # PIR1〜PIR6全てを監視

def on_connect(client, userdata, flags, rc):
    print("Connected to MQTT broker" if rc == 0 else f"Connection failed: {rc}")
    client.subscribe(TOPIC)
    print(f"Subscribed to topic pattern: {TOPIC}")

def on_message(client, userdata, msg):
    print(f"\n--- New MQTT Message ---")
    print(f"Topic: {msg.topic}")
    print(f"Payload: {msg.payload.decode('utf-8')}")
    print("--------------------------")

client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message

print("Connecting to broker...")
client.connect(BROKER, PORT, 60)
client.loop_forever()
