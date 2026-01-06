import pandas as pd
import glob
import os


def merge_csv_files(input_pattern, output_file):
    """
    指定されたパターンのCSVファイルを全て読み込み、統合して保存する関数
    """
    # 1. ファイルの一覧を取得（ワイルドカード指定）
    file_list = glob.glob(input_pattern)

    if not file_list:
        print(f"エラー: '{input_pattern}' に一致するファイルが見つかりませんでした。")
        return

    # ファイル名でソート（日付順に読み込むため）
    file_list.sort()

    print(f"{len(file_list)} 個のファイルを検出しました。")
    print("-" * 40)

    data_list = []

    # 2. 各ファイルを読み込む
    for file in file_list:
        try:
            # CSVを読み込む
            df = pd.read_csv(file)

            # データフレームのリストに追加
            data_list.append(df)
            print(f"読み込み完了: {os.path.basename(file)} ({len(df):,} 行)")

        except Exception as e:
            print(f"読み込みエラー: {file} - {e}")

    if not data_list:
        print("統合できるデータがありませんでした。")
        return

    # 3. データを縦に結合（concat）
    print("-" * 40)
    print("データを結合しています...")
    merged_df = pd.concat(data_list, ignore_index=True)

    # 4. タイムスタンプ順にソート（重要）
    # 'timestamp' または 'Datetime' というカラムがあれば日付として処理
    time_col = None
    for col in ["timestamp", "Datetime", "time", "Date"]:
        if col in merged_df.columns:
            time_col = col
            break

    if time_col:
        print(f"'{time_col}' カラムで時系列順に並べ替えています...")
        # 日付型に変換
        merged_df[time_col] = pd.to_datetime(merged_df[time_col])
        # ソート
        merged_df = merged_df.sort_values(time_col)
    else:
        print("注意: タイムスタンプ列が見つからないため、並べ替えずに保存します。")

    # 5. 統合したデータをCSVとして保存
    merged_df.to_csv(output_file, index=False)

    print("=" * 40)
    print(f"統合完了！")
    print(f"保存ファイル名: {output_file}")
    print(f"合計データ数  : {len(merged_df):,} 行")
    print("=" * 40)


# ==========================================
# 設定エリア
# ==========================================

# 1. 読み込みたいファイルのパターン
# "*" は「あらゆる文字」という意味です。
# 例: "data/*.csv" ならdataフォルダ内の全CSV
input_pattern = "smart_home_*.csv"

# 2. 出力するファイル名
output_file = "smart_home_merged_all.csv"

# ==========================================
# プログラム実行
# ==========================================
if __name__ == "__main__":
    merge_csv_files(input_pattern, output_file)
