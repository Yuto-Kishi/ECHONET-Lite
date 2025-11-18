import requests
import csv
import time
import datetime

# --- 設定 ---

# データを取得したいAPIのURL
API_URL = "https://150.65.179.132:6000/elapi/v1/devices/C0A80B06-013501@ba0256a6fea6c174/properties"

# データを取得する間隔（秒）
INTERVAL_SECONDS = 60

# 保存するCSVファイル名
CSV_FILENAME = "temperature_log.csv"

# ★★★ ここに認証情報を追加 ★★★
# ユーザーから提供されたBearer Token
API_TOKEN = "2daff9d398fbeefd36b2670e"
HEADERS = {"Authorization": f"Bearer {API_TOKEN}"}
# ★★★ ここまで ★★★


# --- ここから下は変更不要 ---

print(f"監視を開始します。API: {API_URL}")
print(f"{INTERVAL_SECONDS}秒ごとに温度を '{CSV_FILENAME}' に記録します。")
print("停止するには Ctrl + C を押してください。")

# SSL証明書のエラーを無視する設定 (自己署名証明書のため)
requests.packages.urllib3.disable_warnings()

try:
    while True:
        try:
            # 1. APIにGETリクエストを送信 (headers=HEADERS を追加)
            response = requests.get(API_URL, headers=HEADERS, verify=False, timeout=10)

            if response.status_code == 200:
                # 2. JSONレスポンスを解析
                data = response.json()

                # 3. 温度とタイムスタンプを取得
                temperature = data["temperature"]
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # 4. CSVファイルに追記
                with open(CSV_FILENAME, "a", newline="", encoding="utf-8") as f:
                    csv_writer = csv.writer(f)
                    # 最初の行にヘッダーを書き込む (ファイルが空の場合のみ)
                    if f.tell() == 0:
                        csv_writer.writerow(["Timestamp", "Temperature"])
                    csv_writer.writerow([timestamp, temperature])

                print(f"[{timestamp}] 記録しました: {temperature} °C")

            elif response.status_code == 401:
                print(
                    "認証エラー (401): Bearer Tokenが間違っているか、期限切れの可能性があります。"
                )
                print("スクリプトを停止します。")
                break  # 認証エラーの場合はループを停止
            else:
                print(f"APIからの応答エラー: Status Code {response.status_code}")

        except requests.exceptions.RequestException as e:
            print(f"リクエストエラー: {e}")
        except KeyError:
            print(
                f"JSONから 'temperature' のキーが見つかりませんでした。受信データ: {response.text}"
            )
        except Exception as e:
            print(f"不明なエラー: {e}")

        # 5. 指定した間隔だけ待機
        time.sleep(INTERVAL_SECONDS)

except KeyboardInterrupt:
    print("\n監視を停止しました。")
