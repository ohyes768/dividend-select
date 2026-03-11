"""
API 数据模型
定义请求和响应的 Pydantic 模型
"""
from typing import Optional

from pydantic import BaseModel, Field


# ========== 基础数据模型 ==========


class DividendStock(BaseModel):
    """
    股息率股票数据模型
    """
    # 基础信息
    code: str = Field(..., description="股票代码")
    name: str = Field(..., description="股票名称")
    exchange: str = Field(..., description="交易所")
    source_index: Optional[str] = Field(None, description="来源指数")
    sw_level1: Optional[str] = Field(None, description="申万一级行业")
    sw_level2: Optional[str] = Field(None, description="申万二级行业")
    sw_level3: Optional[str] = Field(None, description="申万三级行业")
    concept_board: Optional[str] = Field(None, description="概念板块")
    industry_board: Optional[str] = Field(None, description="行业板块")

    # 2025 年数据
    avg_price_2025: Optional[float] = Field(None, description="2025年平均价")
    dividend_2025: Optional[float] = Field(None, description="2025年分红(元/股)")
    dividend_count_2025: Optional[int] = Field(None, description="2025年分红次数")
    yield_2025: Optional[float] = Field(None, description="2025年股息率(%)")

    # 2024 年数据
    avg_price_2024: Optional[float] = Field(None, description="2024年平均价")
    dividend_2024: Optional[float] = Field(None, description="2024年分红(元/股)")
    dividend_count_2024: Optional[int] = Field(None, description="2024年分红次数")
    yield_2024: Optional[float] = Field(None, description="2024年股息率(%)")

    # 2023 年数据
    avg_price_2023: Optional[float] = Field(None, description="2023年平均价")
    dividend_2023: Optional[float] = Field(None, description="2023年分红(元/股)")
    dividend_count_2023: Optional[int] = Field(None, description="2023年分红次数")
    yield_2023: Optional[float] = Field(None, description="2023年股息率(%)")

    # 3 年平均
    avg_price_3y: Optional[float] = Field(None, description="近3年平均股价")
    avg_yield_3y: Optional[float] = Field(None, description="3年平均股息率(%)")

    # 2025 年价格波动
    high_price_2025: Optional[float] = Field(None, description="2025年最高价")
    low_price_2025: Optional[float] = Field(None, description="2025年最低价")
    high_change_pct_2025: Optional[float] = Field(None, description="2025年最高涨幅(%)")
    low_change_pct_2025: Optional[float] = Field(None, description="2025年最低跌幅(%)")


class QuarterlyData(BaseModel):
    """
    季度数据模型
    """
    q1: Optional["Quarter"] = Field(None, description="第一季度")
    q2: Optional["Quarter"] = Field(None, description="第二季度")
    q3: Optional["Quarter"] = Field(None, description="第三季度")
    q4: Optional["Quarter"] = Field(None, description="第四季度")


class Quarter(BaseModel):
    """
    单季度数据模型
    """
    avg_price: Optional[float] = Field(None, description="平均股价")
    dividend: Optional[float] = Field(None, description="分红金额(元/股)")
    yield_pct: Optional[float] = Field(None, alias="yield", description="股息率(%)")

    class Config:
        populate_by_name = True


# 更新前向引用
QuarterlyData.model_rebuild()


# ========== 请求模型 ==========


class StockListQuery(BaseModel):
    """
    股票列表查询参数（通过 Query 参数传递，此处仅作类型参考）
    """
    min_yield: Optional[float] = Field(None, description="最小股息率(%)")
    max_yield: Optional[float] = Field(None, description="最大股息率(%)")
    exchange: Optional[str] = Field(None, description="交易所筛选")
    industry: Optional[str] = Field(None, description="行业筛选")
    index: Optional[str] = Field(None, description="来源指数筛选")
    sort_by: str = Field("avg_yield_3y", description="排序字段")
    sort_order: str = Field("desc", description="排序方向(asc/desc)")
    page: int = Field(1, ge=1, description="页码")
    page_size: int = Field(50, ge=1, le=500, description="每页数量")


# ========== 响应模型 ==========


class StockListResponse(BaseModel):
    """
    股票列表响应模型
    """
    total: int = Field(..., description="总记录数")
    page: int = Field(..., description="当前页码")
    page_size: int = Field(..., description="每页数量")
    items: list[DividendStock] = Field(..., description="股票列表")


class StockDetailResponse(BaseModel):
    """
    股票详情响应模型
    """
    data: DividendStock = Field(..., description="股票数据")
    quarterly: QuarterlyData = Field(..., description="季度数据")


class StatsResponse(BaseModel):
    """
    统计信息响应模型
    """
    total_stocks: int = Field(..., description="总股票数")
    yield_stats: dict = Field(..., description="股息率统计")
    yield_distribution: dict = Field(..., description="股息率分布")
    industry_distribution: dict = Field(..., description="行业分布")
    index_distribution: dict = Field(..., description="指数分布")
    csv_last_modified: Optional[str] = Field(None, description="CSV最后修改时间")


class HealthResponse(BaseModel):
    """
    健康检查响应模型
    """
    status: str = Field(..., description="服务状态")
    service: str = Field(..., description="服务名称")
    version: str = Field(..., description="服务版本")
    csv_exists: bool = Field(..., description="CSV文件是否存在")
    total_records: int = Field(..., description="总记录数")