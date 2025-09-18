#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
複数の部屋CSVを時刻で結合し、学習しやすい形に整形します。
- タイムスタンプ自動検出＆昇順ソート
- 1秒グリッドにリサンプリング（数値は平均・最大5秒まで前方補完）
- True/False / OPEN/CLOSED などを 0/1 に正規化
- 重複列名を「左優先の非NaNで合成」して1本に統合
- ラベル列:
    - room_label, room_label_std（Placeがあれば）
    - num_people（Number of People）
    - occupied_label（Occupied）
    - target_room（在室判定に便利な “最終的にどの部屋か”）
- 特徴量生成:
    - すべての数値列について 5s移動平均/15s移動標準偏差/直近差分 を付与
- 出力:
    - --out で指定した CSV（デフォルト: combined_ml_ready.csv）
    - 使う特徴量の列名JSON（--features_json）
使い方例はファイル末尾のコメントを参照。
"""

import argparse
import re
from pathlib import Path
import json
import numpy as np
import pandas as pd


# ---------------------- 基本ユーティリティ ----------------------
def find_ts_column(df: pd.DataFrame) -> str:
    """時刻っぽい列名を自動検出（先頭優先）"""
    for c in df.columns:
        if re.search(r"(time|timestamp|date)", c, re.I):
            return c
    raise ValueError("タイムスタンプ列が見つかりませんでした。")


def to_numeric_safe(s: pd.Series) -> pd.Series:
    """True/False, OPEN/CLOSED, '0'/'1', 数値文字列などを数値に寄せる"""
    if s.dtype == bool:
        return s.astype("float")

    if s.dtype == object:
        lower = s.astype(str).str.strip().str.lower()
        mapping = {
            "true": 1,
            "false": 0,
            "open": 0,
            "closed": 1,
            "nan": np.nan,
            "none": np.nan,
            "": np.nan,
        }
        mapped = lower.map(mapping)
        # ある程度マップできたらそれを採用
        if mapped.notna().sum() >= max(3, int(0.3 * len(s))):
            return mapped.astype("float")

    # 最後に to_numeric を試す
    return pd.to_numeric(s, errors="coerce")


def normalize_one_dataframe(df: pd.DataFrame, source_name: str) -> pd.DataFrame:
    """1つのCSVを正規化"""
    df = df.copy()

    # タイムスタンプ整形
    ts = find_ts_column(df)
    df[ts] = pd.to_datetime(df[ts], errors="coerce")
    df = df.dropna(subset=[ts]).sort_values(ts)
    df = df[~df[ts].duplicated(keep="first")].set_index(ts)

    # 不要なUnnamed列を落とす
    df = df.loc[:, ~df.columns.str.contains(r"^Unnamed", na=False)]

    # 文字列列は可能な範囲で数値化（0/1化含む）
    for c in df.columns:
        if df[c].dtype == object:
            converted = to_numeric_safe(df[c])
            # ある程度数値化できた列のみ置換
            if converted.notna().sum() >= max(3, int(0.1 * len(converted))):
                df[c] = converted

    # door という名前の列は、CLOSED=1, OPEN=0 の数値化 + open版を追加
    for c in list(df.columns):
        if c.lower() == "door" or re.search(r"\bdoor\b", c, re.I):
            df[c] = to_numeric_safe(df[c])
            if df[c].notna().any():
                df[c + "_open"] = 1 - df[c]

    # thermal-1 があれば数値化確実に
    if "thermal-1" in df.columns:
        df["thermal-1"] = pd.to_numeric(df["thermal-1"], errors="coerce")

    # ラベル系（あれば追加）
    if "Place" in df.columns:
        place = df["Place"].astype(str).str.strip()
        place = place.replace(
            {"nan": np.nan, "None": np.nan, "none": np.nan, "": np.nan}
        )
        df["room_label"] = place
        df["room_label_std"] = place.str.lower().str.replace(r"\s+", "_", regex=True)

    if "Number of People" in df.columns:
        df["num_people"] = pd.to_numeric(df["Number of People"], errors="coerce")

    if "Occupied" in df.columns:
        occ = df["Occupied"]
        if occ.dtype == object:
            occ = occ.astype(str).str.lower().map({"true": 1, "false": 0})
        df["occupied_label"] = pd.to_numeric(occ, errors="coerce")

    # 出所
    df["source_file"] = source_name
    return df


def resample_1s(df: pd.DataFrame, freq="1S") -> pd.DataFrame:
    """1秒グリッドに揃える。数値は平均、それ以外は直近値。数値は最大5秒前まで前方補完。"""
    num = df.select_dtypes(include=[np.number])
    other = df.drop(columns=num.columns, errors="ignore")

    num_rs = num.resample(freq).mean()
    other_rs = other.resample(freq).last()

    merged = pd.concat([num_rs, other_rs], axis=1)
    if not num.columns.empty:
        merged[num.columns] = merged[num.columns].ffill(limit=5)
    return merged


def coalesce_duplicate_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    同名列が複数存在する場合、左->右の順で非NaNを優先して1列に畳み込む。
    pandasは同名列を内部的に許すため、自前でまとめる。
    """
    groups = {}
    for i, c in enumerate(df.columns):
        groups.setdefault(c, []).append(i)

    out = pd.DataFrame(index=df.index)
    for c, idxs in groups.items():
        if len(idxs) == 1:
            out[c] = df.iloc[:, idxs[0]]
        else:
            tmp = df.iloc[:, idxs[0]].copy()
            for j in idxs[1:]:
                tmp = tmp.where(tmp.notna(), df.iloc[:, j])
            out[c] = tmp
    return out


# ---------------------- ラベル合成（どの部屋か） ----------------------
def infer_target_room(df: pd.DataFrame) -> pd.Series:
    """
    同一タイムスタンプにおいて「どの部屋が1か」を推定する。
    ヒューリスティック（優先順）:
      1) room_label が明示的に1種類だけある → その値
      2) occupied_label / thermal-1 / PIR系(0/1) を部屋ヒントと紐づけて
         ちょうど1部屋だけ「在室=1」ならその部屋
      3) 決まらなければ NaN
    ※ 部屋ヒントは列名・値から推測（例: 列名に "(sleeping)" や "washitsu" が含まれる等）
    """
    room_hint_cols = {}  # room_name -> list of Series(0/1)
    # 0/1 っぽい列を抽出
    bin_candidates = df.select_dtypes(include=[np.number]).columns.tolist()
    for c in bin_candidates:
        if df[c].dropna().isin([0, 1]).mean() > 0.8:
            name = c.lower()
            room = None
            # 列名から部屋っぽいキーワードを拾う（必要に応じて増やせます）
            if "sleep" in name:
                room = "sleeping"
            elif "washitsu" in name or "tatami" in name or "japanese" in name:
                room = "washitsu"
            elif "kitchen" in name:
                room = "kitchen"
            elif "living" in name:
                room = "living"
            # 未判別だが thermal-1 のような汎用在室指標は「washitsu」に寄せるケースが多い
            if room is None and ("thermal" in name):
                room = "washitsu"

            if room:
                room_hint_cols.setdefault(room, []).append(df[c])

    # 1) room_label が常に1種類ならそれを返す
    if "room_label_std" in df.columns:
        uniq = df["room_label_std"].dropna().unique()
        if len(uniq) == 1:
            return pd.Series(df["room_label_std"].iloc[0], index=df.index)

    # 2) ヒント統合: 部屋ごとに 0/1 をまとめる（いずれかが1なら1）
    room_score = {}
    for room, cols in room_hint_cols.items():
        if len(cols) == 1:
            room_score[room] = cols[0]
        else:
            s = cols[0].copy()
            for sr in cols[1:]:
                s = s.combine(sr, func=lambda a, b: float(max(a or 0, b or 0)))
            room_score[room] = s

    # 時刻ごとに「ちょうど1部屋だけ1」のときだけ確定
    target = pd.Series(index=df.index, dtype="object")
    if room_score:
        rooms = sorted(room_score.keys())
        M = pd.concat(room_score, axis=1)  # columns: room
        # しきい値は0.5超で1扱い（欠損は0）
        binM = (M.fillna(0) > 0.5).astype(int)
        # 1の部屋数
        cnt = binM.sum(axis=1)
        # ちょうど1つの行だけ確定
        idx = cnt == 1
        if idx.any():
            # argmax 的に部屋名を拾う
            target.loc[idx] = binM[idx].idxmax(axis=1)

    # 3) まだ空のところは room_label_std を埋める（可能なら）
    if "room_label_std" in df.columns:
        target = target.where(target.notna(), df["room_label_std"])

    return target


# ---------------------- 特徴量加工 ----------------------
def add_roll_features(
    df: pd.DataFrame, mean_secs=(5,), std_secs=(15,), diff_secs=(5,)
) -> pd.DataFrame:
    """
    数値列全体に移動特徴量を付与
    """
    out = df.copy()
    num_cols = out.select_dtypes(include=[np.number]).columns

    for w in mean_secs:
        out[[f"{c}__mean{w}s" for c in num_cols]] = (
            out[num_cols].rolling(f"{w}s").mean()
        )

    for w in std_secs:
        out[[f"{c}__std{w}s" for c in num_cols]] = out[num_cols].rolling(f"{w}s").std()

    for w in diff_secs:
        out[[f"{c}__diff{w}s" for c in num_cols]] = (
            out[num_cols] - out[num_cols].rolling(f"{w}s").mean()
        )

    return out


# ---------------------- メイン ----------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+", help="入力CSV（空白や括弧のあるパスもOK）")
    ap.add_argument("--out", default="combined_ml_ready.csv", help="出力CSV")
    ap.add_argument(
        "--features_json",
        default="feature_columns.json",
        help="数値特徴量の列名を書き出すJSON",
    )
    ap.add_argument("--resample", default="1S", help="リサンプリング間隔（例: 1S, 5S）")
    ap.add_argument(
        "--single_person_only",
        action="store_true",
        help="Number of People==1（または欠損）だけに絞る",
    )
    args = ap.parse_args()

    frames = []
    for p in args.inputs:
        src = Path(p).name
        try:
            df = pd.read_csv(p, low_memory=False)
        except UnicodeDecodeError:
            df = pd.read_csv(p, low_memory=False, encoding="utf-8-sig")

        df = normalize_one_dataframe(df, src)
        df = resample_1s(df, args.resample)
        frames.append(df)

    # 時系列で外部結合
    merged = pd.concat(frames, axis=1, join="outer").sort_index()

    # 同名列の畳み込み
    merged = coalesce_duplicate_columns(merged)

    # どの部屋か（ターゲット）を推定
    merged["target_room"] = infer_target_room(merged)

    # 学習向けに timestamp 列に戻す
    merged = merged.reset_index().rename(columns={"index": "timestamp"})

    # シングル人数のみ使用する場合
    if args.single_person_only and ("num_people" in merged.columns):
        mask = merged["num_people"].isna() | (merged["num_people"] == 1)
        merged = merged.loc[mask].copy()

    # 基本の数値特徴
    merged.set_index("timestamp", inplace=True)
    merged = add_roll_features(merged, mean_secs=(5,), std_secs=(15,), diff_secs=(5,))
    merged = merged.reset_index()

    # 使う特徴量の一覧（学習では基本的に数値列＋ rolling で付けた列を使う）
    feature_cols = sorted(
        c
        for c, dt in merged.dtypes.items()
        if (np.issubdtype(dt, np.number))
        and (c not in {"num_people"})  # num_peopleはフィルタ用
    )

    # 書き出し
    merged.to_csv(args.out, index=False)
    with open(args.features_json, "w", encoding="utf-8") as f:
        json.dump(feature_cols, f, ensure_ascii=False, indent=2)

    print(f"✓ wrote CSV: {args.out}  shape={merged.shape}")
    print(
        f"✓ wrote feature list JSON: {args.features_json}  (n_features={len(feature_cols)})"
    )
    # ターゲットの内訳
    if "target_room" in merged.columns:
        print("target_room counts:")
        print(merged["target_room"].value_counts(dropna=False).head(20))


if __name__ == "__main__":
    main()
