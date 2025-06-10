import socket

# 待ち受けるIPアドレスとポート
LISTEN_IP = "0.0.0.0"  # すべてのネットワークインターフェースで待ち受ける
LISTEN_PORT = 12345    # 任意のポート番号

# UDPソケットを作成
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((LISTEN_IP, LISTEN_PORT))

print(f"UDPサーバーが起動しました。ポート {LISTEN_PORT} でメッセージを待っています...")
print("（このウィンドウは開いたままにしてください）")

try:
    while True:
        # データを受信
        data, addr = sock.recvfrom(1024) 
        print(f"\nメッセージ受信！")
        print(f"  - 送信元IPアドレス: {addr[0]}")
        print(f"  - メッセージ内容: {data.decode('utf-8')}")
except KeyboardInterrupt:
    print("\nサーバーを停止します。")
finally:
    sock.close()