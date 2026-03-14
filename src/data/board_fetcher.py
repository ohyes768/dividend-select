"""
板块映射获取器 - 从红利指数持仓汇总.csv读取股票，查询板块信息并更新映射文件
"""
import time
from collections import defaultdict
from typing import Dict, List, Set, Tuple

import efinance as ef
import pandas as pd

from ..utils.helpers import DATA_DIR, setup_logger, load_csv_data, save_csv_data, get_current_date_dir

logger = setup_logger(__name__)


# 交易所后缀映射
EXCHANGE_SUFFIX_MAP = {
    "沪市主板": ".SH",
    "深市主板": ".SZ",
    "创业板": ".SZ",
    "科创板": ".SH",
}


class BoardMappingFetcher:
    """板块映射获取器"""

    # 需要过滤掉的动态标签（非传统行业/概念）
    DYNAMIC_TAGS_TO_FILTER = {
        "昨日高振幅", "昨日高换手", "昨日涨停", "昨日涨停_含一字",
        "昨日首板", "最近多板",
    }

    def __init__(self):
        """初始化"""
        self.stock_to_concepts: Dict[str, Set[str]] = defaultdict(set)
        self.stock_to_industries: Dict[str, Set[str]] = defaultdict(set)
        self.stock_names: Dict[str, str] = {}
        self.failed_stocks: List[str] = []

        self.holdings_file = DATA_DIR / "红利指数持仓汇总.csv"
        self.output_file = DATA_DIR / "个股板块映射.csv"

    def read_dividend_stocks(self) -> List[Tuple[str, str, str]]:
        """
        从红利指数持仓汇总.csv读取股票列表

        Returns:
            List[Tuple[str, str, str]]: [(股票代码, 股票名称, 交易所), ...]
        """
        logger.info("读取红利指数持仓数据...")

        if not self.holdings_file.exists():
            raise FileNotFoundError(f"文件不存在: {self.holdings_file}")

        df = load_csv_data("红利指数持仓汇总.csv")

        # 检查必要列
        required_columns = ["交易所", "股票代码", "股票名称"]
        for col in required_columns:
            if col not in df.columns:
                raise ValueError(f"CSV文件缺少必要列: {col}")

        stocks = []
        for _, row in df.iterrows():
            exchange = str(row["交易所"]).strip()
            code = str(row["股票代码"]).strip().zfill(6)
            name = str(row["股票名称"]).strip()

            # 记录股票名称
            self.stock_names[code] = name
            stocks.append((code, name, exchange))

        logger.info(f"共读取 {len(stocks)} 只股票")
        return stocks

    def get_stock_base_info(self, code: str, name: str) -> Tuple[List[str], List[str]]:
        """
        获取股票的基本信息（行业板块）

        Args:
            code: 股票代码（6位）
            name: 股票名称

        Returns:
            (概念板块列表, 行业板块列表)
        """
        try:
            # 使用 efinance 获取基本信息
            base_info = ef.stock.get_base_info([code])
            industries = []

            if not base_info.empty:
                row = base_info.iloc[0]

                # 获取所属行业
                if '所属行业' in base_info.columns:
                    industry = row['所属行业']
                else:
                    # 尝试获取第6列（通常是行业）
                    industry = str(row.iloc[5]) if len(row) > 5 else ""

                if pd.notna(industry) and str(industry) != "nan" and str(industry).strip():
                    industries.append(str(industry).strip())

            # 获取概念板块
            concepts = []
            try:
                boards = ef.stock.get_belong_board(code)
                if not boards.empty:
                    for _, board_row in boards.iterrows():
                        board_name = board_row.iloc[3]  # 板块名称列
                        if pd.notna(board_name) and str(board_name) != "nan":
                            name = str(board_name).strip()
                            # 过滤掉动态标签
                            if name not in self.DYNAMIC_TAGS_TO_FILTER:
                                concepts.append(name)
            except Exception as e:
                logger.debug(f"获取概念板块失败: {e}")

            return concepts, industries

        except Exception as e:
            logger.debug(f"获取 {code} {name} 信息失败: {e}")
            return [], []

    def process_boards(self, stocks: List[Tuple[str, str, str]], delay: float = 1.0):
        """
        串行处理所有股票的板块信息

        Args:
            stocks: [(股票代码, 股票名称, 交易所), ...]
            delay: 每次请求间隔（秒）
        """
        logger.info(f"开始获取板块信息，共 {len(stocks)} 只股票...")

        for idx, (code, name, exchange) in enumerate(stocks):
            concepts, industries = self.get_stock_base_info(code, name)

            if concepts or industries:
                # 保存数据
                for concept in concepts:
                    self.stock_to_concepts[code].add(concept)
                for industry in industries:
                    self.stock_to_industries[code].add(industry)

                if (idx + 1) % 50 == 0:
                    logger.info(f"进度: {idx + 1}/{len(stocks)}")
            else:
                self.failed_stocks.append(code)

            # 延时避免请求过快
            if idx < len(stocks) - 1:
                time.sleep(delay)

        logger.info(f"板块信息获取完成: 成功 {len(stocks) - len(self.failed_stocks)} 只，失败 {len(self.failed_stocks)} 只")

        if self.failed_stocks:
            logger.warning(f"失败股票: {', '.join(self.failed_stocks)}")

    def save_to_csv(self, date_str: str | None = None):
        """
        保存板块映射到 CSV

        Args:
            date_str: 日期字符串（YYYY-MM格式），None则使用当前日期
        """
        if date_str is None:
            date_str = get_current_date_dir()

        data = []
        for stock_code in sorted(self.stock_names.keys()):
            stock_name = self.stock_names[stock_code]

            # 获取概念板块，为空则标记为"无"
            concepts = self.stock_to_concepts.get(stock_code, set())
            concept_str = ";".join(sorted(concepts)) if concepts else "无"

            # 获取行业板块，为空则标记为"无"
            industries = self.stock_to_industries.get(stock_code, set())
            industry_str = ";".join(sorted(industries)) if industries else "无"

            data.append({
                "股票代码": stock_code,
                "股票简称": stock_name,
                "概念板块": concept_str,
                "行业板块": industry_str,
            })

        df = pd.DataFrame(data)
        df = df.sort_values("股票代码")

        # 使用 utf-8-sig 编码（UTF-8 with BOM），保存到月度目录
        save_csv_data(df, "个股板块映射.csv", date_str)

        logger.info(f"板块映射已保存到 {date_str}/: {len(df)} 条记录")

        return df

    def update(self, show_progress: bool = True, date_str: str | None = None) -> bool:
        """
        更新板块映射文件

        Args:
            show_progress: 是否显示进度信息
            date_str: 日期字符串（YYYY-MM格式），None则使用当前日期

        Returns:
            是否成功
        """
        if date_str is None:
            date_str = get_current_date_dir()

        try:
            if show_progress:
                logger.info("=" * 60)
                logger.info("开始更新板块映射数据...")
                logger.info("=" * 60)

            # 步骤1: 读取红利指数持仓数据
            stocks = self.read_dividend_stocks()

            if not stocks:
                logger.error("未找到股票数据")
                return False

            # 步骤2: 获取板块信息
            self.process_boards(stocks, delay=1.0)

            # 步骤3: 保存到CSV（传入日期参数）
            df = self.save_to_csv(date_str)

            # 统计信息
            has_concept = df[df["概念板块"] != "无"]
            has_industry = df[df["行业板块"] != "无"]
            has_both = df[(df["概念板块"] != "无") & (df["行业板块"] != "无")]

            logger.info(f"有概念板块: {len(has_concept)} 只 ({len(has_concept)*100//len(df)}%)")
            logger.info(f"有行业板块: {len(has_industry)} 只 ({len(has_industry)*100//len(df)}%)")
            logger.info(f"同时有概念和行业: {len(has_both)} 只 ({len(has_both)*100//len(df)}%)")

            if show_progress:
                logger.info("=" * 60)
                logger.info("板块映射更新完成!")
                logger.info("=" * 60)

            return True

        except Exception as e:
            logger.error(f"更新板块映射失败: {e}")
            return False
