import socket
import struct
import sys
import time
from collections import defaultdict

# ECHONET Liteの基本設定
ECHONET_MULTICAST_ADDR = '224.0.23.0'
ECHONET_PORT = 3610

# 機器のクラスコード
NODE_PROFILE = b'\x0e\xf0'
CO2_SENSOR = b'\x00\x12'
TEMP_SENSOR = b'\x00\x11'
HUMIDITY_SENSOR = b'\x00\x13'

# EPC（プロパティコード）
EPC_INSTANCE_LIST = 0xD6
EPC_MEASUREMENT_VALUE = 0xE0


def create_echonet_packet(tid, deoj, epc):
    """指定されたオブジェクトとプロパティに対するGetリクエストパケットを作成する"""
    seoj = b'\x05\xff\x01' # 送信元はコントローラ
    esv = 0x62  # Get
    opc = 0x01  # プロパティは1つ
    pdc = 0x00  # 要求データなし
    packet = struct.pack('!BBH3s3sBBBB', 0x10, 0x81, tid, seoj, deoj, esv, opc, epc, pdc)
    return packet


def parse_property_value(esv, epc, edt):
    """プロパティ値を人間が読める形式に変換する"""
    if esv != 0x72: # Get_Resでなければ処理しない
        return "N/A (Not a Get_Res)"
    
    if epc == EPC_MEASUREMENT_VALUE:
        if len(edt) == 2: # CO2, 温度
            value = struct.unpack('!h', edt)[0] # 符号付きで解釈
            if value == -32767: return "Invalid Value"
            # 温度の場合
            if len(edt) == 2 and value > -1000 and value < 1000: # 温度らしい値か
                 return f"{value / 10.0:.1f} ℃"
            # CO2の場合
            else:
                return f"{struct.unpack('!H', edt)[0]} ppm" # 符号なしで解釈し直し
        elif len(edt) == 1: # 湿度
            value = struct.unpack('!B', edt)[0]
            return f"{value} %RH"
    return edt.hex()


def main():
    # --- 1. UDPソケットの準備 ---
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(2) # 応答待機は2秒

    # --- 2. 機器の探索 ---
    print("ステップ1: ネットワーク上のECHONET Lite機器を探します...")
    discovery_packet = create_echonet_packet(0x0001, NODE_PROFILE + b'\x01', EPC_INSTANCE_LIST)
    sock.sendto(discovery_packet, (ECHONET_MULTICAST_ADDR, ECHONET_PORT))

    device_ip = None
    try:
        data, addr = sock.recvfrom(1024)
        if data[7:10] == NODE_PROFILE + b'\x01': # ノードプロファイルからの応答か
            device_ip = addr[0]
            print(f"-> 成功: 機器を発見しました (IP: {device_ip})")
    except socket.timeout:
        print("-> 失敗: 機器が見つかりませんでした。")
        print("   - ESP32とMacが同じWi-Fiに接続されているか確認してください。")
        print("   - MacのファイアウォールやルーターのAPアイソレーション機能を確認してください。")
        sock.close()
        return

    if not device_ip:
        sock.close()
        return

    # --- 3. 各センサーのデータを取得 ---
    print("\nステップ2: 発見した機器から各センサーのデータを取得します...")
    
    sensor_objects = {
        "CO2濃度": CO2_SENSOR + b'\x01',
        "温度": TEMP_SENSOR + b'\x01',
        "湿度": HUMIDITY_SENSOR + b'\x01',
    }

    results = {}
    tid_counter = 100 # トランザクションIDをリセット

    for name, deoj in sensor_objects.items():
        tid_counter += 1
        print(f"  - {name}のデータを要求中...", end="")
        
        # データ取得リクエストを送信
        request_packet = create_echonet_packet(tid_counter, deoj, EPC_MEASUREMENT_VALUE)
        sock.sendto(request_packet, (device_ip, ECHONET_PORT))
        
        try:
            # 応答を受信
            data, addr = sock.recvfrom(1024)
            # 応答パケットを解析
            esv = data[10]
            epc = data[12]
            pdc = data[13]
            edt = data[14:14+pdc]
            
            # 結果を保存
            results[name] = parse_property_value(esv, epc, edt)
            print(" 完了")

        except socket.timeout:
            results[name] = "応答なし (タイムアウト)"
            print(" 失敗 (タイムアウト)")
        
        time.sleep(0.2) # 連続送信を避けるための短い待機

    sock.close()

    # --- 4. 最終結果の表示 ---
    print("\n--- データ取得結果 ---")
    for name, value in results.items():
        print(f"  {name}: {value}")
    print("----------------------")


if __name__ == "__main__":
    main()