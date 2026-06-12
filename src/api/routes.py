"""
API 路由定义
"""
from datetime import datetime
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Body, HTTPException, Query

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
from src.services import weekly_comparison
from src.data.financial_fetcher import FinancialFetcher
from src.utils.helpers import save_csv_data, DATA_DIR
from src.api.helpers.aux_data import (
    REFRESH_INTERVAL_DAYS,
    aux_file_path,
    current_quarter,
    days_since_update,
    file_mtime_iso,
    find_latest_aux_file,
)
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
        eps=financial_data.get("eps") if financial_data else None,
        eps_year=financial_data.get("eps_year") if financial_data else None,
        payout_ratio=None,  # 下面计算后赋值
        dividend_history=None,  # 先设为 None，后面解析后替换
    )

    # 计算分红比例：使用最近一期年报的 EPS 同比年度的 DPS
    # 仅在 EPS > 0 且对应年度 DPS > 0 时计算，否则保持 None
    eps = financial_data.get("eps") if financial_data else None
    eps_year = financial_data.get("eps_year") if financial_data else None
    if eps is not None and eps > 0 and eps_year is not None:
        dps_key = f"{eps_year}年分红(元/股)"
        dps = _to_float(row.get(dps_key))
        if dps is not None and dps > 0:
            stock.payout_ratio = round(dps / eps * 100, 2)

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
                    "eps": float(fi_row["最新EPS(元)"]) if pd.notna(fi_row.get("最新EPS(元)")) else None,
                    "eps_year": int(fi_row["最新EPS年度"]) if pd.notna(fi_row.get("最新EPS年度")) else None,
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
    min_yield: float = Query(5.0, description="最小股息率(%)，默认5%，传0则不过滤"),
    sort_by: str = Query("avg_yield_3y", description="排序字段"),
    sort_order: str = Query("desc", description="排序方向(asc/desc)")
):
    """
    批量获取股票的 M120 数据

    min_yield=0 时不过滤，返回所有有股息数据的股票（用于前端技术指标匹配）
    默认 min_yield=5 用于 n8n 定时调用（只刷新高股息股）

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

    # 筛选：min_yield=0 时不过滤，返回所有股票（前端匹配用）
    # 否则只返回高股息股（n8n 刷新用）
    if min_yield > 0:
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
    - needs_update: 是否需要更新（文件不存在 或 有股票缺失M120数据）
    - last_updated: 上次更新时间
    - file_exists: 文件是否存在
    - missing_count: 缺失M120数据的股票数量
    - missing_codes: 缺失M120数据的股票代码列表
    """
    if m120_service is None or data_reader is None:
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

    # 读取当前股票列表（与 stocks 接口一致，排除只看高股息的过滤）
    # 用 min_yield=0 获取所有有分红的股票，与前端实际展示范围对齐
    all_stocks_df = data_reader.read_csv()
    all_codes = set(str(int(c)).zfill(6) for c in all_stocks_df["股票代码"])

    # 读取 M120 数据
    m120_data = m120_service.read_m120_data()
    m120_codes = set(m120_data.keys())

    # 找出缺失 M120 的股票（当前股票列表中有，但 m120 数据中没有的）
    missing_codes = sorted(all_codes - m120_codes)
    needs_update = not file_exists or len(missing_codes) > 0

    return {
        "needs_update": needs_update,
        "last_updated": last_updated,
        "file_exists": file_exists,
        "missing_count": len(missing_codes),
        "missing_codes": missing_codes,
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


@router.get("/sw-industry/status")
async def get_sw_industry_status():
    """
    获取申万行业数据状态

    返回：
    - exists: 文件是否存在
    - last_updated: 上次更新时间
    - days_since_update: 距上次更新天数
    - quarter: 数据季度
    - needs_update: 是否需要更新（文件不存在或超过90天）
    """
    path = find_latest_aux_file("个股申万行业映射")
    days = days_since_update(path) if path else None
    return {
        "exists": path is not None,
        "last_updated": file_mtime_iso(path) if path else None,
        "days_since_update": days,
        "quarter": current_quarter(),
        "needs_update": (days is None) or (days > REFRESH_INTERVAL_DAYS),
    }


@router.post("/sw-industry/refresh")
async def refresh_sw_industry(force: bool = Query(False)):
    """
    刷新申万行业数据（通过问财 API）

    需要 PYWENCAI_COOKIE 环境变量

    查询参数：
    - force: 是否强制刷新（忽略90天节流）
    """
    path = find_latest_aux_file("个股申万行业映射")
    days = days_since_update(path) if path else None

    if not force and days is not None and days < REFRESH_INTERVAL_DAYS:
        raise HTTPException(
            status_code=429,
            detail=f"距上次更新仅 {days} 天，<{REFRESH_INTERVAL_DAYS}天，禁止刷新（force=true 强制）"
        )

    try:
        from src.data.sw_industry_fetcher import SwIndustryFetcher
        df = SwIndustryFetcher().fetch_all()
        if df.empty:
            raise HTTPException(status_code=502, detail="akshare 返回空数据")
        return {
            "success": True,
            "count": len(df),
            "quarter": current_quarter(),
            "message": f"申万行业刷新完成，共 {len(df)} 条"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"刷新申万行业失败: {e}")
        raise HTTPException(status_code=500, detail=f"刷新失败: {str(e)}")


@router.get("/financial/status")
async def get_financial_status():
    """
    获取财务指标数据状态

    返回：
    - exists: 文件是否存在
    - last_updated: 上次更新时间
    - data_date: 数据日期（季度）
    - days_since_update: 距上次更新天数
    - quarter: 数据季度
    - needs_update: 是否需要更新
    - missing_codes: 缺失数据的股票代码列表
    """
    if financial_reader is None:
        raise HTTPException(status_code=500, detail="服务未初始化")

    fi_path = find_latest_aux_file("财务指标汇总")
    file_exists = financial_reader.check_exists()
    last_updated = file_mtime_iso(fi_path) if fi_path else None
    days = days_since_update(fi_path) if fi_path else None
    quarter = financial_reader.get_quarter() or current_quarter()
    data_date = None
    missing_codes: list[str] = []

    # 提前计算 filtered_codes（file_exists 真假都需要用到）
    df = data_reader.read_csv()
    df = filter_service.filter_by_3y_dividend(df, min_avg_yield=3.0)
    filtered_codes = df["股票代码"].astype(str).str.zfill(6).tolist()

    if file_exists:
        fi_df = financial_reader.read_csv()
        if not fi_df.empty:
            dates = fi_df["数据日期"].dropna().unique()
            if len(dates) > 0:
                data_date = sorted(dates)[-1]
        existing_codes = fi_df["股票代码"].astype(str).str.zfill(6).tolist()
        missing_codes = [c for c in filtered_codes if c not in existing_codes]
    else:
        missing_codes = filtered_codes

    return {
        "exists": file_exists,
        "last_updated": last_updated,
        "data_date": data_date,
        "days_since_update": days,
        "quarter": quarter,
        "needs_update": (days is None) or (days > REFRESH_INTERVAL_DAYS),
        "missing_count": len(missing_codes),
        "missing_codes": missing_codes,
    }


@router.post("/financial/refresh")
async def refresh_financial_data(
    body: Optional[CodesRequest] = None,
    force: bool = Query(False),
):
    """
    刷新财务指标数据

    只更新根据股息率筛选出来的股票（3年平均股息率 >= 3%）。
    如果某只股票当季度数据还没有，则跳过（返回时会标记为缺失）。

    查询参数：
    - force: 是否强制刷新（忽略90天节流）

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

    fi_path = find_latest_aux_file("财务指标汇总")
    days = days_since_update(fi_path) if fi_path else None
    if not force and days is not None and days < REFRESH_INTERVAL_DAYS:
        raise HTTPException(
            status_code=429,
            detail=f"距上次更新仅 {days} 天，<{REFRESH_INTERVAL_DAYS}天，禁止刷新（force=true 强制）"
        )

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

        # 写入路径：当前季度后缀文件（同季度刷新幂等，跨季度自动新建）
        write_path = aux_file_path("财务指标汇总")

        # 追加模式保存：读取已存在数据，追加新数据
        existing_df = pd.DataFrame()
        if financial_reader.check_exists():
            existing_df = financial_reader.read_csv()

        def on_batch(df_batch: pd.DataFrame):
            nonlocal existing_df
            existing_df = pd.concat([existing_df, df_batch], ignore_index=True)
            write_path.parent.mkdir(parents=True, exist_ok=True)
            existing_df.to_csv(write_path, index=False, encoding="utf-8-sig")
            logger.info(f"已保存 {len(existing_df)} 条财务指标数据")

        results_df = fetcher.fetch_batch(codes, delay=0.3, show_progress=True, batch_size=10, on_batch=on_batch)

        # 最终保存
        if not results_df.empty:
            logger.info(f"财务指标数据已保存到 {write_path}")

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
    """
    获取股东户数数据状态

    返回：
    - exists: 文件是否存在
    - last_updated: 上次更新时间
    - days_since_update: 距上次更新天数
    - quarter: 数据季度
    - needs_update: 是否需要更新（文件不存在或超过90天）
    - record_count: 记录数量
    """
    if shareholder_reader is None:
        raise HTTPException(status_code=500, detail="服务未初始化")

    sh_path = find_latest_aux_file("股东户数汇总")
    days = days_since_update(sh_path) if sh_path else None
    file_exists = shareholder_reader.check_exists()
    record_count = 0

    if file_exists:
        sh_df = shareholder_reader.read_csv()
        if not sh_df.empty:
            record_count = len(sh_df)

    return {
        "exists": file_exists,
        "last_updated": file_mtime_iso(sh_path) if sh_path else None,
        "days_since_update": days,
        "quarter": shareholder_reader.get_quarter() or current_quarter(),
        "needs_update": (days is None) or (days > REFRESH_INTERVAL_DAYS),
        "record_count": record_count,
    }


@router.post("/shareholder/refresh")
async def refresh_shareholder_data(force: bool = Query(False)):
    """
    刷新股东户数数据

    查询参数：
    - force: 是否强制刷新（忽略90天节流）
    """
    sh_path = find_latest_aux_file("股东户数汇总")
    days = days_since_update(sh_path) if sh_path else None

    if not force and days is not None and days < REFRESH_INTERVAL_DAYS:
        raise HTTPException(
            status_code=429,
            detail=f"距上次更新仅 {days} 天，<{REFRESH_INTERVAL_DAYS}天，禁止刷新（force=true 强制）"
        )

    try:
        from src.data.shareholder_fetcher import ShareholderFetcher
        fetcher = ShareholderFetcher()
        success = fetcher.fetch_and_save()
        if not success:
            raise HTTPException(status_code=502, detail="股东户数数据获取失败")
        return {
            "success": True,
            "count": record_count if (record_count := len(shareholder_reader.read_csv())) > 0 else 0,
            "quarter": current_quarter(),
            "message": "股东户数刷新完成"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"刷新股东户数失败: {e}")
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


@router.get("/board/status")
async def get_board_status():
    """
    获取个股板块映射数据状态

    返回：
    - exists: 文件是否存在
    - last_updated: 上次更新时间
    - days_since_update: 距上次更新天数
    - quarter: 数据季度
    - needs_update: 是否需要更新（文件不存在或超过90天）
    - record_count: 现有板块映射记录数
    - missing_count: 持仓股票中未映射板块的股票数
    - missing_codes: 持仓股票中未映射板块的股票代码列表
    """
    path = find_latest_aux_file("个股板块映射")
    days = days_since_update(path) if path else None

    record_count = 0
    missing_codes: list[str] = []
    existing_codes: set[str] = set()

    # 读取现有板块映射文件
    if path is not None and path.exists():
        try:
            existing_df = pd.read_csv(path, encoding="utf-8-sig")
            existing_df["股票代码"] = existing_df["股票代码"].astype(str).str.zfill(6)
            existing_codes = set(existing_df["股票代码"].tolist())
            record_count = len(existing_df)
        except Exception as e:
            logger.warning(f"读取板块映射文件失败: {e}")

    # 计算缺失：持仓股票 - 已有映射
    if data_reader is not None:
        try:
            holdings_df = data_reader.read_csv()
            if not holdings_df.empty and "股票代码" in holdings_df.columns:
                holdings_codes = set(holdings_df["股票代码"].astype(str).str.zfill(6).tolist())
                missing_codes = sorted(holdings_codes - existing_codes)
        except Exception as e:
            logger.warning(f"读取红利指数持仓数据失败: {e}")

    return {
        "exists": path is not None,
        "last_updated": file_mtime_iso(path) if path else None,
        "days_since_update": days,
        "quarter": current_quarter(),
        "needs_update": (days is None) or (days > REFRESH_INTERVAL_DAYS),
        "record_count": record_count,
        "missing_count": len(missing_codes),
        "missing_codes": missing_codes,
    }


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

    # 板块映射文件按季度后缀 glob 取最新
    board_file = find_latest_aux_file("个股板块映射")

    if board_file is None or not board_file.exists():
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
async def refresh_board_mapping(
    body: Optional[CodesRequest] = Body(None),
    force: bool = Query(False),
):
    """
    刷新个股板块映射数据

    不传 body：全量刷新所有红利指数持仓股票（219 只，约3-5 分钟）。
    传 body.codes：仅刷新指定股票，追加到现有 CSV（约 delay×N 秒）。

    查询参数：
    - force: 是否强制刷新（忽略90天节流）

    请求参数（可选）：
    - codes: 股票代码列表（增量补缺时传 status 返回的 missing_codes）

    返回：
    - success: 是否成功
    - message: 处理结果信息
    - mode: "full" 或 "incremental"
    - stats: 统计信息
      - total_stocks: 总股票数
      - success_count: 成功获取数
      - failed_count: 失败数
      - file_path: 文件路径
      - start_time: 开始时间
      - end_time: 结束时间

    注意：
    - 全量刷新耗时较长（约3-5分钟，取决于股票数量）
    - 如果刷新正在进行中，将返回 409 Conflict 错误
    """
    global _is_refreshing_board

    # 90 天节流（与其它辅助数据共用）
    # 注意：仅全量模式强制节流，增量模式不阻断（用户主动补缺）
    if body is None or not body.codes:
        path = find_latest_aux_file("个股板块映射")
        days = days_since_update(path) if path else None
        if not force and days is not None and days < REFRESH_INTERVAL_DAYS:
            raise HTTPException(
                status_code=429,
                detail=f"距上次更新仅 {days} 天，<{REFRESH_INTERVAL_DAYS}天，禁止刷新（force=true 强制）"
            )

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

        # 创建板块映射获取器（不再传 date_str；输出走季度后缀文件）
        from src.data import BoardMappingFetcher
        fetcher = BoardMappingFetcher()

        if body is not None and body.codes:
            # 增量模式：仅刷新指定股票
            codes = [str(c).zfill(6) for c in body.codes]
            logger.info(f"开始按 codes 增量刷新板块映射，共 {len(codes)} 只")
            success = fetcher.update_by_codes(codes, show_progress=True)
            mode = "incremental"
            message = f"板块映射增量刷新完成（{len(codes)} 只）"
        else:
            # 全量模式：刷新所有持仓股票
            logger.info("开始全量刷新板块映射数据")
            success = fetcher.update(show_progress=True)
            mode = "full"
            message = "板块映射全量刷新完成"

        end_time = datetime.now()

        if success:
            logger.info(f"板块映射刷新完成（{mode}）")
            return {
                "success": True,
                "message": message,
                "mode": mode,
                "stats": {
                    "total_stocks": len(fetcher.stock_names),
                    "success_count": len(fetcher.stock_names) - len(fetcher.failed_stocks),
                    "failed_count": len(fetcher.failed_stocks),
                    "file_path": str(fetcher.output_file),
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

    # 优先读 prefilter csv 算 target_count（与 refresh 实际口径对齐）
    # refresh 入口写盘 data/{date_str}/prefilter_stock_list_{date_str}.csv
    prefilter_file = DATA_DIR / date_str / f"prefilter_stock_list_{date_str}.csv"
    target_count = 0
    if prefilter_file.exists():
        try:
            prefilter_df = pd.read_csv(prefilter_file)
            target_count = len(prefilter_df)
        except Exception:
            target_count = 0

    # fallback: prefilter csv 不存在时用原算法（主板+分红>10次）
    # 冷启动或 prefilter 失败时走这条
    if target_count == 0 and dividend_count_file.exists():
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
        # max(0, ...) 兜底：prefilter 后 target 可能 < completed（CSV 残留 1 只历史数据）
        pending_count = max(0, target_count - completed_count) if target_count > 0 else 0
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
        # fhps 全市场预案缓存状态（每次 refresh 会重拉，~30s）
        "fhps": {
            "cache_path": str(DATA_DIR / "fhps" / "fhps_20251231.csv"),
            "cache_exists": (DATA_DIR / "fhps" / "fhps_20251231.csv").exists(),
            "cache_mtime": datetime.fromtimestamp(
                (DATA_DIR / "fhps" / "fhps_20251231.csv").stat().st_mtime
            ).isoformat() if (DATA_DIR / "fhps" / "fhps_20251231.csv").exists() else None,
            "year_end": "20251231",
            "note": "每次 /dividend/refresh 都会强制重拉（~30s），无 mtime TTL",
        },
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
    _is_refreshing = True  # 必须在 try 之前设置，异常路径也保证能复位（finally）

    try:
        logger.info(f"开始刷新股息率数据，min_dividend={request.min_dividend}")

        # 导入必要的模块
        from src.core import DividendCalculator
        from src.data import IndexHoldingsFetcher
        from src.data.fhps_fetcher import FHPSFetcher
        from src.utils import (
            append_csv_row,
            load_existing_codes,
            get_current_date_dir,
        )

        # Step 0: 拉取 fhps 全市场 2025 年报预案数据（每次重拉 ~30s）
        # 行为变更（commit 待补）: 失败从直接 503 改为 logger.warning + 降级
        # 不预筛继续 refresh，prefilter 跳过、calculator 收到 None 走原路径
        # （calculator 仍可能 RuntimeError 进 failed_codes，但 refresh 不会中断）
        logger.info("Step 0: 拉取 fhps 全市场 2025 年报预案数据...")
        fhps_fetcher = None
        try:
            fhps_fetcher = FHPSFetcher(year_end="20251231")
            fhps_fetcher.fetch()
            s = fhps_fetcher.stats()
            logger.info(
                f"fhps 加载完成: {s['total_rows']} 行, 覆盖 {s['unique_stocks']} 只股票"
            )
        except Exception as e:
            logger.warning(f"fhps 拉取失败，降级不预筛继续 refresh: {e}")
            fhps_fetcher = None

        # 获取当前日期目录
        date_str = get_current_date_dir()
        output_file = "近3年股息率汇总.csv"

        # Step 1: 获取股票列表（使用 API 获取）
        logger.info("Step 1: 获取股票列表...")
        fetcher = IndexHoldingsFetcher(use_local=False, fhps_fetcher=fhps_fetcher)
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

        # 写 prefilter 后的 stock_list 持久化（status 接口读这个算 target_count）
        # 在断点续传过滤之前写，保 142 全量；status 接口对齐 refresh 实际口径
        from src.utils.helpers import save_csv_data
        prefilter_df = pd.DataFrame([{"股票代码": s.code} for s in stock_list])
        save_csv_data(prefilter_df, "prefilter_stock_list", date_str)
        logger.info(f"prefilter stock_list 已写盘: {len(stock_list)} 只")

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

        calculator = DividendCalculator(fhps_fetcher=fhps_fetcher)
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
                failed_codes=[str(c) for c in failed_codes],
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
        _is_refreshing = False
        logger.debug("股息率刷新并发控制标志已清除")


@router.post("/dividend/fhps/refresh")
async def refresh_fhps_cache():
    """
    强制刷新 fhps 全市场预案缓存（不动 dividend 主流程）

    用例: 财报季（4-6 月）每天都想看最新 fhps 进度，又不想跑完整 dividend 刷新

    返回:
    - success: 是否成功
    - message: 提示信息
    - stats: fhps 缓存元信息（year_end / cache_path / total_rows / unique_stocks）
    """
    from src.data.fhps_fetcher import FHPSFetcher
    fetcher = FHPSFetcher(year_end="20251231")
    try:
        fetcher.fetch()
        s = fetcher.stats()
        return {
            "success": True,
            "message": "fhps 缓存已刷新",
            "stats": s,
        }
    except Exception as e:
        logger.error(f"fhps 强制刷新失败: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"fhps 刷新失败: {str(e)}",
        )


async def _load_report_context() -> dict:
    """
    加载生成报告所需的全部数据（one-pager / carousel 路由共用）。

    返回:
        dict 含 top_curr / top_3y / top_kofei / top_cagr / top_curr_bars /
             total_stocks / today_str 七个键，可直接 **ctx 传给渲染函数。
    """
    if data_reader is None or sort_service is None or filter_service is None:
        raise HTTPException(status_code=500, detail="服务未初始化")

    from datetime import datetime

    # === 读取数据 ===
    df = data_reader.read_csv()
    if df.empty:
        raise HTTPException(status_code=404, detail="数据文件为空")

    # 读取实时价格和M120
    m120_data = {}
    if m120_service is not None:
        m120_data = m120_service.read_m120_with_deviation()

    # === 计算实时股息率（实时价口径，与前端一致）===
    # 公式：2025年分红(元/股) / 实时价 × 100
    yield_realtime_map = {}
    for _, _r in df.iterrows():
        _code = str(_r["股票代码"]).zfill(6)
        _div = _r.get("2025年分红(元/股)")
        _rt = m120_data.get(_code, {}).get("realtime")
        if pd.notna(_div) and _rt and _rt > 0:
            yield_realtime_map[_code] = round(float(_div) / float(_rt) * 100, 2)
    df = df.copy()
    df["_yield_realtime"] = df["股票代码"].astype(str).str.zfill(6).map(yield_realtime_map)

    # 读取财务指标（含扣非同比和3年CAGR）
    financial_map = {}
    if financial_reader is not None and financial_reader.check_exists():
        fi_df = financial_reader.read_csv()
        for _, fi_row in fi_df.iterrows():
            code = str(fi_row["股票代码"]).zfill(6)
            financial_map[code] = {
                "net_profit_ex_non_recurring_yoy": float(fi_row["扣非净利润同比"]) if pd.notna(fi_row.get("扣非净利润同比")) else None,
                "net_profit_cagr_3y": float(fi_row["3年复合增长率"]) if pd.notna(fi_row.get("3年复合增长率")) else None,
                "eps": float(fi_row["最新EPS(元)"]) if pd.notna(fi_row.get("最新EPS(元)")) else None,
                "eps_year": int(fi_row["最新EPS年度"]) if pd.notna(fi_row.get("最新EPS年度")) else None,
            }

    # 读取申万行业
    sw_map = {}
    if stock_info_service is not None:
        codes = df["股票代码"].astype(str).str.zfill(6).tolist()
        sw_map = stock_info_service.get_stocks_info(codes)

    today_str = datetime.now().strftime("%Y-%m-%d")

    # --- 区块1: 当前股息率TOP10（按实时股息率排序）---
    df_curr_sorted = df.sort_values("_yield_realtime", ascending=False, na_position="last")
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
        if avg_yield_3y_val is not None:
            rank_3y = df[df["3年平均股息率(%)"] >= avg_yield_3y_val].shape[0]
        else:
            rank_3y = None
        div_per_share = float(row["2025年分红(元/股)"]) if pd.notna(row.get("2025年分红(元/股)")) else None
        eps = financial_map.get(code, {}).get("eps")
        # 分红比例 = 分红 / EPS × 100%
        payout_ratio = None
        if div_per_share and eps and eps > 0:
            payout_ratio = round(div_per_share / eps * 100, 2)
        top_curr.append({
            "rank": rank,
            "name": str(row["股票名称"]),
            "yield_curr": float(row["_yield_realtime"]) if pd.notna(row.get("_yield_realtime")) else None,
            "dividend_per_share": div_per_share,
            "payout_ratio": payout_ratio,
            "yield_3y_avg": avg_yield_3y_val,
            "rank_3y": rank_3y,
            "rank_realtime": rank,
            "industry": sw_info.get("sw_level1") or row.get("来源指数") or "",
            "kofei": financial_map.get(code, {}).get("net_profit_ex_non_recurring_yoy"),
            "cagr": financial_map.get(code, {}).get("net_profit_cagr_3y"),
        })

    # --- 区块1扩展: 实时TOP10的昨收/M120比值（用于柱状图） ---
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
            "yield_curr": float(row["_yield_realtime"]) if pd.notna(row.get("_yield_realtime")) else None,
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
        if ratio is not None:
            ratio_val = ratio / 100 + 1
        else:
            ratio_val = None
        div_per_share = float(row["2025年分红(元/股)"]) if pd.notna(row.get("2025年分红(元/股)")) else None
        eps = financial_map.get(code, {}).get("eps")
        payout_ratio = None
        if div_per_share and eps and eps > 0:
            payout_ratio = round(div_per_share / eps * 100, 2)
        top_3y.append({
            "rank": rank,
            "name": str(row["股票名称"]),
            "yield_3y_avg": float(row["3年平均股息率(%)"]) if pd.notna(row.get("3年平均股息率(%)")) else None,
            "yield_curr": float(row["_yield_realtime"]) if pd.notna(row.get("_yield_realtime")) else None,
            "rank_realtime": rank_realtime_map.get(code),
            "ratio": ratio_val,
            "m120": m120_info.get("m120"),
            "payout_ratio": payout_ratio,
            "industry": sw_info.get("sw_level1") or row.get("来源指数") or "",
            "kofei": financial_map.get(code, {}).get("net_profit_ex_non_recurring_yoy"),
            "cagr": financial_map.get(code, {}).get("net_profit_cagr_3y"),
        })

    # --- 区块3: 扣非同比TOP10 ---
    fin_rows = [(code, data) for code, data in financial_map.items() if data.get("net_profit_ex_non_recurring_yoy") is not None]
    fin_rows.sort(key=lambda x: x[1]["net_profit_ex_non_recurring_yoy"], reverse=True)
    top_kofei = []
    for code, data in fin_rows[:10]:
        name_row = df[df["股票代码"].astype(str).str.zfill(6) == code]
        name = str(name_row.iloc[0]["股票名称"]) if not name_row.empty else code
        sw_info = sw_map.get(code, {})
        yield_curr_row = df_curr_sorted[df_curr_sorted["股票代码"].astype(str).str.zfill(6) == code]
        yield_curr = float(yield_curr_row.iloc[0]["_yield_realtime"]) if not yield_curr_row.empty and pd.notna(yield_curr_row.iloc[0].get("_yield_realtime")) else None
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
        yield_curr = float(yield_curr_row.iloc[0]["_yield_realtime"]) if not yield_curr_row.empty and pd.notna(yield_curr_row.iloc[0].get("_yield_realtime")) else None
        top_cagr.append({
            "name": name,
            "cagr": data["net_profit_cagr_3y"],
            "kofei": data["net_profit_ex_non_recurring_yoy"],
            "yield_curr": yield_curr,
            "industry": sw_info.get("sw_level1") or "",
        })

    total_stocks = len(df)

    # === 全量 ratio_map + yield_map + 3y_map：所有股票（用于存档）===
    ratio_map = {}
    full_yield_map = {}
    full_3y_map = {}
    for _, row in df.iterrows():
        code = str(row["股票代码"]).zfill(6)
        name = str(row["股票名称"])
        m120_info = m120_data.get(code, {})
        ratio_raw = m120_info.get("realtime_deviation")
        if ratio_raw is not None:
            ratio_map[name] = round(ratio_raw / 100 + 1, 4)
        if code in yield_realtime_map:
            full_yield_map[name] = yield_realtime_map[code]
        avg_3y = row.get("3年平均股息率(%)")
        if pd.notna(avg_3y):
            full_3y_map[name] = float(avg_3y)

    # 把 ratio 加到 top_curr / top_3y 记录里（compute_changes 依赖此字段）
    for r in top_curr:
        r["ratio"] = ratio_map.get(r["name"])
    for r in top_3y:
        r["ratio"] = ratio_map.get(r["name"])

    # === 排名对比：加载上周 snapshot，计算变动 ===
    prev_snapshot = weekly_comparison.load_previous_snapshot(today_str)
    top_curr_enr, top_3y_enr = weekly_comparison.compute_changes(top_curr, top_3y, prev_snapshot)

    # 生成报告后自动存档（同一周内只存一次，保证周对比）
    if weekly_comparison.should_save_snapshot(today_str):
        weekly_comparison.save_snapshot(
            top_curr, top_3y, today_str, ratio_map,
            full_yield_map=full_yield_map, full_3y_map=full_3y_map
        )

    return {
        "top_curr": top_curr_enr,
        "top_3y": top_3y_enr,
        "top_kofei": top_kofei,
        "top_cagr": top_cagr,
        "top_curr_bars": top_curr_bars,
        "total_stocks": total_stocks,
        "today_str": today_str,
    }


@router.get("/report/one-pager")
async def generate_one_pager_report():
    """
    生成高股息率TOP10全景报告 HTML 并直接下载（A4 一图版，左右布局）

    报告包含 4 个区块：
    1. 当前股息率TOP10（含近3年均值、排名、行业）
    2. 近3年平均股息率TOP10（柱状图，昨收/M120比值）
    3. 扣非净利润同比TOP10（含3年CAGR、当前股息率）
    4. 3年复合增长率TOP10（含扣非同比、当前股息率）
    """
    try:
        ctx = await _load_report_context()
        html_content = _render_one_pager_html(**ctx)

        from fastapi.responses import StreamingResponse
        import io

        filename = f"dividend_report_{ctx['today_str']}.html"
        return StreamingResponse(
            io.BytesIO(html_content.encode("utf-8")),
            media_type="text/html;charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成报告失败: {e}")
        raise HTTPException(status_code=500, detail=f"生成报告失败: {str(e)}")


@router.get("/report/carousel")
async def generate_carousel_report():
    """
    生成高股息率TOP10移动端竖版轮播报告 HTML 并直接下载

    4 个 slide（1080×1920），4 秒自动轮播，支持触摸/键盘/点击 dots 切换。
    每个 slide 右上角带"⬇ 下载当前图"按钮，点击后用 html2canvas 截图为 PNG。
    """
    try:
        ctx = await _load_report_context()
        html_content = _render_carousel_html(
            ctx["top_curr"], ctx["top_3y"], ctx["top_curr_bars"],
            ctx["total_stocks"], ctx["today_str"]
        )

        from fastapi.responses import StreamingResponse
        import io

        filename = f"dividend_carousel_{ctx['today_str']}.html"
        return StreamingResponse(
            io.BytesIO(html_content.encode("utf-8")),
            media_type="text/html;charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成轮播报告失败: {e}")
        raise HTTPException(status_code=500, detail=f"生成轮播报告失败: {str(e)}")


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
    # ratio_min 动态：基于实际数据自适应（min-0.05 留白，下限 0.65），
    # 避免 outlier 跌破 X 轴或被 max(5,...) clamp 成 5px 矮柱
    valid_ratios = [s["ratio"] for s in top_3y if s.get("ratio") is not None]
    ratio_min = max(0.65, min(valid_ratios) - 0.05) if valid_ratios else 0.75
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


# ─────────────────────────────────────────────────────────────────────────────
# Carousel 模板（1080×1920 移动端竖版轮播，含⬇下载原图按钮）
# ─────────────────────────────────────────────────────────────────────────────
CAROUSEL_CSS = """
@font-face{font-family:"TsangerJinKai02";src:url("../fonts/TsangerJinKai02-W04.ttf") format("truetype"),url("https://cdn.jsdelivr.net/gh/tw93/Kami@main/assets/fonts/TsangerJinKai02-W04.ttf") format("truetype");font-weight:400;font-style:normal;}
@font-face{font-family:"TsangerJinKai02";src:url("../fonts/TsangerJinKai02-W05.ttf") format("truetype"),url("https://cdn.jsdelivr.net/gh/tw93/Kami@main/assets/fonts/TsangerJinKai02-W05.ttf") format("truetype");font-weight:500;font-style:normal;}
* { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --p:#f5f4ed;--nb:#141413;--dw:#3d3d3a;--br:#1B365D;
  --bd:#e8e6dc;--bds:#e5e3d8;--tb:#E4ECF5;--ol:#504e49;--st:#6b6a64;
  --serif:"TsangerJinKai02","Source Han Seric SC","Noto Serif CJK SC","Songti SC","STSong",Georgia,serif;
}
html,body{background:#141413;width:1080px;height:1920px;overflow:hidden;}
body{color:var(--nb);font-family:var(--serif);font-size:34pt;line-height:1.4;letter-spacing:.2pt;}
.carousel{position:relative;width:1080px;height:1920px;overflow:hidden;background:var(--p);}
.slide{position:absolute;top:0;left:0;width:100%;height:100%;opacity:0;transition:opacity .6s;background:var(--p);overflow:hidden;}
.slide.active{opacity:1;}
.header{border-left:6pt solid var(--br);border-radius:4pt;padding-left:20pt;margin-bottom:24pt;display:flex;align-items:flex-end;justify-content:space-between;gap:40pt;}
.title-block{flex:1;}
.eyebrow{font-size:28pt;color:var(--br);letter-spacing:3pt;margin-bottom:6pt;}
h1{font-family:var(--serif);font-size:58pt;font-weight:500;line-height:1.15;margin-bottom:10pt;}
.subtitle{font-size:32pt;color:var(--ol);line-height:1.4;}
.meta{font-size:28pt;color:var(--st);text-align:right;line-height:1.4;}
h2{font-family:var(--serif);font-size:34pt;font-weight:500;margin-bottom:14pt;border-left:5pt solid var(--br);padding-left:14pt;}
h2 .sub{font-size:26pt;color:var(--st);font-weight:400;margin-left:10pt;}
table{width:100%;border-collapse:collapse;font-size:22pt;margin:0;break-inside:avoid;}
table th{text-align:left;font-weight:500;color:var(--dw);padding:4pt 6pt;border-bottom:2pt solid var(--bd);white-space:nowrap;}
table td{padding:14pt 6pt;border-bottom:1pt solid var(--bds);vertical-align:top;line-height:1.55;white-space:nowrap;}
table td.num{text-align:right;font-variant-numeric:tabular-nums;}
table th.num{text-align:right;}
/* 股票名/行业列：允许换行（4字以上如"建筑装饰"会折成 2 行），line-height 略小于表体 1.55，因为换行后视觉密度需要更小 */
td.name,td.ind{max-width:200px;word-wrap:break-word;overflow-wrap:anywhere;line-height:1.5;}
.tag{display:inline-block;background:var(--tb);color:var(--br);font-size:20pt;font-weight:500;padding:1pt 6pt;border-radius:6pt;letter-spacing:.3pt;}
figure{margin:8pt 0 0;break-inside:avoid;}
figcaption{font-size:26pt;color:var(--ol);margin-top:8pt;}
.footer{position:absolute;bottom:0;left:0;right:0;padding:20pt 50pt 24pt;border-top:1pt solid var(--bd);font-size:22pt;color:var(--st);line-height:1.8;letter-spacing:.3pt;background:var(--p);}
.content{padding:0 60pt 0 40pt;}
.dots{position:absolute;bottom:180pt;left:50%;transform:translateX(-50%);display:flex;gap:32pt;z-index:10;padding:12pt 28pt;background:rgba(255,255,255,.78);border-radius:32pt;backdrop-filter:blur(6pt);box-shadow:0 4pt 16pt rgba(0,0,0,.08);}
.dot{width:48pt;height:48pt;border-radius:50%;background:var(--bd);transition:background .2s,transform .2s;cursor:pointer;border:0;}
.dot:hover{background:#8a99ad;transform:scale(1.1);}
.dot.active{background:var(--br);transform:scale(1.25);box-shadow:0 0 0 4pt rgba(27,54,93,.28);}
.slide-label{position:absolute;top:130pt;right:50pt;font-size:22pt;color:var(--st);letter-spacing:1pt;z-index:10;}
.dl-btn{position:absolute;top:130pt;right:160pt;z-index:20;background:rgba(255,255,255,.92);color:var(--br);border:1.5pt solid var(--br);border-radius:6pt;padding:6pt 14pt;font-size:20pt;font-weight:500;cursor:pointer;font-family:var(--serif);letter-spacing:.3pt;}
.dl-btn:hover{background:var(--br);color:#fff;}
.dl-btn:disabled{opacity:.4;cursor:wait;}
/* === iPhone 设备边框（电脑端居中，手机端 JS 等比缩放）=== */
body{background:#1a1a1a;margin:0;padding:0;}
.device-shell{position:relative;width:1080px;height:1920px;background:#000;border-radius:60px;border:12px solid #1a1a1a;box-shadow:0 30px 80px rgba(0,0,0,.4),inset 0 0 0 2px #333;margin:40px auto;overflow:hidden;transform-origin:center center;}
/* Dynamic Island */
.dynamic-island{position:absolute;top:14px;left:50%;transform:translateX(-50%);width:240px;height:80px;background:#000;border-radius:40px;z-index:200;pointer-events:none;}
/* iOS 状态栏 */
.status-bar{position:absolute;top:0;left:0;right:0;height:88pt;display:flex;align-items:center;justify-content:space-between;padding:0 80pt 0 100pt;font-size:30pt;font-weight:600;color:#141413;z-index:150;pointer-events:none;letter-spacing:.5pt;box-sizing:border-box;}
.status-bar .sb-right{display:flex;align-items:center;gap:14pt;}
.status-bar svg{width:32pt;height:32pt;display:block;}
/* Home indicator 底部横条 */
.home-indicator{position:absolute;bottom:8px;left:50%;transform:translateX(-50%);width:504px;height:12px;background:#000;border-radius:12px;z-index:200;pointer-events:none;}
/* slide 内容区避开 status bar / home indicator */
.slide{padding-top:120pt;padding-bottom:40pt;box-sizing:border-box;}
.footer{bottom:40pt !important;}
/* iOS 字体回退（iPhone 打开更原生）*/
:root{--serif:"TsangerJinKai02","PingFang SC","Hiragino Sans GB","Source Han Serif SC","Noto Serif CJK SC",Georgia,serif;}
/* 排名变动颜色 */
.rank-up{color:#27ae60;}
.rank-down{color:#c0392b;}
.rank-same{color:#7f8c8d;}
.rank-new{color:#8e44ad;}
/* 上角标样式：用于实时排名 + 变动符号（#20↓2）或股票名后的变动（思维列控↓2） */
table td sup{font-size:14pt;font-weight:500;margin-left:3pt;vertical-align:super;line-height:0;}
"""

CAROUSEL_JS = """
(function(){
  var slides=document.querySelectorAll('.slide'),dots=document.querySelectorAll('.dot'),cur=0,tid;
  function show(i){slides.forEach(function(s,j){s.classList.toggle('active',j===i)});dots.forEach(function(d,j){d.classList.toggle('active',j===i)});cur=i;}
  function next(){show((cur+1)%6);}
  function start(){tid=setInterval(next,10000);}
  function stop(){clearInterval(tid);}
  dots.forEach(function(d){d.addEventListener('click',function(){stop();show(+d.dataset.index);start();});});
  var c=document.getElementById('carousel'),tx=0;
  c.addEventListener('touchstart',function(e){tx=e.touches[0].clientX;stop();},{passive:true});
  c.addEventListener('touchend',function(e){var dx=e.changedTouches[0].clientX-tx;if(dx<-50)show((cur+1)%6);else if(dx>50)show((cur-1+6)%6);start();},{passive:true});
  document.addEventListener('keydown',function(e){if(e.key==='ArrowRight'||e.key==='ArrowDown'){stop();show((cur+1)%6);start();}else if(e.key==='ArrowLeft'||e.key==='ArrowUp'){stop();show((cur-1+6)%6);start();}});
  start();
})();

window.downloadCurrentSlide=async function(){
  // iPhone 12/13/14 标准渲染尺寸（与 CSS device-shell 一致）
  var IPHONE_W=1080,IPHONE_H=1920;

  var btn=document.querySelector('.slide.active .dl-btn');
  var slide=document.querySelector('.slide.active');
  var shell=document.querySelector('.device-shell');
  if(!slide||!shell){alert('找不到当前 slide');return;}
  if(typeof html2canvas==='undefined'){alert('截图库未加载，请检查网络后重试');return;}
  var origText=btn.textContent;
  // 提前记录所有元素的原 display 状态——finally 兜底恢复（避免异常时 UI 残留 hidden）
  var origCss=shell.style.cssText;
  var dotsEl=document.querySelector('.dots');
  var origDotsDisplay=dotsEl?dotsEl.style.display:'';
  var origBtnDisplay=btn.style.display;
  btn.disabled=true;btn.textContent='渲染中...';
  try{
    // 1) 临时清除 device-shell 的 transform（避免 html2canvas 处理嵌套 transform 错位）
    //    注意：origCss 只含 inline 样式（fitDevice 写入的 position/transform），
    //    不含外部 .device-shell CSS 规则——但恢复后 fitDevice 会重新设置，OK
    shell.style.cssText='position:absolute;top:0;left:0;margin:0;transform:none;width:'+IPHONE_W+'px;height:'+IPHONE_H+'px;';
    // 2) 隐藏截图不需要的 UI：轮播 dots / 下载按钮（slide-label 保留，截图带上 1/6 序号）
    if(dotsEl) dotsEl.style.display='none';
    btn.style.display='none';
    // 3) 字体兜底：document.fonts.ready 解决正常情况；font.check 单独探测关键 web font
    //    （如果 CDN 慢或断网，check 会 false 触发额外 sleep 给 web font 加载时间）
    var sleep=function(ms){return new Promise(function(r){setTimeout(r,ms);});};
    await Promise.race([document.fonts.ready, sleep(5000)]);
    if(!document.fonts.check('1em TsangerJinKai02')){await sleep(800);}
    // 4) 等待浏览器完成 reflow（双 RAF 比固定 sleep 更精确，不依赖经验值）
    await new Promise(function(r){requestAnimationFrame(function(){requestAnimationFrame(r);});});
    // 5) html2canvas 截 device-shell 整块（含 iPhone 边框 + 状态栏 + Dynamic Island + home indicator）
    var canvas=await html2canvas(shell,{
      scale:1,useCORS:true,backgroundColor:'#1a1a1a',logging:false,
      width:IPHONE_W,height:IPHONE_H,windowWidth:IPHONE_W,windowHeight:IPHONE_H
    });
    // 6) 恢复 shell（必须在 html2canvas 后立即恢复，否则 fitDevice 监听 resize 时看不到正确状态）
    shell.style.cssText=origCss;
    btn.style.display=origBtnDisplay;
    // 7) 触发下载（文件名加 _iphone 后缀，区分是否含设备边框）
    var idx=Array.prototype.indexOf.call(slide.parentNode.querySelectorAll('.slide'),slide)+1;
    var dateStr=document.querySelector('.slide.active .meta').textContent.trim();
    var a=document.createElement('a');
    a.download='dividend_slide'+idx+'_'+dateStr+'_iphone.png';
    a.href=canvas.toDataURL('image/png');
    document.body.appendChild(a);a.click();document.body.removeChild(a);
  }catch(e){console.error(e);alert('截图失败: '+e.message);}
  finally{
    // 兜底恢复 dots/btn 状态（异常时也保证 UI 不残留 hidden；label/shell 在 try 块尾部已恢复）
    btn.disabled=false;btn.textContent=origText;btn.style.display=origBtnDisplay;
    if(dotsEl) dotsEl.style.display=origDotsDisplay;
  }
};

function fitDevice(){
  var vw=window.innerWidth,vh=window.innerHeight;
  var scale=Math.min(vw/1140,vh/1960);
  var shell=document.querySelector('.device-shell');
  if(shell){
    shell.style.position='fixed';
    shell.style.top='50%';
    shell.style.left='50%';
    shell.style.margin='0';
    shell.style.transform='translate(-50%,-50%) scale('+scale+')';
  }
}
window.addEventListener('resize',fitDevice);
window.addEventListener('orientationchange',fitDevice);
window.addEventListener('load',fitDevice);
fitDevice();
"""


def _pct(v): return "—" if v is None else f"{v:.2f}%"


def _wrap_name(name):
    """股票名每 2 字换行：思维→思<br>维，中国神华→中国<br>神华"""
    if not name:
        return ""
    # 每 2 个字符插入 <br>
    parts = [name[i:i+2] for i in range(0, len(name), 2)]
    return "<br>".join(parts)


def _build_carousel_row_curr(r, bars_map):
    """slide1 实时表行（7 列：# | 股票 | 实时 | 分红比例 | 行业 | 扣非同比 | 3年CAGR）"""
    payout = r.get("payout_ratio")
    payout_str = f"{payout:.2f}%" if payout is not None else "—"
    return (f'<tr><td>{r["rank"]}</td><td class="name">{r["name"]}</td>'
            f'<td class="num">{_pct(r["yield_curr"])}</td>'
            f'<td class="num">{payout_str}</td>'
            f'<td class="ind">{r["industry"]}</td>'
            f'<td class="num">{_pct(r["kofei"])}</td>'
            f'<td class="num">{_pct(r["cagr"])}</td></tr>')


def _build_carousel_row_ay(r):
    """slide4 近3年表行（6 列：# | 股票 | 近3年均值 | 分红比例 | 行业 | 扣非同比 | 3年CAGR）"""
    payout = r.get("payout_ratio")
    payout_str = f"{payout:.2f}%" if payout is not None else "—"
    return (f'<tr><td>{r["rank"]}</td><td class="name">{r["name"]}</td>'
            f'<td class="num">{_pct(r["yield_3y_avg"])}</td>'
            f'<td class="num">{payout_str}</td>'
            f'<td class="ind">{r["industry"]}</td>'
            f'<td class="num">{_pct(r["kofei"])}</td>'
            f'<td class="num">{_pct(r["cagr"])}</td></tr>')


def _build_delta_cell(delta_display):
    """排名变动单元格，颜色根据变动方向（不再显示"新进"）"""
    if delta_display is None or delta_display == "—":
        return '<td class="num"><span class="rank-same">—</span></td>'
    if delta_display.startswith("↑"):
        return f'<td class="num"><span class="rank-up">{delta_display}</span></td>'
    elif delta_display.startswith("↓"):
        return f'<td class="num"><span class="rank-down">{delta_display}</span></td>'
    else:
        return f'<td class="num"><span class="rank-same">{delta_display}</span></td>'


def _build_ratio_delta_cell(delta_display):
    """M120比值数值变动单元格，颜色根据方向（始终是数值，不显示"新进"）"""
    if delta_display is None or delta_display == "—":
        return '<td class="num"><span class="rank-same">—</span></td>'
    if delta_display.startswith("+"):
        return f'<td class="num"><span class="rank-up">{delta_display}</span></td>'
    else:
        return f'<td class="num"><span class="rank-down">{delta_display}</span></td>'


def _build_name_with_delta(name, delta_display):
    """股票名 + 变动角标：思维列控↓2（无变化时只显示名字，不显示角标）"""
    if delta_display is None or delta_display == "—":
        return f'<td class="name">{name}</td>'
    if delta_display.startswith("↑"):
        return f'<td class="name">{name}<sup class="rank-up">{delta_display}</sup></td>'
    if delta_display.startswith("↓"):
        return f'<td class="name">{name}<sup class="rank-down">{delta_display}</sup></td>'
    return f'<td class="name">{name}</td>'


def _build_carousel_row_curr_delta(r, bars_map):
    """slide2 实时股息率TOP10 · 排名变动行（7 列：# | 股票+变动角标 | 实时股息率 | 近3年均值 | 近3年排名 | M120比值 | 比值变动）"""
    ratio = bars_map.get(r["name"], {}).get("ratio")
    ratio_str = f"{ratio:.3f}" if ratio is not None else "—"
    rank_3y = r.get("rank_3y") if r.get("rank_3y") else "—"
    ratio_delta_cell = _build_ratio_delta_cell(r.get("ratio_delta_display"))
    name_cell = _build_name_with_delta(r["name"], r.get("rank_delta_ry_display"))
    return (f'<tr>'
            f'<td>{r["rank"]}</td>'
            f'{name_cell}'
            f'<td class="num">{_pct(r["yield_curr"])}</td>'
            f'<td class="num">{_pct(r["yield_3y_avg"])}</td>'
            f'<td class="num"><span class="tag">#{rank_3y}</span></td>'
            f'<td class="num">{ratio_str}</td>'
            f'{ratio_delta_cell}'
            f'</tr>')


def _build_realtime_rank_cell(rank, delta_display):
    """实时排名 + 变动符号（角标放在排名号左上角）：²#1 / ¹#3（无变化时只显示排名）"""
    rank_str = f'<span class="tag">#{rank}</span>' if rank else '<span class="tag">—</span>'
    if delta_display is None or delta_display == "—":
        return f'<td class="num">{rank_str}</td>'
    if delta_display.startswith("↑"):
        return f'<td class="num"><sup class="rank-up">{delta_display}</sup>{rank_str}</td>'
    if delta_display.startswith("↓"):
        return f'<td class="num"><sup class="rank-down">{delta_display}</sup>{rank_str}</td>'
    return f'<td class="num">{rank_str}</td>'


def _build_carousel_row_ay_delta(r):
    """slide5 近3年股息率TOP10 · 排名变动行（7 列：# | 股票 | 近3年均值 | 实时股息率 | 实时排名 | M120比值 | 比值变动）"""
    ratio = r.get("ratio")
    ratio_str = f"{ratio:.3f}" if ratio is not None else "—"
    realtime_rank_cell = _build_realtime_rank_cell(
        r.get("rank_realtime"),
        r.get("rank_delta_realtime_display")
    )
    ratio_delta_cell = _build_ratio_delta_cell(r.get("ratio_delta_display"))
    return (f'<tr>'
            f'<td>{r["rank"]}</td>'
            f'<td class="name">{r["name"]}</td>'
            f'<td class="num">{_pct(r["yield_3y_avg"])}</td>'
            f'<td class="num">{_pct(r["yield_curr"])}</td>'
            f'{realtime_rank_cell}'
            f'<td class="num">{ratio_str}</td>'
            f'{ratio_delta_cell}'
            f'</tr>')


def _build_vert_svg(stocks, yield_attr="yield_curr", fallback_yield_attr="yield_3y_avg"):
    """生成 1080×1920 竖版 SVG 柱状图（viewBox 1040×720，BAR_W=52, STEP=86, BASE_X=88）
    MN 动态：基于 stocks 实际 ratio 范围自适应（下限 0.65，最小 ratio - 0.05 留白），
    避免 outlier（如 0.715）跌破 X 轴导致柱子反向绘制
    """
    BAR_W, STEP, BASE_X = 52, 86, 88
    MX = 1.25
    valid_ratios = [s["ratio"] for s in stocks if s.get("ratio") is not None]
    MN = max(0.65, min(valid_ratios) - 0.05) if valid_ratios else 0.78
    YBASE, YSCALE = 540.0, 400.0/(MX-MN)
    def yp(r): return YBASE - (r-MN)*YSCALE

    bars=grid_svg=labels=base_svg=""
    for i, st in enumerate(stocks):
        cx = BASE_X + i*STEP
        r = st.get("ratio")
        if r is None: r = 1.0
        yt = yp(r); h = YBASE-yt
        col = "#1B365D" if r>=1.0 else "#B2B1AC"
        bars += f'<rect x="{cx-BAR_W//2}" y="{yt}" width="{BAR_W}" height="{h}" fill="{col}" rx="4"/>\n'
        bars += f'<text x="{cx}" y="{yt-8}" fill="#141413" font-size="22" text-anchor="middle" font-weight="500">{r:.3f}</text>\n'
        nm = st["name"]
        yv = st.get(yield_attr)
        if yv is None:
            yv = st.get(fallback_yield_attr) or 0
        dv = f"{yv:.2f}%"
        labels += f'<text x="{cx}" y="608" fill="#504e49" font-size="22" text-anchor="middle" transform="rotate(-45 {cx} 608)">{nm}</text>\n'
        labels += f'<text x="{cx}" y="640" fill="#504e49" font-size="18" text-anchor="middle" transform="rotate(-45 {cx} 640)">{dv}</text>\n'

    for r_ in [0.80,0.90,0.95,1.00,1.05,1.10,1.15,1.20,1.25]:
        y = yp(r_)
        grid_svg += f'<line x1="60" y1="{y}" x2="970" y2="{y}" stroke="#e8e7e1" stroke-width="1"/>\n'
        grid_svg += f'<text x="50" y="{y+8}" fill="#6b6a64" font-size="20" text-anchor="end">{r_:.2f}</text>\n'
    by = yp(1.00)
    base_svg = f'<line x1="60" y1="{by}" x2="970" y2="{by}" stroke="#1B365D" stroke-width="2" stroke-dasharray="8 6"/>\n'
    base_svg += f'<text x="965" y="{by+10}" fill="#1B365D" font-size="20" text-anchor="end">M120=1</text>\n'

    return (f'<svg viewBox="0 0 1040 720" xmlns="http://www.w3.org/2000/svg" style="width:100%;display:block;">\n'
            f'<rect width="100%" height="100%" fill="#f5f4ed"/>\n'
            f'<line x1="60" y1="{YBASE}" x2="970" y2="{YBASE}" stroke="#141413" stroke-width="1.5"/>\n'
            f'{grid_svg}{base_svg}{bars}{labels}\n'
            f'<text x="20" y="350" fill="#6b6a64" font-size="20" text-anchor="middle" transform="rotate(-90 20 350)" letter-spacing="2">实时价/M120</text>\n</svg>')


def _render_carousel_html(top_curr, top_3y, top_curr_bars, total_stocks, today_str):
    """渲染 1080×1920 移动端竖版轮播 HTML（6 slide），每 slide 含⬇下载原图按钮"""
    bars_map = {b["name"]: b for b in top_curr_bars}
    rows1 = "".join(_build_carousel_row_curr(r, bars_map) for r in top_curr)
    rows3 = "".join(_build_carousel_row_ay(r) for r in top_3y)
    # slide 5 & 6 排名变动
    rows5 = "".join(_build_carousel_row_curr_delta(r, bars_map) for r in top_curr)
    rows6 = "".join(_build_carousel_row_ay_delta(r) for r in top_3y)
    # slide 2 柱状图用 top_curr_bars（含 ratio + yield_curr），不用 top_curr（缺 ratio）
    svg1 = _build_vert_svg(top_curr_bars, yield_attr="yield_curr")
    # slide 4 柱状图用 top_3y（含 ratio + yield_3y_avg）
    svg2 = _build_vert_svg(top_3y, yield_attr="yield_3y_avg", fallback_yield_attr="yield_curr")

    footer_left = f"数据来源：高息研究室 · {total_stocks}只高股息A股样本"
    footer_right = f"{today_str} · 仅供投资参考，不构成投资建议"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=1080,height=1920">
<title>A股高股息率TOP10轮播</title>
<style>{CAROUSEL_CSS}</style>
</head>
<body>
<div class="device-shell">
  <div class="status-bar">
    <span>9:41</span>
    <span class="sb-right">
      <svg viewBox="0 0 20 12" fill="currentColor"><rect x="0" y="8" width="3" height="4" rx="0.5"/><rect x="5" y="6" width="3" height="6" rx="0.5"/><rect x="10" y="3" width="3" height="9" rx="0.5"/><rect x="15" y="0" width="3" height="12" rx="0.5"/></svg>
      <svg viewBox="0 0 16 12" fill="currentColor"><path d="M8 11l1.5-1.5a2.12 2.12 0 00-3 0L8 11z"/><path d="M2 6.5l1.5 1.5a4.24 4.24 0 016 0L11 6.5a6.36 6.36 0 00-9 0z" opacity="0.7"/><path d="M0 4.5l1.5 1.5a6.36 6.36 0 019 0L12 4.5a8.49 8.49 0 00-12 0z" opacity="0.4"/></svg>
      <svg viewBox="0 0 28 14" fill="none"><rect x="0.5" y="0.5" width="24" height="13" rx="3" stroke="currentColor" stroke-width="1" opacity="0.4"/><rect x="2" y="2" width="20" height="10" rx="1.5" fill="currentColor"/><rect x="25" y="5" width="2" height="4" rx="0.5" fill="currentColor" opacity="0.4"/></svg>
    </span>
  </div>
  <div class="dynamic-island"></div>
<div class="carousel" id="carousel">

  <div class="slide active" id="slide1">
    <div class="slide-label">1 / 6</div>
    <button class="dl-btn" onclick="downloadCurrentSlide()">⬇ 下载当前图</button>
    <div class="content">
      <div class="header">
        <div class="title-block">
          <div class="eyebrow">A股 · 股息率分析</div>
          <h1>实时股息率TOP10</h1>
        </div>
        <div class="meta">{today_str}</div>
      </div>
      <h2><span class="sub">分红比例 &amp; 行业 &amp; 扣非同比 &amp; 3年CAGR</span></h2>
      <table>
        <thead><tr><th>#</th><th>股票</th><th class="num">实时股息率</th><th class="num">分红比例</th><th>行业</th><th class="num">扣非同比</th><th class="num">3年CAGR</th></tr></thead>
        <tbody>{rows1}</tbody>
      </table>
    </div>
    <div class="footer">
      {footer_left}<br>
      {footer_right}
    </div>
  </div>

  <div class="slide" id="slide2">
    <div class="slide-label">2 / 6</div>
    <button class="dl-btn" onclick="downloadCurrentSlide()">⬇ 下载当前图</button>
    <div class="content">
      <div class="header">
        <div class="title-block">
          <div class="eyebrow">A股 · 股息率分析</div>
          <h1>实时股息率TOP10</h1>
        </div>
        <div class="meta">{today_str}</div>
      </div>
      <h2><span class="sub">本周变动 &amp; 近3年均值/排名</span></h2>
      <table>
        <thead><tr><th>#</th><th>股票</th><th class="num">实时股息率</th><th class="num">近3年均值</th><th class="num">近3年排名</th><th class="num">M120比值</th><th class="num">比值变动</th></tr></thead>
        <tbody>{rows5}</tbody>
      </table>
    </div>
    <div class="footer">
      {footer_left}<br>
      {footer_right}
    </div>
  </div>

  <div class="slide" id="slide3">
    <div class="slide-label">3 / 6</div>
    <button class="dl-btn" onclick="downloadCurrentSlide()">⬇ 下载当前图</button>
    <div class="content">
      <div class="header">
        <div class="title-block">
          <div class="eyebrow">A股 · 股息率分析</div>
          <h1>实时股息率TOP10</h1>
        </div>
        <div class="meta">{today_str}</div>
      </div>
      <h2>实时价/M120比值<span class="sub">蓝色≥1.00，灰色&lt;1.00</span></h2>
      <figure>{svg1}</figure>
      <figcaption>蓝色表示价格站上M120均线，蓝色虚线为M120基准线</figcaption>
    </div>
    <div class="footer">
      {footer_left}<br>
      {footer_right}
    </div>
  </div>

  <div class="slide" id="slide4">
    <div class="slide-label">4 / 6</div>
    <button class="dl-btn" onclick="downloadCurrentSlide()">⬇ 下载当前图</button>
    <div class="content">
      <div class="header">
        <div class="title-block">
          <div class="eyebrow">A股 · 股息率分析</div>
          <h1>近3年均值TOP10</h1>
        </div>
        <div class="meta">{today_str}</div>
      </div>
      <h2><span class="sub">分红比例 &amp; 行业 &amp; 扣非同比 &amp; 3年CAGR</span></h2>
      <table>
        <thead><tr><th>#</th><th>股票</th><th class="num">近3年均值</th><th class="num">分红</th><th>行业</th><th class="num">扣非同比</th><th class="num">3年CAGR</th></tr></thead>
        <tbody>{rows3}</tbody>
      </table>
    </div>
    <div class="footer">
      {footer_left}<br>
      {footer_right}
    </div>
  </div>

  <div class="slide" id="slide5">
    <div class="slide-label">5 / 6</div>
    <button class="dl-btn" onclick="downloadCurrentSlide()">⬇ 下载当前图</button>
    <div class="content">
      <div class="header">
        <div class="title-block">
          <div class="eyebrow">A股 · 股息率分析</div>
          <h1>近3年均值TOP10</h1>
        </div>
        <div class="meta">{today_str}</div>
      </div>
      <h2><span class="sub">本周变动</span></h2>
      <table>
        <thead><tr><th>#</th><th>股票</th><th class="num">近3年均值</th><th class="num">实时股息率</th><th class="num">实时排名</th><th class="num">M120比值</th><th class="num">比值变动</th></tr></thead>
        <tbody>{rows6}</tbody>
      </table>
    </div>
    <div class="footer">
      {footer_left}<br>
      {footer_right}
    </div>
  </div>

  <div class="slide" id="slide6">
    <div class="slide-label">6 / 6</div>
    <button class="dl-btn" onclick="downloadCurrentSlide()">⬇ 下载当前图</button>
    <div class="content">
      <div class="header">
        <div class="title-block">
          <div class="eyebrow">A股 · 股息率分析</div>
          <h1>近3年均值TOP10</h1>
        </div>
        <div class="meta">{today_str}</div>
      </div>
      <h2>实时价/M120比值<span class="sub">蓝色≥1.00，灰色&lt;1.00</span></h2>
      <figure>{svg2}</figure>
      <figcaption>蓝色表示价格站上M120均线，蓝色虚线为M120基准线</figcaption>
    </div>
    <div class="footer">
      {footer_left}<br>
      {footer_right}
    </div>
  </div>

  <div class="dots">
    <div class="dot active" data-index="0"></div>
    <div class="dot" data-index="1"></div>
    <div class="dot" data-index="2"></div>
    <div class="dot" data-index="3"></div>
    <div class="dot" data-index="4"></div>
    <div class="dot" data-index="5"></div>
  </div>
</div>
  <div class="home-indicator"></div>
</div>
<script src="https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js"></script>
<script>{CAROUSEL_JS}</script>
</body>
</html>"""
