"""
API 路由定义
"""
from datetime import datetime
from typing import Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from src.api.models import (
    DividendStock,
    HealthResponse,
    QuarterlyData,
    Quarter,
    StatsResponse,
    StockDetailResponse,
    StockListResponse,
)
from src.services.data_reader import DataReader
from src.services.filter_service import FilterService
from src.services.sort_service import SortService
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# 创建路由
router = APIRouter()

# 服务实例（在应用启动时初始化）
data_reader: DataReader | None = None
filter_service: FilterService | None = None
sort_service: SortService | None = None


def set_services(reader: DataReader, filterer: FilterService, sorter: SortService):
    """
    设置服务实例

    Args:
        reader: 数据读取服务
        filterer: 数据筛选服务
        sorter: 数据排序服务
    """
    global data_reader, filter_service, sort_service
    data_reader = reader
    filter_service = filterer
    sort_service = sorter


def _row_to_stock_model(row: pd.Series) -> DividendStock:
    """
    将 DataFrame 行转换为股票数据模型

    Args:
        row: DataFrame 行

    Returns:
        股票数据模型
    """
    def _to_float(val) -> Optional[float]:
        """转换为 float，处理空值"""
        if pd.isna(val) or val == "-":
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    def _to_int(val) -> Optional[int]:
        """转换为 int，处理空值"""
        float_val = _to_float(val)
        return int(float_val) if float_val is not None else None

    return DividendStock(
        code=str(row["股票代码"]).zfill(6),
        name=str(row["股票名称"]),
        exchange=str(row.get("交易所", "")),
        source_index=str(row.get("来源指数", "")) if pd.notna(row.get("来源指数")) else None,
        sw_level1=str(row.get("申万一级行业", "")) if pd.notna(row.get("申万一级行业")) else None,
        sw_level2=str(row.get("申万二级行业", "")) if pd.notna(row.get("申万二级行业")) else None,
        sw_level3=str(row.get("申万三级行业", "")) if pd.notna(row.get("申万三级行业")) else None,
        concept_board=str(row.get("概念板块", "")) if pd.notna(row.get("概念板块")) else None,
        industry_board=str(row.get("行业板块", "")) if pd.notna(row.get("行业板块")) else None,
        avg_price_2025=_to_float(row.get("2025年平均价")),
        dividend_2025=_to_float(row.get("2025年分红(元/股)")),
        dividend_count_2025=_to_int(row.get("2025年分红次数")),
        yield_2025=_to_float(row.get("2025年股息率(%)")),
        avg_price_2024=_to_float(row.get("2024年平均价")),
        dividend_2024=_to_float(row.get("2024年分红(元/股)")),
        dividend_count_2024=_to_int(row.get("2024年分红次数")),
        yield_2024=_to_float(row.get("2024年股息率(%)")),
        avg_price_2023=_to_float(row.get("2023年平均价")),
        dividend_2023=_to_float(row.get("2023年分红(元/股)")),
        dividend_count_2023=_to_int(row.get("2023年分红次数")),
        yield_2023=_to_float(row.get("2023年股息率(%)")),
        avg_price_3y=_to_float(row.get("近3年平均股价")),
        avg_yield_3y=_to_float(row.get("3年平均股息率(%)")),
        high_price_2025=_to_float(row.get("2025年最高价")),
        low_price_2025=_to_float(row.get("2025年最低价")),
        high_change_pct_2025=_to_float(row.get("2025年最高涨幅(%)")),
        low_change_pct_2025=_to_float(row.get("2025年最低跌幅(%)")),
    )


def _extract_quarterly_data(row: pd.Series) -> QuarterlyData:
    """
    提取季度数据

    Args:
        row: DataFrame 行

    Returns:
        季度数据模型
    """
    def _to_float(val) -> Optional[float]:
        """转换为 float，处理空值"""
        if pd.isna(val) or val == "-":
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    return QuarterlyData(
        q1=Quarter(
            avg_price=_to_float(row.get("2025Q1平均价")),
            dividend=_to_float(row.get("2025Q1分红(元/股)")),
            yield_pct=_to_float(row.get("2025Q1股息率(%)")),
        ) if _to_float(row.get("2025Q1平均价")) else None,
        q2=Quarter(
            avg_price=_to_float(row.get("2025Q2平均价")),
            dividend=_to_float(row.get("2025Q2分红(元/股)")),
            yield_pct=_to_float(row.get("2025Q2股息率(%)")),
        ) if _to_float(row.get("2025Q2平均价")) else None,
        q3=Quarter(
            avg_price=_to_float(row.get("2025Q3平均价")),
            dividend=_to_float(row.get("2025Q3分红(元/股)")),
            yield_pct=_to_float(row.get("2025Q3股息率(%)")),
        ) if _to_float(row.get("2025Q3平均价")) else None,
        q4=Quarter(
            avg_price=_to_float(row.get("2025Q4平均价")),
            dividend=_to_float(row.get("2025Q4分红(元/股)")),
            yield_pct=_to_float(row.get("2025Q4股息率(%)")),
        ) if _to_float(row.get("2025Q4平均价")) else None,
    )


@router.get("/", response_model=dict)
async def root():
    """根路径"""
    return {
        "service": "dividend-select",
        "version": "1.0.0",
        "description": "A股高股息率TOP50查询工具 API",
        "docs": "/docs",
        "health": "/health"
    }


@router.get("/health", response_model=HealthResponse)
async def health():
    """健康检查"""
    if data_reader is None:
        raise HTTPException(status_code=500, detail="服务未初始化")

    csv_exists = data_reader.check_csv_exists()
    total = data_reader.get_total_count() if csv_exists else 0

    return HealthResponse(
        status="healthy" if csv_exists else "unhealthy",
        service="dividend-select",
        version="1.0.0",
        csv_exists=csv_exists,
        total_records=total
    )


@router.get("/api/stocks", response_model=StockListResponse)
async def get_stocks(
    min_yield: Optional[float] = Query(None, description="最小股息率(%)"),
    max_yield: Optional[float] = Query(None, description="最大股息率(%)"),
    exchange: Optional[str] = Query(None, description="交易所筛选"),
    industry: Optional[str] = Query(None, description="行业筛选"),
    index: Optional[str] = Query(None, description="来源指数筛选"),
    sort_by: str = Query("avg_yield_3y", description="排序字段"),
    sort_order: str = Query("desc", description="排序方向(asc/desc)"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(50, ge=1, le=500, description="每页数量")
):
    """获取股票列表（支持筛选、排序、分页）"""
    if data_reader is None or filter_service is None or sort_service is None:
        raise HTTPException(status_code=500, detail="服务未初始化")

    # 读取数据
    df = data_reader.read_csv()

    # 筛选
    df = filter_service.filter_by_yield_range(df, min_yield, max_yield)
    df = filter_service.filter_by_exchange(df, exchange)
    df = filter_service.filter_by_industry(df, industry)
    df = filter_service.filter_by_index(df, index)

    # 排序
    df = sort_service.sort_by_field(df, sort_by, sort_order)

    # 分页
    total = len(df)
    start = (page - 1) * page_size
    end = start + page_size
    page_df = df.iloc[start:end]

    # 转换为模型
    items = [_row_to_stock_model(row) for _, row in page_df.iterrows()]

    return StockListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=items
    )


@router.get("/api/stocks/{code}", response_model=StockDetailResponse)
async def get_stock_detail(code: str):
    """获取股票详情（含季度数据）"""
    if data_reader is None:
        raise HTTPException(status_code=500, detail="服务未初始化")

    row = data_reader.get_stock_by_code(code)
    if row is None:
        raise HTTPException(status_code=404, detail=f"股票 {code} 不存在")

    stock = _row_to_stock_model(row)
    quarterly = _extract_quarterly_data(row)

    return StockDetailResponse(
        data=stock,
        quarterly=quarterly
    )


@router.get("/api/stats", response_model=StatsResponse)
async def get_stats():
    """获取统计信息"""
    if data_reader is None:
        raise HTTPException(status_code=500, detail="服务未初始化")

    df = data_reader.read_csv()

    # 股息率统计
    yield_col = "3年平均股息率(%)"
    yield_series = pd.to_numeric(df[yield_col].replace("-", None), errors="coerce").dropna()

    yield_stats = {
        "max": float(yield_series.max()) if len(yield_series) > 0 else None,
        "min": float(yield_series.min()) if len(yield_series) > 0 else None,
        "median": float(yield_series.median()) if len(yield_series) > 0 else None,
        "mean": float(yield_series.mean()) if len(yield_series) > 0 else None,
    }

    # 股息率分布
    yield_distribution = {
        "above_6": len(yield_series[yield_series >= 6]),
        "above_5": len(yield_series[yield_series >= 5]),
        "above_4": len(yield_series[yield_series >= 4]),
        "above_3": len(yield_series[yield_series >= 3]),
    }

    # 行业分布
    industry_distribution = {}
    if "申万一级行业" in df.columns:
        industry_counts = df["申万一级行业"].value_counts().head(10).to_dict()
        industry_distribution = {k: int(v) for k, v in industry_counts.items()}

    # 指数分布
    index_distribution = {}
    if "来源指数" in df.columns:
        # 拆分多个指数并计数
        all_indices = df["来源指数"].str.split(",", expand=True).stack().str.strip()
        index_counts = all_indices.value_counts().to_dict()
        index_distribution = {k: int(v) for k, v in index_counts.items()}

    # CSV 最后修改时间
    csv_mtime = None
    if data_reader.check_csv_exists():
        timestamp = data_reader.get_file_mtime()
        csv_mtime = datetime.fromtimestamp(timestamp).isoformat()

    return StatsResponse(
        total_stocks=len(df),
        yield_stats=yield_stats,
        yield_distribution=yield_distribution,
        industry_distribution=industry_distribution,
        index_distribution=index_distribution,
        csv_last_modified=csv_mtime
    )