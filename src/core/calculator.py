"""
股息率计算核心模块
"""
import os
import random
import time
from datetime import datetime, date
from typing import Optional, Callable, List

try:
    import urllib.request as urllib2
except ImportError:
    import urllib2

import akshare as ak
import pandas as pd
import requests

from ..utils.helpers import setup_logger
from ..data.models import (
    StockBasicInfo,
    StockResult,
    YearlyDividendData,
    QuarterlyDividendData,
    PriceVolatilityData,
)

logger = setup_logger(__name__)

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

# 全局限流标志
_rate_limited = False
_consecutive_failures = 0
MAX_CONSECUTIVE_FAILURES = 5

# 阿里云行情API配置
ALIYUN_API_HOST = os.getenv("ALIYUN_API_HOST", "http://alirmcom2.market.alicloudapi.com")
ALIYUN_API_PATH = os.getenv("ALIYUN_API_PATH", "/query/comkm")
ALIYUN_API_APPCODE = os.getenv("ALIYUN_API_APPCODE", "404de3caed3742ca897e75ddff633066")


def is_rate_limited() -> bool:
    """检查是否被限流"""
    return _rate_limited


def set_rate_limited():
    """设置限流标志"""
    global _rate_limited
    _rate_limited = True
    logger.warning("=" * 50)
    logger.warning("检测到连续获取失败，已触发限流保护")
    logger.warning("本次处理将跳过，批量数据时请等待一段时间后再试")
    logger.warning("=" * 50)


class DividendCalculator:
    """股息率计算器"""

    def __init__(self):
        self._price_cache: dict[str, pd.DataFrame] = {}
        self._dividend_cache: dict[str, pd.DataFrame] = {}

    def _get_stock_price(self, code: str) -> Optional[pd.DataFrame]:
        """
        获取股票历史价格数据（带缓存）

        使用不复权价格计算股息率（后复权价格会导致股息率被严重低估）

        使用阿里云行情API获取数据
        """
        global _consecutive_failures

        # 检查限流标志
        if is_rate_limited():
            return None

        # 确保code是字符串
        code = str(code).zfill(6)

        if code in self._price_cache:
            _consecutive_failures = 0  # 成功获取，重置计数
            return self._price_cache[code]

        # 使用阿里云行情API获取数据
        try:
            df = self._get_price_from_aliyun(code)
            if df is not None and not df.empty:
                df["日期"] = pd.to_datetime(df["日期"])
                self._price_cache[code] = df
                _consecutive_failures = 0  # 成功，重置计数
                logger.debug(f"{code}: 使用阿里云接口获取价格数据成功")
                return df
        except Exception as e:
            logger.warning(f"{code}: 阿里云接口失败: {e}")

        # 接口失败了
        _consecutive_failures += 1
        logger.warning(f"连续获取失败次数: {_consecutive_failures}/{MAX_CONSECUTIVE_FAILURES}")

        if _consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            set_rate_limited()

        return None

    def _get_price_from_aliyun(self, code: str) -> Optional[pd.DataFrame]:
        """
        从阿里云行情API获取历史K线数据（翻页获取直到2023年1月1日）

        接口: http://alirmcom2.market.alicloudapi.com/query/comkm

        返回格式:
        {
            "Code": 0,
            "Msg": "",
            "Obj": [
                {"C": 8.7, "Tick": 1776009600, "D": "2026-04-13 00:00:00", "O": 8.7, "H": 8.76, "L": 8.6, "A": 503607600, "V": 581357},
                ...
            ]
        }
        - C: close (收盘)
        - O: open (开盘)
        - H: high (最高)
        - L: low (最低)
        - V: volume (成交量)
        - A: amount (成交额)
        - D: date (日期)
        """
        # 转换代码格式: 沪市 6xxxxx -> SH6xxxxx, 深市 0xxxxx -> SZ0xxxxx
        if code.startswith(("6", "5", "9", "7", "8")):
            symbol = f"SH{code}"
        else:
            symbol = f"SZ{code}"

        # 翻页获取数据，直到覆盖到2023年1月1日
        all_records = []
        pidx = 1
        min_date = "2022-01-01"  # 目标开始日期，获取2022年价格数据

        while True:
            querys = f"period=D&pidx={pidx}&psize=500&symbol={symbol}&withlast=0"
            url = f"{ALIYUN_API_HOST}{ALIYUN_API_PATH}?{querys}"

            request = urllib2.Request(url)
            request.add_header("Authorization", f"APPCODE {ALIYUN_API_APPCODE}")

            try:
                response = urllib2.urlopen(request, timeout=15)
                content = response.read()
            except Exception as e:
                logger.warning(f"阿里云API请求失败: {e}")
                return None if not all_records else pd.DataFrame(all_records)

            if not content:
                break

            import json
            data = json.loads(content)

            # 检查API返回状态
            if isinstance(data, dict):
                code_val = data.get("Code")
                if code_val != 0:
                    logger.warning(f"阿里云API返回错误: Code={code_val}, Msg={data.get('Msg', '')}")
                    break
                klines = data.get("Obj", [])
            else:
                break

            if not klines:
                break

            # 解析K线数据
            for item in klines:
                if isinstance(item, dict):
                    date_str = item.get("D", "")
                    if date_str:
                        all_records.append({
                            "日期": date_str,
                            "开盘": float(item.get("O", 0)) if item.get("O") else None,
                            "收盘": float(item.get("C", 0)) if item.get("C") else None,
                            "最高": float(item.get("H", 0)) if item.get("H") else None,
                            "最低": float(item.get("L", 0)) if item.get("L") else None,
                            "成交量": float(item.get("V", 0)) if item.get("V") else None,
                        })

            # 检查是否已到达目标日期（数据按日期倒序返回）
            last_record = all_records[-1] if all_records else None
            if last_record:
                last_date_str = last_record["日期"][:10]  # 取前10个字符 "YYYY-MM-DD"
                if last_date_str <= min_date:
                    # 已到达目标日期，停止翻页
                    break
                elif len(klines) < 500:
                    # 未到达目标日期但数据不足，说明该股票历史数据不够，停止
                    break

            # 如果数据为空，说明已经到头
            if not klines:
                break

            pidx += 1

        if not all_records:
            return None

        df = pd.DataFrame(all_records)
        return df

    def _get_dividend_data(self, code: str) -> Optional[pd.DataFrame]:
        """
        获取指定股票的分红数据

        1. 使用 stock_dividend_cninfo（巨潮资讯，有分红年度）
        2. 使用 stock_history_dividend_detail 补充预案记录（公告日期-1年作为财年）

        带重试机制（3次，间隔3秒）
        """
        code = str(code).zfill(6)

        if code in self._dividend_cache:
            return self._dividend_cache[code]

        # 获取cninfo数据（主要数据源，有财年）
        df = None
        max_retries = 3
        retry_delay = 3  # 秒

        for attempt in range(1, max_retries + 1):
            try:
                raw_df = ak.stock_dividend_cninfo(symbol=code)
                if raw_df is not None and not raw_df.empty:
                    df = raw_df
                    break
            except Exception as e:
                if attempt < max_retries:
                    logger.warning(f"{code} 巨潮资讯接口失败(第{attempt}次): {e}，{retry_delay}秒后重试...")
                    time.sleep(retry_delay)
                else:
                    logger.warning(f"{code} 巨潮资讯接口失败(第{attempt}次): {e}")

            # 如果是最后一次尝试或者有数据但为空，直接退出
            if attempt == max_retries or (df is not None and not df.empty):
                break

        # 解析cninfo数据
        if df is not None and not df.empty:
            # 标准化列名：cninfo接口返回的是"除权日"而非"除权除息日"
            if "除权日" in df.columns:
                df = df.rename(columns={"除权日": "除权除息日"})

            # 解析报告时间中的财年
            def parse_fiscal_year(report_time):
                if pd.isna(report_time):
                    return None
                report_str = str(report_time).strip()
                if len(report_str) >= 4:
                    try:
                        return int(report_str[:4])
                    except ValueError:
                        pass
                return None

            df = df.copy()
            df["财年"] = df["报告时间"].apply(parse_fiscal_year)
            df["_is_cninfo"] = True
            df["_source"] = "cninfo"

        # 获取detail数据（补充预案，公告日期-1年作为财年）
        detail_df = None
        for attempt in range(1, max_retries + 1):
            try:
                detail_raw = ak.stock_history_dividend_detail(symbol=code)
                if detail_raw is not None and not detail_raw.empty:
                    detail_df = detail_raw
                    break
            except Exception as e:
                if attempt < max_retries:
                    time.sleep(retry_delay)
                else:
                    logger.warning(f"{code} detail接口失败(第{attempt}次): {e}")

            if attempt == max_retries or (detail_df is not None and not detail_df.empty):
                break

        # 合并数据
        if detail_df is not None and not detail_df.empty:
            # 确保cninfo数据有效，如果为空则创建空DataFrame
            if df is None or df.empty:
                df = pd.DataFrame(columns=[
                    "实施方案公告日期", "分红类型", "送股比例", "转增比例",
                    "派息比例", "股权登记日", "除权除息日", "派息日",
                    "股份到账日", "实施方案分红说明", "报告时间", "财年", "_is_cninfo", "_source"
                ])

            # 构建cninfo的去重key：用(财年, 报告时间)组合去重，而非单独用除权日
            cninfo_keys = set()
            for _, row in df.iterrows():
                fiscal_year = row.get("财年")
                report_time = row.get("报告时间")
                if fiscal_year is not None and report_time is not None and not pd.isna(fiscal_year):
                    cninfo_keys.add((int(fiscal_year), str(report_time)))

            # 找出detail中状态为"预案"且不在cninfo中的记录
            new_records = []
            for _, row in detail_df.iterrows():
                # 只补充预案记录
                if row["进度"] != "预案":
                    continue

                # 公告日期-1年作为财年
                announce_date = pd.to_datetime(row["公告日期"])
                fiscal_year = announce_date.year - 1
                report_time = f"{fiscal_year}年报(预案)"

                # 用(财年, 报告时间)去重
                if (fiscal_year, report_time) in cninfo_keys:
                    continue

                new_records.append({
                    "实施方案公告日期": row["公告日期"],
                    "分红类型": "预案",
                    "送股比例": row["送股"],
                    "转增比例": row["转增"],
                    "派息比例": row["派息"],
                    "股权登记日": row["股权登记日"],
                    "除权除息日": row["除权除息日"],
                    "派息日": row.get("红股上市日"),
                    "股份到账日": None,
                    "实施方案分红说明": f"预案: 10派{row['派息']}元",
                    "报告时间": report_time,
                    "财年": fiscal_year,
                    "_is_cninfo": True,
                    "_source": "detail",
                })

            if new_records:
                df = pd.concat([df, pd.DataFrame(new_records)], ignore_index=True)
                logger.info(f"{code}: 补充 {len(new_records)} 条预案记录")

        if df is not None and not df.empty:
            self._dividend_cache[code] = df
            return df

        return None

    def calc_yearly_avg_price(self, price_df: pd.DataFrame, year: int) -> float:
        """计算指定年度的平均股价"""
        year_data = price_df[price_df["日期"].dt.year == year]
        if year_data.empty:
            return 0.0
        return year_data["收盘"].mean()

    def calc_quarterly_avg_price(self, price_df: pd.DataFrame, year: int, quarter: int) -> float:
        """计算指定季度的平均股价"""
        # 季度日期范围
        quarter_months = {
            1: [1, 2, 3],
            2: [4, 5, 6],
            3: [7, 8, 9],
            4: [10, 11, 12],
        }
        months = quarter_months[quarter]
        quarter_data = price_df[
            (price_df["日期"].dt.year == year) &
            (price_df["日期"].dt.month.isin(months))
        ]
        if quarter_data.empty:
            return 0.0
        return quarter_data["收盘"].mean()

    def get_yearly_dividend(self, dividend_df: pd.DataFrame, year: int) -> tuple[float, int]:
        """
        获取指定年度的分红数据

        使用巨潮资讯的"报告时间"字段判断财务年度：
        - 报告时间格式："2025年报"、"2025半年报"、"2024三季报"等
        - 直接提取前4位数字作为财年

        Returns:
            (每股分红金额, 分红次数)
        """
        if dividend_df is None or dividend_df.empty:
            return 0.0, 0

        # 获取分红金额（转换为每股派息）
        total_dividend = 0.0
        count = 0

        for _, row in dividend_df.iterrows():
            # 使用预解析的"财年"列进行匹配
            fiscal_year = row.get("财年")
            if fiscal_year is None or fiscal_year != year:
                continue

            # 根据数据源确定派息字段
            # cninfo: 派息比例
            # 新浪: 派息
            if row.get("_is_cninfo", False):
                val = row.get("派息比例")
            else:
                val = row.get("派息")

            try:
                val = float(val)
                # 分红金额是每10股金额，需要除以10转换为每股
                val /= 10
                total_dividend += val
                count += 1
            except (ValueError, TypeError):
                continue

        return total_dividend, count

    def get_ttm_dividend(self, dividend_details: List = None, current_date: Optional[datetime] = None) -> float:
        """
        计算过去12个月滚动分红（TTM）

        Args:
            dividend_details: 分红详情列表（每项包含 ex_right_date, payout_ratio）
            current_date: 参考日期，默认为今天

        Returns:
            每股分红金额
        """
        from datetime import timedelta

        if not dividend_details:
            return 0.0

        if current_date is None:
            current_date = datetime.now()

        one_year_ago = current_date - timedelta(days=365)
        total_dividend = 0.0

        for detail in dividend_details:
            ex_right_str = detail.ex_right_date
            if not ex_right_str:
                continue

            ex_right_dt = pd.to_datetime(ex_right_str)
            if one_year_ago < ex_right_dt <= current_date:
                total_dividend += detail.payout_ratio

        return total_dividend

    def _load_dividend_detail_from_csv(self, code: str) -> Optional[pd.DataFrame]:
        """从本地CSV读取分红详情"""
        from ..utils.helpers import load_csv_data
        from ..utils.helpers import get_current_date_dir

        date_str = get_current_date_dir()
        df = load_csv_data("分红详情.csv", date_str)

        if df is not None and not df.empty:
            # 筛选指定股票（CSV中股票代码是int类型）
            stock_df = df[df["股票代码"] == int(code.zfill(6))]
            if not stock_df.empty:
                logger.info(f"从本地CSV加载 {code} 分红详情: {len(stock_df)} 条")
                return stock_df
        return None

    def _save_dividend_detail(self, code: str, name: str, dividend_df: pd.DataFrame, date_str: str):
        """保存分红详情到CSV（带去重，只保存近5年数据）"""
        if dividend_df is None or dividend_df.empty:
            return

        from ..utils.helpers import append_csv_row, load_csv_data
        from datetime import datetime, timedelta

        # 先加载已有的分红详情，避免重复保存
        existing_df = load_csv_data("分红详情.csv", date_str)
        existing_keys = set()
        if existing_df is not None and not existing_df.empty:
            for _, row in existing_df.iterrows():
                existing_keys.add((str(row["股票代码"]), str(row["除权除息日"])[:10]))

        # 只保存近5年的数据
        five_years_ago = datetime.now() - timedelta(days=365 * 5)

        for _, row in dividend_df.iterrows():
            ex_right_date = row.get("除权除息日")
            if ex_right_date is None or pd.isna(ex_right_date):
                continue

            # 统一转换为 datetime
            if isinstance(ex_right_date, str):
                ex_right_dt = pd.to_datetime(ex_right_date)
            elif isinstance(ex_right_date, datetime):
                ex_right_dt = ex_right_date
            elif isinstance(ex_right_date, date):
                ex_right_dt = datetime.combine(ex_right_date, datetime.min.time())
            else:
                ex_right_dt = pd.to_datetime(ex_right_date)

            # 跳过5年以前的数据
            if ex_right_dt < five_years_ago:
                continue

            ex_right_str = str(ex_right_date)[:10]
            # 去重检查
            if (code, ex_right_str) in existing_keys:
                continue

            # 统一派息字段
            if row.get("_is_cninfo", False):
                payout = row.get("派息比例")
            else:
                payout = row.get("派息")

            row_data = {
                "股票代码": code,
                "股票名称": name,
                "除权除息日": ex_right_str,
                "派息比例(元/股)": float(payout) / 10 if payout else 0,
                "财年": row.get("财年"),
                "报告时间": row.get("报告时间"),
                "数据来源": row.get("_source", "unknown"),
            }
            append_csv_row(row_data, "分红详情", date_str)
            existing_keys.add((code, ex_right_str))  # 添加到已保存集合

    def _extract_recent_dividends(self, dividend_df: pd.DataFrame, years: int = 5) -> List:
        """从分红数据中提取近N年的分红详情"""
        from datetime import datetime, timedelta
        from ..data.models import DividendDetail

        if dividend_df is None or dividend_df.empty:
            return []

        cutoff_date = datetime.now() - timedelta(days=365 * years)
        details = []

        for _, row in dividend_df.iterrows():
            ex_right_date = row.get("除权除息日")
            if ex_right_date is None or pd.isna(ex_right_date):
                continue

            # 转换为 datetime
            if isinstance(ex_right_date, str):
                ex_right_dt = pd.to_datetime(ex_right_date)
            elif isinstance(ex_right_date, datetime):
                ex_right_dt = ex_right_date
            elif isinstance(ex_right_date, date) and not isinstance(ex_right_date, datetime):
                # datetime.date 但不是 datetime（pandas/akshare返回的是date类型）
                ex_right_dt = datetime.combine(ex_right_date, datetime.min.time())
            else:
                continue

            # 跳过 cutoff_date 之前的数据
            if ex_right_dt < cutoff_date:
                continue

            # 提取派息比例
            if row.get("_is_cninfo", False):
                payout = row.get("派息比例")
            else:
                payout = row.get("派息")

            if payout is None or pd.isna(payout):
                continue

            # 每股派息（除以10）
            payout_per_share = float(payout) / 10

            # 提取财年
            fiscal_year = row.get("财年")
            if fiscal_year is None or pd.isna(fiscal_year):
                fiscal_year = ex_right_dt.year

            details.append(DividendDetail(
                ex_right_date=str(ex_right_date)[:10],
                payout_ratio=payout_per_share,
                fiscal_year=int(fiscal_year)
            ))

        return details

    def get_quarterly_dividend(
        self, dividend_df: pd.DataFrame, year: int, quarter: int
    ) -> tuple[Optional[float], int]:
        """
        获取指定季度的分红数据

        使用巨潮资讯的"报告时间"字段判断财务年度

        Returns:
            (每股分红金额 或 None, 分红次数)
        """
        if dividend_df is None or dividend_df.empty:
            return None, 0

        # 季度映射到报告时间关键词
        quarter_keywords = {
            1: "一季报",
            2: "半年报",    # 注意：中报可能是半年报
            3: "三季报",
            4: "年报",
        }
        target_keyword = quarter_keywords.get(quarter, "")

        total_dividend = 0.0
        count = 0

        for _, row in dividend_df.iterrows():
            # 匹配财年
            fiscal_year = row.get("财年")
            if fiscal_year != year:
                continue

            # 匹配季度关键词（仅cninfo数据有"报告时间"字段）
            report_time = str(row.get("报告时间", ""))
            if target_keyword and target_keyword not in report_time:
                continue

            # 根据数据源确定派息字段
            if row.get("_is_cninfo", False):
                val = row.get("派息比例")
            else:
                val = row.get("派息")

            try:
                val = float(val)
                val /= 10
                total_dividend += val
                count += 1
            except (ValueError, TypeError):
                continue

        if count == 0:
            return None, 0

        return total_dividend, count

    def calc_price_volatility(
        self, price_df: pd.DataFrame, year: int, avg_price: float
    ) -> Optional[PriceVolatilityData]:
        """
        计算指定年度的股价波动数据
        """
        year_data = price_df[price_df["日期"].dt.year == year]
        if year_data.empty:
            return None

        high_price = year_data["收盘"].max()
        low_price = year_data["收盘"].min()

        if avg_price <= 0:
            return None

        # 以平均股价为基准计算涨跌幅
        high_change_pct = (high_price - avg_price) / avg_price * 100
        low_change_pct = (avg_price - low_price) / avg_price * 100

        return PriceVolatilityData(
            high_price=high_price,
            low_price=low_price,
            high_change_pct=high_change_pct,
            low_change_pct=low_change_pct,
        )

    def calculate_stock(self, stock: StockBasicInfo) -> Optional[StockResult]:
        """
        计算单只股票的完整数据

        Returns:
            StockResult 或 None（分红数据获取失败时返回None）
        """
        # 获取分红数据（先获取，失败则直接返回None）
        dividend_df = self._get_dividend_data(stock.code)
        if dividend_df is None:
            logger.warning(f"{stock.code} {stock.name}: 无分红数据，跳过")
            return None

        result = StockResult(
            code=stock.code,
            name=stock.name,
            exchange=stock.exchange,
            source_index=stock.source_index,
        )

        # 提取近5年分红详情
        result.dividend_details = self._extract_recent_dividends(dividend_df, years=5)

        # 获取价格数据
        price_df = self._get_stock_price(stock.code)
        if price_df is None or price_df.empty:
            logger.warning(f"{stock.code} {stock.name}: 无价格数据")
            return None

        # 计算近3年年度数据 (2023, 2024, 2025) 用于平均股息率计算
        years_for_avg = [2023, 2024, 2025]
        valid_yields = []
        valid_prices = []

        for year in years_for_avg:
            avg_price = self.calc_yearly_avg_price(price_df, year)
            dividend, times = self.get_yearly_dividend(dividend_df, year)

            if avg_price > 0 and dividend > 0:
                yield_pct = dividend / avg_price * 100
                valid_yields.append(yield_pct)
                valid_prices.append(avg_price)

            result.yearly_data[year] = YearlyDividendData(
                year=year,
                avg_price=avg_price,
                dividend=dividend,
                dividend_times=times,
                dividend_yield=yield_pct if avg_price > 0 and dividend > 0 else 0.0,
            )

        # 计算近3年平均（只取有有效数据的年份）
        if valid_prices:
            result.avg_price_3y = sum(valid_prices) / len(valid_prices)
        if valid_yields:
            result.avg_yield_3y = sum(valid_yields) / len(valid_yields)

        # 计算近4季度数据（动态计算前4个已过去季度）
        now = datetime.now()
        current_year = now.year
        current_month = now.month
        # 当前季度（如果还在发展中则取上一季度作为"最新已完成"）
        current_quarter = (current_month - 1) // 3 + 1

        # 从上一季度开始往前数4个
        quarter_list = []
        q = current_quarter - 1
        y = current_year
        if q == 0:
            q = 4
            y -= 1
        for _ in range(4):
            quarter_list.append((y, q))
            q -= 1
            if q == 0:
                q = 4
                y -= 1

        for year, q in quarter_list:
            avg_price = self.calc_quarterly_avg_price(price_df, year, q)
            dividend, times = self.get_quarterly_dividend(dividend_df, year, q)

            yield_pct = None
            if avg_price > 0 and dividend is not None and dividend > 0:
                yield_pct = dividend / avg_price * 100

            result.quarterly_data[f"{year}Q{q}"] = QuarterlyDividendData(
                year=year,
                quarter=q,
                avg_price=avg_price,
                dividend=dividend,
                dividend_yield=yield_pct,
            )

        # 计算2025年波动数据
        if 2025 in result.yearly_data:
            avg_price_2025 = result.yearly_data[2025].avg_price
            if avg_price_2025 > 0:
                result.volatility = self.calc_price_volatility(price_df, 2025, avg_price_2025)

        return result

    def calculate_all(
        self,
        stock_list: list[StockBasicInfo],
        limit: int = 0,
        on_complete: Optional[Callable[[StockResult], None]] = None,
    ) -> tuple[list[StockResult], list[str]]:
        """
        计算所有股票

        Args:
            stock_list: 股票基本信息列表
            limit: 限制处理的股票数量（0表示不限制）
            on_complete: 每完成一个股票计算的回调函数（仅在成功时调用）

        Returns:
            (计算结果列表, 失败股票代码列表)
        """
        if limit > 0:
            stock_list = stock_list[:limit]

        results = []
        failed_codes = []
        total = len(stock_list)

        for i, stock in enumerate(stock_list):
            logger.info(f"处理 [{i + 1}/{total}] {stock.code} {stock.name}...")

            try:
                result = self.calculate_stock(stock)
                # 只在成功（非None）时添加结果和调用回调
                if result is not None:
                    results.append(result)
                    if on_complete:
                        on_complete(result)
                else:
                    # calculate_stock 返回 None 表示分红数据获取失败
                    failed_codes.append(stock.code)
            except Exception as e:
                logger.error(f"处理 {stock.code} 失败: {e}")
                failed_codes.append(stock.code)

            time.sleep(1.5)  # 避免 akshare 接口限流

        return results, failed_codes
