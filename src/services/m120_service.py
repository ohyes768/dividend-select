"""
M120 服务
负责获取和计算120日均线数据
"""
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import urllib.request as urllib2
except ImportError:
    import urllib2

import pandas as pd
from pydantic import validate_call

from src.utils.config import AppConfig, PROJECT_ROOT
from src.utils.logger import setup_logger
from src.utils.helpers import get_current_date_dir, DATA_DIR

logger = setup_logger(__name__)

# 阿里云行情API配置（与 calculator.py 保持一致）
ALIYUN_API_HOST = "http://alirmcom2.market.alicloudapi.com"
ALIYUN_API_PATH_HIST = "/query/comkm"  # 历史K线（计算M120用）
ALIYUN_API_PATH_REALTIME = "/query/comrms"  # 批量实时行情
ALIYUN_API_APPCODE = "404de3caed3742ca897e75ddff633066"

# 全局限流标志（与 calculator.py 共用）
_rate_limited = False
_consecutive_failures = 0
MAX_CONSECUTIVE_FAILURES = 5


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


class M120Service:
    """
    M120 服务类

    功能：
    1. 使用阿里云行情API获取股票历史价格数据
    2. 计算 120 日均线（MA120）
    3. 使用 comrms 批量获取实时价格
    4. M120 数据和实时价格分开存储
    5. 读取时实时计算偏离度
    """

    # 数据文件路径
    M120_CSV_FILE = None  # M120均线.csv
    REALTIME_PRICE_CSV_FILE = None  # 实时价格.csv

    @validate_call
    def __init__(self, date_str: str | None = None):
        """
        初始化 M120 服务

        Args:
            date_str: 日期字符串（YYYY-MM格式），None则使用当前日期
        """
        self.date_str = date_str
        self._ensure_data_dir()

    def _ensure_data_dir(self) -> None:
        """确保数据目录存在"""
        if self.M120_CSV_FILE is None:
            date_str = self.date_str if self.date_str else get_current_date_dir()
            self.M120_CSV_FILE = DATA_DIR / date_str / "M120均线.csv"
            self.REALTIME_PRICE_CSV_FILE = DATA_DIR / date_str / "实时价格.csv"
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

    def _get_realtime_prices_batch(self, codes: list[str]) -> dict[str, float]:
        """
        批量获取实时价格（使用 comrms 批量接口）

        Args:
            codes: 股票代码列表

        Returns:
            {股票代码: 实时价格} 字典
        """
        if not codes:
            return {}

        # 转换代码格式: 沪市 6xxxxx -> SH6xxxxx, 深市 0xxxxx -> SZ0xxxxx
        symbols = []
        for code in codes:
            if code.startswith(("6", "5", "9", "7", "8")):
                symbols.append(f"SH{code}")
            else:
                symbols.append(f"SZ{code}")

        # 用逗号分隔多个股票代码
        symbols_str = ",".join(symbols)  # 直接用逗号分隔
        querys = f"symbols={symbols_str}"
        url = f"{ALIYUN_API_HOST}{ALIYUN_API_PATH_REALTIME}?{querys}"

        request = urllib2.Request(url)
        request.add_header("Authorization", f"APPCODE {ALIYUN_API_APPCODE}")

        try:
            response = urllib2.urlopen(request, timeout=15)
            content = response.read()
        except Exception as e:
            logger.warning(f"comrms 批量接口请求失败: {e}")
            return {}

        if not content:
            return {}

        try:
            data = json.loads(content)
        except Exception as e:
            logger.warning(f"comrms 返回 JSON 解析失败: {e}")
            return {}

        # 检查API返回状态
        if isinstance(data, dict):
            code_val = data.get("Code")
            if code_val != 0:
                logger.warning(f"comrms 返回错误: Code={code_val}, Msg={data.get('Msg', '')}")
                return {}
            items = data.get("Obj", [])
            # 调试日志：查看返回的股票代码
            logger.info(f"comrms API 返回: Code={code_val}, Obj数量={len(items)}")
            if len(items) > 0 and len(items) < self.BATCH_SIZE:
                logger.warning(f"返回数量少于请求数量! 请求{self.BATCH_SIZE}只，返回 {len(items)} 只")
                sample = items[0] if items else {}
                logger.warning(f"示例返回: {sample}")
        else:
            return {}

        # 解析返回数据，提取昨日收盘价和实时价格
        # comrms 返回格式: {"C": 股票代码, "N": 名称, "P": 当前价格(实时), "YC": 昨日收盘价, "M": 市场代码, "FS": 完整代码}
        # 注意: comrms 返回的代码格式可能是 "SH601919" 或 "SZ000651"，需要去掉前缀
        result = {}
        for item in items:
            if isinstance(item, dict):
                # 获取股票代码（带 SH/SZ 前缀）
                code_with_prefix = item.get("C", "")
                # 去掉 SH/SZ 前缀，转换为纯数字代码
                code = code_with_prefix
                if code.upper().startswith("SH"):
                    code = code[2:]
                elif code.upper().startswith("SZ"):
                    code = code[2:]
                # 获取昨日收盘价和实时价格
                yc_price = item.get("YC")  # 昨日收盘价
                current_price = item.get("P")  # 当前实时价格

                if code:
                    try:
                        result[code] = {
                            "close": float(yc_price) if yc_price else None,
                            "realtime": float(current_price) if current_price else None,
                        }
                    except (ValueError, TypeError):
                        pass

        logger.info(f"comrms 批量获取实时价格: 请求 {len(codes)} 只，成功 {len(result)} 只")
        return result

    def _get_m120_from_aliyun(self, code: str) -> Optional[dict]:
        """
        从阿里云行情API获取历史K线数据并计算M120

        接口: http://alirmcom2.market.alicloudapi.com/query/comkm
        """
        # 转换代码格式: 沪市 6xxxxx -> SH6xxxxx, 深市 0xxxxx -> SZ0xxxxx
        if code.startswith(("6", "5", "9", "7", "8")):
            symbol = f"SH{code}"
        else:
            symbol = f"SZ{code}"

        # 只需要最近120条数据，不需要翻页
        querys = f"period=D&pidx=1&psize=120&symbol={symbol}&withlast=0"
        url = f"{ALIYUN_API_HOST}{ALIYUN_API_PATH_HIST}?{querys}"

        request = urllib2.Request(url)
        request.add_header("Authorization", f"APPCODE {ALIYUN_API_APPCODE}")

        try:
            response = urllib2.urlopen(request, timeout=15)
            content = response.read()
        except Exception as e:
            logger.warning(f"阿里云API请求失败: {e}")
            return None

        if not content:
            return None

        data = json.loads(content)

        # 检查API返回状态
        if isinstance(data, dict):
            code_val = data.get("Code")
            if code_val != 0:
                logger.warning(f"阿里云API返回错误: Code={code_val}, Msg={data.get('Msg', '')}")
                return None
            klines = data.get("Obj", [])
        else:
            return None

        if not klines or len(klines) < 120:
            logger.warning(f"{code}: 阿里云数据不足120条")
            return None

        # 解析K线数据（数据按日期倒序返回）
        closes = []
        for item in klines[-120:]:  # 取最后120条（最早的120天）
            if isinstance(item, dict) and item.get("C"):
                closes.append(float(item["C"]))

        if len(closes) < 120:
            logger.warning(f"{code}: 有效收盘价不足120天")
            return None

        # 计算M120
        m120 = sum(closes) / len(closes)

        return {
            "m120": round(m120, 2),
        }

    # comrms 批量接口每次最多支持的股票数量（经测试每批约10只）
    BATCH_SIZE = 10

    def update_realtime_prices(self, codes: list[str], show_progress: bool = True) -> int:
        """
        批量更新实时价格（每日调用）

        使用 comrms 批量接口，分批获取所有股票实时价格（每批最多10只）

        Args:
            codes: 股票代码列表
            show_progress: 是否显示进度

        Returns:
            成功更新的数量
        """
        # 确保文件路径已初始化
        if self.REALTIME_PRICE_CSV_FILE is None:
            self._ensure_data_dir()

        logger.info(f"开始批量获取 {len(codes)} 只股票的实时价格...")

        # 分批获取
        all_prices = {}
        total_batches = (len(codes) + self.BATCH_SIZE - 1) // self.BATCH_SIZE

        for i in range(total_batches):
            batch_codes = codes[i * self.BATCH_SIZE:(i + 1) * self.BATCH_SIZE]
            if show_progress:
                logger.info(f"获取第 {i + 1}/{total_batches} 批 ({len(batch_codes)} 只)")

            batch_prices = self._get_realtime_prices_batch(batch_codes)
            all_prices.update(batch_prices)

        if not all_prices:
            logger.warning("实时价格获取失败")
            return 0

        # 保存到 CSV（包含昨日收盘价和实时价格）
        results = []
        date_value = self.date_str if self.date_str else get_current_date_dir()
        for code, price_data in all_prices.items():
            results.append({
                "日期": date_value,
                "股票代码": code,
                "昨日收盘": price_data.get("close"),
                "实时价格": price_data.get("realtime"),
            })

        df = pd.DataFrame(results)
        df.to_csv(self.REALTIME_PRICE_CSV_FILE, index=False, encoding="utf-8-sig")
        logger.info(f"实时价格已保存到 {self.REALTIME_PRICE_CSV_FILE}，共 {len(results)} 条")

        return len(results)

    def update_m120_data(self, codes: list[str], show_progress: bool = True) -> int:
        """
        批量更新 M120 数据（每周调用一次）

        使用 comkm 历史K线接口获取数据计算M120

        Args:
            codes: 股票代码列表
            show_progress: 是否显示进度

        Returns:
            成功更新的数量
        """
        global _consecutive_failures

        # 确保文件路径已初始化
        if self.M120_CSV_FILE is None:
            self._ensure_data_dir()

        results = []
        total = len(codes)
        date_value = self.date_str if self.date_str else get_current_date_dir()

        for i, code in enumerate(codes, 1):
            if show_progress and i % 10 == 0:
                logger.info(f"进度: {i}/{total}")

            # 检查限流标志
            if is_rate_limited():
                break

            m120_data = self._get_m120_from_aliyun(code)
            if m120_data is not None:
                results.append({
                    "日期": date_value,
                    "股票代码": code,
                    "M120": m120_data["m120"],
                })
                _consecutive_failures = 0  # 成功，重置计数
            else:
                _consecutive_failures += 1
                logger.warning(f"连续获取失败次数: {_consecutive_failures}/{MAX_CONSECUTIVE_FAILURES}")

                if _consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    set_rate_limited()
                    break

            # 避免请求过快
            if i < total:
                time.sleep(0.5)

        # 保存到 CSV
        if results:
            df = pd.DataFrame(results)
            df.to_csv(self.M120_CSV_FILE, index=False, encoding="utf-8-sig")
            logger.info(f"M120 均线已保存到 {self.M120_CSV_FILE}，共 {len(results)} 条")

        return len(results)

    def read_m120_with_deviation(self) -> dict[str, dict]:
        """
        读取 M120 数据，并结合实时价格计算偏离度

        Returns:
            {股票代码: {"m120": float, "close": float, "deviation": float}} 字典
        """
        # 确保文件路径已初始化
        if self.M120_CSV_FILE is None or self.REALTIME_PRICE_CSV_FILE is None:
            self._ensure_data_dir()

        # 读取 M120 数据
        if not self.M120_CSV_FILE.exists():
            logger.warning(f"M120 数据文件不存在: {self.M120_CSV_FILE}")
            return {}

        try:
            m120_df = pd.read_csv(self.M120_CSV_FILE, encoding="utf-8-sig")
        except Exception as e:
            logger.error(f"读取 M120 数据失败: {e}")
            return {}

        # 读取实时价格数据（包含昨日收盘和实时价格）
        price_dict = {}
        if self.REALTIME_PRICE_CSV_FILE.exists():
            try:
                price_df = pd.read_csv(self.REALTIME_PRICE_CSV_FILE, encoding="utf-8-sig")
                for _, row in price_df.iterrows():
                    code = str(int(row["股票代码"])).zfill(6)

                    # 兼容新旧CSV格式：新格式有"昨日收盘"和"实时价格"，旧格式只有"收盘价"
                    if "昨日收盘" in price_df.columns:
                        close_val = float(row["昨日收盘"]) if pd.notna(row.get("昨日收盘")) else None
                        realtime_val = float(row["实时价格"]) if pd.notna(row.get("实时价格")) else None
                    else:
                        # 旧格式只有"收盘价"，作为昨日收盘
                        close_val = float(row["收盘价"]) if pd.notna(row.get("收盘价")) else None
                        realtime_val = None

                    price_dict[code] = {
                        "close": close_val,
                        "realtime": realtime_val,
                    }
            except Exception as e:
                logger.error(f"读取实时价格数据失败: {e}")
        else:
            logger.warning(f"实时价格文件不存在，将使用 M120 作为收盘价: {self.REALTIME_PRICE_CSV_FILE}")

        # 合并数据并计算偏离度
        result = {}
        for _, row in m120_df.iterrows():
            code = str(int(row["股票代码"])).zfill(6)
            m120 = float(row["M120"])

            price_data = price_dict.get(code, {})
            close = price_data.get("close")  # 昨日收盘
            realtime = price_data.get("realtime")  # 实时价格

            # 如果没有实时价格，用 M120 代替
            if close is None:
                close = m120
            if realtime is None:
                realtime = close

            # 基于昨日收盘计算偏离度
            deviation = (close - m120) / m120 * 100 if m120 > 0 else 0
            # 基于实时价格计算偏离度
            realtime_deviation = (realtime - m120) / m120 * 100 if m120 > 0 else 0

            result[code] = {
                "m120": m120,
                "close": round(close, 2),
                "realtime": round(realtime, 2),
                "deviation": round(deviation, 2),
                "realtime_deviation": round(realtime_deviation, 2),
            }

        return result

    def read_m120_data(self) -> dict[str, dict]:
        """
        读取 M120 数据（不包含偏离度）

        Returns:
            {股票代码: {"m120": float}} 字典
        """
        # 确保文件路径已初始化
        if self.M120_CSV_FILE is None:
            self._ensure_data_dir()

        if not self.M120_CSV_FILE.exists():
            logger.warning(f"M120 数据文件不存在: {self.M120_CSV_FILE}")
            return {}

        try:
            df = pd.read_csv(self.M120_CSV_FILE, encoding="utf-8-sig")
            result = {}
            for _, row in df.iterrows():
                code = str(int(row["股票代码"])).zfill(6)
                result[code] = {
                    "m120": float(row["M120"]),
                }
            return result
        except Exception as e:
            logger.error(f"读取 M120 数据失败: {e}")
            return {}

    def get_m120_file_mtime(self) -> Optional[float]:
        """获取 M120 数据文件的修改时间"""
        if self.M120_CSV_FILE is None:
            self._ensure_data_dir()
        if self.M120_CSV_FILE.exists():
            return self.M120_CSV_FILE.stat().st_mtime
        return None

    def get_realtime_price_file_mtime(self) -> Optional[float]:
        """获取实时价格数据文件的修改时间"""
        if self.REALTIME_PRICE_CSV_FILE is None:
            self._ensure_data_dir()
        if self.REALTIME_PRICE_CSV_FILE.exists():
            return self.REALTIME_PRICE_CSV_FILE.stat().st_mtime
        return None

    def check_m120_file_exists(self) -> bool:
        """检查 M120 数据文件是否存在"""
        if self.M120_CSV_FILE is None:
            self._ensure_data_dir()
        return self.M120_CSV_FILE.exists()

    def check_realtime_price_file_exists(self) -> bool:
        """检查实时价格数据文件是否存在"""
        if self.REALTIME_PRICE_CSV_FILE is None:
            self._ensure_data_dir()
        return self.REALTIME_PRICE_CSV_FILE.exists()
