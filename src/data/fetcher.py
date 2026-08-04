"""
数据获取层 - 红利指数持仓获取
"""
import platform
import random
import signal
import time
from collections import defaultdict
from typing import Optional

import akshare as ak
import pandas as pd
import requests

from ..utils.helpers import (
    PROJECT_ROOT,
    DATA_DIR,
    is_main_board,
    get_exchange,
    setup_logger,
    load_csv_data,
    save_csv_data,
)
from .models import StockBasicInfo
from .fhps_fetcher import FHPSFetcher

logger = setup_logger(__name__)

# akshare 调用硬超时（秒）：akshare 内部 requests 默认 timeout=None，
# 中证指数公司限流/挂掉时会无限等待。30 秒超时后 raise，让 replace_one_holdings
# 返回 success=False，前端可标记红色失败状态（用户可继续重试或拉其他指数）
AKSHARE_FETCH_TIMEOUT_SECONDS = 30
# signal.alarm 仅在 Unix 上工作（Docker 部署是 Linux 有效），Windows 本地调试时跳过
_USE_SIGNAL_TIMEOUT = platform.system() != "Windows"


class AkshareFetchTimeout(Exception):
    """akshare 调用超过 AKSHARE_FETCH_TIMEOUT_SECONDS 时抛出"""


def _akshare_timeout_handler(signum, frame):
    raise AkshareFetchTimeout(
        f"akshare 调用超过 {AKSHARE_FETCH_TIMEOUT_SECONDS}s 超时"
    )

# 随机 User-Agent 列表
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
]


# 红利指数配置
# 接口：ak.index_stock_cons_weight_csindex(symbol=)（中证指数公司）
DIVIDEND_INDEXES = {
    "000922": "中证红利",
    "932315": "中证红利质量",
    "932309": "红利增长",
    "931468": "红利质量",
    # 跨交易所扩展（同接口可用）
    "000015": "上证红利",        # 上交所，50 只
    # TODO 名称待确认（原 000824 是"中证国企红利"，换成 000825 后名称可能不同）
    "000825": "中证国企红利",
}

# 走另一个 akshare 接口（ak.index_stock_cons）的指数
# 深交所/国证系列，csindex 接口拿不到
ALT_API_INDEXES = {
    "399324": "深证红利",        # 深交所，40 只
    # TODO 名称待确认（原 H30269 是"红利低波100"，换成 H30089 后名称可能不同）
    "H30089": "红利低波100",     # H 开头=国证系列，走 ak.index_stock_cons
}


class IndexHoldingsFetcher:
    """红利指数持仓获取器"""

    def __init__(self, use_local: bool = False, fhps_fetcher: Optional[FHPSFetcher] = None):
        """
        初始化

        Args:
            use_local: 是否使用本地已有数据（跳过API获取）
            fhps_fetcher: fhps 全市场预案 fetcher；非 None 时 get_stock_list 会前置
                过滤掉"2025 年无分红"的股票（口径与 calculator 内部消费一致）。
                None 时跳过 prefilter（用历史累计筛选结果）。
        """
        self.use_local = use_local
        self._fhps_fetcher = fhps_fetcher
        self.holdings_file = DATA_DIR / "红利指数持仓汇总.csv"
        self.dividend_count_file = DATA_DIR / "股票分红次数汇总.csv"
        # 最近一次 fetch_all_holdings 的逐指数状态（供 routes 层透传给前端徽章）
        self.last_index_results: dict[str, dict] = {}
        # fetch_index_holdings 最近一次失败的错误信息（上层读取用于徽章 tooltip）
        self._last_fetch_error: Optional[str] = None

    def fetch_index_holdings(self, index_code: str) -> Optional[pd.DataFrame]:
        """
        获取单个指数的持仓成分股

        akshare 内部 requests 默认 timeout=None，中证指数公司限流时会无限等。
        用 signal.alarm 加 30 秒硬超时（仅 Unix/Docker 有效，Windows 本地调试时跳过）。

        Args:
            index_code: 指数代码

        Returns:
            DataFrame with columns: 股票代码, 股票名称
        """
        self._last_fetch_error = None  # 进入前清空，便于上层读取最近一次错误

        # 30 秒硬超时（仅 Unix 上生效）
        old_handler = None
        if _USE_SIGNAL_TIMEOUT:
            old_handler = signal.signal(signal.SIGALRM, _akshare_timeout_handler)
            signal.alarm(AKSHARE_FETCH_TIMEOUT_SECONDS)

        try:
            logger.info(f"获取指数 {index_code} 的持仓数据...")

            if index_code in ALT_API_INDEXES:
                # 深交所/国证系列，走 ak.index_stock_cons（无权重）
                df = ak.index_stock_cons(symbol=index_code)
                if df is not None and not df.empty:
                    # 列名兼容：可能是 "品种代码"/"品种名称" 或 "成分券代码"/"成分券名称"
                    df = df.rename(columns={
                        "品种代码": "股票代码",
                        "品种名称": "股票名称",
                        "成分券代码": "股票代码",
                        "成分券名称": "股票名称",
                    })
                    if "股票代码" in df.columns:
                        return df[["股票代码", "股票名称"]]
                    logger.warning(f"{index_code}: ak.index_stock_cons 返回未知列 {list(df.columns)}")
                    return None
            else:
                # 中证系列，走 ak.index_stock_cons_weight_csindex（含权重）
                df = ak.index_stock_cons_weight_csindex(symbol=index_code)

                if df is not None and not df.empty:
                    # 标准化列名
                    df = df.rename(columns={
                        "成分券代码": "股票代码",
                        "成分券名称": "股票名称",
                    })
                    return df[["股票代码", "股票名称"]]

        except AkshareFetchTimeout:
            logger.warning(
                f"获取指数 {index_code} 持仓超时 {AKSHARE_FETCH_TIMEOUT_SECONDS}s"
                f"（akshare 内部 hang，上游接口可能限流）"
            )
            self._last_fetch_error = (
                f"{AKSHARE_FETCH_TIMEOUT_SECONDS}s 超时（中证指数公司接口 hang）"
            )
        except Exception as e:
            logger.error(f"获取指数 {index_code} 持仓失败: {e}")
            self._last_fetch_error = str(e)
        finally:
            # 无论成功还是异常，都取消 alarm 并恢复旧 handler
            if _USE_SIGNAL_TIMEOUT:
                signal.alarm(0)
                if old_handler is not None:
                    signal.signal(signal.SIGALRM, old_handler)

        return None

    def fetch_all_holdings(self) -> pd.DataFrame:
        """
        获取所有红利指数的持仓并汇总

        Returns:
            汇总后的DataFrame
        """
        all_holdings = []

        # 合并所有指数（中证系列 + 深交所系列）
        all_indexes = {**DIVIDEND_INDEXES, **ALT_API_INDEXES}
        self.last_index_results = {}  # 每次全量刷新前清空
        for index_code, index_name in all_indexes.items():
            df = self.fetch_index_holdings(index_code)
            if df is not None and not df.empty:
                df["来源指数"] = index_name
                df["来源指数代码"] = index_code
                all_holdings.append(df)
                logger.info(f"  {index_name}: {len(df)} 只成分股")
                self.last_index_results[index_code] = {
                    "code": index_code,
                    "name": index_name,
                    "success": True,
                    "constituents_count": len(df),
                    "error": None,
                }
            else:
                logger.warning(f"  {index_name}: 获取失败")
                self.last_index_results[index_code] = {
                    "code": index_code,
                    "name": index_name,
                    "success": False,
                    "constituents_count": 0,
                    "error": self._last_fetch_error or "未知错误",
                }
            time.sleep(0.5)  # 避免请求过快

        if not all_holdings:
            return pd.DataFrame()

        # 合并并去重，记录股票出现在几个指数中
        combined = pd.concat(all_holdings, ignore_index=True)

        # 统计每只股票出现的指数数量
        index_count = combined.groupby("股票代码").size().reset_index(name="纳入指数数量")
        combined = combined.drop_duplicates(subset=["股票代码"])
        combined = combined.merge(index_count, on="股票代码")

        # 添加交易所信息
        combined["交易所"] = combined["股票代码"].apply(get_exchange)

        # 重新排列列顺序
        combined = combined[["交易所", "股票代码", "股票名称", "来源指数", "来源指数代码", "纳入指数数量"]]

        return combined

    def replace_one_holdings(self, index_code: str, date_str: str | None = None) -> dict:
        """
        单指数刷新：拉新数据 → 替换汇总 CSV 该指数旧行 → 重算"纳入指数数量"+"交易所" → 写回

        与 fetch_all_holdings 的区别：只拉一个指数，保留其他指数的现有成分股不动。
        适用于"全量刷新后某指数失败 → 用户单独点徽章重试"场景。

        Args:
            index_code: 指数代码
            date_str: 日期字符串（YYYY-MM），None 用当前月

        Returns:
            状态 dict（结构与 last_index_records 单条一致）：
            {code, name, success, constituents_count, error}
        """
        from ..utils.helpers import get_current_date_dir, load_csv_data, save_csv_data

        if date_str is None:
            date_str = get_current_date_dir()

        all_indexes = {**DIVIDEND_INDEXES, **ALT_API_INDEXES}
        if index_code not in all_indexes:
            return {
                "code": index_code, "name": "", "success": False,
                "constituents_count": 0, "error": f"未知指数代码 {index_code}",
            }
        index_name = all_indexes[index_code]

        # 1. 拉新数据
        df_new = self.fetch_index_holdings(index_code)
        if df_new is None or df_new.empty:
            return {
                "code": index_code, "name": index_name, "success": False,
                "constituents_count": 0,
                "error": self._last_fetch_error or "拉取失败（akshare 返回空）",
            }

        df_new = df_new.copy()
        df_new["来源指数"] = index_name
        df_new["来源指数代码"] = index_code

        # 2. 读现有汇总 CSV（load_csv_data 自带当月→历史 fallback）
        existing = load_csv_data("红利指数持仓汇总.csv", date_str)
        if existing is None or existing.empty:
            # 当月没汇总 CSV → 只写该指数（其他指数等下次全量刷新）
            combined = df_new
            logger.info(f"  {index_name}: 当月无汇总 CSV，单指数初始化写入")
        else:
            # 删该指数旧行，append 新行（避免该指数的旧成分股残留）
            existing = existing[existing["来源指数代码"] != index_code]
            combined = pd.concat([existing, df_new], ignore_index=True)

        # 3. 重算"纳入指数数量"和"交易所"（口径与 fetch_all_holdings 完全一致）
        index_count = combined.groupby("股票代码").size().reset_index(name="纳入指数数量")
        combined = combined.drop_duplicates(subset=["股票代码"])
        # CSV 读来的 existing 自带老的"纳入指数数量"列，merge 同名列会被 pandas 改名成 _x/_y
        # 导致最后按原名选列 KeyError，merge 前先 drop 掉
        if "纳入指数数量" in combined.columns:
            combined = combined.drop(columns=["纳入指数数量"])
        combined = combined.merge(index_count, on="股票代码")
        combined["交易所"] = combined["股票代码"].apply(get_exchange)
        combined = combined[["交易所", "股票代码", "股票名称", "来源指数", "来源指数代码", "纳入指数数量"]]

        # 4. 写回当月 CSV
        save_csv_data(combined, "红利指数持仓汇总.csv", date_str)
        logger.info(f"  {index_name}: 单指数刷新完成，{len(df_new)} 只成分股，汇总 CSV 共 {len(combined)} 行")

        return {
            "code": index_code, "name": index_name, "success": True,
            "constituents_count": len(df_new), "error": None,
        }

    def fetch_dividend_count(self, stock_code: str) -> int:
        """
        获取单只股票的历史分红次数

        Args:
            stock_code: 股票代码

        Returns:
            历史累计分红次数
        """
        try:
            df = ak.stock_history_dividend()
            if df is not None and not df.empty:
                # 查找指定股票
                stock_data = df[df["代码"] == stock_code]
                if not stock_data.empty:
                    return int(stock_data.iloc[0]["分红次数"])
        except Exception:
            pass
        return 0

    def fetch_all_dividend_counts(self, stock_list: list[str]) -> dict[str, int]:
        """
        批量获取股票的历史分红次数

        Args:
            stock_list: 股票代码列表

        Returns:
            {股票代码: 分红次数}
        """
        result = {}

        try:
            # 批量获取整个市场的分红数据
            logger.info("  正在获取市场分红数据...")
            df = ak.stock_history_dividend()

            if df is None or df.empty:
                logger.error("  获取分红数据失败")
                return result

            # 将股票代码转换为6位字符串格式
            df["代码"] = df["代码"].apply(lambda x: str(x).zfill(6))

            # 筛选出持仓股票的分红数据
            stock_codes_formatted = [str(c).zfill(6) for c in stock_list]
            filtered_df = df[df["代码"].isin(stock_codes_formatted)]

            # 构建结果字典
            for _, row in filtered_df.iterrows():
                code = row["代码"]
                result[code] = int(row["分红次数"])

            logger.info(f"  成功获取 {len(result)} 只股票的分红次数")

        except Exception as e:
            logger.error(f"  获取分红数据失败: {e}")
            # 失败时逐个获取
            total = len(stock_list)
            for i, code in enumerate(stock_list):
                count = self.fetch_dividend_count(code)
                result[code] = count

                if (i + 1) % 10 == 0:
                    logger.info(f"  分红次数获取进度: {i + 1}/{total}")

                time.sleep(0.3)  # 避免请求过快

        return result

    def get_stock_list(self, min_dividend_count: int = 5, min_yield: float = 2.0, date_str: str | None = None) -> list[StockBasicInfo]:
        """
        获取筛选后的股票列表

        Args:
            min_dividend_count: 最小分红次数阈值
            min_yield: 最小股息率阈值（粗略计算），用于快速筛选
            date_str: 日期字符串（YYYY-MM格式），None则使用当前月份

        Returns:
            筛选后的股票基本信息列表
        """
        from ..utils.helpers import get_current_date_dir

        if date_str is None:
            date_str = get_current_date_dir()

        # Step 1: 获取持仓数据（优先使用本地已有文件）
        holdings_df = load_csv_data("红利指数持仓汇总.csv", date_str)
        if holdings_df is not None and not holdings_df.empty:
            logger.info(f"使用本地持仓数据: {len(holdings_df)} 只股票")
        else:
            if self.use_local:
                logger.error("需要本地持仓数据但文件不存在")
                return []
            logger.info("从API获取持仓数据...")
            holdings_df = self.fetch_all_holdings()
            if holdings_df.empty:
                logger.error("获取持仓数据失败")
                return []
            save_csv_data(holdings_df, "红利指数持仓汇总.csv", date_str)
            logger.info(f"持仓数据已保存到 {date_str}/: {len(holdings_df)} 条")

        # Step 2: 获取分红次数（优先使用本地已有文件）
        dividend_df = load_csv_data("股票分红次数汇总.csv", date_str)
        if dividend_df is not None and not dividend_df.empty:
            logger.info(f"使用本地分红次数数据: {len(dividend_df)} 条")
        else:
            if self.use_local:
                logger.error("需要本地分红次数数据但文件不存在")
                return []
            logger.info("获取分红次数数据...")
            stock_codes = holdings_df["股票代码"].tolist()
            dividend_counts = self.fetch_all_dividend_counts(stock_codes)

            dividend_data = []
            for _, row in holdings_df.iterrows():
                code = row["股票代码"]
                dividend_data.append({
                    "股票代码": code,
                    "股票名称": row["股票名称"],
                    "交易所": row["交易所"],
                    "来源指数": row["来源指数"],
                    "分红次数": dividend_counts.get(code, 0),
                })

            dividend_df = pd.DataFrame(dividend_data)
            save_csv_data(dividend_df, "股票分红次数汇总.csv", date_str)
            logger.info(f"分红次数数据已保存到 {date_str}/: {len(dividend_df)} 条")

        # Step 3: 筛选 - 沪深主板 + 分红次数 > min_dividend_count
        if dividend_df is None or dividend_df.empty:
            logger.error("分红次数数据为空")
            return []

        # 筛选主板
        dividend_df["is_main"] = dividend_df["股票代码"].apply(is_main_board)
        main_board_df = dividend_df[dividend_df["is_main"]].copy()

        # 筛选分红次数
        filtered_df = main_board_df[main_board_df["分红次数"] > min_dividend_count].copy()
        logger.info(f"筛选结果: 主板股票 {len(main_board_df)} 只, 分红>{min_dividend_count}次 {len(filtered_df)} 只")

        # Step 4: 粗略计算股息率筛选（已禁用，因接口访问不稳定）
        # if min_yield > 0 and not self.use_local:
        #     filtered_df = self._filter_by_crude_yield(filtered_df, min_yield)
        #     logger.info(f"粗略股息率筛选(>{min_yield}%): 剩余 {len(filtered_df)} 只股票")

        # Step 4.5（新增）: fhps 预筛 —— 排除"2025 年无分红"的股票
        # 约定：调用方（routes.py / main.py）在 Step 0 先 fhps_fetcher.fetch()，
        # _indexed 一定在内存；口径与 calculator 内部消费一致（同 year_end、同
        # ACCEPTED_PROGRESS_STATUSES），无补漏风险。fhps_fetcher=None 时降级跳过。
        if self._fhps_fetcher is not None:
            n_before = len(filtered_df)
            indexed_codes = set(self._fhps_fetcher._indexed.keys())
            filtered_df = filtered_df[
                filtered_df["股票代码"].astype(str).str.zfill(6).isin(indexed_codes)
            ]
            n_after = len(filtered_df)
            n_filtered = n_before - n_after
            if n_filtered > 0:
                logger.info(
                    f"fhps 预筛: 排除 {n_filtered} 只 2025 年无分红股票（剩 {n_after} 只）"
                )
        else:
            logger.info("fhps_fetcher 未注入，跳过 prefilter（用历史累计筛选结果）")

        # 转换为StockBasicInfo列表
        result = []
        for _, row in filtered_df.iterrows():
            result.append(StockBasicInfo(
                code=str(row["股票代码"]),
                name=row["股票名称"],
                exchange=row["交易所"],
                source_index=row["来源指数"],
                dividend_count=row["分红次数"],
            ))

        return result

    def _filter_by_crude_yield(self, df: pd.DataFrame, min_yield: float) -> pd.DataFrame:
        """
        粗略计算股息率进行筛选

        股息率 ≈ 年均派息(元) / 昨日收盘价(元) × 100

        优先使用 akshare 接口，失败后使用东方财富直调接口

        Args:
            df: 股票DataFrame
            min_yield: 最小股息率阈值

        Returns:
            筛选后的DataFrame
        """
        try:
            logger.info("  获取收盘价和年均派息数据进行粗略股息率筛选...")

            # 获取昨收价格
            close_map = self._get_close_prices()
            if not close_map:
                logger.warning("  获取收盘价数据失败，跳过股息率筛选")
                return df

            # 获取年均派息（akshare 一次性获取）
            yield_map = self._get_annual_yield_map()
            if not yield_map:
                logger.warning("  获取年均派息数据失败，跳过股息率筛选")
                return df

            # 计算粗略股息率并筛选
            filtered = []
            for _, row in df.iterrows():
                code = row["股票代码"]
                close = close_map.get(code)  # 昨收
                annual_yield = yield_map.get(code)  # 年均派息

                if close and annual_yield and close > 0:
                    crude_yield = (annual_yield / close) * 100
                    if crude_yield >= min_yield:
                        filtered.append(row)
                else:
                    # 无法计算时保守保留
                    filtered.append(row)

            result_df = pd.DataFrame(filtered)
            logger.info(f"  粗略股息率筛选完成: {len(result_df)}/{len(df)} 只股票通过")
            return result_df

        except Exception as e:
            logger.error(f"  粗略股息率筛选失败: {e}")
            return df

    def _get_close_prices(self) -> dict[str, float]:
        """
        获取所有股票的昨收价格

        优先使用 akshare，失败后使用东方财富直调接口

        Returns:
            {股票代码: 昨收价格}
        """
        # 方法1: akshare
        try:
            df = ak.stock_zh_a_spot_em()
            if df is not None and not df.empty:
                df["代码"] = df["代码"].astype(str).str.zfill(6)
                logger.info("  使用 akshare 获取昨收价格")
                return dict(zip(df["代码"], df["昨收"]))
        except Exception as e:
            logger.warning(f"  akshare.stock_zh_a_spot_em 失败: {e}")

        # 方法2: 东方财富直调接口
        try:
            logger.info("  使用东方财富直调接口获取昨收价格")
            return self._get_close_prices_from_eastmoney()
        except Exception as e:
            logger.error(f"  东方财富直调也失败: {e}")
            return {}

    def _get_close_prices_from_eastmoney(self) -> dict[str, float]:
        """
        从东方财富获取所有股票的昨收价格

        接口: https://push2.eastmoney.com/api/qt/clist/get
        """
        close_map = {}
        page = 1
        page_size = 500

        while True:
            headers = {
                "User-Agent": random.choice(USER_AGENTS),
                "Referer": "https://finance.eastmoney.com/",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Connection": "keep-alive",
            }

            params = {
                "pn": page,
                "pz": page_size,
                "po": 1,
                "np": 1,
                "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                "fltt": 2,
                "invt": 2,
                "fid": "f3",
                "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
                "fields": "f12,f13,f14,f15,f16,f17,f18",
            }

            try:
                response = requests.get(
                    "https://push2.eastmoney.com/api/qt/clist/get",
                    params=params,
                    headers=headers,
                    timeout=15
                )
                data = response.json()

                if data.get("data") is None:
                    break

                diff = data["data"].get("diff")
                if diff is None:
                    break

                # f12=代码, f17=昨收
                for item in diff:
                    code = str(item.get("f12", "")).zfill(6)
                    close = item.get("f17")
                    if close and close != "-" and code != "000000":
                        try:
                            close_map[code] = float(close)
                        except (ValueError, TypeError):
                            continue

                # 检查是否还有下一页
                if len(diff) < page_size:
                    break
                page += 1
                time.sleep(random.uniform(1.0, 2.0))  # 随机间隔 1-2 秒

            except Exception as e:
                logger.warning(f"  第 {page} 页请求失败: {e}")
                time.sleep(5)  # 失败后等待5秒重试
                continue

        logger.info(f"  东方财富获取收盘价成功: {len(close_map)} 只股票")
        return close_map

    def _get_annual_yield_map(self) -> dict[str, float]:
        """
        获取所有股票的年均派息

        Returns:
            {股票代码: 年均派息}
        """
        try:
            df = ak.stock_history_dividend()
            if df is None or df.empty:
                return {}

            df["代码"] = df["代码"].astype(str).str.zfill(6)
            yield_map = {}
            for _, row in df.iterrows():
                code = row["代码"]
                for col in ["年均派息", "每股派息"]:
                    if col in row.index:
                        try:
                            yield_map[code] = float(row[col])
                            break
                        except (ValueError, TypeError):
                            continue
            logger.info(f"  获取年均派息成功: {len(yield_map)} 只股票")
            return yield_map
        except Exception as e:
            logger.error(f"  获取年均派息失败: {e}")
            return {}
