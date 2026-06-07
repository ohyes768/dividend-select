"""基于 2026-05 真实历史数据生成上周 (2026-05-29) snapshot。

数据源：
- data/2026-05/近3年股息率汇总_2026-05.csv  (含 2025年分红)
- data/2026-05/实时价格.csv                  (2026-05 各股票实时价)
- data/2026-05/M120均线_05-25-05-31.csv      (2026-05 M120)

公式：
- 实时股息率 = 2025年分红 / 2026-05 实时价 × 100
- M120比值  = 2026-05 实时价 / M120

输出：data/snapshots/rankings_2026-05-29.csv
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
from src.services.weekly_comparison import save_snapshot, _get_snapshot_path

DATA_DIR_2026_05 = Path(__file__).parent / "data" / "2026-05"
prev_date = "2026-05-29"

# === 读取 2026-05 真实数据 ===
df = pd.read_csv(DATA_DIR_2026_05 / "近3年股息率汇总_2026-05.csv", dtype={"股票代码": str})
df["股票代码"] = df["股票代码"].str.zfill(6)
print(f"读取 2026-05 股息率汇总: {len(df)} 只股票")

price_df = pd.read_csv(DATA_DIR_2026_05 / "实时价格.csv", dtype={"股票代码": str})
price_df["股票代码"] = price_df["股票代码"].str.zfill(6)
# 同一只股票取最新一条（或最后一条）
price_map = {}
for _, r in price_df.iterrows():
    price_map[r["股票代码"]] = float(r["实时价格"]) if pd.notna(r.get("实时价格")) else None
print(f"读取 2026-05 实时价格: {len(price_map)} 只")

m120_df = pd.read_csv(DATA_DIR_2026_05 / "M120均线_05-25-05-31.csv", dtype={"股票代码": str})
m120_df["股票代码"] = m120_df["股票代码"].str.zfill(6)
m120_map = {}
for _, r in m120_df.iterrows():
    m120_map[r["股票代码"]] = float(r["M120"]) if pd.notna(r.get("M120")) else None
print(f"读取 2026-05 M120: {len(m120_map)} 只")

# === 计算 2026-05-29 实时股息率（真实数据） ===
yield_realtime_map = {}
for _, r in df.iterrows():
    code = r["股票代码"]
    div = r.get("2025年分红(元/股)")
    price = price_map.get(code)
    if pd.notna(div) and price and price > 0:
        yield_realtime_map[code] = round(float(div) / price * 100, 2)
df["_yield_realtime"] = df["股票代码"].map(yield_realtime_map)

# === 排序得到 TOP10 ===
df_sorted = df.sort_values("_yield_realtime", ascending=False, na_position="last")

# === 构建 top_curr（上周 TOP10） ===
top_curr_prev = []
for rank, (_, row) in enumerate(df_sorted.head(10).iterrows(), 1):
    code = row["股票代码"]
    name = str(row["股票名称"])
    price = price_map.get(code)
    m120 = m120_map.get(code)
    ratio = round(price / m120, 4) if (price and m120) else None
    top_curr_prev.append({
        "rank": rank,
        "name": name,
        "yield_curr": float(row["_yield_realtime"]) if pd.notna(row.get("_yield_realtime")) else None,
        "yield_3y_avg": float(row.get("3年平均股息率(%)")) if pd.notna(row.get("3年平均股息率(%)")) else None,
        "ratio": ratio,
    })

# === 构建 top_3y_prev（上周近3年均值TOP10） ===
df_3y_sorted = df.sort_values("3年平均股息率(%)", ascending=False, na_position="last")
top_3y_prev = []
for rank, (_, row) in enumerate(df_3y_sorted.head(10).iterrows(), 1):
    code = row["股票代码"]
    name = str(row["股票名称"])
    top_3y_prev.append({
        "rank": rank,
        "name": name,
        "yield_3y_avg": float(row.get("3年平均股息率(%)")) if pd.notna(row.get("3年平均股息率(%)")) else None,
    })

# === 构建全量 ratio_map / full_yield_map / full_3y_map（所有股票，用于存档）===
ratio_map = {}
full_yield_map = {}
full_3y_map = {}
for _, r in df.iterrows():
    code = r["股票代码"]
    name = str(r["股票名称"])
    price = price_map.get(code)
    m120 = m120_map.get(code)
    if price and m120:
        ratio_map[name] = round(price / m120, 4)
    if code in yield_realtime_map:
        full_yield_map[name] = yield_realtime_map[code]
    avg_3y = r.get("3年平均股息率(%)")
    if pd.notna(avg_3y):
        full_3y_map[name] = float(avg_3y)

# === 写 snapshot ===
save_snapshot(top_curr_prev, top_3y_prev, prev_date, ratio_map,
              full_yield_map=full_yield_map, full_3y_map=full_3y_map)

print(f"\n已生成上周 snapshot: {_get_snapshot_path(prev_date)}")
print(f"\n上周 ({prev_date}) 实时股息率 TOP10:")
for r in top_curr_prev:
    print(f"  #{r['rank']:2d} {r['name']:8s}  yield={r['yield_curr']}%  ratio={r['ratio']}")
print(f"\nradio_map 共 {len(ratio_map)} 只股票")