"""
财务指标获取器单元测试 — 覆盖 EPS 提取逻辑

列名依据：akshare.stock_financial_analysis_indicator() 真实返回
（截至 akshare 1.16.x）。回归 guard 防止猜错列名。
"""
import sys
from unittest.mock import patch

import pandas as pd
import pytest

from src.data.financial_fetcher import FinancialFetcher


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

