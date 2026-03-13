"""
PE 数据获取服务
从 akshare 获取股票 PE/PB 等估值指标数据
"""
from datetime import datetime
from typing import Optional

import akshare as ak
import pandas as pd

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class PEDataService:
    """
    PE 数据获取服务
    """

    def __init__(self):
        self._cache: pd.DataFrame | None = None
        self._cache_timestamp: float | None = None
        self._cache_ttl = 3600  # 缓存有效期（秒，1小时）

    def _is_cache_valid(self) -> bool:
        """检查缓存是否有效"""
        if self._cache is None:
            return False
        if self._cache_timestamp is None:
            return False

        current_time = datetime.now().timestamp()
        return (current_time - self._cache_timestamp) < self._cache_ttl

    def fetch_all_pe_data(self, force_refresh: bool = False) -> pd.DataFrame:
        """
        获取所有 A 股的 PE/PB 数据

        Args:
            force_refresh: 是否强制刷新缓存

        Returns:
            包含 PE/PB 数据的 DataFrame
            列: code, name, pe, pb, market_cap, circulation_market_cap
        """
        # 使用缓存
        if not force_refresh and self._is_cache_valid():
            logger.debug("使用缓存 PE 数据")
            return self._cache

        logger.info("从 akshare 获取 A 股 PE/PB 数据...")
        try:
            df = ak.stock_zh_a_spot_em()

            if df is None or df.empty:
                logger.error("获取 PE 数据失败: 返回数据为空")
                return pd.DataFrame(columns=[
                    "code", "name", "pe", "pb", "market_cap", "circulation_market_cap"
                ])

            # 提取需要的列
            # stock_zh_a_spot_em 返回的列名可能包含中文字符
            result_df = pd.DataFrame()

            # 获取股票代码和名称
            result_df["code"] = df["代码"].str.zfill(6)
            result_df["name"] = df["名称"]

            # PE（市盈率）
            if "市盈率-动态" in df.columns:
                result_df["pe"] = pd.to_numeric(df["市盈率-动态"], errors="coerce")
            elif "市盈率" in df.columns:
                result_df["pe"] = pd.to_numeric(df["市盈率"], errors="coerce")
            else:
                result_df["pe"] = None

            # PB（市净率）
            if "市净率" in df.columns:
                result_df["pb"] = pd.to_numeric(df["市净率"], errors="coerce")
            else:
                result_df["pb"] = None

            # 总市值（万元）
            if "总市值" in df.columns:
                result_df["market_cap"] = pd.to_numeric(
                    df["总市值"], errors="coerce"
                )
            else:
                result_df["market_cap"] = None

            # 流通市值（万元）
            if "流通市值" in df.columns:
                result_df["circulation_market_cap"] = pd.to_numeric(
                    df["流通市值"], errors="coerce"
                )
            else:
                result_df["circulation_market_cap"] = None

            # 更新缓存
            self._cache = result_df
            self._cache_timestamp = datetime.now().timestamp()

            logger.info(f"PE 数据获取成功，共 {len(result_df)} 条记录")
            return result_df

        except Exception as e:
            logger.error(f"获取 PE 数据失败: {e}")
            return pd.DataFrame(columns=[
                "code", "name", "pe", "pb", "market_cap", "circulation_market_cap"
            ])

    def get_pe_by_codes(
        self,
        codes: list[str],
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """
        根据股票代码列表获取 PE 数据

        Args:
            codes: 股票代码列表
            force_refresh: 是否强制刷新缓存

        Returns:
            包含指定股票 PE 数据的 DataFrame
        """
        df = self.fetch_all_pe_data(force_refresh=force_refresh)

        if df.empty:
            return pd.DataFrame(columns=[
                "code", "name", "pe", "pb", "market_cap", "circulation_market_cap"
            ])

        # 统一转为 6 位字符串匹配
        codes_formatted = [str(c).zfill(6) for c in codes]
        result = df[df["code"].isin(codes_formatted)]

        return result

    def get_pe_by_code(
        self,
        code: str,
        force_refresh: bool = False,
    ) -> Optional[pd.Series]:
        """
        根据股票代码获取单只股票的 PE 数据

        Args:
            code: 股票代码
            force_refresh: 是否强制刷新缓存

        Returns:
            股票 PE 数据 Series，如果不存在返回 None
        """
        df = self.get_pe_by_codes([code], force_refresh=force_refresh)

        if df.empty:
            return None

        return df.iloc[0]

    def clear_cache(self):
        """清除缓存"""
        self._cache = None
        self._cache_timestamp = None
        logger.debug("PE 数据缓存已清除")


# 全局单例
_pe_service: PEDataService | None = None


def get_pe_service() -> PEDataService:
    """
    获取 PE 数据服务单例

    Returns:
        PEDataService 实例
    """
    global _pe_service
    if _pe_service is None:
        _pe_service = PEDataService()
    return _pe_service