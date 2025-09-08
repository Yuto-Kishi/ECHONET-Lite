# -*- coding: utf-8 -*-
import os
import csv
import json
import time
import spidev
import numpy as np
import cv2
import smbus
import paho.mqtt.client as mqtt
from datetime import datetime, timezone

# ------------------------------- 定数設定 --------------------------------
# Lepton
WIDTH, HEIGHT = 80, 60
PKT_SIZE = 164
RESIZE_FACTOR = 10

PERSON_TEMP_MIN_C = 26.0
PERSON_TEMP_MAX_C = 40.0
MIN_CONTOUR_AREA   = 50

# 表示（X11等がない環境では自動で無効化）
SHOW_WINDOW = bool(os.environ.get("DISPLAY"))

# MQTT（ELWA）
MQTT_BROKER = "150.65.179.132"
MQTT_PORT   = 7883
CID         = "53965d6805152d95"
DEV_ID      = "thermal_1"   # 必要なら変更
TOPIC_PROP  = f"/server/{CID}/{DEV_ID}/properties"
TOPIC_OCC   = f"/server/{CID}/{DEV_ID}/properties/lepton_occupied"

# CSV
CSV_FILE = "lepton_occupancy.csv"
CSV_FIELDS = ["timestamp", "lepton_occupied"]
CSV_WRITE_EVERY_SEC = 1.0  # 1秒ごとにスナップショット追記

# ------------------------------- 初期化 --------------------------------
# SPI
spi = spidev.SpiDev()
spi.open(0, 0)                  # bus=0, CE0
spi.max_speed_hz = 20_000_000   # 20MHz
spi.mode = 0b11                 # Mode 3

# I2C（任意）
try:
    bus = smbus.SMBus(1)
    LEPTON_I2C_ADDR = 0x2A
except FileNotFoundError:
    print("I2Cバスなし：FFC等は未使用で続行します。")
    bus = None

# 背景差分（動体）
backSub = cv2.createBackgroundSubtractorMOG2()
kernel = np.ones((3,3), np.uint8)

# MQTT
client = mqtt.Client()

# 状態
last_occupied = None
last_csv_write = 0.0

# ------------------------------- 関数群 --------------------------------
def ensure_csv_header():
    need_header = (not os.path.exists(CSV_FILE)) or (os.path.getsize(CSV_FILE) == 0)
    if need_header:
        with open(CSV_FILE, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writeheader()

def append_csv(occupied: bool):
    ts = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S%z")
    row = {"timestamp": ts, "lepton_occupied": occupied}
    with open(CSV_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writerow(row)
    print("💾 CSV", row)

def iso_ts():
    return datetime.now(timezone.utc).astimezone().isoformat()

def register_device():
    topic = f"/server/{CID}/register"
    payload = {"id": DEV_ID, "deviceType": "leptonOccupancy"}
    client.publish(topic, json.dumps(payload))

def register_properties():
    # 最初にプロパティ一覧を定義
    payload = {
        "manufacturer": {
            "code": "0x000000",
            "descriptions": {"ja": "JAIST", "en": "JAIST"},
        },
        "protocol": {"type": "custom_mqtt", "version": "1.0"},
        "lepton_occupied": False,
    }
    client.publish(TOPIC_PROP, json.dumps(payload))

def publish_occupied(occupied: bool):
    payload = {"lepton_occupied": occupied, "ts": iso_ts()}
    print("📡 MQTT", TOPIC_OCC, payload)
    client.publish(TOPIC_OCC, json.dumps(payload))

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("✅ MQTT connected")
        register_device()
        time.sleep(0.2)
        register_properties()
    else:
        print("❌ MQTT connect failed:", rc)

client.on_connect = on_connect

def read_frame():
    """Leptonから1フレーム取得"""
    frame = np.zeros((HEIGHT, WIDTH), dtype=np.uint16)
    lines_read = 0
    sync_waits = 0
    max_sync_waits = 1000

    while lines_read < HEIGHT:
        try:
            pkt = spi.readbytes(PKT_SIZE)
        except Exception as e:
            print(f"SPI読み取りエラー: {e}")
            time.sleep(0.01)
            continue

        if len(pkt) != PKT_SIZE:
            continue

        # Discard packet?
        if (pkt[0] & 0x0F) == 0x0F:
            continue

        pkt_id = (pkt[0] << 8) | pkt[1]
        line = pkt_id & 0x0FFF

        if line < HEIGHT:
            data = np.frombuffer(bytearray(pkt[4:]), dtype=">u2")
            if data.size == WIDTH:
                frame[line] = data
                lines_read += 1

        sync_waits += 1
        if sync_waits > max_sync_waits:
            print("同期失敗、再同期…")
            time.sleep(0.5)
            sync_waits = 0

    return frame

def normalize_to_8bit(img):
    i_min, i_max = np.min(img), np.max(img)
    if i_max == i_min:
        return np.zeros_like(img, dtype=np.uint8)
    return ((img - i_min) * 255.0 / (i_max - i_min)).astype(np.uint8)

def raw_to_celsius(raw_data):
    # Radiometric/TLinear前提: Kelvin*100
    return (raw_data / 100.0) - 273.15

# ------------------------------- メイン --------------------------------
def main():
    global last_occupied, last_csv_write

    ensure_csv_header()

    # MQTT 接続
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    client.loop_start()

    print("プログラムを開始します。'q' で終了、's' で保存。")

    try:
        while True:
            # 1) Leptonフレーム取得
            raw_frame = read_frame()
            if raw_frame is None or np.all(raw_frame == 0):
                print("空フレーム、リトライ…")
                time.sleep(0.05)
                continue

            # 2) 温度変換 & 表示グレイスケール
            temp_c_frame = raw_to_celsius(raw_frame)
            vis_gray = normalize_to_8bit(raw_frame)

            # 3) 温度マスク（人の体温帯）
            temp_mask = cv2.inRange(temp_c_frame, PERSON_TEMP_MIN_C, PERSON_TEMP_MAX_C)

            # 4) 動体マスク（ノイズ除去含む）
            motion_mask = backSub.apply(vis_gray)
            motion_mask = cv2.morphologyEx(motion_mask, cv2.MORPH_OPEN,  kernel)
            motion_mask = cv2.morphologyEx(motion_mask, cv2.MORPH_CLOSE, kernel)

            # 5) AND（「動いて」かつ「人温度」）
            combined_mask = cv2.bitwise_and(temp_mask, motion_mask)

            # 6) 輪郭→有効領域あり？で occupied 判定
            contours, _ = cv2.findContours(combined_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            occupied = False
            if contours:
                for cnt in contours:
                    if cv2.contourArea(cnt) >= MIN_CONTOUR_AREA:
                        occupied = True
                        break

            # 7) MQTT（状態が変わったときだけ送信）
            if last_occupied is None or occupied != last_occupied:
                publish_occupied(occupied)
                last_occupied = occupied

            # 8) CSV（1秒ごとにスナップショット）
            now = time.time()
            if now - last_csv_write >= CSV_WRITE_EVERY_SEC:
                append_csv(occupied)
                last_csv_write = now

            # 9) 画面表示（可能な環境のみ）
            if SHOW_WINDOW:
                vis_color = cv2.applyColorMap(vis_gray, cv2.COLORMAP_INFERNO)
                for cnt in contours:
                    if cv2.contourArea(cnt) < MIN_CONTOUR_AREA:
                        continue
                    x, y, w, h = cv2.boundingRect(cnt)
                    cv2.rectangle(vis_color, (x, y), (x+w, y+h), (0, 255, 0), 1)
                    cv2.putText(vis_color, "Person", (x, y-5),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0,255,0), 1)
                cv2.putText(vis_color, f"occupied={occupied}", (2,10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255,255,255), 1)
                resized_vis = cv2.resize(vis_color, (WIDTH*RESIZE_FACTOR, HEIGHT*RESIZE_FACTOR),
                                         interpolation=cv2.INTER_CUBIC)
                try:
                    cv2.imshow("FLIR Lepton - Person Detector", resized_vis)
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord('q'):
                        break
                    elif key == ord('s'):
                        filename = f"lepton_capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                        cv2.imwrite(filename, resized_vis)
                        print(f"画像を保存しました: {filename}")
                except cv2.error:
                    # GUI無しでクラッシュしないように握りつぶす
                    pass
            else:
                # GUIなし運用時の軽いウェイト
                time.sleep(0.01)

    except KeyboardInterrupt:
        print("\n停止要求を受け取りました。")
    finally:
        client.loop_stop()
        client.disconnect()
        spi.close()
        try:
            cv2.destroyAllWindows()
        except cv2.error:
            pass
        print("クリーンアップ完了。")

if __name__ == "__main__":
    main()
