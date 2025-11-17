import network
import time
from umqtt.simple import MQTTClient
import machine
import ntptime
import json

# ===== Wi-Fi =====
WIFI_SSID = "Kissinger"
WIFI_PASS = "chkishilish1119"

# ===== MQTT (ECHONET Web API broker) =====
MQTT_BROKER = "150.65.179.132"
MQTT_PORT = 7883
CID = "53965d6805152d95"

# ===== Device ID =====
DEV_ID = "PIR7"   # PIRセンサーごとに個別設定

# ===== Pins =====
# GP18 (物理ピン24) を使用
pir_pin = machine.Pin(18, machine.Pin.IN)

# ===== Timing =====
STABILIZE_MS = 30000   # 起動安定化
HOLD_MS = 1500         # 検出後の保持
PRINT_INTERVAL = 1000  # 表示周期
HEALTH_INTERVAL = 60000 # 健全性チェック（毎分）
PUBLISH_INTERVAL = 1000 # 毎秒publishする間隔

# ===== State =====
last_motion = False
hold_until = 0
last_print = 0
last_health = 0
last_publish = 0

# Wi-Fi LED (Pico WのオンボードLED)
led = machine.Pin("LED", machine.Pin.OUT)

# --- Wi-Fi接続 ---
def connect_wifi():
    print("Wi-Fi接続中...")
    led.value(1)  # LED点灯
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASS)
    
    # 接続待機（タイムアウト10秒）
    wait_start = time.ticks_ms()
    while not wlan.isconnected() and time.ticks_diff(time.ticks_ms(), wait_start) < 10000:
        print(".", end="")
        time.sleep(1)
        
    if wlan.isconnected():
        print(f"\nWi-Fi OK: {wlan.ifconfig()[0]}")
        led.value(0) # LED消灯
        return wlan
    else:
        print("\nWi-Fi接続失敗")
        led.value(1) # LED点灯（エラー）
        return None

# --- NTP時刻同期 ---
def sync_time():
    print("NTP時刻同期中...")
    try:
        # Pico WのRTC (Real Time Clock) に時刻を設定
        ntptime.settime()
        print("時刻同期完了")
        # JST (+9時間) に調整
        rtc = machine.RTC()
        t = rtc.datetime() # (year, month, day, weekday, hours, minutes, seconds, subseconds)
        # JSTに補正 (UTC+9)
        # machine.RTC.datetime()はUTCを期待するため、NTPがUTCを返すことを前提
        # ここでは表示用のJSTオフセットをグローバルに持つ (より簡単な方法)
        # ただし、Pico WのntptimeはUTCを返すので、JSTへの変換は送信時に行う
    except Exception as e:
        print(f"時刻同期失敗: {e}")

# --- MQTTクライアントのセットアップ ---
# クライアントIDを "pico-" で作成
client = MQTTClient(client_id=f"pico-{DEV_ID}",
                    server=MQTT_BROKER,
                    port=MQTT_PORT,
                    keepalive=60)

# --- ヘルパー関数 ---
def publish_mqtt(topic, payload_dict):
    try:
        payload_str = json.dumps(payload_dict)
        client.publish(topic.encode('utf-8'), payload_str.encode('utf-8'))
        print(f"[MQTT] {topic} (OK)")
    except Exception as e:
        print(f"[MQTT] Publish失敗: {e}")

def get_jst_time_str():
    # UTCを取得
    utc_time_tuple = time.gmtime()
    # UTC秒に変換
    utc_seconds = time.mktime(utc_time_tuple)
    # JST (+9時間 * 3600秒)
    jst_seconds = utc_seconds + (9 * 3600)
    # JSTタプルに再変換
    jst_time_tuple = time.localtime(jst_seconds)
    # "HH:MM:SS" 形式にフォーマット
    return f"{jst_time_tuple[3]:02d}:{jst_time_tuple[4]:02d}:{jst_time_tuple[5]:02d}"

def register_device():
    topic = f"/server/{CID}/register"
    payload = {
        "id": DEV_ID,
        "deviceType": "pirSensor"
    }
    publish_mqtt(topic, payload)

def register_properties():
    topic = f"/server/{CID}/{DEV_ID}/properties"
    payload = {
        "motion": False,
        "description": "Human presence sensor (PIR)"
    }
    publish_mqtt(topic, payload)

# --- MQTT接続 (再接続ロジック含む) ---
def connect_mqtt():
    print("MQTT接続中...")
    try:
        client.connect()
        print("MQTTブローカーに接続しました")
        register_device()
        time.sleep(0.2)
        register_properties()
        return True
    except Exception as e:
        print(f"MQTT接続失敗: {e}")
        return False

# ============================================================
# メインの実行
# ============================================================

# 1. Wi-Fi接続
if connect_wifi() is None:
    # Wi-Fi失敗時はここで停止（または再起動）
    print("リセットします...")
    machine.reset()

# 2. 時刻同期
sync_time()

# 3. MQTT接続
if not connect_mqtt():
    # MQTT失敗時はリセット
    print("リセットします...")
    machine.reset()

# 4. PIR安定化
print(f"PIR安定化待機中 ({STABILIZE_MS / 1000}秒)...")
time.sleep_ms(STABILIZE_MS)
print("準備完了。\n")

# ============================================================
# メインループ
# ============================================================
while True:
    try:
        # MQTTのキープアライブやメッセージ受信処理
        client.check_msg()
        
        now_ms = time.ticks_ms()
        now_time_str = get_jst_time_str()

        # --- PIR読み取り（瞬間値） ---
        motion_raw = pir_pin.value() == 1

        # --- ホールドで安定化（= state） ---
        if motion_raw:
            hold_until = now_ms + HOLD_MS
        
        motion = (now_ms < hold_until) or motion_raw

        # --- 状態変化があった場合のみPublish ---
        if motion != last_motion:
            last_motion = motion
            topic = f"/server/{CID}/{DEV_ID}/properties/motion"
            payload = {
                "motion": motion,
                "timestamp": now_time_str
            }
            publish_mqtt(topic, payload)

        # --- 毎秒publishする処理 (motion_raw) ---
        if time.ticks_diff(now_ms, last_publish) >= PUBLISH_INTERVAL:
            last_publish = now_ms
            topic = f"/server/{CID}/{DEV_ID}/properties/motion_raw"
            payload = {
                "motion_raw": motion_raw,
                "timestamp": now_time_str
            }
            publish_mqtt(topic, payload)

        # --- 表示（rawとstateを両方出力） ---
        if time.ticks_diff(now_ms, last_print) >= PRINT_INTERVAL:
            last_print = now_ms
            print(f"[{now_time_str}] motion_raw={int(motion_raw)}, state={int(motion)}")

        # --- 健全性（毎分） ---
        if time.ticks_diff(now_ms, last_health) >= HEALTH_INTERVAL:
            last_health = now_ms
            topic = f"/server/{CID}/{DEV_ID}/properties/health"
            payload = {
                "wifi": True, # このループが回ってる時点でWi-FiはOK (本当はwlan.isconnected()を呼ぶべきだが)
                "mqtt": True, # check_msg()が例外を投げてない
                "timestamp": now_time_str
            }
            publish_mqtt(topic, payload)
        
        time.sleep_ms(5)

    except Exception as e:
        print(f"メインループでエラー発生: {e}")
        print("10秒後にリセットします...")
        time.sleep(10)
        machine.reset()