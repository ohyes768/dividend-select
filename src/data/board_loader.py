"""
板块信息加载器 - 从本地CSV文件加载板块和行业信息
"""
from typing import Optional

import pandas as pd

from ..utils.helpers import DATA_DIR, setup_logger, get_current_date_dir, get_date_path, get_filename_with_date_suffix
from .models import BoardInfo

logger = setup_logger(__name__)


class BoardInfoLoader:
    """板块信息加载器"""

    def __init__(self, date_str: str | None = None):
        """
        初始化

        Args:
            date_str: 日期字符串（YYYY-MM格式），None则使用当前日期
        """
        self.date_str = date_str if date_str else get_current_date_dir()
        self.board_mapping_file = get_date_path("个股板块映射.csv", self.date_str)
        # 申万行业映射文件固定在 data 目录，不带日期后缀
        self.sw_mapping_file = DATA_DIR / "个股申万行业映射.csv"

        self._board_df: Optional[pd.DataFrame] = None
        self._sw_df: Optional[pd.DataFrame] = None

    def _load_board_mapping(self) -> bool:
        """加载板块映射数据"""
        if self._board_df is not None:
            return True

        if not self.board_mapping_file.exists():
            logger.warning(f"板块映射文件不存在: {self.board_mapping_file}")
            return False

        try:
            self._board_df = pd.read_csv(self.board_mapping_file, encoding="utf-8-sig")
            logger.info(f"板块映射加载成功: {len(self._board_df)} 条")
            return True
        except Exception as e:
            logger.error(f"加载板块映射失败: {e}")
            return False

    def _load_sw_mapping(self) -> bool:
        """加载申万行业映射数据"""
        if self._sw_df is not None:
            return True

        if not self.sw_mapping_file.exists():
            logger.warning(f"申万行业映射文件不存在: {self.sw_mapping_file}")
            return False

        try:
            self._sw_df = pd.read_csv(self.sw_mapping_file, encoding="utf-8-sig")
            # 处理股票代码格式 (001220.SZ -> 001220)
            self._sw_df["股票代码"] = self._sw_df["股票代码"].str.replace(r"\.(SZ|SH)$", "", regex=True)
            logger.info(f"申万行业映射加载成功: {len(self._sw_df)} 条")
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
