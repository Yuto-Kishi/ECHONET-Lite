#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse, json
import numpy as np
import pandas as pd
import joblib


def sticky_decision(
    probs_seq, classes, min_stay_sec=10, switch_need_consec=3, margin=0.05
):
    """
    probs_seq: 時系列での predict_proba 出力 [T, C]
    classes:   ラベル名配列
    """
    T, C = probs_seq.shape
    cur = None
    stay = 0
    out = []
    for t in range(T):
        p = probs_seq[t]
        top_idx = int(np.argmax(p))
        top = classes[top_idx]
        if cur is None:
            cur = top
            stay = 1
        else:
            if top != cur:
                # しきい差分＆連続回数で切替判定を厳しく
                cur_p = p[list(classes).index(cur)]
                if p[top_idx] >= cur_p + margin:
                    # スイッチ候補をカウント
                    stay -= 1
                    if stay <= -switch_need_consec:
                        cur = top
                        stay = min_stay_sec
                else:
                    stay = max(stay, 1) - 1  # 微妙なら現状維持寄り
            else:
                stay = min_stay_sec
        out.append(cur)
        stay = max(-switch_need_consec, min_stay_sec if cur == top else stay)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--model", default="model_out/room_presence_model.pkl")
    ap.add_argument("--features", default="model_out/room_presence_features.json")
    ap.add_argument("--ts-col", default="timestamp")
    ap.add_argument("--out-csv", default="pred_with_sticky.csv")
    ap.add_argument("--min-stay-sec", type=int, default=10)
    ap.add_argument("--switch-need-consec", type=int, default=3)
    ap.add_argument("--margin", type=float, default=0.05)
    args = ap.parse_args()

    bundle = joblib.load(args.model)
    pipe = bundle["pipeline"]
    classes = np.array(bundle["label_encoder"].classes_)
    with open(args.features, "r", encoding="utf-8") as f:
        feat_cols = json.load(f)

    df = pd.read_csv(args.csv, low_memory=False)
    df[args.ts_col] = pd.to_datetime(df[args.ts_col], errors="coerce")
    df = df.dropna(subset=[args.ts_col]).sort_values(args.ts_col).reset_index(drop=True)

    # 必要な特徴だけ取り出し（学習時と同名）
    X = df.reindex(columns=feat_cols)
    # 推論
    proba = pipe.predict_proba(X.values)
    pred_raw = classes[np.argmax(proba, axis=1)]

    # 粘りで平滑化
    pred_smooth = sticky_decision(
        probs_seq=proba,
        classes=classes,
        min_stay_sec=args.min_stay_sec,
        switch_need_consec=args.switch_need_consec,
        margin=args.margin,
    )

    out = pd.DataFrame(
        {
            args.ts_col: df[args.ts_col],
            "pred_raw": pred_raw,
            "pred_sticky": pred_smooth,
        }
    )
    out.to_csv(args.out_csv, index=False)
    print(f"✓ wrote {args.out_csv}  shape={out.shape}")


if __name__ == "__main__":
    main()
