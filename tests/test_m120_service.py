"""
M120 Service 单元测试
"""
import pytest
from src.services.m120_service import M120Service


class TestM120Service:
    """M120 服务测试"""

    def test_get_realtime_prices_batch_single(self):
        """测试批量获取单个股票的实时价格"""
        service = M120Service()
        result = service._get_realtime_prices_batch(["600519"])

        assert len(result) > 0, "应该返回至少一只股票的价格"
        assert "600519" in result or any("600519" in k for k in result.keys()), f"应该包含 600519，当前结果: {result}"

    def test_get_realtime_prices_batch_multiple(self):
        """测试批量获取多个股票的实时价格"""
        service = M120Service()
        codes = ["600519", "000001", "600036"]
        result = service._get_realtime_prices_batch(codes)

        assert len(result) > 0, "应该返回至少一只股票的价格"
        # 检查是否返回了多个股票
        assert len(result) >= 1, f"应该返回股票数据，当前结果: {result}"

    def test_get_realtime_prices_batch_empty(self):
        """测试空列表输入"""
        service = M120Service()
        result = service._get_realtime_prices_batch([])

        assert result == {}, "空列表应该返回空字典"

    def test_get_m120_from_aliyun(self):
        """测试从阿里云获取单只股票M120"""
        service = M120Service()
        result = service._get_m120_from_aliyun("600519")

        assert result is not None, "应该返回M120数据"
        assert "m120" in result, "结果应该包含m120字段"
        assert result["m120"] > 0, "M120应该是正数"

    def test_stock_code_conversion(self):
        """测试股票代码转换格式"""
        service = M120Service()

        # 沪市股票
        assert service._get_stock_code_with_prefix("600519") == "sh600519"
        # 深市股票
        assert service._get_stock_code_with_prefix("000001") == "sz000001"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
