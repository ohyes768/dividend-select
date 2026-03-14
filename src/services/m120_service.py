"""
M120 服务
负责获取和计算120日均线数据
"""
from datetime import datetime
from pathlib import Path
from typing import Optional

import akshare as ak
import pandas as pd
from pydantic import validate_call

from src.utils.config import AppConfig, PROJECT_ROOT
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class M120Service:
    """
    M120 服务类

    功能：
    1. 从 akshare 获取股票历史价格数据
    2. 计算 120 日均线（MA120）
    3. 获取最新收盘价并计算与 M120 的偏离度
    4. 将 M120 数据存储到 CSV 文件
    5. 读取已存储的 M120 数据
    """

    # M120 数据文件路径
    M120_CSV_FILE = PROJECT_ROOT / "data" / "M120数据.csv"

    @validate_call
    def __init__(self):
        """初始化 M120 服务"""
        self._ensure_data_dir()

    def _ensure_data_dir(self) -> None:
        """确保数据目录存在"""
        self.M120_CSV_FILE.parent.mkdir(parents=True, exist_ok=True)

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

    def calculate_m120(self, code: str) -> Optional[dict]:
        """
        计算单只股票的 120 日均线、最新收盘价和偏离度

        Args:
            code: 6位股票代码

        Returns:
            包含以下字段的字典：
            - m120: 120日均线值
            - close: 最新收盘价
            - deviation: 收盘价与M120的偏离度(%) = (close - m120) / m120 * 100
            失败返回 None
        """
        try:
            # 获取历史数据（前复权），symbol 不需要交易所前缀
            df = ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                adjust="qfq"
            )

            if df.empty or len(df) < 120:
                logger.warning(f"股票 {code} 数据不足120天")
                return None

            # 使用收盘价计算 MA120
            closes = df["收盘"].tail(120)
            m120 = closes.mean()

            # 获取最新收盘价（最后一行）
            latest_close = df.iloc[-1]["收盘"]

            # 计算偏离度
            deviation = (latest_close - m120) / m120 * 100

            result = {
                "m120": round(m120, 2),
                "close": round(latest_close, 2),
                "deviation": round(deviation, 2),
            }

            logger.debug(
                f"股票 {code} M120: {m120:.2f}, 收盘价: {latest_close:.2f}, "
                f"偏离度: {deviation:.2f}%"
            )
            return result

        except Exception as e:
            logger.error(f"计算股票 {code} M120 失败: {e}")
            return None

    def update_m120_data(self, codes: list[str], show_progress: bool = True) -> int:
        """
        批量更新 M120 数据

        Args:
            codes: 股票代码列表
            show_progress: 是否显示进度

        Returns:
            成功更新的数量
        """
        results = []
        total = len(codes)

        for i, code in enumerate(codes, 1):
            if show_progress and i % 10 == 0:
                logger.info(f"进度: {i}/{total}")

            m120_data = self.calculate_m120(code)
            if m120_data is not None:
                results.append({
                    "股票代码": code,
                    "M120": m120_data["m120"],
                    "收盘价": m120_data["close"],
                    "偏离度": m120_data["deviation"],
                })

            # 避免请求过快
            if i < total:
                import time
                time.sleep(0.5)

        # 保存到 CSV
        if results:
            df = pd.DataFrame(results)
            df.to_csv(self.M120_CSV_FILE, index=False, encoding="utf-8-sig")
            logger.info(f"M120 数据已保存到 {self.M120_CSV_FILE}，共 {len(results)} 条")

        return len(results)

    def read_m120_data(self) -> dict[str, dict]:
        """
        读取 M120 数据

        Returns:
            {股票代码: {"m120": float, "close": float, "deviation": float}} 字典
        """
        if not self.M120_CSV_FILE.exists():
            logger.warning(f"M120 数据文件不存在: {self.M120_CSV_FILE}")
            return {}

        try:
            df = pd.read_csv(self.M120_CSV_FILE, encoding="utf-8-sig")
            result = {}
            for _, row in df.iterrows():
                code = str(int(row["股票代码"])).zfill(6)
                result[code] = {
                    "m120": row["M120"],
                    "close": row["收盘价"],
                    "deviation": row["偏离度"],
                }
            return result
        except Exception as e:
            logger.error(f"读取 M120 数据失败: {e}")
            return {}

    def get_file_mtime(self) -> Optional[float]:
        """
        获取 M120 数据文件的修改时间

        Returns:
            Unix 时间戳，文件不存在返回 None
        """
        if self.M120_CSV_FILE.exists():
            return self.M120_CSV_FILE.stat().st_mtime
        return None

    def check_file_exists(self) -> bool:
        """
        检查 M120 数据文件是否存在

        Returns:
            文件是否存在
        """
        return self.M120_CSV_FILE.exists()