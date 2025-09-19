#!/usr/bin/env python3
"""
End-to-end training script for single-resident room presence modeling (room + occupancy).

Usage:
  python train_room_presence.py \
    --csv "living_kitchen.csv" "sleeping_room.csv" "washitsu.csv" \
    --outdir ./model_out

The script will:
  - Load and normalize the three CSVs (timestamp, sensor cols, Occupied/Place columns if present)
  - Concatenate and clean
  - Train an Occupancy classifier (binary) with class balancing
  - Train a Room classifier (multi-class) on occupied samples only
  - Report metrics on a held-out stratified split
  - Save trained pipelines (joblib) + an inference helper
"""

import argparse, re
from pathlib import Path
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, accuracy_score
import joblib


def _load_room_csv(path: Path, place_override=None) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)
    # timestamp
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    # ensure columns exist
    for col in ("Occupied", "Number of People", "Place", "Activity"):
        if col not in df.columns:
            df[col] = np.nan
    if place_override:
        df["Place"] = place_override
    # normalize place strings
    df["Place"] = (
        df["Place"]
        .astype(str)
        .str.strip()
        .str.replace(" ", "_")
        .str.replace("-", "_")
        .str.replace("　", "_")
        .str.lower()
    )
    room_map = {
        "washitsu": "washitsu",
        "living_kitchen": "living_kitchen",
        "living-kitchen": "living_kitchen",
        "living": "living_kitchen",
        "kitchen": "living_kitchen",
        "sleeping_room": "sleeping_room",
        "sleepingroom": "sleeping_room",
        "bedroom": "sleeping_room",
    }
    df["Place"] = df["Place"].map(lambda x: room_map.get(x, x))

    def to_int01(x):
        if pd.isna(x):
            return np.nan
        if isinstance(x, (int, float)) and not pd.isna(x):
            return int(float(x) != 0.0)
        s = str(x).strip().lower()
        if s in ("1", "true", "t", "yes", "y", "on"):
            return 1
        if s in ("0", "false", "f", "no", "n", "off"):
            return 0
        return np.nan

    df["Occupied"] = df["Occupied"].apply(to_int01)

    # coerce object columns to numeric where possible
    for c in df.columns:
        if c in ("timestamp", "Place", "Activity"):
            continue
        if df[c].dtype == "O":
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def build_dataset(csv_paths):
    dfs = []
    for p in csv_paths:
        pname = Path(p).name.lower()
        place = None
        if "washitsu" in pname:
            place = "washitsu"
        elif "sleeping" in pname:
            place = "sleeping_room"
        elif "living" in pname or "kitchen" in pname:
            place = "living_kitchen"
        df = _load_room_csv(Path(p), place_override=None)
        if df["Place"].isna().all() and place is not None:
            df["Place"] = place
        dfs.append(df)
    raw = (
        pd.concat(dfs, axis=0, ignore_index=True)
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    raw["room_label"] = np.where(
        raw["Occupied"] == 1, raw["Place"].fillna("unknown"), "none"
    )
    # define features
    drop_cols = {"timestamp", "Place", "Activity", "room_label"}
    numeric_cols = [c for c in raw.columns if c not in drop_cols]
    # coerce numerics
    for c in numeric_cols:
        if raw[c].dtype == "O":
            raw[c] = pd.to_numeric(raw[c], errors="coerce")
    X = raw[numeric_cols]
    y_occ = raw["Occupied"].fillna(0).astype(int)
    y_room = raw["room_label"].astype(str)
    return raw, X, y_occ, y_room, numeric_cols


def train_and_eval(X, y_occ, y_room, outdir: Path):
    # split OCC with class stratification
    Xo_tr, Xo_te, yo_tr, yo_te = train_test_split(
        X, y_occ, test_size=0.2, random_state=42, stratify=y_occ
    )
    num_proc = Pipeline(
        [
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler(with_mean=False)),
        ]
    )
    occ_clf = Pipeline(
        [
            ("prep", num_proc),
            (
                "clf",
                LogisticRegression(
                    max_iter=1000, class_weight="balanced", solver="liblinear"
                ),
            ),
        ]
    )
    occ_clf.fit(Xo_tr, yo_tr)
    occ_pred = occ_clf.predict(Xo_te)
    print("\n=== Occupancy ===")
    print("Accuracy:", accuracy_score(yo_te, occ_pred))
    print(classification_report(yo_te, occ_pred, digits=3))

    # split ROOM only on occupied rows
    mask = y_occ == 1
    Xr = X[mask]
    yr = y_room[mask]
    Xr_tr, Xr_te, yr_tr, yr_te = train_test_split(
        Xr, yr, test_size=0.2, random_state=42, stratify=yr
    )
    room_clf = Pipeline(
        [
            ("prep", num_proc),
            (
                "clf",
                RandomForestClassifier(
                    n_estimators=400,
                    random_state=42,
                    n_jobs=-1,
                    class_weight="balanced",
                ),
            ),
        ]
    )
    room_clf.fit(Xr_tr, yr_tr)
    room_pred = room_clf.predict(Xr_te)
    print("\n=== Room (on occupied only) ===")
    print("Accuracy:", accuracy_score(yr_te, room_pred))
    print(classification_report(yr_te, room_pred, digits=3))

    # save
    outdir.mkdir(parents=True, exist_ok=True)
    joblib.dump(occ_clf, outdir / "occ_classifier.joblib")
    joblib.dump(room_clf, outdir / "room_classifier.joblib")

    # save feature list for inference
    (outdir / "feature_columns.txt").write_text(
        "\n".join(list(X.columns)), encoding="utf-8"
    )

    # write inference helper
    (outdir / "inference.py").write_text(
        r"""
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
""",
        encoding="utf-8",
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--csv",
        nargs="+",
        required=True,
        help="Paths to CSVs (living+kitchen, sleeping, washitsu)",
    )
    ap.add_argument("--outdir", type=str, default="./model_out")
    args = ap.parse_args()
    raw, X, y_occ, y_room, cols = build_dataset(args.csv)
    outdir = Path(args.outdir)
    train_and_eval(X, y_occ, y_room, outdir)
    print(f"\nSaved models to: {outdir.resolve()}")


if __name__ == "__main__":
    main()
