import requests
import csv
import time
import datetime

# --- 設定 ---

# エアコンのプロパティ取得用URL
API_URL = "https://150.65.179.132:6000/elapi/v1/devices/C0A80B03-013001@ba0256a6fea6c174/properties"

# データを取得する間隔（秒）
INTERVAL_SECONDS = 60

# 保存するCSVファイル名
CSV_FILENAME = "co2_log.csv"

# 認証情報 (Bearer Token)
API_TOKEN = ""
HEADERS = {"Authorization": f"Bearer {API_TOKEN}"}

# --- ここから下は変更不要 ---

print(f"監視を開始します。Target: Sharp AirConditioner (CO2)")
print(f"{INTERVAL_SECONDS}秒ごとにCO2濃度を '{CSV_FILENAME}' に記録します。")
print("停止するには Ctrl + C を押してください。")

# SSL証明書エラー警告を無効化
requests.packages.urllib3.disable_warnings()

try:
    while True:
        try:
            # verify=False でSSL検証スキップ
            response = requests.get(API_URL, headers=HEADERS, verify=False, timeout=10)

            if response.status_code == 200:
                data = response.json()

                # JSONから CO2濃度を取得 (キー名: co2Concentration)
                # キーが存在しない場合は None を返す
                co2_val = data.get("co2Concentration")

                # ついでに室温も取得しておくと便利かもしれません
                room_temp = data.get("roomTemperature")

                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                if co2_val is not None:
                    # CSVファイルに追記
                    with open(CSV_FILENAME, "a", newline="", encoding="utf-8") as f:
                        csv_writer = csv.writer(f)
                        # ヘッダー書き込み (ファイルが空の時だけ)
                        if f.tell() == 0:
                            csv_writer.writerow(
                                ["Timestamp", "CO2(ppm)", "RoomTemp(C)"]
                            )

                        csv_writer.writerow([timestamp, co2_val, room_temp])

                    print(f"[{timestamp}] CO2: {co2_val} ppm / 室温: {room_temp} C")
                else:
                    print(
                        f"[{timestamp}] エラー: co2Concentration のデータが含まれていません。"
                    )

            elif response.status_code == 401:
                print("認証エラー (401): トークンを確認してください。停止します。")
                break
            else:
                print(f"APIエラー: {response.status_code} - {response.text}")

        except Exception as e:
            print(f"エラー発生: {e}")

        time.sleep(INTERVAL_SECONDS)

except KeyboardInterrupt:
    print("\n監視を停止しました。")
