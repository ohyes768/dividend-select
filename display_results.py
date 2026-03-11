"""
股息率数据展示工具

用法:
    uv run python display_results.py
    uv run python display_results.py --top 20
    uv run python display_results.py --min-yield 5
"""
import argparse
from pathlib import Path

import pandas as pd


def parse_args():
    parser = argparse.ArgumentParser(description="股息率数据展示工具")
    parser.add_argument("--top", type=int, default=50, help="显示TOP N只股票(默认50)")
    parser.add_argument("--min-yield", type=float, default=0, help="最小股息率筛选(默认0)")
    parser.add_argument("--industry", type=str, default="", help="按申万一级行业筛选")
    return parser.parse_args()


def load_data() -> pd.DataFrame:
    """加载CSV数据"""
    data_file = Path(__file__).parent / "data" / "近3年股息率汇总.csv"
    if not data_file.exists():
        print(f"错误: 数据文件不存在 - {data_file}")
        return pd.DataFrame()

    df = pd.read_csv(data_file, encoding="utf-8-sig")
    return df


def display_header():
    """显示标题"""
    print("\n" + "=" * 90)
    print("                        A股高股息率股票分析报告")
    print("=" * 90)


def display_top_stocks(df: pd.DataFrame, top_n: int):
    """显示TOP N股票"""
    print(f"\n【近3年平均股息率 TOP{top_n}】")
    print("-" * 90)

    # 表头
    print(f"{'排名':<4} {'代码':<8} {'名称':<10} {'3年均值':>10} {'2025':>10} {'2024':>10} {'2023':>10} {'申万一级行业'}")
    print("-" * 90)

    for i, (_, row) in enumerate(df.head(top_n).iterrows(), 1):
        code = str(row.get("股票代码", ""))
        name = str(row.get("股票名称", ""))[:8]  # 截断名称
        y3 = row.get("3年平均股息率(%)", 0) or 0
        y2025 = row.get("2025年股息率(%)", 0) or 0
        y2024 = row.get("2024年股息率(%)", 0) or 0
        y2023 = row.get("2023年股息率(%)", 0) or 0
        industry = str(row.get("申万一级行业", ""))[:10]

        print(f"{i:<4} {code:<8} {name:<10} {y3:>9.2f}% {y2025:>9.2f}% {y2024:>9.2f}% {y2023:>9.2f}% {industry}")


def display_statistics(df: pd.DataFrame):
    """显示统计信息"""
    print("\n【统计信息】")
    print("-" * 90)

    # 获取有效的股息率数据
    yields = pd.to_numeric(df["3年平均股息率(%)"], errors="coerce").dropna()

    if len(yields) == 0:
        print("  无有效股息率数据")
        return

    print(f"  股票总数: {len(df)}")
    print(f"  股息率范围: {yields.min():.2f}% ~ {yields.max():.2f}%")
    print(f"  股息率中位数: {yields.median():.2f}%")
    print(f"  股息率均值: {yields.mean():.2f}%")

    # 分布
    print(f"\n  股息率分布:")
    print(f"    >= 8%:  {len(yields[yields >= 8])} 只")
    print(f"    >= 6%:  {len(yields[yields >= 6])} 只")
    print(f"    >= 5%:  {len(yields[yields >= 5])} 只")
    print(f"    >= 4%:  {len(yields[yields >= 4])} 只")


def display_industry_distribution(df: pd.DataFrame):
    """显示行业分布"""
    print("\n【申万一级行业分布】")
    print("-" * 90)

    industries = df["申万一级行业"].dropna()
    industries = industries[industries != ""]

    if len(industries) == 0:
        print("  无行业数据")
        return

    counts = industries.value_counts()
    print(f"  {'行业':<15} {'数量':>6} {'占比':>8}")
    print("  " + "-" * 35)
    for ind, cnt in counts.items():
        pct = cnt / len(df) * 100
        print(f"  {str(ind):<15} {cnt:>6} {pct:>7.1f}%")


def display_index_distribution(df: pd.DataFrame):
    """显示来源指数分布"""
    print("\n【来源指数分布】")
    print("-" * 90)

    indices = df["来源指数"].dropna()
    counts = indices.value_counts()

    for idx, cnt in counts.items():
        avg_yield = pd.to_numeric(df[df["来源指数"] == idx]["3年平均股息率(%)"], errors="coerce").mean()
        print(f"  {str(idx):<20} {cnt:>4} 只, 平均股息率: {avg_yield:>6.2f}%")


def display_stock_detail(df: pd.DataFrame, code: str):
    """显示单只股票详情"""
    row = df[df["股票代码"].astype(str) == code]
    if row.empty:
        print(f"未找到股票: {code}")
        return

    r = row.iloc[0]
    print("\n" + "=" * 60)
    print(f"  {r['股票代码']} {r['股票名称']}")
    print("=" * 60)
    print(f"  交易所: {r.get('交易所', '')}")
    print(f"  来源指数: {r.get('来源指数', '')}")
    print(f"  申万行业: {r.get('申万一级行业', '')} - {r.get('申万二级行业', '')} - {r.get('申万三级行业', '')}")
    print("-" * 60)
    print(f"  3年平均股息率: {r.get('3年平均股息率(%)', 'N/A')}%")
    print(f"  近3年平均股价: {r.get('近3年平均股价', 'N/A')}")
    print("-" * 60)
    print("  年度数据:")
    print(f"    2025: 股息率 {r.get('2025年股息率(%)', 'N/A')}%, 分红 {r.get('2025年分红(元/10股)', 'N/A')}元")
    print(f"    2024: 股息率 {r.get('2024年股息率(%)', 'N/A')}%, 分红 {r.get('2024年分红(元/10股)', 'N/A')}元")
    print(f"    2023: 股息率 {r.get('2023年股息率(%)', 'N/A')}%, 分红 {r.get('2023年分红(元/10股)', 'N/A')}元")


def main():
    args = parse_args()

    df = load_data()
    if df.empty:
        return

    # 筛选
    if args.min_yield > 0:
        df = df[pd.to_numeric(df["3年平均股息率(%)"], errors="coerce") >= args.min_yield]

    if args.industry:
        df = df[df["申万一级行业"].str.contains(args.industry, na=False)]

    # 按股息率排序
    df = df.sort_values("3年平均股息率(%)", ascending=False)

    # 显示
    display_header()
    display_top_stocks(df, args.top)
    display_statistics(df)
    display_industry_distribution(df)
    display_index_distribution(df)

    print("\n" + "=" * 90)
    print(f"  共 {len(df)} 只股票")
    print("=" * 90 + "\n")


if __name__ == "__main__":
    main()
