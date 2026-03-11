"""
数据处理模块单元测试
"""
import pytest

from data.models import StockInfo, DividendPlan, DividendRecord
from data.processor import StockDataProcessor


class TestStockDataProcessor:
    """StockDataProcessor 测试类"""

    def test_calculate_dividend_yield(self):
        """测试股息率计算"""
        processor = StockDataProcessor()

        # 创建测试股票
        stock = StockInfo(
            stock_code="600519",
            stock_name="贵州茅台",
            market="沪市主板",
            industry="白酒",
            market_cap=20000.0,
            current_price=1500.0,
            pe_ratio=30.0
        )

        # 计算股息率: (25.91 / 1500) * 100 ≈ 1.73%
        dividend_yield = processor.calculate_dividend_yield(stock, 25.91)
        assert abs(dividend_yield - 1.73) < 0.01

    def test_calculate_dividend_yield_zero_price(self):
        """测试股价为0时的股息率计算"""
        processor = StockDataProcessor()

        stock = StockInfo(
            stock_code="600519",
            stock_name="贵州茅台",
            market="沪市主板",
            industry="白酒",
            market_cap=20000.0,
            current_price=0.0,
            pe_ratio=30.0
        )

        dividend_yield = processor.calculate_dividend_yield(stock, 25.91)
        assert dividend_yield == 0.0

    def test_is_abnormal_stock_st(self):
        """测试ST股票识别"""
        processor = StockDataProcessor(exclude_st=True)

        st_stock = StockInfo(
            stock_code="600001",
            stock_name="ST银行",
            market="沪市主板",
            industry="银行",
            market_cap=1000.0,
            current_price=5.0,
            pe_ratio=5.0
        )

        assert processor.is_abnormal_stock(st_stock) is True

    def test_is_abnormal_stock_normal(self):
        """测试正常股票识别"""
        processor = StockDataProcessor(exclude_st=True)

        normal_stock = StockInfo(
            stock_code="600519",
            stock_name="贵州茅台",
            market="沪市主板",
            industry="白酒",
            market_cap=20000.0,
            current_price=1500.0,
            pe_ratio=30.0
        )

        assert processor.is_abnormal_stock(normal_stock) is False

    def test_filter_stocks(self):
        """测试股票过滤"""
        processor = StockDataProcessor(exclude_st=True, exclude_suspended=True)

        stocks = [
            StockInfo("600519", "贵州茅台", "沪市主板", "白酒", 20000.0, 1500.0, 30.0),
            StockInfo("600001", "ST银行", "沪市主板", "银行", 1000.0, 5.0, 5.0),
            StockInfo("000001", "平安银行", "深市主板", "银行", 3000.0, 10.0, 5.0),
            StockInfo("000002", "万科A", "深市主板", "房地产", 1000.0, 0.0, 10.0),  # 停牌
        ]

        filtered, excluded = processor.filter_stocks(stocks)

        # 应该排除ST股票和停牌股票
        assert len(filtered) == 2
        assert excluded == 2
        assert all(s.stock_name not in ["ST银行", "万科A"] for s in filtered)

    def test_rank_by_dividend_yield(self):
        """测试按股息率排序"""
        processor = StockDataProcessor()

        stocks = [
            StockInfo("600001", "股票A", "沪市主板", "行业A", 1000.0, 10.0, 10.0, dividend_yield=3.5),
            StockInfo("600002", "股票B", "沪市主板", "行业B", 1000.0, 10.0, 10.0, dividend_yield=5.2),
            StockInfo("600003", "股票C", "沪市主板", "行业C", 1000.0, 10.0, 10.0, dividend_yield=2.8),
        ]

        ranked = processor.rank_by_dividend_yield(stocks, top_count=3)

        # 应该按降序排列
        assert ranked[0].stock_code == "600002"  # 5.2%
        assert ranked[1].stock_code == "600001"  # 3.5%
        assert ranked[2].stock_code == "600003"  # 2.8%

    def test_rank_by_dividend_yield_top_n(self):
        """测试取TOP N"""
        processor = StockDataProcessor()

        stocks = [
            StockInfo("600001", "股票A", "沪市主板", "行业A", 1000.0, 10.0, 10.0, dividend_yield=3.5),
            StockInfo("600002", "股票B", "沪市主板", "行业B", 1000.0, 10.0, 10.0, dividend_yield=5.2),
            StockInfo("600003", "股票C", "沪市主板", "行业C", 1000.0, 10.0, 10.0, dividend_yield=2.8),
        ]

        ranked = processor.rank_by_dividend_yield(stocks, top_count=2)

        # 应该只返回前2名
        assert len(ranked) == 2
        assert ranked[0].stock_code == "600002"
        assert ranked[1].stock_code == "600001"

    def test_calculate_cumulative_dividend(self):
        """测试累计分红计算"""
        processor = StockDataProcessor()

        plan = DividendPlan(stock_code="600519", year=2023)
        plan.add_record(DividendRecord(amount_per_share=2.5, dividend_ratio=25.0))
        plan.add_record(DividendRecord(amount_per_share=1.5, dividend_ratio=15.0))

        cumulative = processor.calculate_cumulative_dividend(plan)
        assert cumulative == 4.0

    def test_calculate_cumulative_dividend_empty(self):
        """测试空分红计划的累计计算"""
        processor = StockDataProcessor()

        plan = DividendPlan(stock_code="600519", year=2023)
        cumulative = processor.calculate_cumulative_dividend(plan)
        assert cumulative == 0.0

    def test_calculate_cumulative_dividend_none(self):
        """测试None分红计划的累计计算"""
        processor = StockDataProcessor()

        cumulative = processor.calculate_cumulative_dividend(None)
        assert cumulative == 0.0
