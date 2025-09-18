#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Train a single-person room presence classifier (和室 / リビング / 寝室 など) from a 1Hz snapshot CSV.

Usage (examples):
  # ラベル分布だけ確認（学習はしない）
  python train_room_model.py \
    --csv combined_ml_ready.csv \
    --label-config label_config.json \
    --ts-col timestamp \
    --label-report-only

  # 学習して保存
  python train_room_model.py \
    --csv combined_ml_ready.csv \
    --label-config label_config.json \
    --outdir model_out \
    --ts-col timestamp \
    --pir-window-sec 5 \
    --sticky-after-sec 10

Outputs into outdir/:
  - room_presence_model.pkl              (sklearn Pipeline + LabelEncoder + metadata)
  - room_presence_features.json          (list of feature column names used at train)
  - room_presence_meta.json              (meta: ts_col, label columns used, class names, args)
  - room_presence_feature_importances.csv
  - metrics.txt                          (classification report + confusion matrix)

label_config.json (例):
{
  "none_label": "unknown",
  "resolve_multi": "score",               // "score" | "priority" | "drop" | "first"
  "priority": ["sleeping_room","washitsu","living"],
  "label_rules": {
    "sleeping_room": { "any_true": ["sleeping_room__pir2", "sleeping_room__pir_http_1921682121000701", "sleeping_room__pir_http_1921682121000702"] },
    "washitsu":      { "any_true": ["washitsu__pir2", "washitsu__pir_http_0701", "washitsu__pir_http_0702"] },
    "living":        { "any_true": ["living__pir2","living__pir_http_1921682115000701","living__pir_http_1921682115000702",
                                    "living__pir_http_1921682114000701","living__pir_http_1921682114000702",
                                    "living__pir_http_1921682113000701","living__pir_http_1921682113000702"] }
  },
  "co2_columns": {
    "sleeping_room": ["sleeping_room__co2"],
    "washitsu":      ["washitsu__co2"],
    "living":        ["living__co2"]
  },
  // ここは CLI 引数が無ければ fallback として使われます
  "pir_window_sec": 10,
  "sticky_after_sec": 30,
  "co2_window_sec": 120,
  "co2_rise_ppm_per_min": 20,
  "co2_sticky_sec": 90
}
"""

import argparse, json, os, hashlib, warnings, sys
from dataclasses import dataclass, asdict
import numpy as np
import pandas as pd

from sklearn.preprocessing import LabelEncoder
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
import joblib

warnings.filterwarnings("ignore", category=UserWarning)


# ----------------------- utils -----------------------
def _to_bool(x):
    """Return None/True/False from various representations."""
    if pd.isna(x):
        return None
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, (int, float, np.integer, np.floating)):
        # treat 0 as False, otherwise True
        return bool(int(x != 0))
    if isinstance(x, str):
        s = x.strip().lower()
        if s in ("true", "t", "yes", "y", "on", "1"):
            return True
        if s in ("false", "f", "no", "n", "off", "0"):
            return False
        if s in ("open",):  # door open -> False(=無人)扱い
            return False
        if s in ("closed",):  # door closed -> True(=在)扱い
            return True
    return None


def _object_to_numeric(series: pd.Series) -> pd.Series:
    """Map common object/string sensor states to numeric."""
    if series.dtype == object:
        s = series.copy()
        # door states
        mapping = {"OPEN": 0, "open": 0, "CLOSED": 1, "closed": 1}
        s = s.map(mapping).where(~s.isna(), s)
        # booleans
        s = s.map(
            lambda v: (
                1 if _to_bool(v) is True else (0 if _to_bool(v) is False else np.nan)
            )
        )
        try:
            return s.astype(float)
        except:
            return pd.to_numeric(series, errors="coerce")
    if series.dtype == bool:
        return series.astype(float)
    return series


def _ensure_datetime(df: pd.DataFrame, ts_col: str) -> pd.DataFrame:
    if ts_col not in df.columns:
        raise ValueError(
            f"Timestamp column '{ts_col}' not found in CSV. Available: {list(df.columns)[:10]}..."
        )
    df = df.copy()
    df[ts_col] = pd.to_datetime(df[ts_col], errors="coerce")
    df = df.dropna(subset=[ts_col]).sort_values(ts_col).reset_index(drop=True)
    return df


def _sticky_from_bool(flag: pd.Series, sticky_after_sec: int) -> pd.Series:
    """Trueが出た後、sticky_after_sec 秒 True を保持（1Hz前提）。"""
    base = flag.fillna(False).astype(bool).values
    out = np.zeros(len(base), dtype=bool)
    cnt = 0
    for i, v in enumerate(base):
        if v:
            cnt = sticky_after_sec
            out[i] = True
        else:
            if cnt > 0:
                out[i] = True
                cnt -= 1
            else:
                out[i] = False
    return pd.Series(out, index=flag.index)


# -------------------- label helpers -------------------
def _pir_any_true(
    df: pd.DataFrame, cols: list, window_sec: int, sticky_after_sec: int
) -> pd.Series:
    """PIR群の直近 window_sec 秒に 1 つでも反応があれば True、さらに sticky を適用。"""
    if not cols:
        return pd.Series(False, index=df.index)
    mats = []
    for c in cols:
        if c in df.columns:
            s = df[c]
            if s.dtype == object:
                s = s.map(lambda v: 1.0 if _to_bool(v) is True else 0.0)
            else:
                s = (s.fillna(0) != 0).astype(float)
            mats.append(s.rolling(window=window_sec, min_periods=1).max())
        else:
            mats.append(pd.Series(0.0, index=df.index))
    any_true = pd.concat(mats, axis=1).max(axis=1) > 0.0
    return _sticky_from_bool(any_true, sticky_after_sec)


def _pir_score(df: pd.DataFrame, cols: list, window_sec: int) -> pd.Series:
    """
    複数 PIR 列の「直近 window_sec 秒の平均反応（0..1）」を部屋のスコアとして返す。
    列が無い場合は 0。
    """
    if not cols:
        return pd.Series(0.0, index=df.index)
    series_list = []
    for c in cols:
        if c in df.columns:
            s = df[c]
            if s.dtype == object:
                s = s.map(lambda v: 1.0 if _to_bool(v) is True else 0.0)
            else:
                s = (s.fillna(0) != 0).astype(float)
            series_list.append(s.rolling(window=window_sec, min_periods=1).mean())
        else:
            series_list.append(pd.Series(0.0, index=df.index))
    return pd.concat(series_list, axis=1).max(axis=1).fillna(0.0)


def _co2_support(
    df: pd.DataFrame,
    ts_col: str,
    co2_cols: list,
    window_sec: int,
    rise_ppm_per_min: float,
    sticky_sec: int,
) -> pd.Series:
    """
    CO2 の上昇検知（直近 window_sec 秒で rise_ppm_per_min * (window_sec/60) 以上上昇）で True。
    その後 sticky_sec 秒キープ。
    """
    if not co2_cols:
        return pd.Series(False, index=df.index)
    cols_present = [c for c in co2_cols if c in df.columns]
    if not cols_present:
        return pd.Series(False, index=df.index)

    co2 = df[cols_present].apply(pd.to_numeric, errors="coerce").mean(axis=1)
    smooth = co2.rolling(window=window_sec, min_periods=1).mean()
    # 1Hz前提：window_sec 秒前との差で評価
    rise_needed = rise_ppm_per_min * (window_sec / 60.0)
    shifted = smooth.shift(window_sec)
    rise = smooth - shifted
    flag = (rise >= rise_needed).fillna(False)
    return _sticky_from_bool(flag, sticky_sec)


# ------------------- label building -------------------
def build_labels(df: pd.DataFrame, cfg: dict, ts_col_cli: str) -> (pd.Series, set):
    """
    ラベル Series と、ラベル生成に使った列セット（リーケージ防止用）を返す。
    resolve_multi:
      - "first"  : 定義順優先
      - "drop"   : 多重ヒット行は捨てる
      - "score"  : PIRスコアが最大の部屋を選ぶ（推奨）
      - "priority": cfg["priority"] の順を優先
    """
    rooms_cfg = cfg.get("label_rules", {})
    rooms = list(rooms_cfg.keys())
    none_label = cfg.get("none_label", "unknown")
    resolve_multi = cfg.get("resolve_multi", "score")
    if cfg.get("drop_if_multi_true", False):
        resolve_multi = "drop"
    ts_col = cfg.get("ts_col", ts_col_cli)

    # パラメータ（config 優先, なければ CLI で上書きされる想定）
    pir_window_sec = int(cfg.get("pir_window_sec", 10))
    sticky_after_sec = int(cfg.get("sticky_after_sec", 30))
    co2_window_sec = int(cfg.get("co2_window_sec", 120))
    co2_rise_ppm = float(cfg.get("co2_rise_ppm_per_min", 20))
    co2_sticky_sec = int(cfg.get("co2_sticky_sec", 90))

    used_cols = set()
    room_flags = {}
    room_scores = {}

    for room, rule in rooms_cfg.items():
        pir_cols = list(rule.get("any_true", []))
        used_cols.update(pir_cols)

        # PIR any_true + sticky (二値フラグ)
        flag = _pir_any_true(df, pir_cols, pir_window_sec, sticky_after_sec)

        # PIR score（タイブレーク用）
        score = _pir_score(df, pir_cols, pir_window_sec)

        # CO2 補助（任意）
        co2_cols_room = cfg.get("co2_columns", {}).get(room, [])
        if co2_cols_room:
            used_cols.update(co2_cols_room)
            co2_flag = _co2_support(
                df, ts_col, co2_cols_room, co2_window_sec, co2_rise_ppm, co2_sticky_sec
            )
            flag = flag | co2_flag
            # 必要ならスコアに加点（例: score += co2_flag.astype(float)*0.2）
        room_flags[room] = flag.fillna(False).astype(bool)
        room_scores[room] = score.fillna(0.0).astype(float)

    # 行ごとにラベル決定
    labels = []
    rooms_order = list(room_flags.keys())
    priority = cfg.get("priority", rooms_order)

    for i in df.index:
        true_rooms = [r for r in rooms_order if bool(room_flags[r].loc[i])]
        if len(true_rooms) == 1:
            labels.append(true_rooms[0])
        elif len(true_rooms) == 0:
            labels.append(none_label)
        else:
            if resolve_multi == "drop":
                labels.append(None)
            elif resolve_multi == "priority":
                # priority リスト上位を選ぶ
                ordered = [r for r in priority if r in true_rooms]
                labels.append(ordered[0] if ordered else true_rooms[0])
            elif resolve_multi == "score":
                # PIRスコア最大を選ぶ
                best = max(true_rooms, key=lambda r: room_scores[r].loc[i])
                labels.append(best)
            else:  # "first"
                labels.append(true_rooms[0])

    y = pd.Series(labels, index=df.index, name="__label")
    return y, used_cols


# ---------------- feature engineering -----------------
def add_derived_features(df_num: pd.DataFrame, windows=(5, 15)) -> pd.DataFrame:
    """
    追加の派生特徴を効率的に生成（断片化回避のため dict -> concat 一括）。
    """
    out_parts = {}

    # 1-step difference
    for c in df_num.columns:
        out_parts[f"{c}__diff1"] = df_num[c].diff(1)

    # rolling stats
    for w in windows:
        roll = df_num.rolling(window=w, min_periods=1)
        mean_df = roll.mean().add_suffix(f"__r{w}m")
        std_df = roll.std().add_suffix(f"__r{w}s")
        out_parts.update(mean_df.to_dict("series"))
        out_parts.update(std_df.to_dict("series"))

    out = pd.concat([df_num] + [pd.DataFrame(out_parts)], axis=1)
    return out


def make_feature_table(
    df: pd.DataFrame, ts_col: str, label_used_cols: set, add_extra=False
) -> (pd.DataFrame, list):
    """
    特徴量テーブルを作成。元CSVに既に多数の特徴量がある前提で、
    - ts_col と ラベル生成に使った列を除去（リーケージ防止）
    - 数値列のみ採用
    - 必要なら最小限の派生特徴を追加
    """
    df_num = df.drop(columns=[ts_col], errors="ignore").copy()

    for c in df_num.columns:
        df_num[c] = _object_to_numeric(df_num[c])

    # remove columns fully NaN
    df_num = df_num.dropna(axis=1, how="all")

    # Avoid label leakage: drop columns used to create labels
    drop_cols = [c for c in label_used_cols if c in df_num.columns]
    X_base = df_num.drop(columns=drop_cols, errors="ignore")

    # keep only numeric
    X_base = X_base.select_dtypes(include=[np.number]).copy()

    if add_extra:
        X = add_derived_features(X_base, windows=(5, 15))
    else:
        X = X_base

    X = X.replace([np.inf, -np.inf], np.nan)
    return X, list(X.columns)


# ---------------------- main train ---------------------
@dataclass
class Meta:
    ts_col: str
    label_columns_used: list
    class_names: list
    args: dict
    feature_hash: str


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="Integrated 1Hz snapshot CSV path")
    ap.add_argument("--label-config", required=True, help="JSON with label rules")
    ap.add_argument(
        "--outdir", default=None, help="Output directory (label-report-only なら不要)"
    )
    ap.add_argument("--ts-col", default="timestamp")
    ap.add_argument(
        "--test-ratio",
        type=float,
        default=0.3,
        help="Tail ratio for test set (time-ordered split)",
    )

    # ラベル生成パラメータ（config になければこの値が使われる）
    ap.add_argument("--pir-window-sec", type=int, default=None)
    ap.add_argument("--sticky-after-sec", type=int, default=None)
    ap.add_argument("--co2-window-sec", type=int, default=None)
    ap.add_argument("--co2-rise-ppm-per-min", type=float, default=None)
    ap.add_argument("--co2-sticky-sec", type=int, default=None)

    # 学習パラメータ
    ap.add_argument("--n-est", type=int, default=300)
    ap.add_argument("--min-leaf", type=int, default=3)
    ap.add_argument(
        "--no-extra-derived",
        action="store_true",
        help="追加の派生特徴を作らない（デフォルトは作らないので、このフラグは互換用）",
    )
    ap.add_argument(
        "--label-report-only", action="store_true", help="ラベル分布のみ出力して終了"
    )

    args = ap.parse_args()

    # load
    df = pd.read_csv(args.csv, low_memory=False)
    df = _ensure_datetime(df, args.ts_col)

    with open(args.label_config, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # CLI で上書き（指定がある項目のみ）
    if args.pir_window_sec is not None:
        cfg["pir_window_sec"] = int(args.pir_window_sec)
    if args.sticky_after_sec is not None:
        cfg["sticky_after_sec"] = int(args.sticky_after_sec)
    if args.co2_window_sec is not None:
        cfg["co2_window_sec"] = int(args.co2_window_sec)
    if args.co2_rise_ppm_per_min is not None:
        cfg["co2_rise_ppm_per_min"] = float(args.co2_rise_ppm_per_min)
    if args.co2_sticky_sec is not None:
        cfg["co2_sticky_sec"] = int(args.co2_sticky_sec)

    # build labels
    y, used_cols = build_labels(df, cfg, args.ts_col)
    df["__label"] = y

    # レポート
    dist = df["__label"].value_counts(dropna=False)
    print("\nLabel distribution:\n", dist)

    # raw any_true positives (参考)
    for room, rule in cfg.get("label_rules", {}).items():
        cols = [c for c in rule.get("any_true", []) if c in df.columns]
        if cols:
            raw_pos = (df[cols].fillna(0).values != 0).any(axis=1).sum()
        else:
            raw_pos = 0
        print(f"{room} positives (raw any_true): {int(raw_pos)}")

    if args.label_report_only:
        print("⏹  label-report-only: training skipped.")
        return

    if args.outdir is None:
        print("ERROR: --outdir is required when training.", file=sys.stderr)
        sys.exit(2)

    os.makedirs(args.outdir, exist_ok=True)

    # drop rows with None labels
    df = df[~df["__label"].isna()].reset_index(drop=True)
    if df.empty:
        print(
            "ERROR: No labeled rows after filtering. Adjust label rules / parameters.",
            file=sys.stderr,
        )
        sys.exit(1)

    y = df["__label"].astype(str)

    # features
    X_all, feat_cols = make_feature_table(
        df.drop(columns=["__label"]),
        args.ts_col,
        used_cols,
        add_extra=(not args.no_extra_derived)
        and False,  # 既定は追加生成しない（CSVに十分ある想定）
    )

    # align
    X_all, y = X_all.loc[y.index], y.values

    # guard: 最低2クラス必要
    if len(pd.unique(y)) < 2:
        print(
            "⚠️ Only a single class found after labeling. Training is not meaningful; abort.",
            file=sys.stderr,
        )
        # それでも保存したいならここで早期保存処理を書く
        sys.exit(1)

    # time-ordered split
    n = len(X_all)
    split_idx = int(n * (1 - args.test_ratio))
    if split_idx <= 0 or split_idx >= n:
        split_idx = max(1, n - max(1, int(0.3 * n)))
    X_train, X_test = X_all.iloc[:split_idx], X_all.iloc[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]

    # model
    le = LabelEncoder()
    y_train_enc = le.fit_transform(y_train)
    y_test_enc = le.transform(y_test)

    rf = RandomForestClassifier(
        n_estimators=args.n_est,
        min_samples_leaf=args.min_leaf,
        class_weight="balanced_subsample",
        random_state=42,
        n_jobs=-1,
    )

    pipe = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("clf", rf),
        ]
    )
    pipe.fit(X_train, y_train_enc)

    # eval
    y_pred = pipe.predict(X_test)
    rep = classification_report(y_test_enc, y_pred, target_names=list(le.classes_))
    cm = confusion_matrix(y_test_enc, y_pred)

    # save metrics
    with open(os.path.join(args.outdir, "metrics.txt"), "w", encoding="utf-8") as f:
        f.write(rep + "\n\nConfusion matrix (rows=true, cols=pred):\n")
        f.write(pd.DataFrame(cm, index=le.classes_, columns=le.classes_).to_string())

    # feature importances
    imp = pipe.named_steps["clf"].feature_importances_
    imp_df = pd.DataFrame({"feature": feat_cols, "importance": imp}).sort_values(
        "importance", ascending=False
    )
    imp_df.to_csv(
        os.path.join(args.outdir, "room_presence_feature_importances.csv"), index=False
    )

    # save model bundle
    meta = Meta(
        ts_col=args.ts_col,
        label_columns_used=sorted(list(used_cols)),
        class_names=list(le.classes_),
        args=vars(args),
        feature_hash=hashlib.sha256((",".join(feat_cols)).encode("utf-8")).hexdigest(),
    )

    joblib.dump(
        {
            "pipeline": pipe,
            "label_encoder": le,
            "feature_cols": feat_cols,
            "meta": asdict(meta),
        },
        os.path.join(args.outdir, "room_presence_model.pkl"),
    )

    # aux jsons
    with open(
        os.path.join(args.outdir, "room_presence_features.json"), "w", encoding="utf-8"
    ) as f:
        json.dump(feat_cols, f, ensure_ascii=False, indent=2)
    with open(
        os.path.join(args.outdir, "room_presence_meta.json"), "w", encoding="utf-8"
    ) as f:
        json.dump(asdict(meta), f, ensure_ascii=False, indent=2)

    print("✅ Done. Classes:", meta.class_names)
    print("Saved to:", os.path.abspath(args.outdir))


if __name__ == "__main__":
    main()
