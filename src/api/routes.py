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
    CodesRequest,
)
from src.services.data_reader import DataReader
from src.services.filter_service import FilterService
from src.services.m120_service import M120Service
from src.services.pe_service import PEDataService
from src.services.realtime_service import get_realtime_service
from src.services.sort_service import SortService
from src.services.stock_info_service import get_stock_info_service
from src.services.shareholder_financial_reader import ShareholderReader, FinancialReader
from src.data.financial_fetcher import FinancialFetcher
from src.utils.helpers import save_csv_data, DATA_DIR
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# 创建路由
router = APIRouter()


def get_last_4_quarters() -> list[tuple[int, int]]:
    """返回前4个已过去季度的 (年份, 季度) 列表，最新在前

    例如当前是2026年5月(Q2)，返回: [(2026,1), (2025,4), (2025,3), (2025,2)]
    """
    now = datetime.now()
    year = now.year
    month = now.month
    # 当前季度（如果还在发展中则取上一季度作为"最新已完成"）
    current_quarter = (month - 1) // 3 + 1

    # 前4个季度从上一季度开始往前数
    quarters = []
    q = current_quarter - 1  # 从上一个完整季度开始
    y = year
    if q == 0:
        q = 4
        y -= 1

    for _ in range(4):
        quarters.append((y, q))
        q -= 1
        if q == 0:
            q = 4
            y -= 1
    return quarters

# 服务实例（在应用启动时初始化）
data_reader: DataReader | None = None
filter_service: FilterService | None = None
sort_service: SortService | None = None
m120_service: M120Service | None = None
pe_service: PEDataService | None = None
stock_info_service: object | None = None
shareholder_reader: ShareholderReader | None = None
financial_reader: FinancialReader | None = None


def set_services(
    reader: DataReader,
    filterer: FilterService,
    sorter: SortService,
    m120: M120Service,
    pe: PEDataService,
    sh_reader: ShareholderReader | None = None,
    fi_reader: FinancialReader | None = None
):
    """
    设置服务实例

    Args:
        reader: 数据读取服务
        filterer: 数据筛选服务
        sorter: 数据排序服务
        m120: M120 服务
        pe: PE 数据服务
        sh_reader: 股东户数读取服务
        fi_reader: 财务指标读取服务
    """
    global data_reader, filter_service, sort_service, m120_service, pe_service, stock_info_service
    global shareholder_reader, financial_reader
    data_reader = reader
    filter_service = filterer
    sort_service = sorter
    m120_service = m120
    pe_service = pe
    stock_info_service = get_stock_info_service(data_reader)
    shareholder_reader = sh_reader
    financial_reader = fi_reader


def _row_to_stock_model(row: pd.Series, info: Optional[dict] = None,
                         shareholder_data: Optional[dict] = None,
                         financial_data: Optional[dict] = None) -> DividendStock:
    """
    将 DataFrame 行转换为股票数据模型
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

    # 获取前4个季度，动态构建季度数据
    last_4_quarters = get_last_4_quarters()
    quarter_keys = ["q1", "q2", "q3", "q4"]

    # 检查是否有任何季度有数据
    has_any_quarter = any(
        _has_quarter_data(f"{y}Q{q}") for y, q in last_4_quarters
    )

    quarterly = None
    if has_any_quarter:
        from src.api.models import QuarterlyData, Quarter
        quarterly_data = {}
        for i, (y, q) in enumerate(last_4_quarters):
            quarter_label = f"{y}Q{q}"
            key = quarter_keys[i]
            if _has_quarter_data(quarter_label):
                quarterly_data[key] = Quarter(
                    avg_price=_to_float(row.get(f"{quarter_label}平均价")),
                    dividend=_to_float(row.get(f"{quarter_label}分红(元/股)")),
                    yield_pct=_to_float(row.get(f"{quarter_label}股息率(%)")),
                )
            else:
                quarterly_data[key] = None
        quarterly = QuarterlyData(**quarterly_data)

    stock = DividendStock(
        code=str(row["股票代码"]).zfill(6),
        name=str(row["股票名称"]),
        exchange=str(row.get("交易所", "")),
        source_index=str(row.get("来源指数", "")) if pd.notna(row.get("来源指数")) else None,
        sw_level1=info.get("sw_level1") if info else None,
        sw_level2=info.get("sw_level2") if info else None,
        sw_level3=info.get("sw_level3") if info else None,
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
        shareholder_count=shareholder_data.get("shareholder_count") if shareholder_data else None,
        shareholder_change_pct=shareholder_data.get("shareholder_change_pct") if shareholder_data else None,
        per_share_holding=shareholder_data.get("per_share_holding") if shareholder_data else None,
        gross_profit_margin=financial_data.get("gross_profit_margin") if financial_data else None,
        net_profit_margin=financial_data.get("net_profit_margin") if financial_data else None,
        roe=financial_data.get("roe") if financial_data else None,
        debt_asset_ratio=financial_data.get("debt_asset_ratio") if financial_data else None,
        net_profit_ex_non_recurring_yoy=financial_data.get("net_profit_ex_non_recurring_yoy") if financial_data else None,
        net_profit_cagr_3y=financial_data.get("net_profit_cagr_3y") if financial_data else None,
        dividend_history=None,  # 先设为 None，后面解析后替换
    )

    # 解析近5年分红详情
    import json
    history_str = row.get("近5年分红详情")
    if history_str and pd.notna(history_str):
        try:
            history_list = json.loads(history_str)
            from src.api.models import DividendHistoryItem
            stock.dividend_history = []
            for item in history_list:
                vals = list(item.values())
                if len(vals) >= 3:
                    stock.dividend_history.append(DividendHistoryItem(
                        ex_date=str(vals[0]),
                        ratio=float(vals[1]),
                        fiscal_year=int(vals[2])
                    ))
        except (json.JSONDecodeError, TypeError, ValueError, IndexError, KeyError):
            stock.dividend_history = None

    return stock


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

    # 动态获取前4个季度
    last_4_quarters = get_last_4_quarters()
    quarter_keys = ["q1", "q2", "q3", "q4"]

    quarterly_data = {}
    for i, (y, q) in enumerate(last_4_quarters):
        quarter_label = f"{y}Q{q}"
        key = quarter_keys[i]
        if _to_float(row.get(f"{quarter_label}平均价")) is not None:
            quarterly_data[key] = Quarter(
                avg_price=_to_float(row.get(f"{quarter_label}平均价")),
                dividend=_to_float(row.get(f"{quarter_label}分红(元/股)")),
                yield_pct=_to_float(row.get(f"{quarter_label}股息率(%)")),
            )
        else:
            quarterly_data[key] = None

    return QuarterlyData(**quarterly_data)


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

    # 检查是否有数据
    if df.empty:
        return StockListResponse(
            total=0,
            items=[],
            last_updated=None
        )

    # 筛选
    # 如果设置了min_yield，则使用3年连续分红筛选（3年平均>=min_yield 且 每年都有分红）
    if min_yield is not None and min_yield > 0:
        df = filter_service.filter_by_3y_dividend(df, min_avg_yield=min_yield)
    if max_yield is not None:
        df = filter_service.filter_by_yield_range(df, None, max_yield)
    df = filter_service.filter_by_exchange(df, exchange)
    df = filter_service.filter_by_industry(df, industry)
    df = filter_service.filter_by_index(df, index)

    # 排序
    df = sort_service.sort_by_field(df, sort_by, sort_order)

    # 批量查询申万行业信息
    codes = df["股票代码"].astype(str).str.zfill(6).tolist()
    info_map = {}
    if stock_info_service is not None and codes:
        info_map = stock_info_service.get_stocks_info(codes)

    # 批量查询股东户数和财务指标
    shareholder_map = {}
    financial_map = {}
    if shareholder_reader is not None and shareholder_reader.check_exists():
        sh_df = shareholder_reader.read_csv()
        if not sh_df.empty:
            for _, sh_row in sh_df.iterrows():
                code = str(sh_row["股票代码"]).zfill(6)
                shareholder_map[code] = {
                    "shareholder_count": int(sh_row["股东户数"]) if pd.notna(sh_row.get("股东户数")) else None,
                    "shareholder_change_pct": float(sh_row["股东人数增幅"]) if pd.notna(sh_row.get("股东人数增幅")) else None,
                    "per_share_holding": float(sh_row["人均持股数量"]) if pd.notna(sh_row.get("人均持股数量")) else None,
                }

    if financial_reader is not None and financial_reader.check_exists():
        fi_df = financial_reader.read_csv()
        if not fi_df.empty:
            for _, fi_row in fi_df.iterrows():
                code = str(fi_row["股票代码"]).zfill(6)
                financial_map[code] = {
                    "gross_profit_margin": float(fi_row["主营业务利润率"]) if pd.notna(fi_row.get("主营业务利润率")) else None,
                    "net_profit_margin": float(fi_row["净利率"]) if pd.notna(fi_row.get("净利率")) else None,
                    "roe": float(fi_row["ROE"]) if pd.notna(fi_row.get("ROE")) else None,
                    "debt_asset_ratio": float(fi_row["资产负债率"]) if pd.notna(fi_row.get("资产负债率")) else None,
                    "net_profit_ex_non_recurring_yoy": float(fi_row["扣非净利润同比"]) if pd.notna(fi_row.get("扣非净利润同比")) else None,
                    "net_profit_cagr_3y": float(fi_row["3年复合增长率"]) if pd.notna(fi_row.get("3年复合增长率")) else None,
                }

    # 无分页，返回所有数据
    items = [_row_to_stock_model(
        row,
        info_map.get(str(row["股票代码"]).zfill(6)),
        shareholder_map.get(str(row["股票代码"]).zfill(6)),
        financial_map.get(str(row["股票代码"]).zfill(6))
    ) for _, row in df.iterrows()]

    # 获取数据文件最后修改时间
    last_updated = None
    if data_reader.check_csv_exists():
        timestamp = data_reader.get_file_mtime()
        last_updated = datetime.fromtimestamp(timestamp).isoformat()

    return StockListResponse(
        total=len(items),
        items=items,
        last_updated=last_updated
    )


@router.get("/stocks/{code}", response_model=StockDetailResponse)
async def get_stock_detail(code: str):
    """获取股票详情（含季度数据）"""
    if data_reader is None:
        raise HTTPException(status_code=500, detail="服务未初始化")

    row = data_reader.get_stock_by_code(code)
    if row is None:
        raise HTTPException(status_code=404, detail=f"股票 {code} 不存在")

    info = None
    if stock_info_service is not None:
        info = stock_info_service.get_stock_info(code)

    stock = _row_to_stock_model(row, info)
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

    # 空数据处理
    if df.empty:
        return StatsResponse(
            total_stocks=0,
            avg_yield_3y=None,
            avg_yield_2025=None,
            avg_yield_2024=None,
            avg_yield_2023=None,
            yield_stats={
                "max": None,
                "min": None,
                "median": None,
                "mean": None,
            }
        )

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
    timestamp = data_reader.get_file_mtime()
    if timestamp is not None:
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

    # 空数据处理
    if df.empty:
        return M120ListResponse(
            total=0,
            items=[],
            last_updated=None
        )

    # 筛选：3年平均股息率 >= min_yield 且 2023/2024/2025 每年都有分红
    df = filter_service.filter_by_3y_dividend(df, min_avg_yield=min_yield)

    # 读取 M120 数据和实时价格，实时计算偏离度
    m120_data = m120_service.read_m120_with_deviation()

    # 导入计算器用于TTM股息率计算
    from src.core.calculator import DividendCalculator

    # 排序
    df = sort_service.sort_by_field(df, sort_by, sort_order)

    # 构建响应数据
    items = []
    calculator = DividendCalculator()  # 复用同一个实例，带缓存
    for _, row in df.iterrows():
        code = str(row["股票代码"]).zfill(6)
        avg_yield = row.get("3年平均股息率(%)")
        m120_info = m120_data.get(code, {})
        realtime_price = m120_info.get("realtime")

        # 计算实时股息率TTM
        yield_ttm = None
        try:
            if realtime_price:
                # 解析近5年分红详情JSON
                dividend_details = []
                details_json = row.get("近5年分红详情")
                if details_json and pd.notna(details_json):
                    import json
                    details_list = json.loads(details_json)
                    from src.data.models import DividendDetail
                    for d in details_list:
                        dividend_details.append(DividendDetail(
                            ex_right_date=d.get("除权除息日", ""),
                            payout_ratio=float(d.get("派息比例", 0)),
                            fiscal_year=int(d.get("财年", 0))
                        ))

                if dividend_details:
                    ttm_dividend = calculator.get_ttm_dividend(dividend_details)
                    if ttm_dividend > 0 and realtime_price > 0:
                        yield_ttm = round(ttm_dividend / realtime_price * 100, 2)
        except Exception:
            pass  # TTM计算失败不影响其他数据

        items.append(M120Stock(
            code=code,
            name=str(row["股票名称"]),
            avg_yield_3y=float(avg_yield) if pd.notna(avg_yield) else None,
            m120=m120_info.get("m120"),
            close=m120_info.get("close"),
            deviation=m120_info.get("deviation"),
            realtime=realtime_price,
            realtime_deviation=m120_info.get("realtime_deviation"),
            yield_ttm=yield_ttm,
        ))

    # 获取 M120 文件最后修改时间
    last_updated = None
    if m120_service.check_m120_file_exists():
        timestamp = m120_service.get_m120_file_mtime()
        if timestamp:
            last_updated = datetime.fromtimestamp(timestamp).isoformat()

    return M120ListResponse(
        total=len(items),
        items=items,
        last_updated=last_updated
    )


@router.get("/m120/status")
async def get_m120_status():
    """
    获取 M120 数据状态

    返回：
    - needs_update: 是否需要更新（文件不存在则需要）
    - last_updated: 上次更新时间
    - file_exists: 文件是否存在
    - missing_count: 始终为0（前端自行判断缺失）
    - missing_codes: 始终为空列表（前端自行判断缺失）
    """
    if m120_service is None:
        raise HTTPException(status_code=500, detail="服务未初始化")

    from datetime import datetime

    file_exists = m120_service.check_m120_file_exists()
    last_updated = None

    if file_exists:
        m120_service._ensure_data_dir()
        m120_file = m120_service.M120_CSV_FILE
        if m120_file and m120_file.exists():
            timestamp = m120_service.get_m120_file_mtime()
            if timestamp:
                last_updated_dt = datetime.fromtimestamp(timestamp)
                last_updated = last_updated_dt.isoformat()

    # 是否需要更新：文件不存在则需要
    needs_update = not file_exists

    return {
        "needs_update": needs_update,
        "last_updated": last_updated,
        "file_exists": file_exists,
        "missing_count": 0,
        "missing_codes": [],
    }


@router.post("/m120/refresh")
async def refresh_m120_data(body: CodesRequest):
    """
    刷新 M120 数据

    获取指定股票的 120 日均线数据。
    该接口耗时较长，建议在非高峰期调用。

    请求参数：
    - codes: 股票代码列表

    返回：
    - success: 是否成功
    - message: 处理结果信息
    - count: 更新的股票数量
    """
    if data_reader is None or m120_service is None:
        raise HTTPException(status_code=500, detail="服务未初始化")

    try:
        codes = [str(c).zfill(6) for c in body.codes]

        logger.info(f"开始刷新 M120 数据，共 {len(codes)} 只股票: {codes[:5]}...")

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


# ========== 财务指标刷新接口 ==========


_financial_fetcher: FinancialFetcher | None = None


def get_financial_fetcher() -> FinancialFetcher:
    """获取或创建 FinancialFetcher 实例"""
    global _financial_fetcher
    if _financial_fetcher is None:
        _financial_fetcher = FinancialFetcher()
    return _financial_fetcher


@router.get("/financial/status")
async def get_financial_status():
    """
    获取财务指标数据状态

    返回：
    - exists: 文件是否存在
    - last_updated: 上次更新时间
    - data_date: 数据日期（季度）
    - missing_codes: 缺失数据的股票代码列表
    """
    if financial_reader is None:
        raise HTTPException(status_code=500, detail="服务未初始化")

    file_exists = financial_reader.check_exists()
    last_updated = None
    data_date = None
    missing_codes: list[str] = []

    if file_exists:
        fi_df = financial_reader.read_csv()
        if not fi_df.empty:
            # 获取数据日期
            dates = fi_df["数据日期"].dropna().unique()
            if len(dates) > 0:
                data_date = sorted(dates)[-1]

        # 获取当前筛选后的股票代码（3年平均股息率>=3%且每年都有分红）
        df = data_reader.read_csv()
        df = filter_service.filter_by_3y_dividend(df, min_avg_yield=3.0)
        filtered_codes = df["股票代码"].astype(str).str.zfill(6).tolist()

        # 找出缺失数据的股票
        existing_codes = fi_df["股票代码"].astype(str).str.zfill(6).tolist()
        missing_codes = [c for c in filtered_codes if c not in existing_codes]

    return {
        "exists": file_exists,
        "last_updated": last_updated,
        "data_date": data_date,
        "missing_count": len(missing_codes),
        "missing_codes": missing_codes,  # 返回全部缺失代码
    }


@router.post("/financial/refresh")
async def refresh_financial_data(body: Optional[CodesRequest] = None):
    """
    刷新财务指标数据

    只更新根据股息率筛选出来的股票（3年平均股息率 >= 4%）。
    如果某只股票当季度数据还没有，则跳过（返回时会标记为缺失）。

    请求参数：
    - codes: 股票代码列表（可选，如果不传则刷新所有缺失的股票）

    返回：
    - success: 是否成功
    - count: 更新的股票数量
    - missing_count: 缺失数据的股票数量
    - message: 处理结果信息
    """
    global _financial_fetcher

    if data_reader is None or financial_reader is None:
        raise HTTPException(status_code=500, detail="服务未初始化")

    try:
        # 如果请求中指定了 codes，只更新指定的股票；否则更新所有缺失的股票
        if body and body.codes:
            codes = [str(c).zfill(6) for c in body.codes]
        else:
            # 读取股息率数据，筛选：3年平均股息率>=3%且每年都有分红
            df = data_reader.read_csv()
            df = filter_service.filter_by_3y_dividend(df, min_avg_yield=3.0)
            all_codes = df["股票代码"].astype(str).str.zfill(6).tolist()

            # 读取已存在的财务数据
            existing_codes: set[str] = set()
            if financial_reader.check_exists():
                fi_df = financial_reader.read_csv()
                if not fi_df.empty:
                    existing_codes = set(fi_df["股票代码"].astype(str).str.zfill(6).tolist())

            codes = [c for c in all_codes if c not in existing_codes]

        logger.info(f"开始刷新财务指标数据，共 {len(codes)} 只股票")

        # 创建 fetcher 并获取数据（每10个一批保存）
        fetcher = get_financial_fetcher()
        _financial_fetcher = fetcher

        # 追加模式保存：读取已存在数据，追加新数据
        existing_df = pd.DataFrame()
        if financial_reader.check_exists():
            existing_df = financial_reader.read_csv()

        def on_batch(df_batch: pd.DataFrame):
            nonlocal existing_df
            # 追加新数据
            existing_df = pd.concat([existing_df, df_batch], ignore_index=True)
            # 保存到 CSV（覆盖模式）
            save_csv_data(existing_df, fetcher.output_file, fetcher.date_str)
            logger.info(f"已保存 {len(existing_df)} 条财务指标数据")

        results_df = fetcher.fetch_batch(codes, delay=0.3, show_progress=True, batch_size=10, on_batch=on_batch)

        # 最终保存
        if not results_df.empty:
            logger.info(f"财务指标数据已保存到 {fetcher.date_str}/{fetcher.output_file}")

        # 检查当季度是否有数据（数据日期不是最新季度则为缺失）
        current_quarter_date = f"{datetime.now().year}-03-31" if datetime.now().month <= 4 else \
                               f"{datetime.now().year}-06-30" if datetime.now().month <= 7 else \
                               f"{datetime.now().year}-09-30" if datetime.now().month <= 10 else \
                               f"{datetime.now().year}-12-31"

        missing_count = 0
        if not results_df.empty:
            missing_count = len(results_df[results_df["数据日期"] != current_quarter_date])

        return {
            "success": True,
            "count": len(results_df),
            "missing_count": missing_count,
            "message": f"财务指标刷新完成，成功更新 {len(results_df)} 只股票"
        }

    except Exception as e:
        logger.error(f"刷新财务指标数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"刷新失败: {str(e)}")


# ========== 股东户数刷新接口 ==========


@router.get("/shareholder/status")
async def get_shareholder_status():
    """获取股东户数数据状态"""
    if shareholder_reader is None:
        raise HTTPException(status_code=500, detail="服务未初始化")

    file_exists = shareholder_reader.check_exists()
    last_updated = None
    record_count = 0

    if file_exists:
        sh_df = shareholder_reader.read_csv()
        if not sh_df.empty:
            record_count = len(sh_df)
            # 获取文件修改时间
            from src.utils.helpers import DATA_DIR, get_current_date_dir
            date_str = get_current_date_dir()
            filepath = DATA_DIR / date_str / f"股东户数汇总_{date_str}.csv"
            if filepath.exists():
                last_updated = datetime.fromtimestamp(filepath.stat().st_mtime).isoformat()

    return {
        "exists": file_exists,
        "last_updated": last_updated,
        "record_count": record_count,
    }


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


@router.post("/realtime/refresh")
async def refresh_realtime_prices(body: CodesRequest):
    """
    批量刷新指定股票的实时价格

    使用 comrms 批量接口，一次API调用获取所有股票实时价格。
    该接口每日调用一次即可，用于更新实时价格数据。

    请求参数：
    - codes: 股票代码列表

    返回：
    - success: 是否成功
    - message: 处理结果信息
    - count: 更新的股票数量
    """
    if data_reader is None or m120_service is None:
        raise HTTPException(status_code=500, detail="服务未初始化")

    try:
        codes = [str(c).zfill(6) for c in body.codes]

        logger.info(f"开始批量刷新实时价格，共 {len(codes)} 只股票")

        # 批量更新实时价格
        count = m120_service.update_realtime_prices(codes, show_progress=True)

        return {
            "success": True,
            "message": f"实时价格刷新完成，成功更新 {count} 只股票",
            "count": count
        }

    except Exception as e:
        logger.error(f"刷新实时价格失败: {e}")
        raise HTTPException(status_code=500, detail=f"刷新失败: {str(e)}")


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

    # 获取板块映射文件（使用当前月份目录）
    from src.utils.helpers import get_current_date_dir
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


@router.get("/dividend/status")
async def get_dividend_status():
    """
    获取股息率数据状态

    返回：
    - needs_update: 是否需要更新（CSV行数 < 目标数）
    - last_updated: 上次更新时间
    - file_exists: 文件是否存在
    - pending_count: 待完成数量（目标总数 - 已完成数）
    - target_count: 目标股票总数（红利指数持仓数）
    - completed_count: 已完成数（CSV行数）
    - failed_codes: 失败的股票代码列表（始终为空，简化逻辑）
    """
    from datetime import datetime
    from src.utils.helpers import DATA_DIR, get_current_date_dir

    # 股息率数据文件路径
    date_str = get_current_date_dir()  # YYYY-MM格式
    dividend_file = DATA_DIR / date_str / f"近3年股息率汇总_{date_str}.csv"
    dividend_count_file = DATA_DIR / date_str / f"股票分红次数汇总_{date_str}.csv"

    file_exists = dividend_file.exists()
    last_updated = None
    needs_update = True
    pending_count = 0
    completed_count = 0
    failed_codes: list[str] = []

    # 读取股票分红次数汇总行数作为目标总数（已筛选：主板+分红>10次）
    target_count = 0
    if dividend_count_file.exists():
        try:
            dividend_count_df = pd.read_csv(dividend_count_file)
            # 筛选主板股票（000xxx, 002xxx, 600xxx, 601xxx, 603xxx, 605xxx）
            def is_main_board_code(code) -> bool:
                code_str = str(code).zfill(6)
                return (code_str.startswith('000') or code_str.startswith('001') or
                        code_str.startswith('002') or code_str.startswith('003') or
                        code_str.startswith('600') or code_str.startswith('601') or
                        code_str.startswith('603') or code_str.startswith('605'))

            # 应用筛选：主板 + 分红>10次
            main_board_df = dividend_count_df[dividend_count_df['股票代码'].apply(is_main_board_code)]
            target_count = len(main_board_df[main_board_df['分红次数'] > 10])
        except Exception:
            target_count = 0

    # 读取 CSV 实际行数作为已完成数
    if file_exists:
        timestamp = dividend_file.stat().st_mtime
        last_updated_dt = datetime.fromtimestamp(timestamp)
        last_updated = last_updated_dt.isoformat()

        try:
            csv_df = pd.read_csv(dividend_file)
            completed_count = len(csv_df)
        except Exception:
            completed_count = 0

        # 如果已完成数 < 目标数，则需要更新
        pending_count = target_count - completed_count if target_count > 0 else 0
        needs_update = completed_count < target_count
    else:
        # 文件不存在，需要更新
        needs_update = True

    return {
        "needs_update": needs_update,
        "last_updated": last_updated,
        "file_exists": file_exists,
        "pending_count": pending_count,
        "target_count": target_count,
        "completed_count": completed_count,
        "failed_codes": failed_codes,
    }


@router.post("/dividend/refresh", response_model=RefreshResponse)
async def refresh_dividend_data(request: RefreshRequest):
    """
    刷新股息率核心数据

    该接口用于获取红利指数持仓、计算股息率，并保存到数据文件。
    支持增量更新（断点续传），跳过已处理的股票。

    主要用于 n8n 定时任务调用。

    请求参数：
    - min_dividend: 最小分红次数阈值（默认10）

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
            min_yield=2.0,  # 粗略股息率筛选阈值
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
                    target_count=initial_count,
                    completed_count=initial_count,
                    failed_count=0,
                    failed_codes=[],
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
            nonlocal success_count, failed_count
            try:
                ok = append_csv_row(result.to_dict(), output_file, date_str)
                if ok:
                    success_count += 1
                    logger.info(f"已保存 {result.code} {result.name}")
                else:
                    failed_count += 1
                    logger.warning(f"保存 {result.code} 失败（CSV写入错误）")
            except Exception as e:
                logger.error(f"保存 {result.code} 失败: {e}")
                failed_count += 1

        calculator = DividendCalculator()
        _, failed_codes = calculator.calculate_all(stock_list, on_complete=on_stock_complete)

        end_time = datetime.now()
        skipped_count = initial_count - len(stock_list)
        completed_count = skipped_count + success_count
        failed_count = len(failed_codes)

        logger.info(
            f"刷新完成: 目标总数={initial_count}, "
            f"成功={success_count}, 失败={failed_count}, 跳过={skipped_count}, 累计完成={completed_count}"
        )

        return RefreshResponse(
            success=True,
            message=f"刷新完成，成功更新 {success_count} 只股票",
            stats=RefreshStats(
                total_processed=initial_count,
                new_or_updated=success_count,
                skipped=skipped_count,
                target_count=initial_count,
                completed_count=completed_count,
                failed_count=failed_count,
                failed_codes=failed_codes,
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
@router.get("/report/one-pager")
async def generate_one_pager_report():
    """
    生成高股息率TOP10全景报告 HTML 并直接下载

    报告包含 4 个区块：
    1. 当前股息率TOP10（含近3年均值、排名、行业）
    2. 近3年平均股息率TOP10（柱状图，昨收/M120比值）
    3. 扣非净利润同比TOP10（含3年CAGR、当前股息率）
    4. 3年复合增长率TOP10（含扣非同比、当前股息率）
    """
    if data_reader is None or sort_service is None or filter_service is None:
        raise HTTPException(status_code=500, detail="服务未初始化")

    try:
        from datetime import datetime

        # === 读取数据 ===
        df = data_reader.read_csv()
        if df.empty:
            raise HTTPException(status_code=404, detail="数据文件为空")

        # 读取实时价格和M120
        m120_data = {}
        if m120_service is not None:
            m120_data = m120_service.read_m120_with_deviation()

        # 读取财务指标（含扣非同比和3年CAGR）
        financial_map = {}
        if financial_reader is not None and financial_reader.check_exists():
            fi_df = financial_reader.read_csv()
            for _, fi_row in fi_df.iterrows():
                code = str(fi_row["股票代码"]).zfill(6)
                financial_map[code] = {
                    "net_profit_ex_non_recurring_yoy": float(fi_row["扣非净利润同比"]) if pd.notna(fi_row.get("扣非净利润同比")) else None,
                    "net_profit_cagr_3y": float(fi_row["3年复合增长率"]) if pd.notna(fi_row.get("3年复合增长率")) else None,
                }

        # 读取申万行业
        sw_map = {}
        if stock_info_service is not None:
            codes = df["股票代码"].astype(str).str.zfill(6).tolist()
            sw_map = stock_info_service.get_stocks_info(codes)

        # === 计算4个TOP10 ===
        today_str = datetime.now().strftime("%Y-%m-%d")

        # --- 区块1: 当前股息率TOP10 ---
        df_curr_sorted = df.sort_values("2025年股息率(%)", ascending=False)
        # 建立实时排名映射 (code -> rank)
        rank_realtime_map = {}
        for rank, (_, row) in enumerate(df_curr_sorted.iterrows(), 1):
            code = str(row["股票代码"]).zfill(6)
            rank_realtime_map[code] = rank
        top_curr = []
        for rank, (_, row) in enumerate(df_curr_sorted.head(10).iterrows(), 1):
            code = str(row["股票代码"]).zfill(6)
            sw_info = sw_map.get(code, {})
            avg_yield_3y = row.get("3年平均股息率(%)")
            avg_yield_3y_val = float(avg_yield_3y) if pd.notna(avg_yield_3y) else None
            # 近3年排名
            if avg_yield_3y_val is not None:
                rank_3y = df[df["3年平均股息率(%)"] >= avg_yield_3y_val].shape[0]
            else:
                rank_3y = None
            top_curr.append({
                "rank": rank,
                "name": str(row["股票名称"]),
                "yield_curr": float(row["2025年股息率(%)"]) if pd.notna(row.get("2025年股息率(%)")) else None,
                "yield_3y_avg": avg_yield_3y_val,
                "rank_3y": rank_3y,
                "rank_realtime": rank,
                "industry": sw_info.get("sw_level1") or row.get("来源指数") or "",
                "kofei": financial_map.get(code, {}).get("net_profit_ex_non_recurring_yoy"),
                "cagr": financial_map.get(code, {}).get("net_profit_cagr_3y"),
            })

        # --- 区块1扩展: 实时TOP10的昨收/M120比值（用于柱状图） ---
        # 复用 m120_data 和 df_curr_sorted 构建 top_curr_bars
        top_curr_bars = []
        for _, row in df_curr_sorted.head(10).iterrows():
            code = str(row["股票代码"]).zfill(6)
            m120_info = m120_data.get(code, {})
            ratio = m120_info.get("realtime_deviation")
            if ratio is not None:
                ratio_val = ratio / 100 + 1
            else:
                ratio_val = None
            top_curr_bars.append({
                "name": str(row["股票名称"]),
                "yield_curr": float(row["2025年股息率(%)"]) if pd.notna(row.get("2025年股息率(%)")) else None,
                "ratio": ratio_val,
            })

        # --- 区块2: 近3年平均股息率TOP10（含ratio） ---
        df_3y_sorted = df.sort_values("3年平均股息率(%)", ascending=False)
        top_3y = []
        for rank, (_, row) in enumerate(df_3y_sorted.head(10).iterrows(), 1):
            code = str(row["股票代码"]).zfill(6)
            sw_info = sw_map.get(code, {})
            m120_info = m120_data.get(code, {})
            ratio = m120_info.get("realtime_deviation")
            # realtime_deviation is already (realtime/m120 - 1) * 100 as percentage
            # convert to ratio: ratio = deviation/100 + 1
            if ratio is not None:
                ratio_val = ratio / 100 + 1
            else:
                ratio_val = None
            top_3y.append({
                "rank": rank,
                "name": str(row["股票名称"]),
                "yield_3y_avg": float(row["3年平均股息率(%)"]) if pd.notna(row.get("3年平均股息率(%)")) else None,
                "yield_curr": float(row["2025年股息率(%)"]) if pd.notna(row.get("2025年股息率(%)")) else None,
                "rank_realtime": rank_realtime_map.get(code),
                "ratio": ratio_val,
                "m120": m120_info.get("m120"),
                "industry": sw_info.get("sw_level1") or row.get("来源指数") or "",
                "kofei": financial_map.get(code, {}).get("net_profit_ex_non_recurring_yoy"),
                "cagr": financial_map.get(code, {}).get("net_profit_cagr_3y"),
            })

        # --- 区块3: 扣非同比TOP10 ---
        fin_rows = [(code, data) for code, data in financial_map.items() if data.get("net_profit_ex_non_recurring_yoy") is not None]
        fin_rows.sort(key=lambda x: x[1]["net_profit_ex_non_recurring_yoy"], reverse=True)
        top_kofei = []
        for code, data in fin_rows[:10]:
            # 找股票名称
            name_row = df[df["股票代码"].astype(str).str.zfill(6) == code]
            name = str(name_row.iloc[0]["股票名称"]) if not name_row.empty else code
            sw_info = sw_map.get(code, {})
            yield_curr_row = df_curr_sorted[df_curr_sorted["股票代码"].astype(str).str.zfill(6) == code]
            yield_curr = float(yield_curr_row.iloc[0]["2025年股息率(%)"]) if not yield_curr_row.empty and pd.notna(yield_curr_row.iloc[0].get("2025年股息率(%)")) else None
            top_kofei.append({
                "name": name,
                "kofei": data["net_profit_ex_non_recurring_yoy"],
                "cagr": data["net_profit_cagr_3y"],
                "yield_curr": yield_curr,
                "industry": sw_info.get("sw_level1") or "",
            })

        # --- 区块4: 3年CAGR TOP10 ---
        cagr_rows = [(code, data) for code, data in financial_map.items() if data.get("net_profit_cagr_3y") is not None]
        cagr_rows.sort(key=lambda x: x[1]["net_profit_cagr_3y"], reverse=True)
        top_cagr = []
        for code, data in cagr_rows[:10]:
            name_row = df[df["股票代码"].astype(str).str.zfill(6) == code]
            name = str(name_row.iloc[0]["股票名称"]) if not name_row.empty else code
            sw_info = sw_map.get(code, {})
            yield_curr_row = df_curr_sorted[df_curr_sorted["股票代码"].astype(str).str.zfill(6) == code]
            yield_curr = float(yield_curr_row.iloc[0]["2025年股息率(%)"]) if not yield_curr_row.empty and pd.notna(yield_curr_row.iloc[0].get("2025年股息率(%)")) else None
            top_cagr.append({
                "name": name,
                "cagr": data["net_profit_cagr_3y"],
                "kofei": data["net_profit_ex_non_recurring_yoy"],
                "yield_curr": yield_curr,
                "industry": sw_info.get("sw_level1") or "",
            })

        total_stocks = len(df)

        # === 渲染 HTML ===
        html_content = _render_one_pager_html(
            top_curr, top_3y, top_kofei, top_cagr, top_curr_bars, total_stocks, today_str
        )

        # === 返回下载响应 ===
        from fastapi.responses import StreamingResponse
        import io

        filename = f"dividend_report_{today_str}.html"
        response = StreamingResponse(
            io.BytesIO(html_content.encode("utf-8")),
            media_type="text/html;charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"}
        )
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成报告失败: {e}")
        raise HTTPException(status_code=500, detail=f"生成报告失败: {str(e)}")


def _render_one_pager_html(top_curr, top_3y, top_kofei, top_cagr, top_curr_bars, total_stocks, today_str):
    """渲染单页报告 HTML — 左右布局：表格左，柱状图右，只保留2个区块"""

    # ---- 构建表格行 HTML ----
    def curr_row(r):
        rank_3y_str = f'<span class="tag">#{r["rank_3y"]}</span>' if r.get("rank_3y") else '<span class="tag">—</span>'
        kofei_str = f"{r['kofei']:.2f}%" if r.get('kofei') is not None else "—"
        cagr_str = f"{r['cagr']:.2f}%" if r.get('cagr') is not None else "—"
        return f"""<tr>
  <td>{r['rank']}</td>
  <td class="name">{r['name']}</td>
  <td class="num">{r['yield_curr']:.2f}%</td>
  <td class="num">{r['yield_3y_avg']:.2f}%</td>
  <td class="num">{rank_3y_str}</td>
  <td class="ind">{r.get('industry', '')}</td>
  <td class="num">{kofei_str}</td>
  <td class="num">{cagr_str}</td>
</tr>"""

    def avg3y_row(r, rank):
        rank_rt_str = f'<span class="tag">#{r["rank_realtime"]}</span>' if r.get("rank_realtime") else '<span class="tag">—</span>'
        kofei_str = f"{r['kofei']:.2f}%" if r.get('kofei') is not None else "—"
        cagr_str = f"{r['cagr']:.2f}%" if r.get('cagr') is not None else "—"
        return f"""<tr>
  <td>{rank}</td>
  <td class="name">{r['name']}</td>
  <td class="num">{r['yield_3y_avg']:.2f}%</td>
  <td class="num">{r['yield_curr']:.2f}%</td>
  <td class="num">{rank_rt_str}</td>
  <td class="ind">{r.get('industry', '')}</td>
  <td class="num">{kofei_str}</td>
  <td class="num">{cagr_str}</td>
</tr>"""

    curr_rows_html = "\n".join(curr_row(r) for r in top_curr)
    avg3y_rows_html = "\n".join(avg3y_row(r, i+1) for i, r in enumerate(top_3y))

    bars_svg_curr, x_labels_svg_curr = _build_m120_bars_svg(top_curr_bars, svg_width=480, svg_height=200)
    bars_svg_3y, x_labels_svg_3y = _build_m120_bars_svg(top_3y, svg_width=480, svg_height=200)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A股高股息率TOP10分析</title>
<meta name="author" content="dividend-select">
<meta name="description" content="当前股息率与近3年股息率TOP10分析">
<style>
@font-face {{
  font-family "TsangerJinKai02";
  src: url("../fonts/TsangerJinKai02-W04.ttf") format("truetype"),
     url("https://cdn.jsdelivr.net/gh/tw93/Kami@main/assets/fonts/TsangerJinKai02-W04.ttf") format("truetype");
  font-weight: 400;
  font-style: normal;
}}
@font-face {{
  font-family: "TsangerJinKai02";
  src: url("../fonts/TsangerJinKai02-W05.ttf") format("truetype"),
     url("https://cdn.jsdelivr.net/gh/tw93/Kami@main/assets/fonts/TsangerJinKai02-W05.ttf") format("truetype");
  font-weight: 500;
  font-style: normal;
}}
@page {{ size: A4; margin: 10mm 14mm 10mm 14mm; background: #f5f4ed; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
:root {{
  --parchment: #f5f4ed;
  --near-black: #141413;
  --dark-warm: #3d3d3a;
  --olive: #504e49;
  --stone: #6b6a64;
  --brand: #1B365D;
  --border: #e8e6dc;
  --border-soft: #e5e3d8;
  --tag-bg: #E4ECF5;
  --serif: "TsangerJinKai02", "Source Han Seric SC", "Noto Serif CJK SC", "Songti SC", Georgia, serif;
}}
html, body {{ background: var(--parchment); height: 100%; }}
@media screen {{ body {{ width: 100%; margin: 0 auto; padding: 8mm 12mm; height: 100%; box-sizing: border-box; }} }}
@media (max-width: 600px) {{ body {{ padding: 4pt; font-size: 9pt; }} .blocks .block {{ grid-template-columns: 1fr; gap: 6pt; }} .header {{ flex-direction: column; gap: 4pt; }} }}
body {{ color: var(--near-black); font-family: var(--serif); font-size: 8.5pt; line-height: 1.4; letter-spacing: 0.2pt; }}
.header {{ border-left: 2.5pt solid var(--brand); border-radius: 1.5pt; padding-left: 8pt; margin-bottom: 8pt; display: flex; align-items: flex-end; justify-content: space-between; gap: 16pt; }}
.title-block {{ flex: 1; }}
.eyebrow {{ font-size: 7.5pt; color: var(--brand); letter-spacing: 1pt; margin-bottom: 2pt; }}
h1 {{ font-family: var(--serif); font-size: 18pt; font-weight: 500; color: var(--near-black); line-height: 1.15; margin-bottom: 3pt; }}
.subtitle {{ font-size: 9pt; color: var(--olive); line-height: 1.4; }}
.meta {{ font-size: 7.5pt; color: var(--stone); text-align: right; line-height: 1.4; }}
.blocks {{ display: flex; flex-direction: column; gap: 4pt; margin-bottom: 4pt; }}
.blocks .block {{ display: grid; grid-template-columns: 1fr 1fr; gap: 6pt; align-items: stretch; }}
.blocks .block section {{ break-inside: avoid; display: flex; flex-direction: column; }}
.blocks .block section h2 {{ flex: 0 0 auto; margin-bottom: 2pt; }}
.blocks .block section table {{ flex: 0 0 auto; }}
.blocks .block section figure {{ flex: 0 0 auto; display: flex; flex-direction: column; justify-content: flex-end; max-height: 300px; }}
.blocks .block section figure svg {{ width: 100%; height: 250px; }}
h2 {{ font-family: var(--serif); font-size: 10pt; font-weight: 500; color: var(--near-black); margin-bottom: 4pt; border-left: 1.8pt solid var(--brand); padding-left: 5pt; }}
h2 .sub {{ font-size: 7.5pt; color: var(--stone); font-weight: 400; margin-left: 4pt; }}
table {{ width: 100%; border-collapse: collapse; font-size: 7.5pt; margin: 0; break-inside: avoid; }}
table th {{ text-align: left; font-weight: 500; color: var(--dark-warm); padding: 2pt 4pt; border-bottom: 0.7pt solid var(--border); background: transparent; white-space: nowrap; }}
table td {{ padding: 2pt 4pt; border-bottom: 0.3pt solid var(--border-soft); vertical-align: top; line-height: 1.3; }}
table td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
table th.num {{ text-align: right; }}
table td.name {{ max-width: 56px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
table td.ind {{ max-width: 58px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.tag {{ display: inline-block; background: var(--tag-bg); color: var(--brand); font-size: 6pt; font-weight: 500; padding: 0.3pt 2pt; border-radius: 2pt; letter-spacing: 0.1pt; }}
figure {{ margin: 0; break-inside: avoid; }}
figcaption {{ font-size: 7pt; color: var(--olive); margin-top: 2pt; line-height: 1.35; }}
.footer {{ margin-top: 5pt; padding-top: 3pt; border-top: 0.3pt dotted var(--border); font-size: 7pt; color: var(--stone); display: flex; justify-content: space-between; letter-spacing: 0.15pt; }}
</style>
</head>
<body>

<div class="header">
  <div class="title-block">
    <div class="eyebrow">A股 · 股息率分析</div>
    <h1>高股息率TOP10排名全景</h1>
    <div class="subtitle">实时 vs 近3年平均股息率 · 扣非净利润同比 vs 3年复合增长率 · 数据更新于 {today_str}</div>
  </div>
  <div class="meta">{total_stocks}只股票<br>样本覆盖</div>
</div>

<div class="blocks">

  <!-- BLOCK 1: 实时股息率TOP10 (左表格 右柱状图) -->
  <div class="block">
    <section>
      <h2>实时股息率TOP10<span class="sub">近3年均值 &amp; 排名 &amp; 行业 &amp; 扣非同比 &amp; 3年CAGR</span></h2>
      <table>
        <thead>
          <tr><th>#</th><th>股票</th><th class="num">实时</th><th class="num">近3年均值</th><th class="num">近3年排名</th><th>行业</th><th class="num">扣非同比</th><th class="num">3年CAGR</th></tr>
        </thead>
        <tbody>
{curr_rows_html}
        </tbody>
      </table>
    </section>
    <section>
      <h2>实时TOP10<span class="sub">昨日收盘/M120比值</span></h2>
      <figure>
        <svg viewBox="0 0 480 200" xmlns="http://www.w3.org/2000/svg" style="width:100%;display:block;">
          <rect width="100%" height="100%" fill="#f5f4ed"/>
          <line x1="40" y1="160" x2="476" y2="160" stroke="#141413" stroke-width="0.7"/>
          <line x1="40" y1="120" x2="476" y2="120" stroke="#e8e7e1" stroke-width="0.5"/>
          <text x="34" y="124" fill="#6b6a64" font-size="7" font-family="inherit" text-anchor="end">0.90</text>
          <line x1="40" y1="96" x2="476" y2="96" stroke="#e8e7e1" stroke-width="0.5"/>
          <text x="34" y="100" fill="#6b6a64" font-size="7" font-family="inherit" text-anchor="end">1.00</text>
          <line x1="40" y1="64" x2="476" y2="64" stroke="#e8e7e1" stroke-width="0.5"/>
          <text x="34" y="68" fill="#6b6a64" font-size="7" font-family="inherit" text-anchor="end">1.10</text>
          <line x1="40" y1="32" x2="476" y2="32" stroke="#e8e7e1" stroke-width="0.5"/>
          <text x="34" y="36" fill="#6b6a64" font-size="7" font-family="inherit" text-anchor="end">1.20</text>
          <line x1="40" y1="96" x2="476" y2="96" stroke="#1B365D" stroke-width="0.8" stroke-dasharray="4 3"/>
          <text x="468" y="100" fill="#1B365D" font-size="6" font-family="inherit">M120=1</text>
          {bars_svg_curr}
          {x_labels_svg_curr}
          <text x="10" y="100" fill="#6b6a64" font-size="6" font-family="inherit" text-anchor="middle" transform="rotate(-90 10 100)" letter-spacing="0.1em">昨收/M120</text>
        </svg>
      </figure>
      <figcaption>蓝色≥1.00，灰色&lt;1.00</figcaption>
    </section>
  </div>

  <!-- BLOCK 2: 近3年均值TOP10 (左表格 右柱状图) -->
  <div class="block">
    <section>
      <h2>近3年均值TOP10<span class="sub">实时股息率 &amp; 排名 &amp; 行业 &amp; 扣非同比 &amp; 3年CAGR</span></h2>
      <table>
        <thead>
          <tr><th>#</th><th>股票</th><th class="num">近3年均值</th><th class="num">实时</th><th class="num">实时排名</th><th>行业</th><th class="num">扣非同比</th><th class="num">3年CAGR</th></tr>
        </thead>
        <tbody>
{avg3y_rows_html}
        </tbody>
      </table>
    </section>
    <section>
      <h2>近3年均值TOP10<span class="sub">昨日收盘/M120比值</span></h2>
      <figure>
        <svg viewBox="0 0 480 200" xmlns="http://www.w3.org/2000/svg" style="width:100%;display:block;">
          <rect width="100%" height="100%" fill="#f5f4ed"/>
          <line x1="40" y1="160" x2="476" y2="160" stroke="#141413" stroke-width="0.7"/>
          <line x1="40" y1="120" x2="476" y2="120" stroke="#e8e7e1" stroke-width="0.5"/>
          <text x="34" y="124" fill="#6b6a64" font-size="7" font-family="inherit" text-anchor="end">0.90</text>
          <line x1="40" y1="96" x2="476" y2="96" stroke="#e8e7e1" stroke-width="0.5"/>
          <text x="34" y="100" fill="#6b6a64" font-size="7" font-family="inherit" text-anchor="end">1.00</text>
          <line x1="40" y1="64" x2="476" y2="64" stroke="#e8e7e1" stroke-width="0.5"/>
          <text x="34" y="68" fill="#6b6a64" font-size="7" font-family="inherit" text-anchor="end">1.10</text>
          <line x1="40" y1="32" x2="476" y2="32" stroke="#e8e7e1" stroke-width="0.5"/>
          <text x="34" y="36" fill="#6b6a64" font-size="7" font-family="inherit" text-anchor="end">1.20</text>
          <line x1="40" y1="96" x2="476" y2="96" stroke="#1B365D" stroke-width="0.8" stroke-dasharray="4 3"/>
          <text x="468" y="100" fill="#1B365D" font-size="6" font-family="inherit">M120=1</text>
          {bars_svg_3y}
          {x_labels_svg_3y}
          <text x="10" y="100" fill="#6b6a64" font-size="6" font-family="inherit" text-anchor="middle" transform="rotate(-90 10 100)" letter-spacing="0.1em">昨收/M120</text>
        </svg>
      </figure>
      <figcaption>蓝色≥1.00，灰色&lt;1.00</figcaption>
    </section>
  </div>

</div>

<div class="footer">
  <span>数据来源：dividend-select · {total_stocks}只高股息A股样本</span>
  <span>{today_str} · 仅供投资参考，不构成投资建议</span>
</div>

</body>
</html>"""
    return html


def _build_m120_bars_svg(top_3y, svg_width=480, svg_height=200):
    """构建近3年TOP10柱状图的 SVG 元素

    Args:
        top_3y: 数据列表
        svg_width: SVG viewBox 宽度（默认480，保持向后兼容）
        svg_height: SVG viewBox 高度（默认300），控制 Y 轴范围
    """
    # 基于 svg_height 计算 Y 轴范围（基准线 y=160 → 下方留 40px）
    bottom = svg_height - 40
    top = 20
    baseline = bottom  # 基准线（对应 ratio_min）
    ratio_min = 0.75
    ratio_max = 1.30
    y_scale = (bottom - top) / (ratio_max - ratio_min)  # (ratio - ratio_min) → 像素

    # x 轴范围: 左轴 40，右轴 svg_width-14
    left_axis = 40
    right_edge = svg_width - 14
    bar_w = 24  # 柱宽
    positions = []
    n = min(len(top_3y), 10)
    if n > 1:
        step = (right_edge - left_axis) / (n - 1)
        positions = [int(left_axis + i * step) for i in range(n)]
    else:
        positions = [int((left_axis + right_edge) / 2)]

    def ratio_to_y(r):
        return baseline - (r - ratio_min) * y_scale

    bars = []
    labels = []

    for i, stock in enumerate(top_3y[:10]):
        cx = positions[i]
        ratio = stock["ratio"]
        if ratio is None:
            h = 20
            y_top = baseline - h
            col = "#B2B1AC"
            ratio_str = "—"
        else:
            h = max(5, (ratio - ratio_min) * y_scale)
            y_top = ratio_to_y(ratio)
            ratio_str = f"{ratio:.3f}"
            col = "#1B365D" if ratio >= 1.0 else "#504e49" if ratio >= 0.95 else "#B2B1AC"

        bars.append(f'<rect x="{cx-bar_w//2}" y="{y_top}" width="{bar_w}" height="{h}" fill="{col}" rx="2"/>')
        bars.append(f'<text x="{cx}" y="{y_top-4}" fill="#141413" font-size="8" font-family="inherit" font-weight="500" text-anchor="middle">{ratio_str}</text>')

        name = stock.get("name", "")
        # 优先用 yield_curr（实时TOP10），其次用 yield_3y_avg（近3年均值TOP10）
        yield_val = stock.get("yield_curr") if stock.get("yield_curr") is not None else stock.get("yield_3y_avg")
        yield_str = f"{yield_val:.2f}%" if yield_val is not None else "—"
        labels.append(f'<text x="{cx}" y="{baseline+18}" fill="#504e49" font-size="7.5" font-family="inherit" text-anchor="middle" transform="rotate(-35 {cx} {baseline+18})">{name}</text>')
        labels.append(f'<text x="{cx}" y="{baseline+30}" fill="#504e49" font-size="6.5" font-family="inherit" text-anchor="middle" transform="rotate(-35 {cx} {baseline+30})">{yield_str}</text>')

    bars_svg = "\n        ".join(bars)
    labels_svg = "\n        ".join(labels)
    return bars_svg, labels_svg
