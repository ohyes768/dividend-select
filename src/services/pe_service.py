"""
PE 数据获取服务
从 akshare 获取股票 PE/PB 等估值指标数据
"""
from datetime import datetime
from pathlib import Path
from typing import Optional

import akshare as ak
import pandas as pd

from src.utils.config import PROJECT_ROOT
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class PEDataService:
    """
    PE 数据获取服务

    功能：
    1. 从 akshare 获取股票 PE/PB 数据
    2. 将 PE/PB 数据存储到 CSV 文件
    3. 读取已存储的 PE/PB 数据
    """

    # PE 数据文件路径
    PE_CSV_FILE = PROJECT_ROOT / "data" / "PE数据.csv"

    def __init__(self):
        self._ensure_data_dir()

    def _ensure_data_dir(self) -> None:
        """确保数据目录存在"""
        self.PE_CSV_FILE.parent.mkdir(parents=True, exist_ok=True)

    def update_pe_data(self, codes: list[str] | None = None, show_progress: bool = True) -> int:
        """
        更新 PE/PB 数据

        Args:
            codes: 股票代码列表，None 表示更新全部
            show_progress: 是否显示进度

        Returns:
            成功更新的数量
        """
        logger.info("从 akshare 获取 A 股 PE/PB 数据...")
        try:
            df = ak.stock_zh_a_spot_em()

            if df is None or df.empty:
                logger.error("获取 PE 数据失败: 返回数据为空")
                return 0

            # 提取需要的列
            result_df = pd.DataFrame()

            # 获取股票代码和名称
            result_df["股票代码"] = df["代码"].str.zfill(6)
            result_df["股票名称"] = df["名称"]

            # PE（市盈率）
            if "市盈率-动态" in df.columns:
                result_df["PE"] = pd.to_numeric(df["市盈率-动态"], errors="coerce")
            elif "市盈率" in df.columns:
                result_df["PE"] = pd.to_numeric(df["市盈率"], errors="coerce")
            else:
                result_df["PE"] = None

            # PB（市净率）
            if "市净率" in df.columns:
                result_df["PB"] = pd.to_numeric(df["市净率"], errors="coerce")
            else:
                result_df["PB"] = None

            # 总市值（万元）
            if "总市值" in df.columns:
                result_df["总市值"] = pd.to_numeric(df["总市值"], errors="coerce")
            else:
                result_df["总市值"] = None

            # 流通市值（万元）
            if "流通市值" in df.columns:
                result_df["流通市值"] = pd.to_numeric(df["流通市值"], errors="coerce")
            else:
                result_df["流通市值"] = None

            # 筛选指定股票
            if codes:
                codes_formatted = [str(c).zfill(6) for c in codes]
                result_df = result_df[result_df["股票代码"].isin(codes_formatted)]

            # 保存到 CSV
            result_df.to_csv(self.PE_CSV_FILE, index=False, encoding="utf-8-sig")
            logger.info(f"PE 数据已保存到 {self.PE_CSV_FILE}，共 {len(result_df)} 条")

            return len(result_df)

        except Exception as e:
            logger.error(f"更新 PE 数据失败: {e}")
            return 0

    def read_pe_data(self) -> dict[str, dict]:
        """
        读取 PE 数据

        Returns:
            {股票代码: {"pe": float, "pb": float, "market_cap": float, "circulation_market_cap": float}} 字典
        """
        if not self.PE_CSV_FILE.exists():
            logger.warning(f"PE 数据文件不存在: {self.PE_CSV_FILE}")
            return {}

        try:
            df = pd.read_csv(self.PE_CSV_FILE, encoding="utf-8-sig")
            result = {}
            for _, row in df.iterrows():
                code = str(row["股票代码"]).zfill(6)
                result[code] = {
                    "pe": row["PE"] if pd.notna(row["PE"]) else None,
                    "pb": row["PB"] if pd.notna(row["PB"]) else None,
                    "market_cap": row["总市值"] if pd.notna(row["总市值"]) else None,
                    "circulation_market_cap": row["流通市值"] if pd.notna(row["流通市值"]) else None,
                }
            return result
        except Exception as e:
            logger.error(f"读取 PE 数据失败: {e}")
            return {}

    def get_pe_by_codes(
        self,
        codes: list[str],
    ) -> pd.DataFrame:
        """
        根据股票代码列表获取 PE 数据

        Args:
            codes: 股票代码列表

        Returns:
            包含指定股票 PE 数据的 DataFrame
        """
        pe_data = self.read_pe_data()

        if not pe_data:
            return pd.DataFrame(columns=[
                "code", "name", "pe", "pb", "market_cap", "circulation_market_cap"
            ])

        # 统一转为 6 位字符串匹配
        codes_formatted = [str(c).zfill(6) for c in codes]

        # 筛选
        result_data = []
        for code in codes_formatted:
            if code in pe_data:
                data = pe_data[code]
                result_data.append({
                    "code": code,
                    "name": "",  # CSV 中没有名称，可以返回空
                    "pe": data["pe"],
                    "pb": data["pb"],
                    "market_cap": data["market_cap"],
                    "circulation_market_cap": data["circulation_market_cap"],
                })

        if result_data:
            return pd.DataFrame(result_data)
        return pd.DataFrame(columns=[
            "code", "name", "pe", "pb", "market_cap", "circulation_market_cap"
        ])

    def get_pe_by_code(
        self,
        code: str,
    ) -> Optional[pd.Series]:
        """
        根据股票代码获取单只股票的 PE 数据

        Args:
            code: 股票代码

        Returns:
            股票 PE 数据 Series，如果不存在返回 None
        """
        df = self.get_pe_by_codes([code])

        if df.empty:
            return None

        return df.iloc[0]

    def fetch_all_pe_data(self, force_refresh: bool = False) -> pd.DataFrame:
        """
        获取所有 PE 数据（兼容旧接口）

        Args:
            force_refresh: 是否强制刷新（忽略）

        Returns:
            包含 PE/PB 数据的 DataFrame
        """
        # 直接从 CSV 读取
        if not self.PE_CSV_FILE.exists():
            logger.warning(f"PE 数据文件不存在: {self.PE_CSV_FILE}，请先运行 update_pe_data() 生成数据")
            return pd.DataFrame(columns=[
                "code", "name", "pe", "pb", "market_cap", "circulation_market_cap"
            ])

        pe_data = self.read_pe_data()

        if not pe_data:
            return pd.DataFrame(columns=[
                "code", "name", "pe", "pb", "market_cap", "circulation_market_cap"
            ])

        # 转换为 DataFrame
        result_data = []
        for code, data in pe_data.items():
            result_data.append({
                "code": code,
                "name": "",  # CSV 中没有名称
                "pe": data["pe"],
                "pb": data["pb"],
                "market_cap": data["market_cap"],
                "circulation_market_cap": data["circulation_market_cap"],
            })

        return pd.DataFrame(result_data)

    def get_file_mtime(self) -> Optional[float]:
        """
        获取 PE 数据文件的修改时间

        Returns:
            Unix 时间戳，文件不存在返回 None
        """
        if self.PE_CSV_FILE.exists():
            return self.PE_CSV_FILE.stat().st_mtime
        return None

    def check_file_exists(self) -> bool:
        """
        检查 PE 数据文件是否存在

        Returns:
            文件是否存在
        """
        return self.PE_CSV_FILE.exists()


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