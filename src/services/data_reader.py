"""
CSV 数据读取服务
"""
from pathlib import Path
from time import time
from typing import Optional

import pandas as pd

from src.utils.config import AppConfig
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class DataReader:
    """
    CSV 数据读取服务
    负责读取股息率数据文件，提供数据访问接口
    """

    def __init__(self):
        self.csv_path = AppConfig.get_csv_file()
        self.encoding = AppConfig.get_encoding()
        self._cache: pd.DataFrame | None = None
        self._cache_timestamp: float | None = None
        self._cache_ttl = 30  # 缓存有效期（秒）

    def check_csv_exists(self) -> bool:
        """检查 CSV 文件是否存在"""
        return self.csv_path.exists()

    def get_total_count(self) -> int:
        """获取总记录数"""
        df = self.read_csv()
        return len(df)

    def get_file_mtime(self) -> float:
        """获取文件修改时间"""
        return self.csv_path.stat().st_mtime

    def _is_cache_valid(self) -> bool:
        """检查缓存是否有效"""
        if self._cache is None:
            return False
        if self._cache_timestamp is None:
            return False

        # 检查文件是否被修改
        current_mtime = self.get_file_mtime()
        return abs(current_mtime - self._cache_timestamp) < 1

    def read_csv(self, force_refresh: bool = False) -> pd.DataFrame:
        """
        读取 CSV 文件

        Args:
            force_refresh: 是否强制刷新缓存

        Returns:
            数据 DataFrame
        """
        if not self.check_csv_exists():
            raise FileNotFoundError(f"数据文件不存在: {self.csv_path}")

        # 使用缓存
        if not force_refresh and self._is_cache_valid():
            logger.debug("使用缓存数据")
            return self._cache

        logger.info(f"读取数据文件: {self.csv_path}")
        try:
            df = pd.read_csv(self.csv_path, encoding=self.encoding)
            self._cache = df
            self._cache_timestamp = self.get_file_mtime()
            logger.info(f"数据加载成功，共 {len(df)} 条记录")
            return df
        except Exception as e:
            logger.error(f"读取 CSV 文件失败: {e}")
            raise

    def get_stock_by_code(self, code: str) -> Optional[pd.Series]:
        """
        根据股票代码获取单只股票数据

        Args:
            code: 股票代码（支持 6 位数字）

        Returns:
            股票数据 Series，如果不存在返回 None
        """
        df = self.read_csv()

        # 获取第一列（股票代码列）
        code_col = df.columns[0]

        # 统一转为 6 位字符串匹配
        code = str(code).zfill(6)
        df[code_col] = df[code_col].astype(str).str.zfill(6)

        row = df[df[code_col] == code]
        if row.empty:
            return None

        return row.iloc[0]

    def clear_cache(self):
        """清除缓存"""
        self._cache = None
        self._cache_timestamp = None
        logger.debug("缓存已清除")