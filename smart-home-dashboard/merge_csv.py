import pandas as pd
import glob
import os


def merge_csv_files(input_pattern, output_file):
    """
    指定されたパターンのCSVファイルを全て読み込み、統合して保存する関数
    """
    # 1. ファイルの一覧を取得
    file_list = glob.glob(input_pattern)

    # 【重要】出力ファイル名がリストに含まれていたら除外する（無限ループ防止）
    if output_file in file_list:
        print(
            f"除外: 出力ファイルと同じ名前のため '{output_file}' を読み込み対象から外します。"
        )
        file_list.remove(output_file)

    if not file_list:
        print(f"エラー: '{input_pattern}' に一致するファイルが見つかりませんでした。")
        return

    # ファイル名でソート
    file_list.sort()

    print(f"{len(file_list)} 個のファイルを検出しました。")
    print("-" * 40)

    data_list = []

    # 2. 各ファイルを読み込む
    for file in file_list:
        try:
            # CSVを読み込む
            # low_memory=False を指定して警告を抑制
            df = pd.read_csv(file, low_memory=False)

            data_list.append(df)
            print(f"読み込み完了: {os.path.basename(file)} ({len(df):,} 行)")

        except Exception as e:
            print(f"読み込みエラー: {file} - {e}")

    if not data_list:
        print("統合できるデータがありませんでした。")
        return

    # 3. データを縦に結合
    print("-" * 40)
    print("データを結合しています...")
    merged_df = pd.concat(data_list, ignore_index=True)

    # 4. タイムスタンプ順にソート
    time_col = None
    for col in ["timestamp", "Datetime", "time", "Date"]:
        if col in merged_df.columns:
            time_col = col
            break

    if time_col:
        print(f"'{time_col}' カラムで時系列順に並べ替えています...")
        try:
            # 【重要】format='mixed' を指定して、'T'あり/なし等が混在しても自動判定させる
            merged_df[time_col] = pd.to_datetime(merged_df[time_col], format="mixed")

            # ソート
            merged_df = merged_df.sort_values(time_col)
        except Exception as e:
            print(f"警告: 日付変換に失敗しました ({e})。ソートせずに保存します。")
    else:
        print("注意: タイムスタンプ列が見つからないため、並べ替えずに保存します。")

    # 5. 保存
    merged_df.to_csv(output_file, index=False)

    print("=" * 40)
    print(f"統合完了！")
    print(f"保存ファイル名: {output_file}")
    print(f"合計データ数  : {len(merged_df):,} 行")
    if time_col:
        print(f"期間: {merged_df[time_col].min()} 〜 {merged_df[time_col].max()}")
    print("=" * 40)


# ==========================================
# 設定エリア
# ==========================================
input_pattern = "smart_home_*.csv"
output_file = "smart_home_merged_all.csv"

# ==========================================
# 実行
# ==========================================
if __name__ == "__main__":
    merge_csv_files(input_pattern, output_file)
