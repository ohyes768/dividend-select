"""
API 数据模型
定义请求和响应的 Pydantic 模型
"""
from typing import Optional

from pydantic import BaseModel, Field


# ========== 基础数据模型 ==========


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
    yield_pct: Optional[float] = Field(None, description="股息率(%)")


# 更新前向引用
QuarterlyData.model_rebuild()


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

    # 季度数据
    quarterly: Optional[QuarterlyData] = Field(None, description="季度数据")


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
    股票列表响应模型（无分页）
    """
    total: int = Field(..., description="总记录数")
    items: list[DividendStock] = Field(..., description="股票列表")
    last_updated: Optional[str] = Field(None, description="数据最后更新时间")


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


# ========== PE 相关模型 ==========


class StockPE(BaseModel):
    """
    股票PE数据模型
    """
    code: str = Field(..., description="股票代码")
    name: str = Field(..., description="股票名称")
    pe: Optional[float] = Field(None, description="市盈率(PE)")
    pb: Optional[float] = Field(None, description="市净率(PB)")
    market_cap: Optional[float] = Field(None, description="总市值(万元)")
    circulation_market_cap: Optional[float] = Field(None, description="流通市值(万元)")


class StockPEResponse(BaseModel):
    """
    股票PE数据响应模型
    """
    total: int = Field(..., description="总记录数")
    items: list[StockPE] = Field(..., description="股票PE列表")
    last_updated: Optional[str] = Field(None, description="数据最后更新时间")


# ========== M120 相关模型 ==========


class M120Stock(BaseModel):
    """
    M120 股票数据模型
    """
    code: str = Field(..., description="股票代码")
    name: str = Field(..., description="股票名称")
    avg_yield_3y: Optional[float] = Field(None, description="3年平均股息率(%)")
    m120: Optional[float] = Field(None, description="120日均线")
    close: Optional[float] = Field(None, description="最新收盘价")
    deviation: Optional[float] = Field(None, description="收盘价与M120的偏离度(%)")


class M120ListResponse(BaseModel):
    """
    M120 股票列表响应模型
    """
    total: int = Field(..., description="总记录数")
    items: list[M120Stock] = Field(..., description="股票列表")
    last_updated: Optional[str] = Field(None, description="数据最后更新时间")


# ========== 实时股价相关模型 ==========


class RealtimePriceRequest(BaseModel):
    """
    实时股价请求模型
    """
    code: str = Field(..., description="股票代码")
    m120: float = Field(..., description="120日均线值", gt=0)


class RealtimePriceResponse(BaseModel):
    """
    实时股价响应模型
    """
    code: str = Field(..., description="股票代码")
    close: Optional[float] = Field(None, description="最新收盘价")
    deviation: Optional[float] = Field(None, description="偏离度(%)")
    timestamp: Optional[str] = Field(None, description="数据获取时间")


# ========== 股票信息相关模型 ==========


class StockInfo(BaseModel):
    """
    股票行业/概念信息模型
    """
    code: str = Field(..., description="股票代码")
    exchange: Optional[str] = Field(None, description="交易所")
    sw_level1: Optional[str] = Field(None, description="申万一级行业")
    sw_level2: Optional[str] = Field(None, description="申万二级行业")
    sw_level3: Optional[str] = Field(None, description="申万三级行业")
    concept_board: Optional[str] = Field(None, description="概念板块")
    industry_board: Optional[str] = Field(None, description="行业板块")


class StockInfoRequest(BaseModel):
    """
    批量查询股票信息请求模型
    """
    codes: list[str] = Field(..., description="股票代码列表", min_length=1)


class StockInfoResponse(BaseModel):
    """
    批量查询股票信息响应模型
    """
    items: list[StockInfo] = Field(..., description="股票信息列表")
    total: int = Field(..., description="总记录数")


# ========== 股息率刷新相关模型 ==========


class RefreshStats(BaseModel):
    """
    刷新统计信息模型
    """
    total_processed: int = Field(..., description="处理总数")
    new_or_updated: int = Field(..., description="新增/更新数")
    skipped: int = Field(..., description="跳过数（已存在）")
    file_path: str = Field(..., description="文件路径")
    start_time: str = Field(..., description="开始时间 (ISO 8601)")
    end_time: str = Field(..., description="结束时间 (ISO 8601)")


class RefreshRequest(BaseModel):
    """
    股息率刷新请求模型
    """
    min_dividend: int = Field(5, description="最小分红次数阈值，默认5", ge=1)


class RefreshResponse(BaseModel):
    """
    股息率刷新响应模型
    """
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="操作结果消息")
    stats: RefreshStats = Field(..., description="统计信息")


# ========== 板块相关模型 ==========


class BoardInfo(BaseModel):
    """
    股票板块信息模型
    """
    code: str = Field(..., description="股票代码")
    name: str = Field(..., description="股票名称")
    concept_board: Optional[str] = Field(None, description="概念板块")
    industry_board: Optional[str] = Field(None, description="行业板块")


class BoardInfoResponse(BaseModel):
    """
    板块信息响应模型
    """
    total: int = Field(..., description="总记录数")
    items: list[BoardInfo] = Field(..., description="板块信息列表")
    last_updated: Optional[str] = Field(None, description="数据最后更新时间")