"""
FastAPI 应用入口
dividend-select 后端服务
"""
from contextlib import asynccontextmanager
import sys
from pathlib import Path

# 加载 .env / .env.local（在所有 import 之前，确保 os.getenv 读到值）
try:
    from dotenv import load_dotenv
    PROJECT_ROOT = Path(__file__).parent.parent
    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv(PROJECT_ROOT / ".env.local", override=True)  # .env.local 优先级最高
except ImportError:
    pass  # 没装 python-dotenv 也不报错，走 os.getenv 默认值

# 添加项目根目录到 Python 路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import router, set_services
from src.scheduler.manager import SchedulerManager
from src.scheduler.routes import router as scheduler_router
from src.services.alert_service import init_alert_service
from src.services.data_reader import DataReader
from src.services.favorites_service import FavoritesService
from src.services.filter_service import FilterService
from src.services.m120_service import M120Service
from src.services.pe_service import PEDataService
from src.services.sort_service import SortService
from src.services.shareholder_financial_reader import ShareholderReader, FinancialReader
from src.utils.config import AppConfig
from src.utils.logger import setup_logger

# 配置日志
logger = setup_logger("dividend-select")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理

    Args:
        app: FastAPI 应用实例

    Yields:
        None
    """
    # 启动事件
    logger.info("=" * 50)
    logger.info("dividend-select 服务启动中...")
    logger.info(f"版本: 1.0.0")
    logger.info(f"服务器地址: {AppConfig.get_server_host()}:{AppConfig.get_server_port()}")
    logger.info(f"数据文件: {AppConfig.get_csv_file()}")
    logger.info("=" * 50)

    # 初始化服务
    data_reader = DataReader()
    filter_service = FilterService()
    sort_service = SortService()
    m120_service = M120Service()
    pe_service = PEDataService()
    shareholder_reader = ShareholderReader()
    financial_reader = FinancialReader()
    favorites_service = FavoritesService.get_instance()

    # 设置服务到路由
    set_services(data_reader, filter_service, sort_service, m120_service, pe_service,
                 shareholder_reader, financial_reader, favorites_service)

    # 初始化挡位监控服务（依赖 favorites + m120 + pe + data_reader）
    init_alert_service(
        favorites_service=favorites_service,
        m120_service=m120_service,
        pe_service=pe_service,
        data_reader=data_reader,
    )
    logger.info("挡位监控服务（AlertService）已初始化")

    # 检查数据文件
    if data_reader.check_csv_exists():
        total = data_reader.get_total_count()
        logger.info(f"数据文件加载成功，共 {total} 条记录")
    else:
        logger.warning(f"数据文件不存在: {AppConfig.get_csv_file()}")

    # 检查 M120 数据文件
    if m120_service.check_m120_file_exists():
        m120_count = len(m120_service.read_m120_data())
        logger.info(f"M120 数据文件加载成功，共 {m120_count} 条记录")
    else:
        logger.info("M120 数据文件不存在，请调用 POST /api/m120/refresh 接口刷新数据")

    # 检查实时价格数据文件
    if m120_service.check_realtime_price_file_exists():
        logger.info("实时价格数据文件已存在")
    else:
        logger.info("实时价格数据文件不存在，请调用 POST /api/realtime/refresh 接口刷新数据")

    # 检查股东户数数据文件
    if shareholder_reader.check_exists():
        sh_count = len(shareholder_reader.read_csv())
        logger.info(f"股东户数数据文件已存在，共 {sh_count} 条记录")
    else:
        logger.info("股东户数数据文件不存在，请运行 shareholder_fetcher.py 获取数据")

    # 检查财务指标数据文件
    if financial_reader.check_exists():
        fi_count = len(financial_reader.read_csv())
        logger.info(f"财务指标数据文件已存在，共 {fi_count} 条记录")
    else:
        logger.info("财务指标数据文件不存在，请运行 financial_fetcher.py 获取数据")

    # 收藏服务
    fav_count = len(favorites_service.get_all()["codes"])
    logger.info(f"收藏服务就绪，当前 {fav_count} 只收藏")

    # 初始化 scheduler（依赖 data_reader，单 worker 模式）
    scheduler = SchedulerManager(
        port=AppConfig.get_server_port(),
        config_path=PROJECT_ROOT / "config" / "scheduler.json",
        history_path=PROJECT_ROOT / "data" / "scheduler_runs.jsonl",
    )
    scheduler.start(services={"data_reader": data_reader})
    app.state.scheduler = scheduler
    logger.info("Scheduler 已启动")

    yield

    # 关闭事件
    logger.info("dividend-select 服务关闭中...")
    await scheduler.shutdown(wait=True, timeout=30)


# 创建 FastAPI 应用
app = FastAPI(
    title="Dividend Select API",
    description="A股高股息率TOP50查询工具 API",
    version="1.0.0",
    lifespan=lifespan
)

# 配置 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应限制来源
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由（添加 /api 前缀）
app.include_router(router, prefix='/api/dividend')
# scheduler 管理 API（最终路径 /api/dividend/scheduler/*）
app.include_router(scheduler_router, prefix='/api/dividend')


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=AppConfig.get_server_host(),
        port=AppConfig.get_server_port(),
        reload=False,
        log_level=AppConfig.get_log_level().lower()
    )