"""
股票信息服务
批量查询股票的行业/概念信息
"""
from typing import Optional

import pandas as pd

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class StockInfoService:
    """
    股票信息服务

    功能：
    1. 批量查询股票的申万行业信息
    2. 批量查询股票的概念板块信息
    3. 批量查询股票的行业板块信息
    """

    def __init__(self, data_reader):
        """
        初始化股票信息服务

        Args:
            data_reader: DataReader 实例
        """
        self.data_reader = data_reader

    def get_stocks_info(self, codes: list[str]) -> dict[str, dict]:
        """
        批量获取股票的行业/概念信息

        Args:
            codes: 股票代码列表

        Returns:
            {股票代码: {
                "sw_level1": str,
                "sw_level2": str,
                "sw_level3": str,
                "concept_board": str,
                "industry_board": str,
                "exchange": str,
            }} 字典
        """
        if not codes:
            return {}

        df = self.data_reader.read_csv()

        # 获取第一列（股票代码列）
        code_col = df.columns[0]
        df[code_col] = df[code_col].astype(str).str.zfill(6)

        # 统一转为 6 位字符串匹配
        codes_formatted = [str(c).zfill(6) for c in codes]

        # 筛选
        filtered_df = df[df[code_col].isin(codes_formatted)]

        if filtered_df.empty:
            return {}

        result = {}
        for _, row in filtered_df.iterrows():
            code = str(row[code_col])
            result[code] = {
                "sw_level1": str(row.get("申万一级行业", "")) if pd.notna(row.get("申万一级行业")) else None,
                "sw_level2": str(row.get("申万二级行业", "")) if pd.notna(row.get("申万二级行业")) else None,
                "sw_level3": str(row.get("申万三级行业", "")) if pd.notna(row.get("申万三级行业")) else None,
                "concept_board": str(row.get("概念板块", "")) if pd.notna(row.get("概念板块")) else None,
                "industry_board": str(row.get("行业板块", "")) if pd.notna(row.get("行业板块")) else None,
                "exchange": str(row.get("交易所", "")) if pd.notna(row.get("交易所")) else None,
            }

        return result

    def get_stock_info(self, code: str) -> Optional[dict]:
        """
        获取单只股票的行业/概念信息

        Args:
            code: 股票代码

        Returns:
            股票信息字典，如果不存在返回 None
        """
        result = self.get_stocks_info([code])
        return result.get(code)


# 全局单例
_stock_info_service: StockInfoService | None = None


def get_stock_info_service(data_reader) -> StockInfoService:
    """
    获取股票信息服务单例

    Args:
        data_reader: DataReader 实例

    Returns:
        StockInfoService 实例
    """
    global _stock_info_service
    if _stock_info_service is None:
        _stock_info_service = StockInfoService(data_reader)
    return _stock_info_service