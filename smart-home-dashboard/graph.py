import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from scipy import stats

# ==========================================
# 1. データの準備
# ==========================================
# マージ済みのデータを読み込みます
df = pd.read_csv("smart_home_merged_all.csv")
df["timestamp"] = pd.to_datetime(df["timestamp"])
df = df.sort_values("timestamp")

# 欠損値処理と移動平均（スムージング）
# センサーの微小なノイズを除去して、傾向を見やすくします
window_size = 5
df["living_co2_smooth"] = df["C0A80367-013001_co2"].rolling(window=window_size).mean()

# 上昇率（ppm/min）の計算
df["dt_min"] = df["timestamp"].diff().dt.total_seconds() / 60.0
df["living_co2_rate"] = df["living_co2_smooth"].diff() / df["dt_min"]

# ノイズ除去（極端な値を除外）
df = df[df["dt_min"] > 0.1]  # データ間隔が短すぎる場合を除外
df_clean = df.dropna(subset=["living_co2_rate", "Label_Living_Count"])

# 1人と2人のデータのみを抽出
target_df = df_clean[df_clean["Label_Living_Count"].isin([1, 2])].copy()
target_df["Label_Living_Count"] = target_df["Label_Living_Count"].astype(int)

# 上昇している局面（>0.5 ppm/min）のみに絞る（入室時などの特徴を見るため）
rising_df = target_df[target_df["living_co2_rate"] > 0.5].copy()

# ==========================================
# 2. グラフの描画
# ==========================================
fig = plt.figure(figsize=(12, 5))
plt.style.use("seaborn-v0_8-whitegrid")  # 論文向けの綺麗なスタイル

# --- 左側：箱ひげ図 (CO2濃度の絶対値) ---
ax1 = plt.subplot(1, 2, 1)
sns.boxplot(
    x="Label_Living_Count",
    y="C0A80367-013001_co2",
    data=target_df,
    palette="Set2",
    width=0.5,
    ax=ax1,
)
ax1.set_title("Living Room: CO2 Comparison", fontsize=14)
ax1.set_xlabel("Number of People", fontsize=12)
ax1.set_ylabel("CO2 Concentration (ppm)", fontsize=12)
ax1.grid(True, linestyle="--", alpha=0.7)

# --- 右側：正規分布付きヒストグラム (CO2上昇スピード) ---
ax2 = plt.subplot(1, 2, 2)

# 1人のデータ
data_1 = rising_df[rising_df["Label_Living_Count"] == 1]["living_co2_rate"]
sns.histplot(
    data_1, kde=True, stat="density", color="blue", label="1 Person", alpha=0.3, ax=ax2
)

# 2人のデータ
data_2 = rising_df[rising_df["Label_Living_Count"] == 2]["living_co2_rate"]
sns.histplot(
    data_2, kde=True, stat="density", color="red", label="2 People", alpha=0.3, ax=ax2
)

# 正規分布曲線のフィッティング線を追加
x_range = np.linspace(0, 40, 100)
# 1人
mu1, std1 = stats.norm.fit(data_1)
ax2.plot(x_range, stats.norm.pdf(x_range, mu1, std1), "b--", linewidth=2)
# 2人
mu2, std2 = stats.norm.fit(data_2)
ax2.plot(x_range, stats.norm.pdf(x_range, mu2, std2), "r--", linewidth=2)

ax2.set_title("Living Room: CO2 Rising Rate Distribution", fontsize=14)
ax2.set_xlabel("Rising Speed (ppm/min)", fontsize=12)
ax2.set_ylabel("Density", fontsize=12)
ax2.legend()
ax2.set_xlim(0, 30)  # 範囲は見やすいように調整

plt.tight_layout()
plt.show()

# 画像保存
# plt.savefig("co2_analysis_graph.png", dpi=300)
