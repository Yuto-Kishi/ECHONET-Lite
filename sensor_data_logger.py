import requests
import json
import csv
import datetime
import os
import time # timeモジュールをインポート

# データ取得先のURL
URL = "http://150.65.179.132:7000/elapi/v1/devices/192168215305FD01/properties/operationStatus"

# 保存するCSVファイル名
CSV_FILE = "door_sensor_log_continuous.csv"

def get_sensor_data():
    """
    センサーのデータをURLから取得してJSONとして返す
    """
    try:
        response = requests.get(URL)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        # ネットワークエラーなどはコンソールに表示するが、プログラムは止めない
        print(f"エラー: データ取得に失敗 - {e}")
        return None

def append_to_csv(data):
    """
    取得したデータをCSVファイルに追記する
    """
    # CSVファイルが存在するかチェックし、なければヘッダーを書き込む
    file_exists = os.path.isfile(CSV_FILE)
    try:
        with open(CSV_FILE, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)

            if not file_exists:
                writer.writerow(["timestamp", "is_closed"])

            current_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            raw_status = data.get("operationStatus")
            
            # '81'が「閉」状態であると仮定
            is_closed = (raw_status == "81")

            writer.writerow([current_time, is_closed])
            print(f"記録成功: {current_time}, is_closed={is_closed}")

    except IOError as e:
        print(f"エラー: ファイル書き込みに失敗 - {e}")
    except (KeyError, TypeError):
        # JSONの形式が不正な場合
        print("エラー: JSONデータの形式が不正です。")


def main():
    """
    メインの処理。無限ループで1秒ごとにデータを取得・記録する。
    """
    print("データ記録を開始します。停止するには Ctrl+C を押してください。")
    while True:
        sensor_data = get_sensor_data()
        if sensor_data:
            append_to_csv(sensor_data)
        
        # ★変更点: 1秒待機する
        time.sleep(1)

if __name__ == "__main__":
    main()