# -*- coding: utf-8 -*-
# ====== MQTT / 環境設定 ======
BROKER = "150.65.179.132"
PORT = 7883
CID = "53965d6805152d95"

# ESP32 の Device ID（トピック上のID）
PIRS = ["PIR1", "PIR2", "PIR3", "PIR4"]

# ====== 背景画像（食堂・居間のみ） ======
# ← 今回添付の画像ファイル名を使います
FLOOR_IMAGE = "living_dining.png"

# ====== 可視化パラメータ ======
CANVAS_WIDTH = 1000  # 表示幅(px) お好みで調整
ACTIVE_WINDOW_SEC = 2.5  # motion_raw==1 を活動とみなす時間窓

# ====== セクション定義（0..1 の正規化矩形） ======
# X: left→right, Y: top→bottom
SECTIONS = {
    "PIR2": (0.00, 0.00, 0.33, 0.33),
    "PIR2&PIR1": (0.33, 0.00, 0.66, 0.33),
    "PIR1": (0.66, 0.00, 1.00, 0.33),
    "PIR2&PIR4": (0.00, 0.33, 0.33, 0.66),
    "PIR1&PIR3": (0.66, 0.33, 1.00, 0.66),
    "PIR4": (0.00, 0.66, 0.33, 1.00),
    "PIR4&PIR3": (0.33, 0.66, 0.66, 1.00),
    "PIR3": (0.66, 0.66, 1.00, 1.00),
}

# ====== PIR 実配置位置（0..1 の正規化座標でマーカー表示） ======
# 角/辺に置く想定の初期値です。実機に合わせて微調整してください。
# 例: 左上 = (0.10, 0.12), 右上 = (0.90, 0.12), 左下 = (0.10, 0.88), 右下 = (0.90, 0.88)
PIR_POS = {
    "PIR1": (0.85, 0.15),  # 右上寄り
    "PIR2": (0.15, 0.15),  # 左上寄り
    "PIR3": (0.85, 0.85),  # 右下寄り
    "PIR4": (0.15, 0.85),  # 左下寄り
}

# ====== “反応セット → セクション名” の決定規則 ======
COMBO_TO_SECTION = {
    frozenset({"PIR1"}): "PIR1",
    frozenset({"PIR2"}): "PIR2",
    frozenset({"PIR3"}): "PIR3",
    frozenset({"PIR4"}): "PIR4",
    frozenset({"PIR1", "PIR2"}): "PIR2&PIR1",
    frozenset({"PIR3", "PIR4"}): "PIR4&PIR3",
    frozenset({"PIR1", "PIR3"}): "PIR1&PIR3",
    frozenset({"PIR2", "PIR4"}): "PIR2&PIR4",
}
