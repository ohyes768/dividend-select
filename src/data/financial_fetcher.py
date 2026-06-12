"""
财务指标获取器 - 逐只获取股票财务指标数据
"""
import time
from datetime import date
from typing import Optional

import akshare as ak
import pandas as pd

from ..utils.helpers import (
    DATA_DIR,
    setup_logger,
)

# 季度扣非同比的"本期"固定口径（akshare stock_financial_analysis_indicator
# 实际返回到 2026Q1）。选择"全市场固定季度"而非"每只股票最新季度"，
# 是为了让前端展示口径一致（2026Q1 vs 2025Q1 同比）。
QUARTERLY_YOY_REPORT_DATE = date(2026, 3, 31)  # 2026Q1
QUARTERLY_YOY_BASE_DATE = date(2025, 3, 31)    # 2025Q1（去年同期）

logger = setup_logger(__name__)


class FinancialFetcher:
    """财务指标获取器"""

    def __init__(self):
        self.output_file = "财务指标汇总.csv"

    def fetch_one(self, code: str, start_year: Optional[str] = None) -> Optional[dict]:
        """
        获取单只股票的财务指标

        Args:
            code: 股票代码（6位）
            start_year: 起始年份，默认 '2023'

        Returns:
            财务指标字典，如果失败返回 None
        """
        code = str(code).zfill(6)

        if start_year is None:
            start_year = "2022"  # 需要2022年数据计算3年复合增长率

        try:
            df = ak.stock_financial_analysis_indicator(symbol=code, start_year=start_year)

            if df is None or df.empty:
                logger.debug(f"获取 {code} 财务指标失败：无数据")
                return None

            # 按日期降序排列
            df = df.sort_values("日期", ascending=False)
            latest = df.iloc[0]

            # 提取关键指标
            result = {
                "股票代码": code,
                "数据日期": str(latest.get("日期", "")),
                "主营业务利润率": self._safe_float(latest.get("主营业务利润率(%)")),
                "净利率": self._safe_float(latest.get("净利率(%)")),
                "ROE": self._safe_float(latest.get("加权净资产收益率(%)")),
                "资产负债率": self._safe_float(latest.get("资产负债率(%)")),
            }

            # 计算扣非净利润同比增速和3年复合增长率
            growth_metrics = self._calc_growth_metrics(df)
            result.update(growth_metrics)

            # 计算最近一期年报的 EPS（摊薄每股收益），用于后续计算分红比例
            eps_metrics = self._calc_latest_eps(df)
            result.update(eps_metrics)

            # 计算 2026Q1 vs 2025Q1 扣非同比（前端 hover tooltip 用）
            quarterly_metrics = self._calc_quarterly_yoy(df)
            result.update(quarterly_metrics)

            # 添加数据季度
            from ..api.helpers.aux_data import current_quarter
            result["数据季度"] = current_quarter()

            return result

        except Exception as e:
            logger.debug(f"获取 {code} 财务指标失败: {e}")
            return None

    def fetch_batch(self, codes: list[str], delay: float = 0.5, show_progress: bool = True, batch_size: int = 10, on_batch: Optional[callable] = None) -> pd.DataFrame:
        """
        批量获取指定股票的财务指标

        Args:
            codes: 股票代码列表
            delay: 每次请求间隔（秒）
            show_progress: 是否显示进度

        Returns:
            财务指标 DataFrame
        """
        results = []
        total = len(codes)
        failed = 0

        for i, code in enumerate(codes):
            code = str(code).zfill(6)
            result = self.fetch_one(code)

            if result:
                results.append(result)
            else:
                failed += 1

            # 显示进度
            if show_progress and (i + 1) % 10 == 0:
                logger.info(f"财务指标获取进度: {i + 1}/{total}, 失败: {failed}")

            # 每 batch_size 个或最后一批，保存一次
            if (i + 1) % batch_size == 0 or i == total - 1:
                if results:
                    df_batch = pd.DataFrame(results)
                    if on_batch:
                        on_batch(df_batch)
                    # 清空已保存的结果
                    results = []

            # 请求间隔
            if i < total - 1:
                time.sleep(delay)

        if show_progress:
            logger.info(f"财务指标获取完成: 成功 {len(results)}/{total}, 失败 {failed}")

        if not results:
            return pd.DataFrame()

        df = pd.DataFrame(results)
        return df

    def fetch_and_save(self, codes: list[str], delay: float = 0.5) -> bool:
        """
        获取财务指标并保存到CSV（根目录固定路径）

        Args:
            codes: 股票代码列表
            delay: 每次请求间隔（秒）

        Returns:
            是否保存成功
        """
        df = self.fetch_batch(codes, delay=delay)
        if df.empty:
            return False

        try:
            from ..api.helpers.aux_data import aux_file_path
            output_path = aux_file_path("财务指标汇总")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(output_path, index=False, encoding="utf-8-sig")
            logger.info(f"财务指标数据已保存到 {output_path}，共 {len(df)} 条")
            return True
        except Exception as e:
            logger.error(f"保存财务指标数据失败: {e}")
            return False

    @staticmethod
    def _safe_float(value) -> Optional[float]:
        """安全转换为 float"""
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    def _calc_latest_eps(self, df: pd.DataFrame) -> dict:
        """
        计算最近一期年报的基本每股收益（EPS）

        取 akshare 的"加权每股收益(元)"，与"摊薄每股收益(元)"的差异：
        摊薄EPS 在年内大额回购注销场景下会显著偏高（分母被注销后股本拉低），
        与"每股分红"的口径不一致，导致分红比例计算失真（如华特达因 2024 年）。

        Args:
            df: 财务指标 DataFrame

        Returns:
            {
                "最新EPS年度": int 或 None,   # 例如 2024
                "最新EPS(元)": float 或 None, # 例如 1.20；亏损股保留负值
            }
        """
        year_end_df = df[df["日期"].astype(str).str.contains("12-31")].sort_values("日期", ascending=False)

        if year_end_df.empty:
            return {"最新EPS年度": None, "最新EPS(元)": None}

        latest = year_end_df.iloc[0]
        eps_date = str(latest.get("日期", ""))
        year = int(eps_date[:4]) if len(eps_date) >= 4 else None
        return {
            "最新EPS年度": year,
            "最新EPS(元)": self._safe_float(latest.get("加权每股收益(元)")),
        }

    def _calc_quarterly_yoy(self, df: pd.DataFrame) -> dict:
        """
        计算固定季度（2026Q1 vs 2025Q1）的扣非净利润同比

        固定取全市场 2026Q1 口径（QUARTERLY_YOY_REPORT_DATE = 2026-03-31），
        让前端展示口径一致。新股或未发布该季报的股票返回 None。

        Args:
            df: 财务指标 DataFrame（已按日期降序排列）

        Returns:
            {
                "最新季度扣非(元)": float 或 None,         # 2026Q1 扣非绝对值
                "最新季度扣非同比(%)": float 或 None,      # (2026Q1-2025Q1) / abs(2025Q1) * 100
            }
        """
        col = "扣除非经常性损益后的净利润(元)"
        dates = pd.to_datetime(df["日期"]).dt.date
        report_row = df[dates == QUARTERLY_YOY_REPORT_DATE]
        base_row = df[dates == QUARTERLY_YOY_BASE_DATE]

        if report_row.empty:
            return {"最新季度扣非(元)": None, "最新季度扣非同比(%)": None}

        report_value = self._safe_float(report_row.iloc[0][col])

        if base_row.empty:
            return {"最新季度扣非(元)": report_value, "最新季度扣非同比(%)": None}

        base_value = self._safe_float(base_row.iloc[0][col])
        if base_value is None or base_value == 0 or report_value is None:
            return {"最新季度扣非(元)": report_value, "最新季度扣非同比(%)": None}

        yoy = (report_value - base_value) / abs(base_value) * 100
        return {
            "最新季度扣非(元)": report_value,
            "最新季度扣非同比(%)": round(yoy, 2),
        }

    def _calc_growth_metrics(self, df: pd.DataFrame) -> dict:
        """
        计算扣非净利润同比增速和3年复合增长率

        Args:
            df: 财务指标 DataFrame（已按日期降序排列）

        Returns:
            包含扣非净利润同比和3年复合增长率的字典
        """
        # 取年末数据（12-31）进行计算，按日期降序（最新年份在前）
        year_end_df = df[df["日期"].astype(str).str.contains("12-31")].sort_values("日期", ascending=False)

        if len(year_end_df) < 2:
            return {
                "扣非净利润同比": None,
                "3年复合增长率": None,
            }

        # 获取近3年年末扣非净利润（降序排列，最新在前）
        col = "扣除非经常性损益后的净利润(元)"
        values = year_end_df[col].tolist()

        # 最新年份的值（降序排列后 values[0] 是最新年份）
        latest_value = self._safe_float(values[0])

        # 计算同比增速（当年 vs 上年）
        yoy_growth = None
        if len(values) >= 2 and values[1] != 0:
            prev_value = self._safe_float(values[1])
            if prev_value is not None and prev_value != 0:
                yoy_growth = (latest_value - prev_value) / abs(prev_value) * 100

        # 计算3年复合增长率 (CAGR)
        cagr_3y = None
        if len(values) >= 3:
            start_value = self._safe_float(values[2])   # 3年前
            end_value = self._safe_float(values[0])     # 今年
            if start_value and end_value and not (start_value <= 0 or end_value <= 0):
                cagr_3y = ((end_value / start_value) ** (1 / 2) - 1) * 100

        return {
            "扣非净利润同比": round(yoy_growth, 2) if yoy_growth is not None else None,
            "3年复合增长率": round(cagr_3y, 2) if cagr_3y is not None else None,
        }


# 导入 numpy 用于 NaN 检查
import numpy as np


def main():
    """主函数 - 获取并保存财务指标数据"""
    from ..utils.helpers import get_current_date_dir

    # 从股息率CSV读取股票代码
    date_str = get_current_date_dir()
    dividend_file = DATA_DIR / date_str / f"近3年股息率汇总_{date_str}.csv"

    if not dividend_file.exists():
        logger.error(f"股息率数据文件不存在: {dividend_file}")
        return

    df = pd.read_csv(dividend_file, encoding="utf-8-sig")
    codes = df["股票代码"].astype(str).str.zfill(6).tolist()

    logger.info(f"从 {dividend_file} 读取了 {len(codes)} 只股票")

    fetcher = FinancialFetcher()

    logger.info("=" * 60)
    logger.info("开始获取财务指标数据...")
    logger.info("=" * 60)

    success = fetcher.fetch_and_save(codes)

    if success:
        logger.info("=" * 60)
        logger.info("财务指标数据获取完成!")
        logger.info("=" * 60)
    else:
        logger.error("财务指标数据获取失败")


if __name__ == "__main__":
    main()