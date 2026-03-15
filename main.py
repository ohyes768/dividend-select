"""
A股高股息率TOP50查询工具 - 主程序入口

用法:
    uv run python main.py                    # 获取最新持仓数据，跳过板块映射更新（默认）
    uv run python main.py --use-local        # 使用本地已有数据（跳过API获取）
    uv run python main.py --update-board     # 获取最新持仓数据 + 更新板块映射
    uv run python main.py --limit 10         # 限制处理10只股票（测试用）
    uv run python main.py --use-local --limit 10

数据文件说明:
    - 所有CSV文件按月保存到 data/YYYY-MM/ 目录
    - 移动文件：红利指数持仓汇总.csv、股票分红次数汇总.csv、个股板块映射.csv、M120数据.csv、PE数据.csv、近3年股息率汇总.csv
"""
import argparse
from datetime import datetime

import pandas as pd

from src.data import IndexHoldingsFetcher, BoardInfoLoader, BoardMappingFetcher
from src.core import DividendCalculator
from src.utils import setup_logger, save_csv_data, append_csv_row, load_existing_codes, move_all_data_files, get_current_date_dir
from src.data.models import StockResult

logger = setup_logger(__name__)

OUTPUT_FILE = "近3年股息率汇总.csv"


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="A股高股息率TOP50查询工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--use-local",
        action="store_true",
        help="使用本地已有数据（红利指数持仓汇总.csv、股票分红次数汇总.csv），跳过API获取",
    )
    parser.add_argument(
        "--update-board",
        action="store_true",
        help="更新板块映射（需要调用API获取板块信息，默认跳过）",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="限制处理的股票数量（0表示不限制，用于测试）",
    )
    parser.add_argument(
        "--min-dividend",
        type=int,
        default=5,
        help="最小分红次数阈值（默认5）",
    )
    return parser.parse_args()


def display_summary(results: list, df: pd.DataFrame):
    """显示汇总信息"""
    print("\n" + "=" * 80)
    print("                        A股高股息率股票分析报告")
    print("=" * 80)
    print(f"  处理时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  股票数量: {len(results)}")
    print(f"  筛选条件: 沪深主板 + 历史分红次数 > 5")
    print("=" * 80)

    # 按股息率排序
    df_sorted = df.sort_values("3年平均股息率(%)", ascending=False)

    # TOP20
    print("\n【近3年平均股息率 TOP20】")
    print("-" * 80)

    top20 = df_sorted.head(20)
    for i, (_, row) in enumerate(top20.iterrows(), 1):
        code = str(row["股票代码"])
        name = str(row["股票名称"])
        yield_3y = row.get("3年平均股息率(%)", "")
        yield_2025 = row.get("2025年股息率(%)", "")

        # 处理股息率显示
        try:
            yield_str = f"{float(yield_3y):.2f}%" if yield_3y and yield_3y != "" else "N/A"
        except (ValueError, TypeError):
            yield_str = "N/A"

        try:
            yield_2025_str = f"{float(yield_2025):.2f}%" if yield_2025 and yield_2025 != "" else "N/A"
        except (ValueError, TypeError):
            yield_2025_str = "N/A"

        print(f"  {i:2d}. {code} {name:8s}  3年均值: {yield_str:>8s}  2025: {yield_2025_str:>8s}")

    # 统计信息
    print("\n【统计信息】")
    print("-" * 80)

    # 过滤出有效的数值型股息率数据
    yields = pd.to_numeric(df_sorted["3年平均股息率(%)"], errors="coerce").dropna()
    if len(yields) > 0:
        print(f"  股息率范围: {yields.min():.2f}% ~ {yields.max():.2f}%")
        print(f"  股息率中位数: {yields.median():.2f}%")
        print(f"  股息率均值: {yields.mean():.2f}%")

        # 分布
        print(f"\n  股息率分布:")
        print(f"    > 6%:  {len(yields[yields > 6])} 只")
        print(f"    > 5%:  {len(yields[yields > 5])} 只")
        print(f"    > 4%:  {len(yields[yields > 4])} 只")
    else:
        print("  无有效股息率数据")


def main():
    """主程序"""
    args = parse_args()

    # 获取当前日期目录
    date_str = get_current_date_dir()

    print("\n" + "=" * 60)
    print("         A股高股息率TOP50查询工具")
    print("=" * 60)
    print(f"  使用本地数据: {'是' if args.use_local else '否'}")
    print(f"  更新板块映射: {'是' if args.update_board else '否（默认跳过）'}")
    print(f"  处理数量限制: {args.limit if args.limit > 0 else '无限制'}")
    print(f"  最小分红次数: {args.min_dividend}")
    print(f"  日期目录: {date_str}")
    print("=" * 60 + "\n")

    # 移动历史数据到月度目录（仅在完整运行模式下）
    if not args.use_local:
        logger.info("Step 0: 移动当前数据到月度目录...")
        logger.info(f"  移动到目录: {date_str}")
        if move_all_data_files():
            logger.info("  数据移动完成")
        else:
            logger.warning("  部分数据移动失败，将继续执行")
        print()

    # Step 1: 获取股票列表（数据会保存到 date_str 目录）
    logger.info("Step 1: 获取股票列表...")
    fetcher = IndexHoldingsFetcher(use_local=args.use_local)
    stock_list = fetcher.get_stock_list(min_dividend_count=args.min_dividend, date_str=date_str)

    if not stock_list:
        logger.error("获取股票列表失败，程序退出")
        return

    logger.info(f"获取到 {len(stock_list)} 只符合条件的股票")

    # Step 2: 更新板块映射（仅指定 --update-board 时执行）
    if args.update_board:
        logger.info("Step 2: 更新板块映射...")
        board_fetcher = BoardMappingFetcher(date_str=date_str)
        if board_fetcher.update(show_progress=False, date_str=date_str):
            # 板块映射已通过 save_to_csv(date_str) 保存到日期目录
            pass
        else:
            logger.warning("板块映射更新失败，将继续使用本地数据")
    else:
        logger.info("Step 2: 跳过板块映射更新（使用本地数据）")

    # Step 3: 检查已处理的股票，实现断点续传
    existing_codes = load_existing_codes(OUTPUT_FILE, date_str)
    if existing_codes:
        logger.info(f"已存在 {len(existing_codes)} 只股票数据，将跳过")
        stock_list = [s for s in stock_list if str(s.code).zfill(6) not in existing_codes]

    if not stock_list:
        logger.info("所有股票已处理完成，无需重新计算")
        return

    logger.info(f"待处理 {len(stock_list)} 只股票")

    # 限制处理数量
    if args.limit > 0:
        stock_list = stock_list[:args.limit]

    # Step 4: 计算股息率并增量写入（保存到 date_str 目录）
    logger.info("Step 4: 计算股息率（增量写入）...")

    def on_stock_complete(result: StockResult):
        """每计算完一个股票，追加写入CSV"""
        # 追加写入CSV到日期目录
        append_csv_row(result.to_dict(), OUTPUT_FILE, date_str)
        logger.info(f"已保存 {result.code} {result.name}")

    calculator = DividendCalculator()
    results = calculator.calculate_all(stock_list, on_complete=on_stock_complete)

    logger.info(f"处理完成，新增 {len(results)} 只股票数据")
    print(f"\n[DONE] 处理完成! 新增 {len(results)} 只股票，已保存到 data/{date_str}/{OUTPUT_FILE}\n")


if __name__ == "__main__":
    main()
