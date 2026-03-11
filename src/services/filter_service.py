"""
数据筛选服务
"""
from typing import Optional

import pandas as pd

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class FilterService:
    """
    数据筛选服务
    提供按条件筛选数据的功能
    """

    # 股息率列名映射
    YIELD_COLUMNS = {
        "avg_yield_3y": "3年平均股息率(%)",
        "yield_2025": "2025年股息率(%)",
        "yield_2024": "2024年股息率(%)",
        "yield_2023": "2023年股息率(%)",
    }

    def filter_by_yield_range(
        self,
        df: pd.DataFrame,
        min_yield: Optional[float],
        max_yield: Optional[float],
        field: str = "avg_yield_3y"
    ) -> pd.DataFrame:
        """
        按股息率范围筛选

        Args:
            df: 数据 DataFrame
            min_yield: 最小股息率（%）
            max_yield: 最大股息率（%）
            field: 股息率字段（avg_yield_3y, yield_2025, yield_2024, yield_2023）

        Returns:
            筛选后的 DataFrame
        """
        if min_yield is None and max_yield is None:
            return df

        # 获取对应的列名
        col_name = self.YIELD_COLUMNS.get(field)
        if col_name not in df.columns:
            logger.warning(f"股息率列不存在: {col_name}")
            return df

        filtered_df = df.copy()

        # 筛选最小值
        if min_yield is not None:
            # 处理空值和 "-" 标记
            filtered_df[col_name] = pd.to_numeric(
                filtered_df[col_name].replace("-", None),
                errors="coerce"
            )
            filtered_df = filtered_df[
                filtered_df[col_name].fillna(0) >= min_yield
            ]

        # 筛选最大值
        if max_yield is not None:
            filtered_df[col_name] = pd.to_numeric(
                filtered_df[col_name].replace("-", None),
                errors="coerce"
            )
            filtered_df = filtered_df[
                filtered_df[col_name].fillna(999) <= max_yield
            ]

        logger.debug(
            f"股息率筛选: 最小={min_yield}, 最大={max_yield}, "
            f"字段={field}, 结果={len(filtered_df)}条"
        )

        return filtered_df

    def filter_by_exchange(
        self,
        df: pd.DataFrame,
        exchange: Optional[str]
    ) -> pd.DataFrame:
        """
        按交易所筛选

        Args:
            df: 数据 DataFrame
            exchange: 交易所（沪市主板、深市主板）

        Returns:
            筛选后的 DataFrame
        """
        if exchange is None:
            return df

        if "交易所" not in df.columns:
            logger.warning("交易所列不存在")
            return df

        filtered_df = df[df["交易所"] == exchange].copy()

        logger.debug(f"交易所筛选: {exchange}, 结果={len(filtered_df)}条")

        return filtered_df

    def filter_by_industry(
        self,
        df: pd.DataFrame,
        industry: Optional[str]
    ) -> pd.DataFrame:
        """
        按行业筛选（申万一级行业）

        Args:
            df: 数据 DataFrame
            industry: 行业名称

        Returns:
            筛选后的 DataFrame
        """
        if industry is None:
            return df

        if "申万一级行业" not in df.columns:
            logger.warning("申万一级行业列不存在")
            return df

        filtered_df = df[df["申万一级行业"] == industry].copy()

        logger.debug(f"行业筛选: {industry}, 结果={len(filtered_df)}条")

        return filtered_df

    def filter_by_index(
        self,
        df: pd.DataFrame,
        index_name: Optional[str]
    ) -> pd.DataFrame:
        """
        按来源指数筛选

        Args:
            df: 数据 DataFrame
            index_name: 指数名称

        Returns:
            筛选后的 DataFrame
        """
        if index_name is None:
            return df

        if "来源指数" not in df.columns:
            logger.warning("来源指数列不存在")
            return df

        # 支持模糊匹配（因为可能包含多个指数，如"中证红利, 红利增长"）
        filtered_df = df[df["来源指数"].str.contains(index_name, na=False)].copy()

        logger.debug(f"指数筛选: {index_name}, 结果={len(filtered_df)}条")

        return filtered_df