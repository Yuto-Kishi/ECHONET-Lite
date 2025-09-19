#!/usr/bin/env python3
import argparse
import os
import pandas as pd
import numpy as np
import joblib
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, accuracy_score


# ----------------------------
# Utility
# ----------------------------
def get_output_feature_names(fitted_pipe, input_cols=None):
    """
    Return the actual feature names produced by the preprocessor step in a fitted Pipeline.
    Works with ColumnTransformer + (Optionally) OneHot/Imputer, etc.
    """
    pre = fitted_pipe.named_steps["pre"]
    try:
        names = pre.get_feature_names_out(input_cols)
    except TypeError:
        names = pre.get_feature_names_out()
    return list(names)


# ----------------------------
# Data loading & feature eng
# ----------------------------
def load_and_concat_csv(files):
    dfs = []
    for f in files:
        df = pd.read_csv(f, low_memory=False)
        # unify timestamp column
        ts_col = None
        for c in ["timestamp", "time", "datetime", "created_at"]:
            if c in df.columns:
                ts_col = c
                break
        if ts_col is None:
            raise ValueError(f"No timestamp col in {f}")
        df[ts_col] = pd.to_datetime(df[ts_col], errors="coerce")
        df = df.dropna(subset=[ts_col]).sort_values(ts_col)
        dfs.append(df)
    return pd.concat(dfs, ignore_index=True)


def engineer_features(df):
    # assume timestamp col exists
    ts_col = None
    for c in ["timestamp", "time", "datetime", "created_at"]:
        if c in df.columns:
            ts_col = c
            break
    if ts_col is None:
        raise ValueError("No timestamp column found")

    df = df.set_index(ts_col).resample("1s").mean()  # resample to 1s
    # fill missing occupancy/room columns if needed
    df = df.reset_index()
    return df


def build_dataset(csv_files):
    raw = load_and_concat_csv(csv_files)
    raw = engineer_features(raw)

    # Example: occupancy label
    if "Occupied" in raw.columns:
        y_occ = raw["Occupied"].fillna(0).astype(int).values
    else:
        raise ValueError("No Occupied column found")

    # Example: room label
    if "Place" in raw.columns:
        y_room = raw["Place"].fillna("unknown").astype(str).values
    else:
        y_room = np.array(["unknown"] * len(raw))

    # Features = all numeric except labels
    drop_cols = ["Occupied", "Place", "Activity"]
    X = raw.drop(columns=[c for c in drop_cols if c in raw.columns], errors="ignore")

    # Drop all-NaN columns to prevent mismatch with transformer
    X = X.loc[:, X.notna().any(axis=0)]

    return raw, X, y_occ, y_room, X.columns.tolist()


# ----------------------------
# Training
# ----------------------------
def train_and_eval(raw, X, y_occ, y_room, outdir):
    os.makedirs(outdir, exist_ok=True)

    # ---- Occupancy model ----
    X_train, X_test, y_occ_train, y_occ_test = train_test_split(
        X, y_occ, test_size=0.3, shuffle=False
    )

    occ_pipe = Pipeline(
        [
            (
                "pre",
                ColumnTransformer(
                    [
                        (
                            "num",
                            Pipeline(
                                [
                                    ("imputer", SimpleImputer(strategy="median")),
                                    ("scaler", StandardScaler()),
                                ]
                            ),
                            X.columns.tolist(),
                        )
                    ],
                    remainder="drop",
                ),
            ),
            ("clf", RandomForestClassifier(n_estimators=100, random_state=42)),
        ]
    )

    occ_pipe.fit(X_train, y_occ_train)
    y_occ_pred = occ_pipe.predict(X_test)
    print("\n=== Occupancy (time split) ===")
    print("Accuracy:", accuracy_score(y_occ_test, y_occ_pred))
    print(classification_report(y_occ_test, y_occ_pred))

    # Save
    joblib.dump(occ_pipe, os.path.join(outdir, "occupancy_model.pkl"))

    # Feature importance
    occ_importances = occ_pipe.named_steps["clf"].feature_importances_
    occ_feat_names = get_output_feature_names(occ_pipe, input_cols=X_train.columns)
    min_len = min(len(occ_importances), len(occ_feat_names))
    fi_occ = pd.DataFrame(
        {"feature": occ_feat_names[:min_len], "importance": occ_importances[:min_len]}
    ).sort_values("importance", ascending=False)
    fi_occ.to_csv(os.path.join(outdir, "feature_importance_occupancy.csv"), index=False)

    # ---- Room model (on occupied only) ----
    mask_occ = y_occ == 1
    X_occ = X.loc[mask_occ]
    y_room_occ = y_room[mask_occ]

    if len(np.unique(y_room_occ)) > 1:
        X_train_occ, X_test_occ, y_room_train, y_room_test = train_test_split(
            X_occ, y_room_occ, test_size=0.3, shuffle=False
        )

        room_pipe = Pipeline(
            [
                (
                    "pre",
                    ColumnTransformer(
                        [
                            (
                                "num",
                                Pipeline(
                                    [
                                        ("imputer", SimpleImputer(strategy="median")),
                                        ("scaler", StandardScaler()),
                                    ]
                                ),
                                X_occ.columns.tolist(),
                            )
                        ],
                        remainder="drop",
                    ),
                ),
                ("clf", RandomForestClassifier(n_estimators=100, random_state=42)),
            ]
        )

        room_pipe.fit(X_train_occ, y_room_train)
        y_room_pred = room_pipe.predict(X_test_occ)
        print("\n=== Room (occupied only, time split) ===")
        print("Accuracy:", accuracy_score(y_room_test, y_room_pred))
        print(classification_report(y_room_test, y_room_pred))

        joblib.dump(room_pipe, os.path.join(outdir, "room_model.pkl"))

        room_importances = room_pipe.named_steps["clf"].feature_importances_
        room_feat_names = get_output_feature_names(
            room_pipe, input_cols=X_train_occ.columns
        )
        min_len = min(len(room_importances), len(room_feat_names))
        fi_room = pd.DataFrame(
            {
                "feature": room_feat_names[:min_len],
                "importance": room_importances[:min_len],
            }
        ).sort_values("importance", ascending=False)
        fi_room.to_csv(os.path.join(outdir, "feature_importance_room.csv"), index=False)
    else:
        print(
            "\n[WARN] Only one room label present in occupied samples. Skipping room model training."
        )


# ----------------------------
# Main
# ----------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", nargs="+", required=True, help="CSV files to load")
    parser.add_argument("--outdir", required=True, help="Output directory")
    args = parser.parse_args()

    raw, X, y_occ, y_room, cols = build_dataset(args.csv)
    train_and_eval(raw, X, y_occ, y_room, args.outdir)


if __name__ == "__main__":
    main()
