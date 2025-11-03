# -*- coding: utf-8 -*-
import json
import time
import threading
from itertools import combinations

import paho.mqtt.client as mqtt
from PIL import Image, ImageDraw, ImageFont
import streamlit as st

# 設定はあなたの config_sections.py から読み込み
from config_sections import (
    BROKER,
    PORT,
    CID,
    PIRS,
    FLOOR_IMAGE,
    ACTIVE_WINDOW_SEC,
    SECTIONS,
    PIR_POS,
    COMBO_TO_SECTION,
)

# ====== UI 基本設定 ======
st.set_page_config(page_title="Living Presence Monitor", layout="wide")

# ====== 状態（セッションスコープ） ======
if "last_on" not in st.session_state:
    # 各PIRの最終「motion_raw==1」を時刻（epoch秒）で保持
    st.session_state.last_on = {pid: 0.0 for pid in PIRS}
if "mqtt_ok" not in st.session_state:
    st.session_state.mqtt_ok = False
if "subscribed" not in st.session_state:
    st.session_state.subscribed = False

# ====== MQTT サブスクライブ ======
TOPIC_FMT = "/server/{cid}/{dev}/properties/motion_raw"


def on_connect(client, userdata, flags, rc):
    st.session_state.mqtt_ok = rc == 0
    if rc == 0 and not st.session_state.subscribed:
        for dev in PIRS:
            topic = TOPIC_FMT.format(cid=CID, dev=dev)
            client.subscribe(topic, qos=0)
        st.session_state.subscribed = True


def on_message(client, userdata, msg):
    # 期待ペイロード： {"motion_raw": true/false, "timestamp": "HH:MM:SS"} など
    try:
        data = json.loads(msg.payload.decode("utf-8"))
        motion_raw = bool(data.get("motion_raw", False))
    except Exception:
        # 文字列 "0"/"1" などフォールバック
        payload = msg.payload.decode("utf-8").strip().lower()
        motion_raw = payload in ("1", "true", "on")

    # dev名をトピックから抽出
    parts = msg.topic.split("/")
    dev = parts[3] if len(parts) >= 4 else None
    if dev in st.session_state.last_on and motion_raw:
        st.session_state.last_on[dev] = time.time()


def ensure_mqtt():
    client = mqtt.Client(client_id=f"ui-{int(time.time())}", clean_session=True)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(BROKER, PORT, keepalive=30)

    # 別スレッドで常時回す
    th = threading.Thread(target=client.loop_forever, daemon=True)
    th.start()
    return client


if not st.session_state.get("mqtt_started", False):
    ensure_mqtt()
    st.session_state.mqtt_started = True


# ====== 可視化ユーティリティ ======
def draw_scene(active_sections, active_pirs):
    """背景の上にセクション（赤）とPIR位置（青）を描く"""
    img = Image.open(FLOOR_IMAGE).convert("RGBA")
    w, h = img.size
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)

    # セクション枠（薄いグレー）
    for name, (x0, y0, x1, y1) in SECTIONS.items():
        rect = (int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h))
        d.rectangle(rect, outline=(60, 60, 60, 180), width=3)

    # アクティブなセクションを赤で塗る
    for name in active_sections:
        if name not in SECTIONS:
            continue
        x0, y0, x1, y1 = SECTIONS[name]
        rect = (int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h))
        d.rectangle(rect, fill=(255, 64, 64, 120), outline=(200, 0, 0, 220), width=4)

    # PIR配置を青でマーク
    for pid, (px, py) in PIR_POS.items():
        cx, cy = int(px * w), int(py * h)
        r = max(6, int(min(w, h) * 0.01))
        color = (30, 90, 200, 255) if pid not in active_pirs else (30, 160, 255, 255)
        d.ellipse(
            (cx - r, cy - r, cx + r, cy + r),
            fill=color,
            outline=(255, 255, 255, 200),
            width=2,
        )
        d.text((cx + r + 4, cy - r - 2), pid, fill=(20, 20, 20, 220))

    return Image.alpha_composite(img, overlay)


def decide_sections(active_pirs):
    """有効PIR集合→ハイライトすべきセクション集合を決定"""
    fs = frozenset(active_pirs)
    if not fs:
        return set()

    # 正規に一意決定できる場合
    sec = COMBO_TO_SECTION.get(fs)
    if sec:
        return {sec}

    # あいまい（3台以上など）→部分集合（1台 or 2台）のマッチを全部塗る
    result = set()
    for k in range(1, 3):  # 1台と2台の組合せだけを見る
        for sub in combinations(active_pirs, k):
            sname = COMBO_TO_SECTION.get(frozenset(sub))
            if sname:
                result.add(sname)
    return result


# ====== レイアウト ======
left, right = st.columns([4, 3])

with right:
    st.markdown("### Presence (last {:.1f}s)".format(ACTIVE_WINDOW_SEC))
    now = time.time()
    rows = []
    for pid in PIRS:
        age = now - st.session_state.last_on[pid]
        active = age <= ACTIVE_WINDOW_SEC
        rows.append(
            (
                pid,
                "ON" if active else "off",
                f"{age:4.1f}s ago" if st.session_state.last_on[pid] > 0 else "—",
            )
        )
    st.table(
        {
            "PIR": [r[0] for r in rows],
            "state": [r[1] for r in rows],
            "last_on": [r[2] for r in rows],
        }
    )

    st.write("MQTT:", "✅ connected" if st.session_state.mqtt_ok else "❌ disconnected")

with left:
    # 直近 ACTIVE_WINDOW_SEC 内に反応したPIRを抽出
    now = time.time()
    active_pirs = {
        pid
        for pid, t in st.session_state.last_on.items()
        if (now - t) <= ACTIVE_WINDOW_SEC
    }
    active_sections = decide_sections(active_pirs)
    canvas = draw_scene(active_sections, active_pirs)
    st.image(canvas, use_column_width=True)

# ====== 1秒ごとの自動更新 ======
try:
    from streamlit_autorefresh import st_autorefresh

    st_autorefresh(interval=1000, key="auto_refresh")
except Exception:
    # 代替：軽いインジケータ（Streamlitはループを推奨しないため、手動F5でも可）
    st.caption(
        "Auto-refresh: 1s (fallback mode) — consider `pip install streamlit-autorefresh`"
    )
