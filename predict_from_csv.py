#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse, os, json
import numpy as np
import pandas as pd
import joblib


def ensure_datetime(df, ts_col):
    df = df.copy()
    df[ts_col] = pd.to_datetime(df[ts_col], errors="coerce")
    df = df.dropna(subset=[ts_col]).sort_values(ts_col).reset_index(drop=True)
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="incoming 1Hz snapshot CSV")
    ap.add_argument("--model", default="model_out/room_presence_model.pkl")
    ap.add_argument("--out", default="predicted_rooms.csv")
    args = ap.parse_args()

    bundle = joblib.load(args.model)
    pipe = bundle["pipeline"]
    le = bundle["label_encoder"]
    feat_cols = bundle["feature_cols"]
    meta = bundle["meta"]
    ts_col = meta["ts_col"]

    df = pd.read_csv(args.csv, low_memory=False)
    df = ensure_datetime(df, ts_col)

    # 同じ前処理で特徴量列を合わせる（存在しない列はNaNで補完）
    X = df.reindex(columns=feat_cols)
    pred = pipe.predict(X)
    labels = le.inverse_transform(pred)

    out = df[[ts_col]].copy()
    out["pred_room"] = labels
    out.to_csv(args.out, index=False)
    print(f"✓ wrote {args.out}  shape={out.shape}")


if __name__ == "__main__":
    main()
