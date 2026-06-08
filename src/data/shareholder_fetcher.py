"""
股东户数获取器 - 批量获取全市场股东户数数据
"""
import time
from typing import Optional

import akshare as ak
import pandas as pd

from ..utils.helpers import (
    DATA_DIR,
    setup_logger,
    save_csv_data,
    get_current_date_dir,
)

logger = setup_logger(__name__)


class ShareholderFetcher:
    """股东户数获取器"""

    def __init__(self, date_str: Optional[str] = None):
        """
        初始化

        Args:
            date_str: 日期字符串（YYYY-MM格式），None则使用当前日期
        """
        self.date_str = date_str if date_str else get_current_date_dir()
        self.output_file = "股东户数汇总.csv"

    def fetch_all(self, date: Optional[str] = None) -> pd.DataFrame:
        """
        批量获取全市场股东户数

        Args:
            date: 季度末日期（如 '20250630'），None则使用最近季度

        Returns:
            全市场股东户数 DataFrame
        """
        try:
            # 如果未指定日期，使用最近的季度末
            if date is None:
                date = self._get_latest_quarter_date()

            logger.info(f"正在获取 {date} 股东户数数据...")

            df = ak.stock_hold_num_cninfo(date=date)

            if df is None or df.empty:
                logger.error("获取股东户数数据失败")
                return pd.DataFrame()

            # 标准化列名
            df = df.rename(columns={
                "证券代码": "股票代码",
                "证券简称": "股票名称",
                "变动日期": "数据日期",
                "本期股东人数": "股东户数",
                "上期股东人数": "上期股东户数",
                "股东人数增幅": "股东人数增幅",
                "本期人均持股数量": "人均持股数量",
            })

            # 格式化股票代码为6位字符串
            df["股票代码"] = df["股票代码"].astype(str).str.zfill(6)

            # 选择需要的列
            columns = ["股票代码", "股票名称", "股东户数", "上期股东户数",
                       "股东人数增幅", "人均持股数量", "数据日期"]
            available_cols = [col for col in columns if col in df.columns]
            df = df[available_cols]

            logger.info(f"成功获取 {len(df)} 只股票的股东户数数据")

            return df

        except Exception as e:
            logger.error(f"获取股东户数数据失败: {e}")
            return pd.DataFrame()

    def fetch_and_save(self, date: Optional[str] = None) -> bool:
        """
        获取股东户数并保存到CSV

        Args:
            date: 季度末日期

        Returns:
            是否保存成功
        """
        df = self.fetch_all(date)
        if df.empty:
            return False

        try:
            save_csv_data(df, self.output_file, self.date_str)
            logger.info(f"股东户数数据已保存到 {self.date_str}/{self.output_file}")
            return True
        except Exception as e:
            logger.error(f"保存股东户数数据失败: {e}")
            return False

    def filter_by_stocks(self, codes: list[str], date: Optional[str] = None) -> pd.DataFrame:
        """
        获取指定股票的股东户数

        Args:
            codes: 股票代码列表
            date: 季度末日期

        Returns:
            筛选后的 DataFrame
        """
        df = self.fetch_all(date)
        if df.empty:
            return pd.DataFrame()

        codes_formatted = [str(c).zfill(6) for c in codes]
        filtered = df[df["股票代码"].isin(codes_formatted)]

        logger.info(f"筛选出 {len(filtered)} 只股票的股东户数")
        return filtered

    def _get_latest_quarter_date(self) -> str:
        """
        获取最近季度末日期

        Returns:
            格式为 'YYYYMMDD' 的日期字符串
        """
        from datetime import datetime
        now = datetime.now()
        year = now.year
        month = now.month

        # 根据当前月份确定最近季度末
        if month <= 3:
            # 年初，取上一年度Q4
            return f"{year - 1}1231"
        elif month <= 6:
            # Q1末
            return f"{year}0331"
        elif month <= 9:
            # Q2末
            return f"{year}0630"
        else:
            # Q3末
            return f"{year}0930"


def main():
    """主函数 - 获取并保存股东户数数据"""
    fetcher = ShareholderFetcher()

    logger.info("=" * 60)
    logger.info("开始获取股东户数数据...")
    logger.info("=" * 60)

    success = fetcher.fetch_and_save()

    if success:
        logger.info("=" * 60)
        logger.info("股东户数数据获取完成!")
        logger.info("=" * 60)
    else:
        logger.error("股东户数数据获取失败")


if __name__ == "__main__":
    main()