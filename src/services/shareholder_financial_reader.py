"""
CSV 数据读取服务 - 股东户数和财务指标
"""
from pathlib import Path
from typing import Optional

import pandas as pd

from ..utils.helpers import DATA_DIR, setup_logger, get_current_date_dir

logger = setup_logger(__name__)


class ShareholderReader:
    """
    股东户数数据读取服务
    """

    def __init__(self, date_str: Optional[str] = None):
        self.date_str = date_str if date_str else get_current_date_dir()
        self._cache: pd.DataFrame | None = None

    def _get_file_path(self) -> Path:
        """获取文件路径"""
        filename = f"股东户数汇总_{self.date_str}.csv"
        return DATA_DIR / self.date_str / filename

    def check_exists(self) -> bool:
        """检查文件是否存在"""
        return self._get_file_path().exists()

    def read_csv(self) -> pd.DataFrame:
        """读取股东户数数据"""
        filepath = self._get_file_path()
        if not filepath.exists():
            logger.warning(f"股东户数文件不存在: {filepath}")
            return pd.DataFrame()

        try:
            df = pd.read_csv(filepath, encoding="utf-8-sig")
            df["股票代码"] = df["股票代码"].astype(str).str.zfill(6)
            return df
        except Exception as e:
            logger.error(f"读取股东户数数据失败: {e}")
            return pd.DataFrame()

    def get_stock_data(self, code: str) -> Optional[dict]:
        """获取单只股票的股东户数数据"""
        df = self.read_csv()
        if df.empty:
            return None

        code = str(code).zfill(6)
        row = df[df["股票代码"] == code]
        if row.empty:
            return None

        row = row.iloc[0]
        return {
            "shareholder_count": int(row["股东户数"]) if pd.notna(row.get("股东户数")) else None,
            "shareholder_change_pct": float(row["股东人数增幅"]) if pd.notna(row.get("股东人数增幅")) else None,
            "per_share_holding": float(row["人均持股数量"]) if pd.notna(row.get("人均持股数量")) else None,
        }


class FinancialReader:
    """
    财务指标数据读取服务
    """

    def __init__(self, date_str: Optional[str] = None):
        self.date_str = date_str if date_str else get_current_date_dir()
        self._cache: pd.DataFrame | None = None

    def _get_file_path(self) -> Path:
        """获取文件路径"""
        filename = f"财务指标汇总_{self.date_str}.csv"
        return DATA_DIR / self.date_str / filename

    def check_exists(self) -> bool:
        """检查文件是否存在"""
        return self._get_file_path().exists()

    def read_csv(self) -> pd.DataFrame:
        """读取财务指标数据"""
        filepath = self._get_file_path()
        if not filepath.exists():
            logger.warning(f"财务指标文件不存在: {filepath}")
            return pd.DataFrame()

        try:
            df = pd.read_csv(filepath, encoding="utf-8-sig")
            df["股票代码"] = df["股票代码"].astype(str).str.zfill(6)
            return df
        except Exception as e:
            logger.error(f"读取财务指标数据失败: {e}")
            return pd.DataFrame()

    def get_stock_data(self, code: str) -> Optional[dict]:
        """获取单只股票的财务指标数据"""
        df = self.read_csv()
        if df.empty:
            return None

        code = str(code).zfill(6)
        row = df[df["股票代码"] == code]
        if row.empty:
            return None

        row = row.iloc[0]
        return {
            "gross_profit_margin": float(row["主营业务利润率"]) if pd.notna(row.get("主营业务利润率")) else None,
            "net_profit_margin": float(row["净利率"]) if pd.notna(row.get("净利率")) else None,
            "roe": float(row["ROE"]) if pd.notna(row.get("ROE")) else None,
            "debt_asset_ratio": float(row["资产负债率"]) if pd.notna(row.get("资产负债率")) else None,
            "net_profit_ex_non_recurring_yoy": float(row["扣非净利润同比"]) if pd.notna(row.get("扣非净利润同比")) else None,
            "net_profit_cagr_3y": float(row["3年复合增长率"]) if pd.notna(row.get("3年复合增长率")) else None,
            "eps_year": int(row["最新EPS年度"]) if pd.notna(row.get("最新EPS年度")) else None,
            "eps": float(row["最新EPS(元)"]) if pd.notna(row.get("最新EPS(元)")) else None,
        }