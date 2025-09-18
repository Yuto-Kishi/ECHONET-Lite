# predict_batch_from_integrated.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse, json, joblib, numpy as np, pandas as pd
from pathlib import Path


def _to_bool(x):
    if pd.isna(x):
        return None
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, (int, float, np.integer, np.floating)):
        return bool(int(x != 0))
    if isinstance(x, str):
        s = x.strip().lower()
        if s in ("true", "t", "yes", "y", "on", "1"):
            return True
        if s in ("false", "f", "no", "n", "off", "0"):
            return False
        if s in ("open",):
            return False
        if s in ("closed",):
            return True
    return None


def _object_to_numeric(series: pd.Series) -> pd.Series:
    if series.dtype == object:
        s = series.copy()
        mapping = {"OPEN": 0, "open": 0, "CLOSED": 1, "closed": 1}
        s = s.map(mapping).where(~s.isna(), s)
        s = s.map(
            lambda v: (
                1 if _to_bool(v) is True else (0 if _to_bool(v) is False else np.nan)
            )
        )
        try:
            return s.astype(float)
        except Exception:
            return pd.to_numeric(series, errors="coerce")
    elif series.dtype == bool:
        return series.astype(float)
    return series


def add_derived_features(df_num: pd.DataFrame, windows=(5, 15)) -> pd.DataFrame:
    out = df_num.copy()
    for c in df_num.columns:
        out[f"{c}__diff1"] = df_num[c].diff(1)
    for w in windows:
        roll = df_num.rolling(window=w, min_periods=1)
        out[[f"{c}__r{w}m" for c in df_num.columns]] = roll.mean().values
        out[[f"{c}__r{w}s" for c in df_num.columns]] = roll.std().values
    return out


def make_features(df: pd.DataFrame, ts_col: str, feature_cols: list) -> pd.DataFrame:
    df = df.copy()
    if ts_col in df.columns:
        df[ts_col] = pd.to_datetime(df[ts_col], errors="coerce")
        df = df.dropna(subset=[ts_col]).sort_values(ts_col).reset_index(drop=True)

    X_base = df.drop(columns=[ts_col], errors="ignore")
    for c in X_base.columns:
        X_base[c] = _object_to_numeric(X_base[c])
    X_base = X_base.select_dtypes(include=[np.number])
    X_all = add_derived_features(X_base, windows=(5, 15))
    # 学習時に存在した列だけに合わせる（無い列は追加）
    for c in feature_cols:
        if c not in X_all.columns:
            X_all[c] = np.nan
    X_all = X_all[feature_cols]
    X_all = X_all.replace([np.inf, -np.inf], np.nan)
    return X_all


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--model", default="model_out/room_presence_model.pkl")
    ap.add_argument("--out", default="predictions.csv")
    ap.add_argument("--ts-col", default="timestamp")
    args = ap.parse_args()

    bundle = joblib.load(args.model)
    pipe = bundle["pipeline"]
    le = bundle["label_encoder"]
    feat_cols = bundle["feature_cols"]

    df = pd.read_csv(args.csv, low_memory=False)
    X = make_features(df, args.ts_col, feat_cols)
    proba = pipe.predict_proba(X)
    pred = le.inverse_transform(np.argmax(proba, axis=1))

    out = pd.DataFrame(
        {
            "timestamp": (
                pd.to_datetime(df[args.ts_col], errors="coerce")
                if args.ts_col in df.columns
                else pd.NaT
            ),
            "pred_room": pred,
        }
    )
    for i, c in enumerate(le.classes_):
        out[f"proba_{c}"] = proba[:, i]
    out.to_csv(args.out, index=False)
    print(f"✓ predictions -> {args.out}  shape={out.shape}")


if __name__ == "__main__":
    main()
