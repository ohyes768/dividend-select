"""
数据模型定义
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List
import json


@dataclass
class StockBasicInfo:
    """股票基本信息"""
    code: str              # 股票代码
    name: str              # 股票名称
    exchange: str          # 交易所（沪市主板/深市主板）
    source_index: str      # 来源指数
    dividend_count: int    # 历史累计分红次数


@dataclass
class YearlyDividendData:
    """年度股息数据"""
    year: int
    avg_price: float           # 年平均股价
    dividend: float            # 年分红金额（元/股）
    dividend_times: int        # 年分红次数
    dividend_yield: float      # 年股息率 (%)


@dataclass
class QuarterlyDividendData:
    """季度股息数据"""
    year: int
    quarter: int               # 1-4
    avg_price: float           # 季度平均股价
    dividend: Optional[float]  # 季度分红金额（元/股），无分红则为None
    dividend_yield: Optional[float]  # 季度股息率 (%)，无分红则为None


@dataclass
class PriceVolatilityData:
    """股价波动数据（2025年）"""
    high_price: float          # 最高价
    low_price: float           # 最低价
    high_change_pct: float     # 最高价相对平均股价涨幅 (%)
    low_change_pct: float      # 最低价相对平均股价跌幅 (%)


@dataclass
class BoardInfo:
    """板块信息"""
    concept_boards: str        # 概念板块（分号分隔）
    industry_boards: str       # 行业板块（分号分隔）
    sw_level1: str             # 申万一级行业
    sw_level2: str             # 申万二级行业
    sw_level3: str             # 申万三级行业


@dataclass
class DividendDetail:
    """单次分红详情"""
    ex_right_date: str    # 除权除息日 YYYY-MM-DD
    payout_ratio: float   # 派息比例（元/股）
    fiscal_year: int      # 财年


@dataclass
class StockResult:
    """单只股票的完整结果"""
    # 基本信息
    code: str
    name: str
    exchange: str
    source_index: str

    # 近3年年度数据
    yearly_data: dict[int, YearlyDividendData] = field(default_factory=dict)
    avg_price_3y: float = 0.0      # 近3年平均股价
    avg_yield_3y: float = 0.0      # 近3年平均股息率

    # 近4季度数据
    quarterly_data: dict[str, QuarterlyDividendData] = field(default_factory=dict)

    # 2025年波动数据
    volatility: Optional[PriceVolatilityData] = None

    # 近5年分红详情（用于TTM计算）
    dividend_details: List[DividendDetail] = field(default_factory=list)

    def to_dict(self) -> dict:
        """转换为字典，用于CSV导出"""
        result = {
            "股票代码": str(self.code).zfill(6),
            "股票名称": self.name,
            "交易所": self.exchange,
            "来源指数": self.source_index,
        }

        # 近3年年度数据
        for year in [2025, 2024, 2023]:
            if year in self.yearly_data:
                yd = self.yearly_data[year]
                result[f"{year}年平均价"] = round(yd.avg_price, 2)
                result[f"{year}年分红(元/股)"] = round(yd.dividend, 2)
                result[f"{year}年分红次数"] = yd.dividend_times
                result[f"{year}年股息率(%)"] = round(yd.dividend_yield, 2)
            else:
                result[f"{year}年平均价"] = ""
                result[f"{year}年分红(元/股)"] = ""
                result[f"{year}年分红次数"] = ""
                result[f"{year}年股息率(%)"] = ""

        result["近3年平均股价"] = round(self.avg_price_3y, 2) if self.avg_price_3y else ""
        result["3年平均股息率(%)"] = round(self.avg_yield_3y, 2) if self.avg_yield_3y else ""

        # 近4季度数据（动态计算前4个已过去季度）
        now = datetime.now()
        current_year = now.year
        current_month = now.month
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

        for y, q in quarter_list:
            quarter_label = f"{y}Q{q}"
            if quarter_label in self.quarterly_data:
                qd = self.quarterly_data[quarter_label]
                result[f"{quarter_label}平均价"] = round(qd.avg_price, 2)
                result[f"{quarter_label}分红(元/股)"] = round(qd.dividend, 2) if qd.dividend else "-"
                result[f"{quarter_label}股息率(%)"] = round(qd.dividend_yield, 2) if qd.dividend_yield else "-"
            else:
                result[f"{quarter_label}平均价"] = ""
                result[f"{quarter_label}分红(元/股)"] = ""
                result[f"{quarter_label}股息率(%)"] = ""

        # 2025年波动数据
        if self.volatility:
            result["2025年最高价"] = round(self.volatility.high_price, 2)
            result["2025年最低价"] = round(self.volatility.low_price, 2)
            result["2025年最高涨幅(%)"] = round(self.volatility.high_change_pct, 2)
            result["2025年最低跌幅(%)"] = round(self.volatility.low_change_pct, 2)
        else:
            result["2025年最高价"] = ""
            result["2025年最低价"] = ""
            result["2025年最高涨幅(%)"] = ""
            result["2025年最低跌幅(%)"] = ""

        # 近5年分红详情（JSON格式）
        if self.dividend_details:
            details_list = [
                {
                    "除权除息日": d.ex_right_date,
                    "派息比例": round(d.payout_ratio, 4),
                    "财年": d.fiscal_year
                }
                for d in self.dividend_details
            ]
            result["近5年分红详情"] = json.dumps(details_list, ensure_ascii=False)
        else:
            result["近5年分红详情"] = ""

        return result
