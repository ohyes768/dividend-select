"""
板块映射获取器 - 从红利指数持仓汇总.csv读取股票，查询板块信息并更新映射文件
"""
import time
from collections import defaultdict
from typing import Dict, List, Set, Tuple

import pandas as pd

from ..utils.helpers import DATA_DIR, setup_logger, load_csv_data, get_current_date_dir, get_date_path, get_filename_with_date_suffix
from .board_eastmoney import fetch_boards_for_stock

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

    def __init__(self, date_str: str | None = None):
        """
        初始化

        Args:
            date_str: 日期字符串（YYYY-MM格式），None则使用当前日期
                       仅用于读取红利指数持仓汇总（按月分目录），
                       输出文件改用季度后缀固定路径
        """
        self.stock_to_concepts: Dict[str, Set[str]] = defaultdict(set)
        self.stock_to_industries: Dict[str, Set[str]] = defaultdict(set)
        self.stock_names: Dict[str, str] = {}
        self.failed_stocks: List[str] = []

        self.date_str = date_str if date_str else get_current_date_dir()
        self.holdings_file = get_date_path("红利指数持仓汇总.csv", self.date_str)
        # 输出文件改为季度后缀：data/个股板块映射_YYYYQn.csv
        from ..api.helpers.aux_data import aux_file_path
        self.output_file = aux_file_path("个股板块映射")

    def read_dividend_stocks(self) -> List[Tuple[str, str, str]]:
        """
        从红利指数持仓汇总.csv读取股票列表

        Returns:
            List[Tuple[str, str, str]]: [(股票代码, 股票名称, 交易所), ...]
        """
        logger.info("读取红利指数持仓数据...")

        if not self.holdings_file.exists():
            raise FileNotFoundError(f"文件不存在: {self.holdings_file}")

        df = load_csv_data("红利指数持仓汇总.csv", self.date_str)

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
        获取股票板块信息（行业 + 概念）
        数据源: 东财 emweb CoreConception API（替代 efinance，单只 ~200ms）

        Args:
            code: 股票代码（6位）
            name: 股票名称（未使用，保留签名兼容）

        Returns:
            (概念板块列表, 行业板块列表)
        """
        try:
            return fetch_boards_for_stock(code)
        except Exception as e:
            logger.debug(f"获取 {code} {name} 板块失败: {e}")
            return [], []

    def process_boards(self, stocks: List[Tuple[str, str, str]], delay: float = 0.2):
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

    def save_to_csv(self, date_str: str | None = None, append: bool = False):
        """
        保存板块映射到 CSV（季度后缀固定路径，data/个股板块映射_YYYYQn.csv）

        Args:
            date_str: 已废弃参数（保留签名兼容），不再影响输出路径
            append: 是否追加到现有 CSV（用于增量补缺）
                   - True: 读现有 CSV → 与新数据合并去重 → 写回
                   - False（默认）: 全量覆盖
        """
        from ..api.helpers.aux_data import current_quarter

        new_data = []
        for stock_code in sorted(self.stock_names.keys()):
            stock_name = self.stock_names[stock_code]

            # 获取概念板块，为空则标记为"无"
            concepts = self.stock_to_concepts.get(stock_code, set())
            concept_str = ";".join(sorted(concepts)) if concepts else "无"

            # 获取行业板块，为空则标记为"无"
            industries = self.stock_to_industries.get(stock_code, set())
            industry_str = ";".join(sorted(industries)) if industries else "无"

            new_data.append({
                "股票代码": stock_code,
                "股票简称": stock_name,
                "概念板块": concept_str,
                "行业板块": industry_str,
                "数据季度": current_quarter(),
            })

        new_df = pd.DataFrame(new_data)

        # 边界：本次没拉到任何数据（efinance 全失败）
        if new_df.empty:
            logger.warning("save_to_csv：无新数据可写入，保持现有 CSV 不变")
            if self.output_file.exists():
                return pd.read_csv(self.output_file, encoding="utf-8-sig")
            return new_df

        if append and self.output_file.exists():
            # 追加模式：读现有 CSV，与新数据合并去重（按股票代码）
            try:
                existing_df = pd.read_csv(self.output_file, encoding="utf-8-sig")
                existing_df["股票代码"] = existing_df["股票代码"].astype(str).str.zfill(6)
                # 移除现有 CSV 中要被新数据覆盖的记录
                new_codes = set(new_df["股票代码"].tolist())
                existing_df = existing_df[~existing_df["股票代码"].isin(new_codes)]
                # 合并：新数据在前，现有数据在后
                df = pd.concat([new_df, existing_df], ignore_index=True)
                df = df.sort_values("股票代码").reset_index(drop=True)
                logger.info(f"追加模式：新增 {len(new_df)} 条，合并现有 {len(existing_df)} 条，共 {len(df)} 条")
            except Exception as e:
                logger.warning(f"读取现有 CSV 失败，改用全量覆盖: {e}")
                df = new_df
        else:
            df = new_df.sort_values("股票代码").reset_index(drop=True)

        # 写入季度后缀文件
        self.output_file.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(self.output_file, index=False, encoding="utf-8-sig")

        logger.info(f"板块映射已保存到 {self.output_file}: {len(df)} 条记录")

        return df

    def update(self, show_progress: bool = True, date_str: str | None = None) -> bool:
        """
        更新板块映射文件（全量：所有持仓股票）

        Args:
            show_progress: 是否显示进度信息
            date_str: 已废弃参数（保留签名兼容），不再影响输出路径

        Returns:
            是否成功
        """
        try:
            if show_progress:
                logger.info("=" * 60)
                logger.info("开始更新板块映射数据（全量）...")
                logger.info("=" * 60)

            # 步骤1: 读取红利指数持仓数据
            stocks = self.read_dividend_stocks()

            if not stocks:
                logger.error("未找到股票数据")
                return False

            # 步骤2: 获取板块信息
            self.process_boards(stocks, delay=0.2)

            # 步骤3: 保存到 CSV（全量覆盖）
            df = self.save_to_csv(date_str, append=False)

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

    def update_by_codes(self, codes: List[str], show_progress: bool = True) -> bool:
        """
        按 codes 增量更新板块映射（仅刷新指定股票，复用 process_boards）

        Args:
            codes: 股票代码列表（6位字符串）
            show_progress: 是否显示进度信息

        Returns:
            是否成功
        """
        if not codes:
            logger.warning("update_by_codes 收到空 codes，跳过")
            return True

        try:
            codes_set = {str(c).zfill(6) for c in codes}

            if show_progress:
                logger.info("=" * 60)
                logger.info(f"开始按 codes 增量更新板块映射（{len(codes_set)} 只）...")
                logger.info("=" * 60)

            # 从红利指数持仓数据查 code -> name
            holdings_df = pd.DataFrame()
            if self.holdings_file.exists():
                try:
                    holdings_df = load_csv_data("红利指数持仓汇总.csv", self.date_str)
                except Exception as e:
                    logger.warning(f"读取红利指数持仓数据失败: {e}")

            name_map: Dict[str, str] = {}
            if not holdings_df.empty and "股票代码" in holdings_df.columns and "股票名称" in holdings_df.columns:
                for _, row in holdings_df.iterrows():
                    code = str(row["股票代码"]).strip().zfill(6)
                    name_map[code] = str(row["股票名称"]).strip()

            # 构造 stocks 列表（持仓没有 name 时用空字符串）
            stocks = []
            for code in sorted(codes_set):
                name = name_map.get(code, "")
                stocks.append((code, name, ""))
                # 提前填充 stock_names（process_boards 不会主动加）
                self.stock_names[code] = name

            if not stocks:
                logger.error("未找到有效股票数据")
                return False

            # 复用 process_boards 拉板块
            self.process_boards(stocks, delay=0.2)

            # 追加保存（不覆盖已有记录）
            df = self.save_to_csv(append=True)

            # 统计本次新增（df 可能是空 DataFrame 或缺列）
            if not df.empty and "概念板块" in df.columns:
                has_concept = df[df["概念板块"] != "无"]
                has_industry = df[df["行业板块"] != "无"]
                logger.info(f"本次增量更新：{len(stocks)} 只；现有 CSV 共 {len(df)} 条")
                logger.info(f"有概念板块: {len(has_concept)} 只，有行业板块: {len(has_industry)} 只")
            else:
                logger.info(f"本次增量更新：{len(stocks)} 只（efinance 全部失败，无新数据）")

            if show_progress:
                logger.info("=" * 60)
                logger.info("增量板块映射更新完成!")
                logger.info("=" * 60)

            return True

        except Exception as e:
            logger.error(f"增量更新板块映射失败: {e}")
            return False
