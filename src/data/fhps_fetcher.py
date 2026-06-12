"""
fhps (分红送配) 批量数据获取器
数据源: akshare.stock_fhps_em(date) — 东方财富数据中心
"""
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import akshare as ak
import pandas as pd

from ..utils.helpers import DATA_DIR, setup_logger

logger = setup_logger(__name__)


# 缓存目录: data/fhps/
FHPS_CACHE_DIR = DATA_DIR / "fhps"

# 接受的分红方案进度（含"董事会决议通过"，仅过滤"未通过/已撤销"等）
ACCEPTED_PROGRESS_STATUSES = frozenset({"实施分配", "股东大会决议通过", "董事会决议通过"})


class FHPSFetcher:
    """
    fhps_em 分红送配批量数据获取与缓存。

    行为:
    - fetch() 强制重拉 ak.stock_fhps_em（~30s, 3651 行）→ 写盘 → 重建内存索引
    - get_for_code(code) O(1) 内存查表，过滤 方案进度
    - stats() 供 /dividend/status 报告

    每次 /dividend/refresh 都调用 fetch()，不引入 mtime TTL（用户决策）。
    CSV 写盘仅用于审计/持久化。
    """

    def __init__(self, year_end: str = "20251231"):
        """
        Args:
            year_end: 财报年度结束日 (YYYYMMDD)，如 "20251231" 对应 2025 年报
        """
        self.year_end = year_end
        self.cache_path = FHPS_CACHE_DIR / f"fhps_{year_end}.csv"
        self._df: Optional[pd.DataFrame] = None
        self._indexed: dict[str, pd.DataFrame] = {}

    def fetch(self) -> pd.DataFrame:
        """
        强制从 akshare 拉取全市场分红送配，写盘 + 重建内存索引。

        Returns:
            原始全市场 fhps DataFrame (~3651 rows × 18 cols)

        Raises:
            RuntimeError: 网络失败 / 返回空 / schema 异常
        """
        logger.info(f"开始拉取 fhps 全市场数据: year_end={self.year_end}")
        t0 = time.time()

        try:
            df = ak.stock_fhps_em(date=self.year_end)
        except Exception as e:
            raise RuntimeError(f"ak.stock_fhps_em({self.year_end}) 网络/解析失败: {e}") from e

        elapsed = time.time() - t0
        logger.info(f"ak.stock_fhps_em 返回: {len(df) if df is not None else 0} 行, 耗时 {elapsed:.1f}s")

        if df is None or df.empty:
            raise RuntimeError(
                f"ak.stock_fhps_em({self.year_end}) 返回空数据（接口变更或数据未就绪）"
            )

        df = self._normalize_columns(df)
        df["代码"] = df["代码"].astype(str).str.zfill(6)
        # 财年从 year_end 推断（如 "20251231" → 2025），全市场这一批都是同一财年
        df["财年"] = int(self.year_end[:4])

        # 写盘（审计/持久化用，不参与 TTL 决策）
        FHPS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        df.to_csv(self.cache_path, index=False, encoding="utf-8-sig")
        logger.info(f"fhps 缓存已写入: {self.cache_path}")

        self._df = df
        self._indexed = {}
        self._build_index()
        return df

    def get_for_code(self, code: str) -> pd.DataFrame:
        """
        查指定股票在 fhps 中所有"方案进度可接受"的记录。

        Returns:
            该股票已过滤的 DataFrame（可能为空，**不**抛错）
        """
        if not self._indexed:
            # 内存无索引 → 上层没调过 fetch()，打 WARNING 提示
            logger.warning(
                f"fhps 索引未构建（未调 fetch()），无法查 {code}。请先调用 fhps_fetcher.fetch()"
            )
            return pd.DataFrame()
        code = str(code).zfill(6)
        return self._indexed.get(code, pd.DataFrame())

    def stats(self) -> dict:
        """返回缓存/索引元信息，供 /dividend/status 报告"""
        cache_exists = self.cache_path.exists()
        cache_mtime = (
            datetime.fromtimestamp(self.cache_path.stat().st_mtime).isoformat()
            if cache_exists else None
        )
        return {
            "year_end": self.year_end,
            "cache_path": str(self.cache_path),
            "cache_exists": cache_exists,
            "cache_mtime": cache_mtime,
            "total_rows": len(self._df) if self._df is not None else None,
            "unique_stocks": len(self._indexed),
            "fetched": self._df is not None,
        }

    # ---- private ----

    def _normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """akshare 列名版本兼容: 缺失列填 None（不抛错）"""
        required = [
            "代码", "名称", "送转股份-送转总比例", "送转股份-送股比例", "送转股份-转股比例",
            "现金分红-现金分红比例", "现金分红-股息率", "每股收益", "每股净资产",
            "每股公积金", "每股未分配利润", "净利润同比增长", "总股本",
            "预案公告日", "股权登记日", "除权除息日", "方案进度", "最新公告日期",
        ]
        for col in required:
            if col not in df.columns:
                logger.warning(f"akshare fhps_em 缺少列: {col}（已补 None，不影响本次拉取）")
                df[col] = None
        return df

    def _build_index(self) -> None:
        """构造 code → 已过滤 DataFrame 索引（一次 groupby）"""
        if self._df is None or self._df.empty:
            self._indexed = {}
            return

        # 过滤"未通过/已撤销"等非可接受状态
        mask = self._df["方案进度"].isin(ACCEPTED_PROGRESS_STATUSES)
        n_raw = len(self._df)
        n_skipped = (~mask).sum()
        filtered = self._df[mask].copy()
        filtered = filtered.dropna(subset=["代码"])

        self._indexed = {
            code: group.reset_index(drop=True)
            for code, group in filtered.groupby("代码")
        }
        logger.info(
            f"fhps 索引构建完成: 原始 {n_raw} 行 → 过滤 {n_skipped} 行非可接受状态 → "
            f"索引 {len(filtered)} 行, 覆盖 {len(self._indexed)} 只股票"
        )
