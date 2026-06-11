"""
板块信息加载器 - 从本地CSV文件加载板块和行业信息
"""
from pathlib import Path
from typing import Optional

import pandas as pd

from ..api.helpers.aux_data import find_latest_aux_file
from ..utils.helpers import setup_logger
from .models import BoardInfo

logger = setup_logger(__name__)


class BoardInfoLoader:
    """板块信息加载器"""

    def __init__(self, date_str: str | None = None):
        """
        初始化

        Args:
            date_str: 已废弃参数（保留签名兼容），不再影响文件路径
        """
        # 板块和申万行业都改为季度后缀文件：data/{prefix}_YYYYQn.csv
        # 具体路径在 _load_* 中动态 glob 取最新
        self.board_mapping_file: Optional[Path] = None
        self.sw_mapping_file: Optional[Path] = None

        self._board_df: Optional[pd.DataFrame] = None
        self._sw_df: Optional[pd.DataFrame] = None

    def _load_board_mapping(self) -> bool:
        """加载板块映射数据（每次调用动态 glob 最新季度后缀文件）"""
        if self._board_df is not None:
            return True

        # 每次都重新 glob，避免 refresh 后仍读旧文件
        self.board_mapping_file = find_latest_aux_file("个股板块映射")
        if self.board_mapping_file is None or not self.board_mapping_file.exists():
            logger.warning("个股板块映射文件不存在")
            return False

        try:
            self._board_df = pd.read_csv(self.board_mapping_file, encoding="utf-8-sig")
            logger.info(f"板块映射加载成功: {len(self._board_df)} 条 from {self.board_mapping_file.name}")
            return True
        except Exception as e:
            logger.error(f"加载板块映射失败: {e}")
            return False

    def _load_sw_mapping(self) -> bool:
        """加载申万行业映射数据（每次调用动态 glob 最新季度后缀文件）"""
        if self._sw_df is not None:
            return True

        # 每次都重新 glob，避免 refresh 后仍读旧文件
        self.sw_mapping_file = find_latest_aux_file("个股申万行业映射")
        if self.sw_mapping_file is None or not self.sw_mapping_file.exists():
            logger.warning(f"申万行业映射文件不存在")
            return False

        try:
            self._sw_df = pd.read_csv(self.sw_mapping_file, encoding="utf-8-sig")
            # 处理股票代码格式 (001220.SZ -> 001220)
            self._sw_df["股票代码"] = self._sw_df["股票代码"].str.replace(r"\.(SZ|SH)$", "", regex=True)
            logger.info(f"申万行业映射加载成功: {len(self._sw_df)} 条 from {self.sw_mapping_file.name}")
            return True
        except Exception as e:
            logger.error(f"加载申万行业映射失败: {e}")
            return False

    def get_board_info(self, stock_code: str) -> BoardInfo:
        """
        获取股票的板块信息

        Args:
            stock_code: 股票代码

        Returns:
            BoardInfo 对象
        """
        # 统一转换为6位字符串格式
        code_normalized = str(stock_code).zfill(6)

        result = BoardInfo(
            concept_boards="",
            industry_boards="",
            sw_level1="",
            sw_level2="",
            sw_level3="",
        )

        # 获取板块信息
        if self._load_board_mapping() and self._board_df is not None:
            # 确保DataFrame中的代码也是6位格式
            row = self._board_df[self._board_df["股票代码"].astype(str).str.zfill(6) == code_normalized]
            if not row.empty:
                result.concept_boards = str(row.iloc[0].get("概念板块", ""))
                result.industry_boards = str(row.iloc[0].get("行业板块", ""))

        # 获取申万行业信息
        if self._load_sw_mapping() and self._sw_df is not None:
            # 申万映射已经去掉了后缀，直接用6位格式比较
            row = self._sw_df[self._sw_df["股票代码"] == code_normalized]
            if not row.empty:
                result.sw_level1 = str(row.iloc[0].get("一级行业", ""))
                result.sw_level2 = str(row.iloc[0].get("二级行业", ""))
                result.sw_level3 = str(row.iloc[0].get("三级行业", ""))

        return result

    def get_all_board_info(self, stock_codes: list[str]) -> dict[str, BoardInfo]:
        """
        批量获取股票的板块信息

        Args:
            stock_codes: 股票代码列表

        Returns:
            {股票代码: BoardInfo}
        """
        # 预加载所有数据
        self._load_board_mapping()
        self._load_sw_mapping()

        result = {}
        for code in stock_codes:
            result[code] = self.get_board_info(code)

        return result
