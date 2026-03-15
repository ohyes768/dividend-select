"""
API 路由定义
"""
from datetime import datetime
from typing import Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from src.api.models import (
    BoardInfo,
    BoardInfoResponse,
    DividendStock,
    HealthResponse,
    M120ListResponse,
    M120Stock,
    QuarterlyData,
    Quarter,
    RealtimePriceRequest,
    RealtimePriceResponse,
    StockInfo,
    StockInfoRequest,
    StockInfoResponse,
    StatsResponse,
    StockDetailResponse,
    StockListResponse,
    StockPEResponse,
    StockPE,
    RefreshRequest,
    RefreshResponse,
    RefreshStats,
)
from src.services.data_reader import DataReader
from src.services.filter_service import FilterService
from src.services.m120_service import M120Service
from src.services.pe_service import PEDataService
from src.services.realtime_service import get_realtime_service
from src.services.sort_service import SortService
from src.services.stock_info_service import get_stock_info_service
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# 创建路由
router = APIRouter()

# 服务实例（在应用启动时初始化）
data_reader: DataReader | None = None
filter_service: FilterService | None = None
sort_service: SortService | None = None
m120_service: M120Service | None = None
pe_service: PEDataService | None = None
stock_info_service: object | None = None


def set_services(
    reader: DataReader,
    filterer: FilterService,
    sorter: SortService,
    m120: M120Service,
    pe: PEDataService
):
    """
    设置服务实例

    Args:
        reader: 数据读取服务
        filterer: 数据筛选服务
        sorter: 数据排序服务
        m120: M120 服务
        pe: PE 数据服务
    """
    global data_reader, filter_service, sort_service, m120_service, pe_service, stock_info_service
    data_reader = reader
    filter_service = filterer
    sort_service = sorter
    m120_service = m120
    pe_service = pe
    stock_info_service = get_stock_info_service(data_reader)


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

    def _has_quarter_data(quarter: str) -> bool:
        """检查季度是否有数据"""
        return _to_float(row.get(f"{quarter}平均价")) is not None

    # 构建季度数据
    quarterly = None
    if any(_has_quarter_data(q) for q in ["2025Q1", "2025Q2", "2025Q3", "2025Q4"]):
        from src.api.models import QuarterlyData, Quarter
        quarterly = QuarterlyData(
            q1=Quarter(
                avg_price=_to_float(row.get("2025Q1平均价")),
                dividend=_to_float(row.get("2025Q1分红(元/股)")),
                yield_pct=_to_float(row.get("2025Q1股息率(%)")),
            ) if _has_quarter_data("2025Q1") else None,
            q2=Quarter(
                avg_price=_to_float(row.get("2025Q2平均价")),
                dividend=_to_float(row.get("2025Q2分红(元/股)")),
                yield_pct=_to_float(row.get("2025Q2股息率(%)")),
            ) if _has_quarter_data("2025Q2") else None,
            q3=Quarter(
                avg_price=_to_float(row.get("2025Q3平均价")),
                dividend=_to_float(row.get("2025Q3分红(元/股)")),
                yield_pct=_to_float(row.get("2025Q3股息率(%)")),
            ) if _has_quarter_data("2025Q3") else None,
            q4=Quarter(
                avg_price=_to_float(row.get("2025Q4平均价")),
                dividend=_to_float(row.get("2025Q4分红(元/股)")),
                yield_pct=_to_float(row.get("2025Q4股息率(%)")),
            ) if _has_quarter_data("2025Q4") else None,
        )

    return DividendStock(
        code=str(row["股票代码"]).zfill(6),
        name=str(row["股票名称"]),
        exchange=str(row.get("交易所", "")),
        source_index=str(row.get("来源指数", "")) if pd.notna(row.get("来源指数")) else None,
        sw_level1=None,
        sw_level2=None,
        sw_level3=None,
        concept_board=None,
        industry_board=None,
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
        quarterly=quarterly,
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


@router.get("/stocks", response_model=StockListResponse)
async def get_stocks(
    min_yield: float = Query(5, description="最小股息率(%)，默认5%"),
    max_yield: Optional[float] = Query(None, description="最大股息率(%)"),
    exchange: Optional[str] = Query(None, description="交易所筛选"),
    industry: Optional[str] = Query(None, description="行业筛选"),
    index: Optional[str] = Query(None, description="来源指数筛选"),
    sort_by: str = Query("avg_yield_3y", description="排序字段"),
    sort_order: str = Query("desc", description="排序方向(asc/desc)")
):
    """获取股票列表（支持筛选、排序，无分页）"""
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

    # 无分页，返回所有数据
    items = [_row_to_stock_model(row) for _, row in df.iterrows()]

    return StockListResponse(
        total=len(items),
        items=items
    )


@router.get("/stocks/{code}", response_model=StockDetailResponse)
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


@router.get("/stats", response_model=StatsResponse)
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


@router.get("/m120", response_model=M120ListResponse)
async def get_m120_stocks(
    min_yield: float = Query(5.0, description="最小股息率(%)，默认5%"),
    sort_by: str = Query("avg_yield_3y", description="排序字段"),
    sort_order: str = Query("desc", description="排序方向(asc/desc)")
):
    """
    批量获取筛选出来的股息率>=5的股票的 M120 数据

    该接口每天刷新一次 M120 数据，适用于 n8n 定时调用。

    返回数据：
    - 股票代码
    - 股票名称
    - 3年平均股息率
    - 120日均线（M120）
    - 最新收盘价
    - 收盘价与M120的偏离度(%)
    """
    if data_reader is None or sort_service is None or m120_service is None:
        raise HTTPException(status_code=500, detail="服务未初始化")

    # 读取股息率数据
    df = data_reader.read_csv()

    # 筛选股息率 > 3
    yield_col = "3年平均股息率(%)"
    df["3年平均股息率(%)"] = pd.to_numeric(
        df[yield_col].replace("-", None),
        errors="coerce"
    )
    df = df[df["3年平均股息率(%)"] > min_yield]

    # 读取 M120 数据
    m120_data = m120_service.read_m120_data()

    # 排序
    df = sort_service.sort_by_field(df, sort_by, sort_order)

    # 构建响应数据
    items = []
    for _, row in df.iterrows():
        code = str(row["股票代码"]).zfill(6)
        avg_yield = row.get("3年平均股息率(%)")
        m120_info = m120_data.get(code, {})

        items.append(M120Stock(
            code=code,
            name=str(row["股票名称"]),
            avg_yield_3y=float(avg_yield) if pd.notna(avg_yield) else None,
            m120=m120_info.get("m120"),
            close=m120_info.get("close"),
            deviation=m120_info.get("deviation"),
        ))

    # 获取 M120 文件最后修改时间
    last_updated = None
    if m120_service.check_file_exists():
        timestamp = m120_service.get_file_mtime()
        last_updated = datetime.fromtimestamp(timestamp).isoformat()

    return M120ListResponse(
        total=len(items),
        items=items,
        last_updated=last_updated
    )


@router.post("/m120/refresh")
async def refresh_m120_data():
    """
    刷新 M120 数据

    获取所有股息率 > 3 的股票的 120 日均线数据。
    该接口耗时较长，建议在非高峰期调用。

    返回：
    - success: 是否成功
    - message: 处理结果信息
    - count: 更新的股票数量
    """
    if data_reader is None or m120_service is None:
        raise HTTPException(status_code=500, detail="服务未初始化")

    try:
        # 读取股息率数据
        df = data_reader.read_csv()

        # 筛选股息率 > 3
        yield_col = "3年平均股息率(%)"
        df["3年平均股息率(%)"] = pd.to_numeric(
            df[yield_col].replace("-", None),
            errors="coerce"
        )
        df = df[df["3年平均股息率(%)"] > 3]

        # 获取需要更新的股票代码列表
        codes = df["股票代码"].astype(str).str.zfill(6).tolist()

        logger.info(f"开始刷新 M120 数据，共 {len(codes)} 只股票")

        # 更新 M120 数据
        count = m120_service.update_m120_data(codes, show_progress=True)

        return {
            "success": True,
            "message": f"M120 数据刷新完成，成功更新 {count} 只股票",
            "count": count
        }

    except Exception as e:
        logger.error(f"刷新 M120 数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"刷新失败: {str(e)}")


# ========== PE 相关接口 ==========


@router.get("/pe", response_model=StockPEResponse)
async def get_pe_data(
    code: Optional[str] = Query(None, description="股票代码（查询单只股票）"),
    codes: Optional[str] = Query(None, description="股票代码列表，逗号分隔（批量查询）"),
    force_refresh: bool = Query(False, description="是否强制刷新缓存（已废弃）")
):
    """
    获取股票 PE/PB 数据

    参数说明：
    - code: 查询单只股票
    - codes: 批量查询，格式如 "600000,600001,600002"

    返回数据：
    - code: 股票代码
    - name: 股票名称
    - pe: 市盈率
    - pb: 市净率
    - market_cap: 总市值（万元）
    - circulation_market_cap: 流通市值（万元）
    """
    if pe_service is None:
        raise HTTPException(status_code=500, detail="服务未初始化")

    if code and codes:
        raise HTTPException(status_code=400, detail="不能同时使用 code 和 codes 参数")

    if code:
        # 查询单只股票
        row = pe_service.get_pe_by_code(code)
        if row is None:
            raise HTTPException(status_code=404, detail=f"股票 {code} 的 PE 数据不存在")

        items = [StockPE(
            code=str(row["code"]),
            name=str(row["name"]) if pd.notna(row["name"]) else "",
            pe=float(row["pe"]) if pd.notna(row["pe"]) else None,
            pb=float(row["pb"]) if pd.notna(row["pb"]) else None,
            market_cap=float(row["market_cap"]) if pd.notna(row["market_cap"]) else None,
            circulation_market_cap=float(row["circulation_market_cap"]) if pd.notna(row["circulation_market_cap"]) else None,
        )]
    elif codes:
        # 批量查询指定股票
        code_list = [c.strip() for c in codes.split(",") if c.strip()]
        if not code_list:
            raise HTTPException(status_code=400, detail="codes 参数不能为空")

        df = pe_service.get_pe_by_codes(code_list)

        items = []
        for _, row in df.iterrows():
            items.append(StockPE(
                code=str(row["code"]),
                name=str(row["name"]) if pd.notna(row["name"]) else "",
                pe=float(row["pe"]) if pd.notna(row["pe"]) else None,
                pb=float(row["pb"]) if pd.notna(row["pb"]) else None,
                market_cap=float(row["market_cap"]) if pd.notna(row["market_cap"]) else None,
                circulation_market_cap=float(row["circulation_market_cap"]) if pd.notna(row["circulation_market_cap"]) else None,
            ))
    else:
        # 不传参数时返回空列表，避免返回全部数据
        items = []

    last_updated = None
    if pe_service.get_file_mtime():
        last_updated = datetime.fromtimestamp(pe_service.get_file_mtime()).isoformat()

    return StockPEResponse(
        total=len(items),
        items=items,
        last_updated=last_updated
    )


@router.post("/pe/update")
async def update_pe_data():
    """
    更新 PE/PB 数据

    从 akshare 获取最新的 A 股 PE/PB 数据并保存到 CSV 文件。

    该操作可能需要较长时间（约 10-30 秒），因为需要从 akshare 获取全部 A 股数据。

    Returns:
        - success: 是否成功
        - count: 更新的记录数
        - message: 操作结果消息
    """
    if pe_service is None:
        raise HTTPException(status_code=500, detail="服务未初始化")

    try:
        count = pe_service.update_pe_data()
        return {
            "success": True,
            "count": count,
            "message": f"PE 数据更新完成，共 {count} 条记录"
        }
    except Exception as e:
        logger.error(f"更新 PE 数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")


# ========== 实时股价相关接口 ==========


@router.post("/realtime-price", response_model=RealtimePriceResponse)
async def get_realtime_price(request: RealtimePriceRequest):
    """
    获取单只股票的实时收盘价和偏离度

    该接口用于获取股票的实时收盘价，并根据传入的 M120 值计算偏离度。
    适用于前端刷新按钮调用，获取最新的价格和偏离度数据。

    请求参数：
    - code: 股票代码（6位）
    - m120: 120日均线值

    返回数据：
    - code: 股票代码
    - close: 最新收盘价
    - deviation: 偏离度(%) = (close - m120) / m120 * 100
    - timestamp: 数据获取时间
    """
    try:
        realtime_service = get_realtime_service()

        # 获取实时收盘价
        close = realtime_service.get_realtime_close(request.code)

        if close is None:
            raise HTTPException(status_code=404, detail=f"股票 {request.code} 的实时价格获取失败")

        # 计算偏离度
        deviation = realtime_service.calculate_deviation(close, request.m120)

        return RealtimePriceResponse(
            code=request.code,
            close=close,
            deviation=deviation,
            timestamp=datetime.now().isoformat()
        )

    except ValueError as e:
        logger.error(f"参数错误: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取实时价格失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取实时价格失败: {str(e)}")


# ========== 股票信息相关接口 ==========


@router.post("/stocks/info", response_model=StockInfoResponse)
async def get_stocks_info(request: StockInfoRequest):
    """
    批量获取股票的行业/概念信息

    根据股票代码列表批量查询：
    - 交易所
    - 申万一级行业
    - 申万二级行业
    - 申万三级行业
    - 概念板块
    - 行业板块

    请求参数：
    - codes: 股票代码列表

    返回数据：
    - code: 股票代码
    - exchange: 交易所
    - sw_level1: 申万一级行业
    - sw_level2: 申万二级行业
    - sw_level3: 申万三级行业
    - concept_board: 概念板块
    - industry_board: 行业板块
    """
    if stock_info_service is None:
        raise HTTPException(status_code=500, detail="服务未初始化")

    try:
        info_map = stock_info_service.get_stocks_info(request.codes)

        # 转换为列表
        items = []
        for code, info in info_map.items():
            items.append(StockInfo(
                code=code,
                exchange=info.get("exchange"),
                sw_level1=info.get("sw_level1"),
                sw_level2=info.get("sw_level2"),
                sw_level3=info.get("sw_level3"),
                concept_board=info.get("concept_board"),
                industry_board=info.get("industry_board"),
            ))

        return StockInfoResponse(
            total=len(items),
            items=items
        )

    except Exception as e:
        logger.error(f"获取股票信息失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取股票信息失败: {str(e)}")


# ========== 板块映射刷新接口 ==========


@router.get("/board", response_model=BoardInfoResponse)
async def get_board_info(
    code: Optional[str] = Query(None, description="股票代码（查询单只股票）"),
    codes: Optional[str] = Query(None, description="股票代码列表，逗号分隔（批量查询）")
):
    """
    获取股票板块信息

    参数说明：
    - code: 查询单只股票
    - codes: 批量查询，格式如 "600000,600001,600002"

    返回数据：
    - code: 股票代码
    - name: 股票名称
    - concept_board: 概念板块
    - industry_board: 行业板块
    """
    if data_reader is None:
        raise HTTPException(status_code=500, detail="服务未初始化")

    if code and codes:
        raise HTTPException(status_code=400, detail="不能同时使用 code 和 codes 参数")

    # 获取当前日期目录下的板块映射文件
    from src.utils.helpers import get_current_date_dir, DATA_DIR
    date_str = get_current_date_dir()
    board_file = DATA_DIR / date_str / "个股板块映射.csv"

    if not board_file.exists():
        raise HTTPException(status_code=404, detail="板块数据文件不存在，请先调用 /board/refresh")

    try:
        df = pd.read_csv(board_file, encoding="utf-8-sig")
    except Exception as e:
        logger.error(f"读取板块数据失败: {e}")
        raise HTTPException(status_code=500, detail="读取板块数据失败")

    items = []

    if code:
        # 查询单只股票
        row = df[df["股票代码"].astype(str).str.zfill(6) == str(code).zfill(6)]
        if row.empty:
            raise HTTPException(status_code=404, detail=f"股票 {code} 的板块数据不存在")

        row = row.iloc[0]
        items.append(BoardInfo(
            code=str(row["股票代码"]).zfill(6),
            name=str(row["股票简称"]),
            concept_board=str(row["概念板块"]) if pd.notna(row["概念板块"]) else None,
            industry_board=str(row["行业板块"]) if pd.notna(row["行业板块"]) else None,
        ))
    elif codes:
        # 批量查询指定股票
        code_list = [c.strip() for c in codes.split(",") if c.strip()]
        if not code_list:
            raise HTTPException(status_code=400, detail="codes 参数不能为空")

        codes_formatted = [str(c).zfill(6) for c in code_list]
        df_filtered = df[df["股票代码"].astype(str).str.zfill(6).isin(codes_formatted)]

        for _, row in df_filtered.iterrows():
            items.append(BoardInfo(
                code=str(row["股票代码"]).zfill(6),
                name=str(row["股票简称"]),
                concept_board=str(row["概念板块"]) if pd.notna(row["概念板块"]) else None,
                industry_board=str(row["行业板块"]) if pd.notna(row["行业板块"]) else None,
            ))
    else:
        # 不传参数时返回空列表，避免返回全部数据
        items = []

    # 获取文件最后修改时间
    last_updated = None
    if board_file.exists():
        timestamp = board_file.stat().st_mtime
        last_updated = datetime.fromtimestamp(timestamp).isoformat()

    return BoardInfoResponse(
        total=len(items),
        items=items,
        last_updated=last_updated
    )


# 全局并发控制标志
_is_refreshing_board: bool = False


@router.post("/board/refresh")
async def refresh_board_mapping():
    """
    刷新个股板块映射数据

    该接口用于获取所有红利指数持仓股票的概念板块和行业板块信息，并保存到CSV文件。
    适用于 n8n 定时任务调用，建议每周或每月更新一次。

    返回：
    - success: 是否成功
    - message: 处理结果信息
    - stats: 统计信息
      - total_stocks: 总股票数
      - success_count: 成功获取数
      - failed_count: 失败数
      - file_path: 文件路径
      - start_time: 开始时间
      - end_time: 结束时间

    注意：
    - 该接口耗时较长（约3-5分钟，取决于股票数量）
    - 如果刷新正在进行中，将返回 409 Conflict 错误
    """
    global _is_refreshing_board

    # 并发控制
    if _is_refreshing_board:
        logger.warning("板块映射刷新请求被拒绝：已有刷新任务正在进行中")
        raise HTTPException(
            status_code=409,
            detail="板块映射刷新正在进行中，请稍后再试"
        )

    start_time = datetime.now()

    try:
        # 设置并发标志
        _is_refreshing_board = True
        logger.info("开始刷新板块映射数据")

        # 导入必要的模块
        from src.data import BoardMappingFetcher
        from src.utils import get_current_date_dir

        # 获取当前日期目录
        date_str = get_current_date_dir()
        output_file = "个股板块映射.csv"

        # 创建板块映射获取器
        fetcher = BoardMappingFetcher(date_str=date_str)

        # 更新板块映射
        success = fetcher.update(show_progress=True, date_str=date_str)

        end_time = datetime.now()

        if success:
            logger.info(f"板块映射刷新完成")
            return {
                "success": True,
                "message": "板块映射刷新完成",
                "stats": {
                    "total_stocks": len(fetcher.stock_names),
                    "success_count": len(fetcher.stock_names) - len(fetcher.failed_stocks),
                    "failed_count": len(fetcher.failed_stocks),
                    "file_path": f"data/{date_str}/{output_file}",
                    "start_time": start_time.isoformat(),
                    "end_time": end_time.isoformat(),
                }
            }
        else:
            logger.error("板块映射刷新失败")
            raise HTTPException(
                status_code=500,
                detail="板块映射刷新失败"
            )

    except HTTPException:
        # 重新抛出 HTTP 异常（如并发冲突）
        raise
    except Exception as e:
        logger.error(f"刷新板块映射失败: {e}")
        end_time = datetime.now()
        raise HTTPException(
            status_code=500,
            detail=f"刷新失败: {str(e)}"
        )
    finally:
        # 确保并发标志被清除
        _is_refreshing_board = False
        logger.debug("板块映射并发控制标志已清除")


# ========== 股息率刷新接口 ==========


# 全局并发控制标志
_is_refreshing: bool = False


@router.post("/dividend/refresh", response_model=RefreshResponse)
async def refresh_dividend_data(request: RefreshRequest):
    """
    刷新股息率核心数据

    该接口用于获取红利指数持仓、计算股息率，并保存到数据文件。
    支持增量更新（断点续传），跳过已处理的股票。

    主要用于 n8n 定时任务调用。

    请求参数：
    - min_dividend: 最小分红次数阈值（默认5）

    返回数据：
    - success: 是否成功
    - message: 操作结果消息
    - stats: 统计信息
      - total_processed: 处理总数
      - new_or_updated: 新增/更新数
      - skipped: 跳过数（已存在）
      - file_path: 文件路径
      - start_time: 开始时间
      - end_time: 结束时间

    注意：
    - 该接口耗时较长（30秒-5分钟），建议在非高峰期调用
    - 如果刷新正在进行中，将返回 409 Conflict 错误
    - 部分股票处理失败不影响整体，会记录错误日志
    """
    global _is_refreshing

    # 并发控制
    if _is_refreshing:
        logger.warning("刷新请求被拒绝：已有刷新任务正在进行中")
        raise HTTPException(
            status_code=409,
            detail="刷新正在进行中，请稍后再试"
        )

    start_time = datetime.now()

    try:
        # 设置并发标志
        _is_refreshing = True
        logger.info(f"开始刷新股息率数据，min_dividend={request.min_dividend}")

        # 导入必要的模块
        from src.core import DividendCalculator
        from src.data import IndexHoldingsFetcher
        from src.utils import (
            append_csv_row,
            load_existing_codes,
            get_current_date_dir,
        )

        # 获取当前日期目录
        date_str = get_current_date_dir()
        output_file = "近3年股息率汇总.csv"

        # Step 1: 获取股票列表（使用 API 获取）
        logger.info("Step 1: 获取股票列表...")
        fetcher = IndexHoldingsFetcher(use_local=False)
        stock_list = fetcher.get_stock_list(
            min_dividend_count=request.min_dividend,
            date_str=date_str
        )

        if not stock_list:
            logger.error("获取股票列表失败，程序退出")
            return RefreshResponse(
                success=False,
                message="获取股票列表失败",
                stats=RefreshStats(
                    total_processed=0,
                    new_or_updated=0,
                    skipped=0,
                    file_path=f"data/{date_str}/{output_file}",
                    start_time=start_time.isoformat(),
                    end_time=datetime.now().isoformat(),
                )
            )

        logger.info(f"获取到 {len(stock_list)} 只符合条件的股票")

        # Step 2: 检查已处理的股票，实现断点续传
        existing_codes = load_existing_codes(output_file, date_str)
        initial_count = len(stock_list)

        if existing_codes:
            logger.info(f"已存在 {len(existing_codes)} 只股票数据，将跳过")
            stock_list = [s for s in stock_list if str(s.code).zfill(6) not in existing_codes]

        if not stock_list:
            logger.info("所有股票已处理完成，无需重新计算")
            end_time = datetime.now()
            return RefreshResponse(
                success=True,
                message="所有股票已处理完成",
                stats=RefreshStats(
                    total_processed=initial_count,
                    new_or_updated=0,
                    skipped=initial_count,
                    file_path=f"data/{date_str}/{output_file}",
                    start_time=start_time.isoformat(),
                    end_time=end_time.isoformat(),
                )
            )

        logger.info(f"待处理 {len(stock_list)} 只股票")

        # Step 3: 计算股息率并增量写入
        logger.info("Step 3: 计算股息率（增量写入）...")

        success_count = 0
        failed_count = 0

        def on_stock_complete(result):
            """每计算完一个股票，追加写入CSV"""
            nonlocal success_count
            try:
                append_csv_row(result.to_dict(), output_file, date_str)
                success_count += 1
                logger.info(f"已保存 {result.code} {result.name}")
            except Exception as e:
                logger.error(f"保存 {result.code} 失败: {e}")
                failed_count += 1

        calculator = DividendCalculator()
        calculator.calculate_all(stock_list, on_complete=on_stock_complete)

        end_time = datetime.now()
        skipped_count = initial_count - len(stock_list)

        logger.info(
            f"刷新完成: 处理总数={initial_count}, "
            f"成功={success_count}, 失败={failed_count}, 跳过={skipped_count}"
        )

        return RefreshResponse(
            success=True,
            message=f"刷新完成，成功更新 {success_count} 只股票",
            stats=RefreshStats(
                total_processed=initial_count,
                new_or_updated=success_count,
                skipped=skipped_count,
                file_path=f"data/{date_str}/{output_file}",
                start_time=start_time.isoformat(),
                end_time=end_time.isoformat(),
            )
        )

    except HTTPException:
        # 重新抛出 HTTP 异常（如并发冲突）
        raise
    except Exception as e:
        logger.error(f"刷新股息率数据失败: {e}")
        end_time = datetime.now()
        raise HTTPException(
            status_code=500,
            detail=f"刷新失败: {str(e)}"
        )
    finally:
        # 确保并发标志被清除
        _is_refreshing = False
        logger.debug("并发控制标志已清除")