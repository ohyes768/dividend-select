"""
股息率计算核心模块
"""
import time
from datetime import datetime
from typing import Optional, Callable

import akshare as ak
import pandas as pd

from ..utils.helpers import setup_logger
from ..data.models import (
    StockBasicInfo,
    StockResult,
    YearlyDividendData,
    QuarterlyDividendData,
    PriceVolatilityData,
)

logger = setup_logger(__name__)


class DividendCalculator:
    """股息率计算器"""

    def __init__(self):
        self._price_cache: dict[str, pd.DataFrame] = {}
        self._dividend_cache: dict[str, pd.DataFrame] = {}

    def _get_stock_price(self, code: str) -> Optional[pd.DataFrame]:
        """
        获取股票历史价格数据（带缓存）

        使用不复权价格计算股息率（后复权价格会导致股息率被严重低估）
        """
        # 确保code是字符串
        code = str(code).zfill(6)

        if code in self._price_cache:
            return self._price_cache[code]

        try:
            # 使用不复权价格计算股息率
            # 注意：股息率 = 分红 / 股价，分红是实际金额，股价也应该是实际价格
            # 后复权价格会把过去的分红加回去，导致股息率被严重低估
            # akshare 接口: stock_zh_a_hist - A股历史行情数据
            df = ak.stock_zh_a_hist(symbol=code, adjust="")
            if df is not None and not df.empty:
                # 标准化日期列
                df["日期"] = pd.to_datetime(df["日期"])
                self._price_cache[code] = df
                return df
        except Exception as e:
            logger.warning(f"获取 {code} 价格数据失败: {e} [接口: ak.stock_zh_a_hist]")

        return None

    def _get_dividend_data(self, code: str) -> Optional[pd.DataFrame]:
        """
        获取指定股票的分红数据

        使用 stock_history_dividend_detail 获取详细分红数据
        """
        code = str(code).zfill(6)

        if code in self._dividend_cache:
            return self._dividend_cache[code]

        try:
            # 使用 stock_history_dividend_detail 获取详细分红数据
            # akshare 接口: stock_history_dividend_detail - A股历史分红详情
            df = ak.stock_history_dividend_detail(symbol=code, indicator="分红")
            if df is not None and not df.empty:
                # 标准化日期列
                date_col = None
                for col in ["除权除息日", "派息日期", "实施公告日期", "公告日期"]:
                    if col in df.columns:
                        date_col = col
                        break

                if date_col:
                    df["日期"] = pd.to_datetime(df[date_col], errors="coerce")
                else:
                    # 如果没有日期列，尝试从分红年度解析
                    if "分红年度" in df.columns:
                        df["日期"] = pd.to_datetime(df["分红年度"], format="%Y", errors="coerce")

                self._dividend_cache[code] = df
                return df
        except Exception as e:
            logger.warning(f"获取 {code} 分红数据失败: {e} [接口: ak.stock_history_dividend_detail]")

        return None

    def calc_yearly_avg_price(self, price_df: pd.DataFrame, year: int) -> float:
        """计算指定年度的平均股价"""
        year_data = price_df[price_df["日期"].dt.year == year]
        if year_data.empty:
            return 0.0
        return year_data["收盘"].mean()

    def calc_quarterly_avg_price(self, price_df: pd.DataFrame, year: int, quarter: int) -> float:
        """计算指定季度的平均股价"""
        # 季度日期范围
        quarter_months = {
            1: [1, 2, 3],
            2: [4, 5, 6],
            3: [7, 8, 9],
            4: [10, 11, 12],
        }
        months = quarter_months[quarter]
        quarter_data = price_df[
            (price_df["日期"].dt.year == year) &
            (price_df["日期"].dt.month.isin(months))
        ]
        if quarter_data.empty:
            return 0.0
        return quarter_data["收盘"].mean()

    def get_yearly_dividend(self, dividend_df: pd.DataFrame, year: int) -> tuple[float, int]:
        """
        获取指定年度的分红数据

        Returns:
            (每股分红金额, 分红次数)
        """
        if dividend_df is None or dividend_df.empty:
            return 0.0, 0

        # 筛选年度数据
        if "日期" in dividend_df.columns:
            year_data = dividend_df[dividend_df["日期"].dt.year == year]
        else:
            return 0.0, 0

        if year_data.empty:
            return 0.0, 0

        # 获取分红金额（转换为每股派息）
        total_dividend = 0.0
        count = 0

        # 查找分红金额列 - 注意："派息"、"每10股派息(元)" 列是每10股派息金额，需要除以10
        amount_col = None
        for col in ["派息", "每10股派息(元)", "分红金额", "每股派息(元)"]:
            if col in year_data.columns:
                amount_col = col
                break

        if amount_col:
            for _, row in year_data.iterrows():
                val = row.get(amount_col, 0)
                try:
                    val = float(val)
                    # "每股派息(元)" 已经是每股金额，其他列需要除以10转换为每股
                    if amount_col != "每股派息(元)":
                        val /= 10
                    total_dividend += val
                    count += 1
                except (ValueError, TypeError):
                    continue

        return total_dividend, count

    def get_quarterly_dividend(
        self, dividend_df: pd.DataFrame, year: int, quarter: int
    ) -> tuple[Optional[float], int]:
        """
        获取指定季度的分红数据

        Returns:
            (每股分红金额 或 None, 分红次数)
        """
        if dividend_df is None or dividend_df.empty:
            return None, 0

        # 季度日期范围
        quarter_months = {
            1: [1, 2, 3],
            2: [4, 5, 6],
            3: [7, 8, 9],
            4: [10, 11, 12],
        }
        months = quarter_months[quarter]

        if "日期" in dividend_df.columns:
            quarter_data = dividend_df[
                (dividend_df["日期"].dt.year == year) &
                (dividend_df["日期"].dt.month.isin(months))
            ]
        else:
            return None, 0

        if quarter_data.empty:
            return None, 0

        # 获取分红金额（转换为每股派息）
        total_dividend = 0.0
        count = 0

        # 查找分红金额列 - 注意："派息"、"每10股派息(元)" 列是每10股派息金额，需要除以10
        amount_col = None
        for col in ["派息", "每10股派息(元)", "分红金额", "每股派息(元)"]:
            if col in quarter_data.columns:
                amount_col = col
                break

        if amount_col:
            for _, row in quarter_data.iterrows():
                val = row.get(amount_col, 0)
                try:
                    val = float(val)
                    # "每股派息(元)" 已经是每股金额，其他列需要除以10转换为每股
                    if amount_col != "每股派息(元)":
                        val /= 10
                    total_dividend += val
                    count += 1
                except (ValueError, TypeError):
                    continue

        if count == 0:
            return None, 0

        return total_dividend, count

    def calc_price_volatility(
        self, price_df: pd.DataFrame, year: int, avg_price: float
    ) -> Optional[PriceVolatilityData]:
        """
        计算指定年度的股价波动数据
        """
        year_data = price_df[price_df["日期"].dt.year == year]
        if year_data.empty:
            return None

        high_price = year_data["收盘"].max()
        low_price = year_data["收盘"].min()

        if avg_price <= 0:
            return None

        # 以平均股价为基准计算涨跌幅
        high_change_pct = (high_price - avg_price) / avg_price * 100
        low_change_pct = (avg_price - low_price) / avg_price * 100

        return PriceVolatilityData(
            high_price=high_price,
            low_price=low_price,
            high_change_pct=high_change_pct,
            low_change_pct=low_change_pct,
        )

    def calculate_stock(self, stock: StockBasicInfo) -> Optional[StockResult]:
        """
        计算单只股票的完整数据

        Returns:
            StockResult 或 None（分红数据获取失败时返回None）
        """
        # 获取分红数据（先获取，失败则直接返回None）
        dividend_df = self._get_dividend_data(stock.code)
        if dividend_df is None:
            logger.warning(f"{stock.code} {stock.name}: 无分红数据，跳过")
            return None

        result = StockResult(
            code=stock.code,
            name=stock.name,
            exchange=stock.exchange,
            source_index=stock.source_index,
        )

        # 获取价格数据
        price_df = self._get_stock_price(stock.code)
        if price_df is None or price_df.empty:
            logger.warning(f"{stock.code} {stock.name}: 无价格数据")
            return None

        # 计算近3年年度数据 (2023, 2024, 2025)
        years = [2023, 2024, 2025]
        valid_yields = []

        for year in years:
            avg_price = self.calc_yearly_avg_price(price_df, year)
            dividend, times = self.get_yearly_dividend(dividend_df, year)

            yield_pct = 0.0
            if avg_price > 0 and dividend > 0:
                yield_pct = dividend / avg_price * 100
                valid_yields.append(yield_pct)

            result.yearly_data[year] = YearlyDividendData(
                year=year,
                avg_price=avg_price,
                dividend=dividend,
                dividend_times=times,
                dividend_yield=yield_pct,
            )

        # 计算近3年平均股价和平均股息率
        valid_prices = [result.yearly_data[y].avg_price for y in years if result.yearly_data[y].avg_price > 0]
        if valid_prices:
            result.avg_price_3y = sum(valid_prices) / len(valid_prices)
        if valid_yields:
            result.avg_yield_3y = sum(valid_yields) / len(valid_yields)

        # 计算近4季度数据 (2025Q1-Q4)
        for q in range(1, 5):
            avg_price = self.calc_quarterly_avg_price(price_df, 2025, q)
            dividend, times = self.get_quarterly_dividend(dividend_df, 2025, q)

            yield_pct = None
            if avg_price > 0 and dividend is not None and dividend > 0:
                yield_pct = dividend / avg_price * 100

            result.quarterly_data[f"2025Q{q}"] = QuarterlyDividendData(
                year=2025,
                quarter=q,
                avg_price=avg_price,
                dividend=dividend,
                dividend_yield=yield_pct,
            )

        # 计算2025年波动数据
        if 2025 in result.yearly_data:
            avg_price_2025 = result.yearly_data[2025].avg_price
            if avg_price_2025 > 0:
                result.volatility = self.calc_price_volatility(price_df, 2025, avg_price_2025)

        return result

    def calculate_all(
        self,
        stock_list: list[StockBasicInfo],
        limit: int = 0,
        on_complete: Optional[Callable[[StockResult], None]] = None,
    ) -> list[StockResult]:
        """
        计算所有股票

        Args:
            stock_list: 股票基本信息列表
            limit: 限制处理的股票数量（0表示不限制）
            on_complete: 每完成一个股票计算的回调函数（仅在成功时调用）

        Returns:
            计算结果列表（仅包含成功的股票）
        """
        if limit > 0:
            stock_list = stock_list[:limit]

        results = []
        total = len(stock_list)

        for i, stock in enumerate(stock_list):
            logger.info(f"处理 [{i + 1}/{total}] {stock.code} {stock.name}...")

            try:
                result = self.calculate_stock(stock)
                # 只在成功（非None）时添加结果和调用回调
                if result is not None:
                    results.append(result)
                    if on_complete:
                        on_complete(result)
            except Exception as e:
                logger.error(f"处理 {stock.code} 失败: {e}")

            time.sleep(1.5)  # 避免 akshare 接口限流

        return results
