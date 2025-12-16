import os

# ========= 設定 =========
INPUT_FILE = "smart_home_snapshot.csv"  # 元のファイル名
OUTPUT_FILE = "smart_home_snapshot_clean.csv"  # 出力するファイル名
TARGET_DATE_STR = "2025-12-07"  # この日付以降を残す

# ========= 列定義 (174列) =========
PIR_DEVICES = [
    "PIR1",
    "PIR2",
    "PIR3",
    "PIR4",
    "PIR18",
    "PIR13",
    "PIR11",
    "PIR5",
    "PIR21",
    "PIR17",
    "PIR6",
    "PIR8",
    "PIR9",
    "PIR10",
    "PIR15",
    "PIR19",
    "PIR20",
    "PIR22",
    "PIR24",
]
M5_DEVICES = [
    "M5Stack1",
    "M5Stack2",
    "M5Stack3",
    "M5Stack4",
    "M5Stack5",
    "M5Stack6",
    "M5Stack8",
    "M5Stack10",
]
AIR_PURIFIERS = [
    "C0A8033B-013501",
    "C0A8033E-013501",
    "C0A80341-013501",
    "C0A8033D-013501",
    "C0A8033C-013501",
    "C0A80342-013501",
    "C0A80343-013501",
    "C0A80344-013501",
]
AIRCONS = ["C0A80367-013001", "C0A80368-013001"]


def build_columns():
    cols = ["timestamp"]
    for pir in PIR_DEVICES:
        cols.append(f"{pir}_motion")
    m5_metrics = ["co2", "temp", "hum", "pm2_5", "voc"]
    for m5 in M5_DEVICES:
        for m in m5_metrics:
            cols.append(f"{m5}_{m}")
    air_metrics = [
        "opStatus",
        "temp",
        "hum",
        "pm25",
        "gas",
        "illuminance",
        "dust",
        "power",
        "flow",
        "odor",
        "dirt",
    ]
    for ap in AIR_PURIFIERS:
        for m in air_metrics:
            cols.append(f"{ap}_{m}")
    ac_metrics = [
        "opStatus",
        "mode",
        "setTemp",
        "roomTemp",
        "hum",
        "outsideTemp",
        "blowTemp",
        "power",
        "totalPower",
        "flow",
        "human",
        "sunshine",
        "co2",
    ]
    for ac in AIRCONS:
        for m in ac_metrics:
            cols.append(f"{ac}_{m}")
    return cols


def main():
    if not os.path.exists(INPUT_FILE):
        print(f"エラー: {INPUT_FILE} が見つかりません。")
        return

    new_header = build_columns()
    expected_col_count = len(new_header)
    print(f"ターゲット列数: {expected_col_count} (これに合致するデータのみ残します)")

    output_lines = []
    output_lines.append(",".join(new_header) + "\n")

    with open(INPUT_FILE, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    kept_count = 0
    skipped_date = 0
    skipped_col = 0

    # デバッグ用：最初の数行の日付を確認
    print("--- データ確認 (最初の3行) ---")

    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue

        parts = line.split(",")

        # タイムスタンプのクリーニング (空白除去、引用符除去)
        raw_ts = parts[0]
        ts_clean = raw_ts.strip().strip('"').strip("'")

        # ヘッダー行はスキップ
        if "timestamp" in ts_clean.lower():
            continue

        # デバッグ表示
        if i < 3:
            print(f"行{i+1}: 生データ='{raw_ts}' -> 整形後='{ts_clean}'")

        # 日付判定 (文字列として比較)
        # "2025-12-07..." >= "2025-12-07" は True になる
        if ts_clean >= TARGET_DATE_STR:
            # 列数チェック
            if len(parts) == expected_col_count:
                output_lines.append(line + "\n")
                kept_count += 1
            else:
                skipped_col += 1
        else:
            skipped_date += 1

    # 結果保存
    if kept_count > 0:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.writelines(output_lines)
        print("\n" + "=" * 30)
        print(f"✅ 成功！ {OUTPUT_FILE} を作成しました。")
        print(f"抽出件数: {kept_count} 行")
        print(f"除外 (日付が古い): {skipped_date} 行")
        print(f"除外 (列数が不一致): {skipped_col} 行")
    else:
        print("\n" + "=" * 30)
        print("⚠️ 警告: データが1件も抽出されませんでした。")
        print(f"日付が古いと判定された数: {skipped_date}")
        print(
            "データが本当に12月7日以降を含んでいるか、ファイルの中身を確認してください。"
        )


if __name__ == "__main__":
    main()
