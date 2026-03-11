"""
数据模型单元测试
"""
import pytest

from data.models import (
    DividendRecord,
    DividendPlan,
    TrendData,
    StockInfo,
    MarketMetadata
)


class TestDividendRecord:
    """DividendRecord 测试类"""

    def test_create_dividend_record(self):
        """测试创建分红记录"""
        record = DividendRecord(
            amount_per_share=2.5,
            dividend_ratio=25.0,
            record_date="2024-06-15",
            ex_date="2024-06-16",
            pay_date="2024-06-20"
        )

        assert record.amount_per_share == 2.5
        assert record.dividend_ratio == 25.0
        assert record.record_date == "2024-06-15"
        assert record.ex_date == "2024-06-16"
        assert record.pay_date == "2024-06-20"
        assert record.dividend_type == "现金分红"


class TestDividendPlan:
    """DividendPlan 测试类"""

    def test_create_dividend_plan(self):
        """测试创建分红计划"""
        plan = DividendPlan(stock_code="600519", year=2023)

        assert plan.stock_code == "600519"
        assert plan.year == 2023
        assert plan.records == []
        assert plan.total_amount == 0.0

    def test_add_record(self):
        """测试添加分红记录"""
        plan = DividendPlan(stock_code="600519", year=2023)

        record1 = DividendRecord(amount_per_share=2.5, dividend_ratio=25.0)
        record2 = DividendRecord(amount_per_share=1.5, dividend_ratio=15.0)

        plan.add_record(record1)
        plan.add_record(record2)

        assert len(plan.records) == 2
        assert plan.total_amount == 4.0


class TestTrendData:
    """TrendData 测试类"""

    def test_create_trend_data(self):
        """测试创建趋势数据"""
        trend = TrendData(stock_code="600519")

        assert trend.stock_code == "600519"
        assert trend.yields == []
        assert trend.trend_symbol == "→"

    def test_trend_with_yields(self):
        """测试带收益率的趋势数据"""
        trend = TrendData(
            stock_code="600519",
            yields=[2.5, 2.3, 2.1],
            trend_symbol="↗"
        )

        assert trend.stock_code == "600519"
        assert trend.yields == [2.5, 2.3, 2.1]
        assert trend.trend_symbol == "↗"


class TestStockInfo:
    """StockInfo 测试类"""

    def test_create_stock_info(self):
        """测试创建股票信息"""
        stock = StockInfo(
            stock_code="600519",
            stock_name="贵州茅台",
            market="沪市主板",
            industry="白酒",
            market_cap=20000.0,
            current_price=1500.0,
            pe_ratio=30.0
        )

        assert stock.stock_code == "600519"
        assert stock.stock_name == "贵州茅台"
        assert stock.market == "沪市主板"
        assert stock.industry == "白酒"
        assert stock.market_cap == 20000.0
        assert stock.current_price == 1500.0
        assert stock.pe_ratio == 30.0
        assert stock.dividend_yield == 0.0
        assert stock.dividend_plan is None
        assert stock.trend_data is None

    def test_stock_info_with_dividend_yield(self):
        """测试带股息率的股票信息"""
        stock = StockInfo(
            stock_code="600519",
            stock_name="贵州茅台",
            market="沪市主板",
            industry="白酒",
            market_cap=20000.0,
            current_price=1500.0,
            pe_ratio=30.0,
            dividend_yield=2.5
        )

        assert stock.dividend_yield == 2.5


class TestMarketMetadata:
    """MarketMetadata 测试类"""

    def test_create_market_metadata(self):
        """测试创建市场元数据"""
        metadata = MarketMetadata(
            update_time="2024-03-09 12:00:00",
            data_source="akshare",
            total_stocks=5000,
            filtered_stocks=4800,
            excluded_stocks=200
        )

        assert metadata.update_time == "2024-03-09 12:00:00"
        assert metadata.data_source == "akshare"
        assert metadata.total_stocks == 5000
        assert metadata.filtered_stocks == 4800
        assert metadata.excluded_stocks == 200
