# -*- coding: utf-8 -*-
# ====== MQTT / 環境設定 ======
BROKER = "150.65.179.132"
PORT = 7883
CID = "53965d6805152d95"

# ESP32 の Device ID（トピック上のID）——画像上のラベルにもそのまま使います
PIRS = ["PIR1", "PIR2", "PIR3", "PIR4"]

# ====== 背景画像（食堂・居間のみ） ======
# ここに、あなたの「食堂・居間」PNGを置いてファイル名を書き換えてください
FLOOR_IMAGE = "living_dining.png"  # 例）スクショを PNG 保存して置く

# ====== 可視化パラメータ ======
CANVAS_WIDTH = 900  # 表示幅（px）
ACTIVE_WINDOW_SEC = 2.5  # motion_raw==1 を「活動中」と見なす時間窓（秒）

# ====== セクション定義（正規化 0..1 の矩形） ======
# 画像を 3x3 の格子として各セルを命名。あなたが添付した図の意図に合わせています。
#   X: left→right (0..1), Y: top→bottom (0..1)
# セクション名 : (x0,y0,x1,y1)
SECTIONS = {
    "PIR2": (0.00, 0.00, 0.33, 0.33),
    "PIR2&PIR1": (0.33, 0.00, 0.66, 0.33),  # 上段中央（PIR2 と PIR1 の共通域）
    "PIR1": (0.66, 0.00, 1.00, 0.33),
    "PIR2&PIR4": (0.00, 0.33, 0.33, 0.66),  # 左中央（PIR2 と PIR4 の共通域）
    # "CENTER"    : (0.33, 0.33, 0.66, 0.66),   # （必要なら中央セルも使えます）
    "PIR1&PIR3": (0.66, 0.33, 1.00, 0.66),  # 右中央（PIR1 と PIR3 の共通域）
    "PIR4": (0.00, 0.66, 0.33, 1.00),
    "PIR4&PIR3": (0.33, 0.66, 0.66, 1.00),  # 下段中央（PIR4 と PIR3 の共通域）
    "PIR3": (0.66, 0.66, 1.00, 1.00),
}

# ====== “反応セット → セクション名” の決定規則 ======
# motion_raw==1 が “直近 ACTIVE_WINDOW_SEC 内” に来た PIR の集合からセクションを一意決定します。
# 想定ルール（添付図に対応）：
#   単独: PIR1 / PIR2 / PIR3 / PIR4
#   ペア: {PIR1,PIR2}→"PIR2&PIR1" / {PIR3,PIR4}→"PIR4&PIR3"
#        {PIR1,PIR3}→"PIR1&PIR3" / {PIR2,PIR4}→"PIR2&PIR4"
#   上記以外（3台同時など）は曖昧として None を返し、重ね塗り表示にします。
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
# ====== PIR 実配置位置（0..1 の正規化座標でマーカー表示） ======
# 角または壁付け位置に応じて調整
PIR_POS = {
    "PIR1": (0.85, 0.10),  # 右上付近
    "PIR2": (0.15, 0.15),  # 左上付近
    "PIR3": (0.85, 0.85),  # 右下付近
    "PIR4": (0.15, 0.85),  # 左下付近
}
