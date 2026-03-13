"""
FastAPI 应用入口
dividend-select 后端服务
"""
from contextlib import asynccontextmanager
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import router, set_services
from src.services.data_reader import DataReader
from src.services.filter_service import FilterService
from src.services.m120_service import M120Service
from src.services.pe_service import PEDataService
from src.services.sort_service import SortService
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

    # 设置服务到路由
    set_services(data_reader, filter_service, sort_service, m120_service, pe_service)

    # 检查数据文件
    if data_reader.check_csv_exists():
        total = data_reader.get_total_count()
        logger.info(f"数据文件加载成功，共 {total} 条记录")
    else:
        logger.warning(f"数据文件不存在: {AppConfig.get_csv_file()}")

    # 检查 M120 数据文件
    if m120_service.check_file_exists():
        m120_count = len(m120_service.read_m120_data())
        logger.info(f"M120 数据文件加载成功，共 {m120_count} 条记录")
    else:
        logger.info("M120 数据文件不存在，请调用 POST /api/m120/refresh 接口刷新数据")

    yield

    # 关闭事件
    logger.info("dividend-select 服务关闭")


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
app.include_router(router, prefix='/api')


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=AppConfig.get_server_host(),
        port=AppConfig.get_server_port(),
        reload=False,
        log_level=AppConfig.get_log_level().lower()
    )