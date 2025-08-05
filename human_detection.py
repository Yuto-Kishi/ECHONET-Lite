import requests
import json
import csv
import datetime
import os
import time

# ★変更点1: PIRセンサーのURLに変更
URL = "http://150.65.179.132:7000/elapi/v1/devices/1921682112000702/properties/detection"

# ★変更点2: 保存するCSVファイル名を変更
CSV_FILE = "pir_sensor_log.csv"

def get_sensor_data():
    """
    センサーのデータをURLから取得してJSONとして返す
    """
    try:
        response = requests.get(URL)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"エラー: データ取得に失敗 - {e}")
        return None

def append_to_csv(data):
    """
    取得したデータをCSVファイルに追記する
    """
    file_exists = os.path.isfile(CSV_FILE)
    try:
        with open(CSV_FILE, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)

            if not file_exists:
                # ★変更点3: ヘッダーをPIRセンサー用に変更
                writer.writerow(["timestamp", "is_detected"])

            current_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # ★変更点4: JSONから 'detection' キーの値を取得
            # 画像から、値はすでに true/false のようなので、そのまま利用します
            is_detected = data.get("detection", False) # キーが存在しない場合はFalseとする

            writer.writerow([current_time, is_detected])
            print(f"記録成功: {current_time}, is_detected={is_detected}")

    except IOError as e:
        print(f"エラー: ファイル書き込みに失敗 - {e}")
    except (KeyError, TypeError):
        print("エラー: JSONデータの形式が不正です。")


def main():
    """
    メインの処理。無限ループで1秒ごとにデータを取得・記録する。
    """
    print(f"{CSV_FILE} へのデータ記録を開始します。停止するには Ctrl+C を押してください。")
    while True:
        sensor_data = get_sensor_data()
        if sensor_data:
            append_to_csv(sensor_data)
        
        time.sleep(1)

if __name__ == "__main__":
    main()