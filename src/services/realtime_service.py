"""
实时股价服务
负责获取单只股票的实时收盘价
"""
from typing import Optional

import akshare as ak
import pandas as pd

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class RealtimePriceService:
    """
    实时股价服务类

    功能：
    1. 从 akshare 获取股票实时价格数据
    2. 返回最新收盘价
    """

    def _get_stock_code_with_prefix(self, code: str) -> str:
        """
        获取带交易所前缀的股票代码

        Args:
            code: 6位股票代码

        Returns:
            带前缀的股票代码（如 sh600000 或 sz000001）
        """
        # 沪市主板: 600xxx, 601xxx, 603xxx, 605xxx
        if code.startswith(("600", "601", "603", "605")):
            return f"sh{code}"
        # 深市主板: 000xxx, 001xxx, 002xxx, 003xxx
        elif code.startswith(("000", "001", "002", "003")):
            return f"sz{code}"
        else:
            raise ValueError(f"不支持的股票代码: {code}")

    def get_realtime_close(self, code: str) -> Optional[float]:
        """
        获取单只股票的最新收盘价

        Args:
            code: 6位股票代码

        Returns:
            最新收盘价，失败返回 None
        """
        try:
            # 使用分时数据接口获取最新价格（更快，不需要交易所前缀）
            df = ak.stock_intraday_em(symbol=code)

            if df is None or df.empty:
                logger.warning(f"获取股票 {code} 分时数据失败: 返回数据为空")
                return None

            # 获取最后一行（最新）的成交价
            latest_close = df.iloc[-1]["成交价"]

            if latest_close is None or pd.isna(latest_close):
                logger.warning(f"股票 {code} 最新成交价为空")
                return None

            logger.debug(f"股票 {code} 最新收盘价: {latest_close:.2f}")
            return float(latest_close)

        except Exception as e:
            logger.error(f"获取股票 {code} 实时价格失败: {e}")
            return None

    def calculate_deviation(self, close: float, m120: float) -> Optional[float]:
        """
        根据收盘价和 M120 计算偏离度

        Args:
            close: 最新收盘价
            m120: 120日均线值

        Returns:
            偏离度(%)，失败返回 None
        """
        try:
            if m120 <= 0:
                logger.warning(f"M120 值无效: {m120}")
                return None

            deviation = (close - m120) / m120 * 100
            logger.debug(f"收盘价: {close:.2f}, M120: {m120:.2f}, 偏离度: {deviation:.2f}%")
            return round(deviation, 2)

        except Exception as e:
            logger.error(f"计算偏离度失败: {e}")
            return None


# 全局单例
_realtime_service: RealtimePriceService | None = None


def get_realtime_service() -> RealtimePriceService:
    """
    获取实时股价服务单例

    Returns:
        RealtimePriceService 实例
    """
    global _realtime_service
    if _realtime_service is None:
        _realtime_service = RealtimePriceService()
    return _realtime_service