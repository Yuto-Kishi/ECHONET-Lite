
import pandas as pd, numpy as np, joblib
from pathlib import Path

def _coerce_numeric(df):
    for c in df.columns:
        if c in ("timestamp","Place","Activity","room_label"): continue
        if df[c].dtype == "O":
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

def load_models(model_dir):
    mdir = Path(model_dir)
    occ = joblib.load(mdir/"occ_classifier.joblib")
    room = joblib.load(mdir/"room_classifier.joblib")
    cols = (mdir/"feature_columns.txt").read_text(encoding="utf-8").splitlines()
    return occ, room, cols

def predict_room_presence(df, occ_model, room_model, feature_cols):
    df = df.copy()
    df = _coerce_numeric(df)
    # ensure feature alignment
    for c in feature_cols:
        if c not in df.columns:
            df[c] = np.nan
    X = df[feature_cols]
    occ_pred = occ_model.predict(X)
    room_pred = np.array(["none"] * len(df), dtype=object)
    mask = occ_pred == 1
    if mask.any():
        room_pred[mask] = room_model.predict(X[mask])
    res = df[["timestamp"]].copy() if "timestamp" in df.columns else pd.DataFrame(index=df.index)
    res["occupied_pred"] = occ_pred
    res["room_pred"] = room_pred
    return res
