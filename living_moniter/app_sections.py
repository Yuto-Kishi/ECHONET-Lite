# -*- coding: utf-8 -*-
import json, time, threading
from datetime import datetime
from typing import Dict, Tuple, Optional

import streamlit as st
from streamlit_autorefresh import st_autorefresh
import paho.mqtt.client as mqtt
from PIL import Image, ImageDraw, ImageFont

from config_sections import (
    BROKER,
    PORT,
    CID,
    PIRS,
    FLOOR_IMAGE,
    CANVAS_WIDTH,
    ACTIVE_WINDOW_SEC,
    SECTIONS,
    PIR_POS,
    COMBO_TO_SECTION,
)

TOPIC = f"/server/{CID}/+/properties/motion_raw"

st.set_page_config(page_title="Living-Dining PIR Map", layout="wide")
st_autorefresh(interval=1000, key="auto-refresh-1s")  # ★ 1秒ごと自動更新

# ------- 状態共有 -------
if "last_true_ts" not in st.session_state:
    st.session_state.last_true_ts: Dict[str, float] = {pid: 0.0 for pid in PIRS}
if "last_val" not in st.session_state:
    st.session_state.last_val: Dict[str, int] = {pid: 0 for pid in PIRS}
if "logs" not in st.session_state:
    st.session_state.logs = []  # (ts, dev, val)
if "started" not in st.session_state:
    st.session_state.started = False

_lock = threading.Lock()


# ------- MQTT -------
def _dev_from_topic(topic: str) -> str:
    # /server/CID/DEV_ID/properties/motion_raw
    try:
        return topic.split("/")[3]
    except Exception:
        return "UNKNOWN"


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        client.subscribe(TOPIC)
    else:
        print("MQTT connect error:", rc)


def on_message(client, userdata, msg):
    dev = _dev_from_topic(msg.topic)
    if dev not in PIRS:  # 想定外は無視
        return
    try:
        data = json.loads(msg.payload.decode("utf-8"))
    except Exception:
        return
    val = 1 if bool(data.get("motion_raw", False)) else 0
    ts = data.get("timestamp", datetime.now().strftime("%H:%M:%S"))
    now = time.time()
    with _lock:
        st.session_state.last_val[dev] = val
        if val == 1:
            st.session_state.last_true_ts[dev] = now
        st.session_state.logs.append((ts, dev, val))
        st.session_state.logs = st.session_state.logs[-300:]


def mqtt_worker():
    cli = mqtt.Client()
    cli.on_connect = on_connect
    cli.on_message = on_message
    while True:
        try:
            cli.connect(BROKER, PORT, 60)
            cli.loop_forever()
        except Exception as e:
            print("MQTT error:", e)
            time.sleep(1.5)


if not st.session_state.started:
    threading.Thread(target=mqtt_worker, daemon=True).start()
    st.session_state.started = True


# ------- 描画ユーティリティ -------
def _scale_xy(xy, size):
    x, y = xy
    W, H = size
    return int(x * W), int(y * H)


def _scale_rect(rect, size):
    x0, y0, x1, y1 = rect
    W, H = size
    return int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H)


def draw_base(bg: Image.Image) -> Image.Image:
    """セクション枠＋ラベル＋PIRマーカーを常時描画"""
    img = bg.copy()
    draw = ImageDraw.Draw(img, "RGBA")

    # セクション枠（薄い線）とラベル
    for name, rect in SECTIONS.items():
        box = _scale_rect(rect, img.size)
        draw.rectangle(box, outline=(60, 60, 60, 180), width=2)
        cx = (box[0] + box[2]) // 2
        cy = (box[1] + box[3]) // 2
        draw.text((cx - 40, cy - 10), name, fill=(80, 80, 80, 220))

    # PIR 実配置マーカー
    for pid, xy in PIR_POS.items():
        px, py = _scale_xy(xy, img.size)
        r = 10
        color = (30, 120, 200, 220)  # マーカー色
        draw.ellipse(
            (px - r, py - r, px + r, py + r),
            fill=color,
            outline=(255, 255, 255, 220),
            width=2,
        )
        draw.text((px + 12, py - 10), pid, fill=(20, 20, 20, 230))
    return img


def overlay_section(
    img: Image.Image, section: str, color=(255, 60, 60, 110)
) -> Image.Image:
    if section not in SECTIONS:
        return img
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(over, "RGBA")
    box = _scale_rect(SECTIONS[section], img.size)
    draw.rectangle(box, fill=color, outline=(120, 20, 20, 220), width=3)
    return Image.alpha_composite(img, over)


def overlay_union(img: Image.Image, act: set) -> Image.Image:
    """規則にない組合せ（0/3/4台）→ 単独セルを重ね塗り表示"""
    singles = {"PIR1", "PIR2", "PIR3", "PIR4"}
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(over, "RGBA")
    for pid in act & singles:
        if pid in SECTIONS:
            box = _scale_rect(SECTIONS[pid], img.size)
            draw.rectangle(
                box, fill=(255, 170, 0, 90), outline=(120, 90, 0, 220), width=2
            )
    return Image.alpha_composite(img, over)


def active_set(now: float) -> frozenset:
    with _lock:
        A = {
            pid
            for pid in PIRS
            if (now - st.session_state.last_true_ts.get(pid, 0.0)) <= ACTIVE_WINDOW_SEC
        }
    return frozenset(A)


# ------- UI -------
colL, colR = st.columns([3, 1])

with colL:
    # 背景の読み込み＆スケール
    base_img = Image.open(FLOOR_IMAGE).convert("RGBA")
    W0, H0 = base_img.size
    scale = CANVAS_WIDTH / float(W0)
    base_img = base_img.resize((int(W0 * scale), int(H0 * scale)))
    base_img = draw_base(base_img)  # セクション枠 + PIR位置マーカー

    # 現在の活動セット → セクション判定
    A = active_set(time.time())
    section = COMBO_TO_SECTION.get(A)

    if section:
        out = overlay_section(base_img, section)
        st.image(out, use_column_width=False)
        st.success(f"Active PIRs = {sorted(A)} → **Section: {section}**")
    else:
        out = overlay_union(base_img, set(A))
        st.image(out, use_column_width=False)
        if len(A) == 0:
            st.info("No PIR active in the recent window.")
        else:
            st.warning(f"Ambiguous active set: {sorted(A)}")

with colR:
    st.markdown("### Last motion_raw (recent)")
    with _lock:
        for ts, dev, val in st.session_state.logs[-30:][::-1]:
            st.write(f"**[{ts}] {dev} → motion={val}**")
    st.markdown("---")
    st.caption(
        f"Refresh: 1s · Active window: {ACTIVE_WINDOW_SEC}s · Broker: {BROKER}:{PORT}"
    )
