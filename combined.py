# combined.py
# CSV統合 → リサンプル → 重複列の安全な折り畳み → 特徴量生成 → ラベル作成

import argparse
import json
import os
from typing import List, Tuple, Dict

import numpy as np
import pandas as pd

# --------------------------
# 設定 / ユーティリティ
# --------------------------
TIME_COL_CANDIDATES = [
    "timestamp",
    "time",
    "datetime",
    "date",
    "ts",
    "Timestamp",
    "Time",
    "Datetime",
    "Date",
    "TS",
    "Unnamed: 0",
]

BOOL_PATTERNS_TRUE = {"true", "1", "on", "yes"}
BOOL_PATTERNS_FALSE = {"false", "0", "off", "no"}
DOOR_MAP = {"open": 0, "closed": 1}


def guess_room_from_filename(path: str) -> str:
    name = os.path.basename(path).lower()
    if "washitsu" in name or "和室" in name:
        return "washitsu"
    if "sleep" in name or "寝室" in name:
        return "sleeping_room"
    if "living" in name or "kitchen" in name or "リビング" in name:
        return "living"
    return "unknown"


def read_csv_any(path: str) -> pd.DataFrame:
    for enc in ["utf-8", "cp932", "shift-jis"]:
        try:
            return pd.read_csv(path, encoding=enc, low_memory=False)
        except Exception:
            continue
    return pd.read_csv(path, low_memory=False)


def find_timestamp_col(df: pd.DataFrame) -> str:
    for c in TIME_COL_CANDIDATES:
        if c in df.columns:
            return c
    # 最初に日時化できる列を探す
    for c in df.columns:
        s = pd.to_datetime(df[c], errors="coerce")
        if s.notna().mean() > 0.8:
            return c
    raise ValueError(
        "timestamp列が見つかりません。候補: " + ", ".join(TIME_COL_CANDIDATES)
    )


def parse_timestamp(s: pd.Series) -> pd.Series:
    dt = pd.to_datetime(s, errors="coerce")
    if dt.isna().mean() > 0.5:
        num = pd.to_numeric(s, errors="coerce")
        if num.notna().any():
            # ms か 秒かを簡易推定
            ms_dt = pd.to_datetime(num, unit="ms", errors="coerce")
            sec_dt = pd.to_datetime(num, unit="s", errors="coerce")
            dt = ms_dt if ms_dt.notna().mean() >= sec_dt.notna().mean() else sec_dt
    return dt


def normalize_boolish_series(col: pd.Series) -> pd.Series:
    """Seriesを0/1のInt64へ（open/closed, true/false 等にも対応）"""
    if pd.api.types.is_bool_dtype(col):
        return col.astype("Int64")

    if pd.api.types.is_numeric_dtype(col):
        return (
            pd.to_numeric(col, errors="coerce")
            .round()
            .clip(lower=0, upper=1)
            .astype("Int64")
        )

    s = col.astype(str).str.strip().str.lower()
    # door表現
    if s.isin(DOOR_MAP.keys()).mean() > 0.3:
        return s.map(DOOR_MAP).astype("Int64")

    mapped = s.map(
        {**{k: 1 for k in BOOL_PATTERNS_TRUE}, **{k: 0 for k in BOOL_PATTERNS_FALSE}}
    )
    mapped = mapped.fillna(s.map({"open": 0, "closed": 1}))
    return mapped.astype("Int64")


def normalize_boolish_column(col: pd.Series | pd.DataFrame) -> pd.Series | pd.DataFrame:
    """Series でも DataFrame でもOK（重複列対策）"""
    if isinstance(col, pd.DataFrame):
        return col.apply(normalize_boolish_series, axis=0)
    else:
        return normalize_boolish_series(col)


def prefixed_columns(df: pd.DataFrame, prefix: str, exclude: List[str]) -> pd.DataFrame:
    rename_map = {c: f"{prefix}__{c}" for c in df.columns if c not in exclude}
    return df.rename(columns=rename_map)


def resample_df(df: pd.DataFrame, freq: str = "1s") -> pd.DataFrame:
    """数値は平均、その他は最後の値"""
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("resample_df: index must be DatetimeIndex")
    num = df.select_dtypes(include=[np.number]).resample(freq).mean()
    other = df.drop(columns=num.columns, errors="ignore").resample(freq).last()
    out = pd.concat([num, other], axis=1)
    return out


def collapse_duplicate_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    同名列を安全に折り畳む：
      - 全列が数値/ブール ⇒ 行方向 max（ORに相当）
      - それ以外混在 ⇒ 行方向で「最後に観測された値」（bfill→1列目）
    返り値は列名が一意なDataFrame
    """
    cols = df.columns
    dup_names = cols[cols.duplicated()].unique()
    if len(dup_names) == 0:
        return df

    out = df.copy()
    for name in dup_names:
        same = out.loc[:, out.columns == name]
        # dtypeがすべて数値/ブール？
        all_numeric = all(
            pd.api.types.is_numeric_dtype(same[c])
            or pd.api.types.is_bool_dtype(same[c])
            for c in same.columns
        )
        if all_numeric:
            agg = same.apply(pd.to_numeric, errors="coerce").max(axis=1)
        else:
            # 右優先で非欠損を採用（各時刻で「最後に観測された値」）
            agg = same.bfill(axis=1).iloc[:, 0]
        out = out.drop(columns=same.columns).assign(**{name: agg})
    # 念のため一度並べ替え（元の順序は大事ではない）
    out = out.loc[:, ~out.columns.duplicated()]
    return out


def add_time_window_features(
    base: pd.DataFrame, windows=(5, 10, 30, 60)
) -> pd.DataFrame:
    """mean/std/diff(rolling-mean) を一括生成して断片化を回避"""
    num_cols = [c for c in base.columns if pd.api.types.is_numeric_dtype(base[c])]
    frames = [base]
    for w in windows:
        roll = base[num_cols].rolling(f"{w}s")
        frames.append(roll.mean().add_suffix(f"__mean{w}s"))
        frames.append(roll.std().add_suffix(f"__std{w}s"))
        frames.append(
            base[num_cols].diff().rolling(f"{w}s").mean().add_suffix(f"__diff{w}s")
        )
    return pd.concat(frames, axis=1)


def build_room_labels(
    df: pd.DataFrame,
    room_keys=("washitsu", "sleeping_room", "living"),
    single_person_only=True,
) -> Tuple[pd.DataFrame, pd.Series]:
    """
    各部屋の在室フラグ is_occ_<room> を作成（pir/occupied/thermal/detection/sound_trig/mic_occupied を OR）
    """
    occ_flags: Dict[str, pd.Series] = {}

    for rk in room_keys:
        # プレフィックス一致
        pat_cols = [c for c in df.columns if c.startswith(f"{rk}__")]
        # 在室に効きそうな列だけ
        cand = [
            c
            for c in pat_cols
            if any(
                k in c.lower()
                for k in [
                    "pir",
                    "occupied",
                    "thermal",
                    "detection",
                    "sound_trig",
                    "mic_occupied",
                ]
            )
            and "door" not in c.lower()
        ]
        if not cand:
            occ_flags[rk] = pd.Series(0, index=df.index, dtype="Int64")
            continue

        sub = df[cand].copy()
        # まず重複列があれば畳む（ここにも安全弁）
        sub = collapse_duplicate_columns(sub)

        # 0/1化
        for c in list(sub.columns):
            sub[c] = normalize_boolish_column(sub[c])

        # 平均リサンプル等で0-1中間がある場合は >0.5 をON
        flag = (sub.fillna(0) > 0.5).any(axis=1).astype("Int64")
        occ_flags[rk] = flag

    occ_df = pd.DataFrame(
        {f"is_occ_{rk}": occ_flags[rk] for rk in room_keys}, index=df.index
    )

    # target_room の決定
    sum_occ = occ_df.sum(axis=1)
    if single_person_only:
        target = pd.Series("unknown", index=df.index, dtype="object")
        one = sum_occ == 1
        for rk in room_keys:
            target = np.where(one & (occ_df[f"is_occ_{rk}"] == 1), rk, target)
        target = pd.Series(target, index=df.index, dtype="object")
    else:
        target = pd.Series("unknown", index=df.index, dtype="object")
        # 優先順（washitsu → sleeping → living）
        for rk in room_keys:
            target = np.where(
                (occ_df[f"is_occ_{rk}"] == 1) & (target == "unknown"), rk, target
            )
        target = pd.Series(target, index=df.index, dtype="object")

    return occ_df, target


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_index()
    df = df.ffill(limit=30).bfill(limit=2)
    # 数値の欠損は中央値で埋める
    for c in df.columns:
        if pd.api.types.is_numeric_dtype(df[c]) and df[c].isna().any():
            df[c] = df[c].fillna(df[c].median())
    return df


# --------------------------
# メインフロー
# --------------------------
def load_one(path: str, resample: str) -> Tuple[str, pd.DataFrame]:
    room_key = guess_room_from_filename(path)
    raw = read_csv_any(path)
    ts_col = find_timestamp_col(raw)
    dt = parse_timestamp(raw[ts_col])

    raw = raw.copy()
    raw.index = dt
    raw = raw.drop(columns=[ts_col], errors="ignore")
    raw = raw[~raw.index.isna()]
    raw = raw[~raw.index.duplicated(keep="last")]

    # 0/1 化できそうな列は事前に寄せる
    for c in list(raw.columns):
        if (
            any(
                k in str(c).lower()
                for k in [
                    "pir",
                    "occupied",
                    "door",
                    "thermal",
                    "detection",
                    "sound_trig",
                    "mic_occupied",
                ]
            )
            or raw[c].dtype == object
        ):
            try:
                raw[c] = normalize_boolish_column(raw[c])
            except Exception:
                pass

    # リサンプル
    rs = resample_df(raw, resample)

    # ファイル内の重複列もここで畳む
    rs = collapse_duplicate_columns(rs)

    # プレフィックス付与
    prefix = (
        room_key
        if room_key != "unknown"
        else os.path.splitext(os.path.basename(path))[0]
    )
    pref = prefixed_columns(rs, prefix, exclude=[])
    return room_key, pref


def run(
    inputs: List[str],
    out_path: str,
    feat_json: str,
    resample: str,
    single_person_only: bool,
):
    if not inputs:
        raise SystemExit("No input CSVs. e.g., python combined.py 'a.csv' 'b.csv' ...")

    frames = []
    for p in inputs:
        if not os.path.exists(p):
            print(f"⚠️  not found: {p}")
            continue
        rk, df = load_one(p, resample)
        frames.append(df)

    if not frames:
        raise SystemExit("読み込めるCSVがありませんでした。")

    # 時系列で外部結合 → ここでも重複列を畳む
    combined = pd.concat(frames, axis=1).sort_index()
    combined = collapse_duplicate_columns(combined)

    # 軽いクリーニング
    combined = clean_dataframe(combined)

    # 在室フラグ & target_room
    room_keys = ["washitsu", "sleeping_room", "living"]
    occ_df, target = build_room_labels(
        combined, room_keys=room_keys, single_person_only=single_person_only
    )
    combined = pd.concat([combined, occ_df], axis=1)
    combined["target_room"] = target.astype("object")

    # 特徴量（断片化回避）
    feature_base = add_time_window_features(combined, windows=(5, 10, 30, 60)).copy()

    # timestamp列を戻す
    feature_base = feature_base.reset_index().rename(columns={"index": "timestamp"})
    if "timestamp" not in feature_base.columns:
        feature_base.rename(
            columns={feature_base.columns[0]: "timestamp"}, inplace=True
        )

    # 特徴量リスト
    drop_cols = {"timestamp", "target_room"}
    feature_cols = [c for c in feature_base.columns if c not in drop_cols]

    # 保存
    feature_base.to_csv(out_path, index=False)
    with open(feat_json, "w", encoding="utf-8") as f:
        json.dump(feature_cols, f, ensure_ascii=False, indent=2)

    print(f"✓ wrote CSV: {out_path}  shape={feature_base.shape}")
    print(f"✓ wrote feature list JSON: {feat_json}  (n_features={len(feature_cols)})")
    print("target_room counts:")
    print(feature_base["target_room"].value_counts(dropna=False))


def main():
    parser = argparse.ArgumentParser(
        description="Merge CSVs → resample → features → labels (single-person)."
    )
    parser.add_argument("inputs", nargs="+", help="入力CSVパス（zshは()等をクォート）")
    parser.add_argument("--out", default="combined_ml_ready.csv", help="出力CSV")
    parser.add_argument(
        "--features_json", default="feature_columns.json", help="特徴量リストJSON"
    )
    parser.add_argument(
        "--resample", default="1s", help="リサンプル周期（例: 1s, 2s, 500ms）"
    )
    parser.add_argument(
        "--single_person_only",
        action="store_true",
        help="同時複数在室は unknown に落とす",
    )
    args = parser.parse_args()

    resample = str(args.resample).lower()
    run(args.inputs, args.out, args.features_json, resample, args.single_person_only)


if __name__ == "__main__":
    main()
