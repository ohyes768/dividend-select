"""
数据排序服务
"""
from typing import Literal

import pandas as pd

from src.utils.logger import setup_logger

logger = setup_logger(__name__)

SortOrder = Literal["asc", "desc"]


class SortService:
    """
    数据排序服务
    提供按字段排序数据的功能
    """

    # 支持的排序字段映射（API 字段 -> CSV 列名）
    SORT_FIELDS = {
        "avg_yield_3y": "3年平均股息率(%)",
        "yield_2025": "2025年股息率(%)",
        "yield_2024": "2024年股息率(%)",
        "yield_2023": "2023年股息率(%)",
        "avg_price_3y": "近3年平均股价",
        "dividend_2025": "2025年分红(元/股)",
        "dividend_2024": "2024年分红(元/股)",
        "dividend_2023": "2023年分红(元/股)",
        "high_change_pct_2025": "2025年最高涨幅(%)",
        "low_change_pct_2025": "2025年最低跌幅(%)",
        "high_price_2025": "2025年最高价",
        "low_price_2025": "2025年最低价",
    }

    # 按代码排序（默认）
    DEFAULT_SORT_FIELD = "股票代码"

    @classmethod
    def get_valid_fields(cls) -> list[str]:
        """获取所有有效的排序字段"""
        return list(cls.SORT_FIELDS.keys())

    @classmethod
    def is_valid_field(cls, field: str) -> bool:
        """检查排序字段是否有效"""
        return field in cls.SORT_FIELDS or field == "code"

    @classmethod
    def _get_csv_column_name(cls, field: str) -> str:
        """
        获取 API 字段对应的 CSV 列名

        Args:
            field: API 字段名

        Returns:
            CSV 列名
        """
        # 特殊处理 code 字段
        if field == "code":
            return cls.DEFAULT_SORT_FIELD

        return cls.SORT_FIELDS.get(field, cls.DEFAULT_SORT_FIELD)

    def sort_by_field(
        self,
        df: pd.DataFrame,
        sort_by: str = "avg_yield_3y",
        sort_order: SortOrder = "desc"
    ) -> pd.DataFrame:
        """
        按字段排序

        Args:
            df: 数据 DataFrame
            sort_by: 排序字段（API 字段名）
            sort_order: 排序方向（asc/desc）

        Returns:
            排序后的 DataFrame
        """
        # 获取对应的列名
        col_name = self._get_csv_column_name(sort_by)

        if col_name not in df.columns:
            logger.warning(f"排序列不存在: {col_name}，使用默认排序")
            col_name = self.DEFAULT_SORT_FIELD

        # 复制数据避免修改原始 DataFrame
        sorted_df = df.copy()

        # 对数值列进行处理（处理空值和 "-" 标记）
        if col_name not in ["股票代码", "股票名称", "交易所", "来源指数"]:
            sorted_df[col_name] = pd.to_numeric(
                sorted_df[col_name].replace("-", None),
                errors="coerce"
            )

        # 排序
        ascending = (sort_order == "asc")
        sorted_df = sorted_df.sort_values(
            by=col_name,
            ascending=ascending,
            na_position="last"  # 空值排在最后
        )

        logger.debug(
            f"排序: 字段={sort_by}({col_name}), "
            f"方向={sort_order}, 结果={len(sorted_df)}条"
        )

        return sorted_df.reset_index(drop=True)