"""
数据获取层 - 红利指数持仓获取
"""
import time
from collections import defaultdict
from typing import Optional

import akshare as ak
import pandas as pd

from ..utils.helpers import (
    PROJECT_ROOT,
    DATA_DIR,
    is_main_board,
    get_exchange,
    setup_logger,
    load_csv_data,
    save_csv_data,
)
from .models import StockBasicInfo

logger = setup_logger(__name__)


# 红利指数配置
DIVIDEND_INDEXES = {
    "000922": "中证红利",
    "932315": "中证红利质量",
    "932309": "红利增长",
    "931468": "红利质量",
}


class IndexHoldingsFetcher:
    """红利指数持仓获取器"""

    def __init__(self, use_local: bool = False):
        """
        初始化

        Args:
            use_local: 是否使用本地已有数据（跳过API获取）
        """
        self.use_local = use_local
        self.holdings_file = DATA_DIR / "红利指数持仓汇总.csv"
        self.dividend_count_file = DATA_DIR / "股票分红次数汇总.csv"

    def fetch_index_holdings(self, index_code: str) -> Optional[pd.DataFrame]:
        """
        获取单个指数的持仓成分股

        Args:
            index_code: 指数代码

        Returns:
            DataFrame with columns: 股票代码, 股票名称
        """
        try:
            logger.info(f"获取指数 {index_code} 的持仓数据...")

            # 使用akshare获取中证指数成分股
            df = ak.index_stock_cons_weight_csindex(symbol=index_code)

            if df is not None and not df.empty:
                # 标准化列名
                df = df.rename(columns={
                    "成分券代码": "股票代码",
                    "成分券名称": "股票名称",
                })
                return df[["股票代码", "股票名称"]]

        except Exception as e:
            logger.error(f"获取指数 {index_code} 持仓失败: {e}")

        return None

    def fetch_all_holdings(self) -> pd.DataFrame:
        """
        获取所有红利指数的持仓并汇总

        Returns:
            汇总后的DataFrame
        """
        all_holdings = []

        for index_code, index_name in DIVIDEND_INDEXES.items():
            df = self.fetch_index_holdings(index_code)
            if df is not None and not df.empty:
                df["来源指数"] = index_name
                df["来源指数代码"] = index_code
                all_holdings.append(df)
                logger.info(f"  {index_name}: {len(df)} 只成分股")
            else:
                logger.warning(f"  {index_name}: 获取失败")
            time.sleep(0.5)  # 避免请求过快

        if not all_holdings:
            return pd.DataFrame()

        # 合并并去重，记录股票出现在几个指数中
        combined = pd.concat(all_holdings, ignore_index=True)

        # 统计每只股票出现的指数数量
        index_count = combined.groupby("股票代码").size().reset_index(name="纳入指数数量")
        combined = combined.drop_duplicates(subset=["股票代码"])
        combined = combined.merge(index_count, on="股票代码")

        # 添加交易所信息
        combined["交易所"] = combined["股票代码"].apply(get_exchange)

        # 重新排列列顺序
        combined = combined[["交易所", "股票代码", "股票名称", "来源指数", "来源指数代码", "纳入指数数量"]]

        return combined

    def fetch_dividend_count(self, stock_code: str) -> int:
        """
        获取单只股票的历史分红次数

        Args:
            stock_code: 股票代码

        Returns:
            历史累计分红次数
        """
        try:
            df = ak.stock_history_dividend()
            if df is not None and not df.empty:
                # 查找指定股票
                stock_data = df[df["代码"] == stock_code]
                if not stock_data.empty:
                    return int(stock_data.iloc[0]["分红次数"])
        except Exception:
            pass
        return 0

    def fetch_all_dividend_counts(self, stock_list: list[str]) -> dict[str, int]:
        """
        批量获取股票的历史分红次数

        Args:
            stock_list: 股票代码列表

        Returns:
            {股票代码: 分红次数}
        """
        result = {}

        try:
            # 批量获取整个市场的分红数据
            logger.info("  正在获取市场分红数据...")
            df = ak.stock_history_dividend()

            if df is None or df.empty:
                logger.error("  获取分红数据失败")
                return result

            # 将股票代码转换为6位字符串格式
            df["代码"] = df["代码"].apply(lambda x: str(x).zfill(6))

            # 筛选出持仓股票的分红数据
            stock_codes_formatted = [str(c).zfill(6) for c in stock_list]
            filtered_df = df[df["代码"].isin(stock_codes_formatted)]

            # 构建结果字典
            for _, row in filtered_df.iterrows():
                code = row["代码"]
                result[code] = int(row["分红次数"])

            logger.info(f"  成功获取 {len(result)} 只股票的分红次数")

        except Exception as e:
            logger.error(f"  获取分红数据失败: {e}")
            # 失败时逐个获取
            total = len(stock_list)
            for i, code in enumerate(stock_list):
                count = self.fetch_dividend_count(code)
                result[code] = count

                if (i + 1) % 10 == 0:
                    logger.info(f"  分红次数获取进度: {i + 1}/{total}")

                time.sleep(0.3)  # 避免请求过快

        return result

    def get_stock_list(self, min_dividend_count: int = 5, date_str: str | None = None) -> list[StockBasicInfo]:
        """
        获取筛选后的股票列表

        Args:
            min_dividend_count: 最小分红次数阈值
            date_str: 日期字符串（YYYY-MM格式），None则使用当前月份

        Returns:
            筛选后的股票基本信息列表
        """
        from ..utils.helpers import get_current_date_dir

        if date_str is None:
            date_str = get_current_date_dir()

        # Step 1: 获取持仓数据
        if self.use_local:
            logger.info("使用本地持仓数据...")
            holdings_df = load_csv_data("红利指数持仓汇总.csv", date_str)
            dividend_df = load_csv_data("股票分红次数汇总.csv", date_str)
        else:
            logger.info("从API获取持仓数据...")
            holdings_df = self.fetch_all_holdings()
            if holdings_df.empty:
                logger.error("获取持仓数据失败")
                return []

            # 保存持仓数据到当前月份目录
            save_csv_data(holdings_df, "红利指数持仓汇总.csv", date_str)
            logger.info(f"持仓数据已保存到 {date_str}/: {len(holdings_df)} 条")

            # Step 2: 获取分红次数
            logger.info("获取分红次数数据...")
            stock_codes = holdings_df["股票代码"].tolist()
            dividend_counts = self.fetch_all_dividend_counts(stock_codes)

            # 构建分红次数DataFrame
            dividend_data = []
            for _, row in holdings_df.iterrows():
                code = row["股票代码"]
                dividend_data.append({
                    "股票代码": code,
                    "股票名称": row["股票名称"],
                    "交易所": row["交易所"],
                    "来源指数": row["来源指数"],
                    "分红次数": dividend_counts.get(code, 0),
                })

            dividend_df = pd.DataFrame(dividend_data)
            save_csv_data(dividend_df, "股票分红次数汇总.csv", date_str)
            logger.info(f"分红次数数据已保存到 {date_str}/: {len(dividend_df)} 条")

        # Step 3: 筛选 - 沪深主板 + 分红次数 > 5
        if dividend_df is None or dividend_df.empty:
            logger.error("分红次数数据为空")
            return []

        # 筛选主板
        dividend_df["is_main"] = dividend_df["股票代码"].apply(is_main_board)
        main_board_df = dividend_df[dividend_df["is_main"]].copy()

        # 筛选分红次数
        filtered_df = main_board_df[main_board_df["分红次数"] > min_dividend_count].copy()

        logger.info(f"筛选结果: 主板股票 {len(main_board_df)} 只, 分红>5次 {len(filtered_df)} 只")

        # 转换为StockBasicInfo列表
        result = []
        for _, row in filtered_df.iterrows():
            result.append(StockBasicInfo(
                code=row["股票代码"],
                name=row["股票名称"],
                exchange=row["交易所"],
                source_index=row["来源指数"],
                dividend_count=row["分红次数"],
            ))

        return result
