"""
IndexHoldingsFetcher 单元测试

覆盖 fhps prefilter 行为（方案 A）：
- excludes_no_dividend_codes: 持仓含 600123, fhps 索引不含 → 600123 被排除
- includes_dividend_codes: 持仓含 601318, fhps 索引含 → 601318 保留
- skipped_when_fhps_none: fhps_fetcher=None → stock_list 与原逻辑一致
- preserves_min_dividend_count: prefilter 跟 min_dividend_count 是 AND，不互相覆盖
"""
import sys
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

# 阻止 src 包下 __init__.py 触发 akshare 拉取（main 包 __init__ 行为）
# sys.path 在 conftest 缺失的情况下，需要在 import 前设置
sys.path.insert(0, "src")

from src.data.fetcher import IndexHoldingsFetcher  # noqa: E402


class FakeFHPSFetcher:
    """最小可用的 FHPSFetcher 替身：只暴露 _indexed 字典"""

    def __init__(self, codes: list[str]):
        # 索引 key 用 zfill(6) str，跟 FHPSFetcher._build_index 行为一致
        self._indexed = {code: pd.DataFrame() for code in codes}


@pytest.fixture
def holdings_df():
    """3 只主板股票：600123/601318/000001"""
    return pd.DataFrame({
        "股票代码": ["600123", "601318", "000001"],
        "股票名称": ["兰花科创", "中国平安", "平安银行"],
        "交易所": ["SH", "SH", "SZ"],
        "来源指数": ["中证红利", "中证红利", "中证红利"],
    })


@pytest.fixture
def dividend_df():
    """3 只股票，分红次数都 > 5
    真实生产 dividend_df 由 fetcher.py:245-257 构造，包含"股票名称/交易所/来源指数"列
    （用于最后构造 StockBasicInfo）。mock 路径要复现这个 schema。
    """
    return pd.DataFrame({
        "股票代码": ["600123", "601318", "000001"],
        "股票名称": ["兰花科创", "中国平安", "平安银行"],
        "交易所": ["SH", "SH", "SZ"],
        "来源指数": ["中证红利", "中证红利", "中证红利"],
        "分红次数": [10, 15, 12],
    })


@pytest.fixture
def mock_csv(holdings_df, dividend_df):
    """mock load_csv_data 按调用顺序返回：先 holdings, 再 dividend"""
    # 按调用顺序返回：fetcher.py 实际只调 load_csv_data 两次（持仓/分红次数），
    # 用 side_effect 列表比字符串匹配更稳
    with patch("src.data.fetcher.load_csv_data") as mock_load, \
         patch("src.data.fetcher.save_csv_data", return_value=True):
        mock_load.side_effect = [holdings_df, dividend_df]
        yield mock_load


class TestIndexHoldingsFetcherPrefilter:
    """IndexHoldingsFetcher prefilter 行为测试"""

    def test_prefilter_excludes_no_dividend_codes(self, mock_csv, caplog):
        """持仓含 600123, fhps 索引不含 → 600123 被排除"""
        # fhps 索引只含 601318/000001，600123 不在
        fake_fhps = FakeFHPSFetcher(codes=["601318", "000001"])
        fetcher = IndexHoldingsFetcher(use_local=True, fhps_fetcher=fake_fhps)

        result = fetcher.get_stock_list(min_dividend_count=5, date_str="2026-06")

        codes = [s.code for s in result]
        assert "600123" not in codes, f"600123 (无 2025 分红) 应被 prefilter 排除，实际 codes={codes}"
        assert "601318" in codes
        assert "000001" in codes
        assert len(result) == 2

    def test_prefilter_includes_dividend_codes(self, mock_csv):
        """持仓含 601318, fhps 索引含 → 601318 保留"""
        fake_fhps = FakeFHPSFetcher(codes=["601318"])
        fetcher = IndexHoldingsFetcher(use_local=True, fhps_fetcher=fake_fhps)

        result = fetcher.get_stock_list(min_dividend_count=5, date_str="2026-06")

        codes = [s.code for s in result]
        assert "601318" in codes, f"601318 应被保留，实际 codes={codes}"
        assert "600123" not in codes
        assert "000001" not in codes
        assert len(result) == 1

    def test_prefilter_skipped_when_fhps_none(self, mock_csv):
        """fhps_fetcher=None → 跳过 prefilter, 返回原 stock_list"""
        fetcher = IndexHoldingsFetcher(use_local=True, fhps_fetcher=None)

        result = fetcher.get_stock_list(min_dividend_count=5, date_str="2026-06")

        # 全部 3 只都保留（不预筛）
        codes = [s.code for s in result]
        assert "600123" in codes
        assert "601318" in codes
        assert "000001" in codes
        assert len(result) == 3

    def test_prefilter_preserves_min_dividend_count(self, mock_csv):
        """prefilter 跟 min_dividend_count 是 AND，不互相覆盖"""
        # 000001 分红次数=12, 600123 分红次数=10
        # min_dividend_count=11 → 000001 通过，600123 被 Step 3 排除
        # 假设 fhps 索引含全部 3 只，验证 min_dividend_count 仍生效
        fake_fhps = FakeFHPSFetcher(codes=["600123", "601318", "000001"])
        fetcher = IndexHoldingsFetcher(use_local=True, fhps_fetcher=fake_fhps)

        result = fetcher.get_stock_list(min_dividend_count=11, date_str="2026-06")

        codes = [s.code for s in result]
        # 600123 分红次数=10 < 11 → 被 min_dividend_count 排除
        assert "600123" not in codes, f"600123 分红次数=10 应被 min_dividend_count=11 排除"
        # 000001 分红次数=12 > 11 → 保留
        assert "000001" in codes
        # 601318 分红次数=15 > 11 → 保留
        assert "601318" in codes
        assert len(result) == 2
