"""
财务指标获取器单元测试 — 覆盖 EPS 提取逻辑

列名依据：akshare.stock_financial_analysis_indicator() 真实返回
（截至 akshare 1.16.x）。回归 guard 防止猜错列名。
"""
import sys
from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest

from src.data.financial_fetcher import (
    FinancialFetcher,
    QUARTERLY_YOY_BASE_DATE,
    QUARTERLY_YOY_REPORT_DATE,
)


class TestCalcLatestEps:
    """_calc_latest_eps 单元测试（取最近一期年报的 EPS）"""

    @pytest.fixture
    def fetcher(self):
        return FinancialFetcher()

    def test_calc_latest_eps_normal(self, fetcher):
        """正常情况：3 年 12-31 数据，返回最新一年 EPS"""
        df = pd.DataFrame({
            "日期": ["2022-12-31", "2023-12-31", "2024-12-31", "2025-03-31"],
            "摊薄每股收益(元)": [0.80, 1.00, 1.20, 0.30],
        })
        result = fetcher._calc_latest_eps(df)
        assert result == {"最新EPS年度": 2024, "最新EPS(元)": 1.20}

    def test_calc_latest_eps_no_year_end(self, fetcher):
        """没有 12-31 数据：返回 None dict"""
        df = pd.DataFrame({
            "日期": ["2024-03-31", "2024-06-30", "2024-09-30"],
            "摊薄每股收益(元)": [0.30, 0.60, 0.90],
        })
        result = fetcher._calc_latest_eps(df)
        assert result == {"最新EPS年度": None, "最新EPS(元)": None}

    def test_calc_latest_eps_negative(self, fetcher):
        """亏损股：EPS 负值保留（路由层识别"亏损"）"""
        df = pd.DataFrame({
            "日期": ["2022-12-31", "2023-12-31", "2024-12-31"],
            "摊薄每股收益(元)": [0.50, -0.20, -0.50],
        })
        result = fetcher._calc_latest_eps(df)
        assert result == {"最新EPS年度": 2024, "最新EPS(元)": -0.50}

    def test_calc_latest_eps_latest_year_first(self, fetcher):
        """取最新一年而非最早：数据乱序时仍取 2024 而非 2022"""
        df = pd.DataFrame({
            "日期": ["2024-12-31", "2022-12-31", "2023-12-31"],
            "摊薄每股收益(元)": [1.50, 0.80, 1.00],
        })
        result = fetcher._calc_latest_eps(df)
        assert result["最新EPS年度"] == 2024
        assert result["最新EPS(元)"] == 1.50

    def test_calc_latest_eps_missing_eps_column(self, fetcher):
        """摊薄每股收益列不存在：返回 None EPS 但年度有值"""
        df = pd.DataFrame({
            "日期": ["2024-12-31", "2023-12-31"],
            # 故意没有"摊薄每股收益(元)"列
        })
        result = fetcher._calc_latest_eps(df)
        assert result == {"最新EPS年度": 2024, "最新EPS(元)": None}

    def test_calc_latest_eps_real_akshare_columns(self, fetcher):
        """Regression guard：使用真实 akshare 返回的多列 DataFrame

        历史 bug：曾误用"基本每股收益(元)"，但 akshare 实际返回"摊薄每股收益(元)"。
        本测试用真实列名 + 真实日期格式（datetime.date）防止再犯。
        """
        import datetime
        df = pd.DataFrame({
            "日期": [
                datetime.date(2022, 12, 31),
                datetime.date(2023, 12, 31),
                datetime.date(2024, 12, 31),
                datetime.date(2025, 12, 31),  # 用户期望的 2025 年报
                datetime.date(2025, 3, 31),
            ],
            "摊薄每股收益(元)": [0.50, 0.80, 1.00, 1.20, 0.30],
            "基本每股收益(元)": [0.51, 0.81, 1.01, 1.21, 0.31],  # 真实也有，但用错列
            "加权每股收益(元)": [0.52, 0.82, 1.02, 1.22, 0.32],
            "扣除非经常性损益后的净利润(元)": [1e8, 1.5e8, 2e8, 2.5e8, 0.6e8],
        })
        result = fetcher._calc_latest_eps(df)
        # 必须取到 2025 年报数据
        assert result["最新EPS年度"] == 2025, f"应取 2025-12-31，实际 {result}"
        assert result["最新EPS(元)"] == 1.20, f"应用摊薄EPS=1.20，实际 {result}"


class TestCalcQuarterlyYoy:
    """_calc_quarterly_yoy 单元测试（固定 2026Q1 vs 2025Q1 扣非同比）"""

    @pytest.fixture
    def fetcher(self):
        return FinancialFetcher()

    def test_normal(self, fetcher):
        """正常：2026Q1=272e8, 2025Q1=268e8, 同比=(272-268)/268≈1.49%"""
        df = pd.DataFrame({
            "日期": [QUARTERLY_YOY_REPORT_DATE, QUARTERLY_YOY_BASE_DATE,
                     date(2025, 12, 31), date(2024, 12, 31)],
            "扣除非经常性损益后的净利润(元)": [272e8, 268e8, 1000e8, 950e8],
        })
        result = fetcher._calc_quarterly_yoy(df)
        assert result["最新季度扣非(元)"] == 272e8
        # (272-268)/268 * 100 = 1.4925... → round 2 → 1.49
        assert result["最新季度扣非同比(%)"] == 1.49

    def test_missing_2026q1(self, fetcher):
        """未发布 2026Q1（如新股刚上市）：绝对值与同比都 None"""
        df = pd.DataFrame({
            "日期": [QUARTERLY_YOY_BASE_DATE, date(2025, 12, 31), date(2024, 12, 31)],
            "扣除非经常性损益后的净利润(元)": [268e8, 1000e8, 950e8],
        })
        result = fetcher._calc_quarterly_yoy(df)
        assert result == {"最新季度扣非(元)": None, "最新季度扣非同比(%)": None}

    def test_missing_2025q1(self, fetcher):
        """有 2026Q1 但缺去年同期（极少见）：绝对值有、同比 None"""
        df = pd.DataFrame({
            "日期": [QUARTERLY_YOY_REPORT_DATE, date(2025, 12, 31)],
            "扣除非经常性损益后的净利润(元)": [272e8, 1000e8],
        })
        result = fetcher._calc_quarterly_yoy(df)
        assert result["最新季度扣非(元)"] == 272e8
        assert result["最新季度扣非同比(%)"] is None

    def test_base_value_zero(self, fetcher):
        """去年同期扣非=0（基数极小/亏损边缘）：同比 None 避免除零爆炸"""
        df = pd.DataFrame({
            "日期": [QUARTERLY_YOY_REPORT_DATE, QUARTERLY_YOY_BASE_DATE],
            "扣除非经常性损益后的净利润(元)": [100e8, 0],
        })
        result = fetcher._calc_quarterly_yoy(df)
        assert result["最新季度扣非(元)"] == 100e8
        assert result["最新季度扣非同比(%)"] is None

    def test_real_akshare_columns_and_dates(self, fetcher):
        """Regression guard：真实 akshare 列名 + datetime.date 格式
        防止再改 akshare 接口时猜错列名或日期解析。
        """
        import datetime
        df = pd.DataFrame({
            "日期": [
                datetime.date(2025, 3, 31),  # 去年同期
                datetime.date(2026, 3, 31),  # 本期
                datetime.date(2025, 12, 31),
                datetime.date(2024, 12, 31),
            ],
            "摊薄每股收益(元)": [0.30, 0.32, 1.20, 1.00],  # 干扰列
            "扣除非经常性损益后的净利润(元)": [268e8, 272e8, 1000e8, 950e8],
        })
        result = fetcher._calc_quarterly_yoy(df)
        assert result["最新季度扣非(元)"] == 272e8
        assert result["最新季度扣非同比(%)"] == 1.49

