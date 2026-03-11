"""
工具函数
"""
import logging
from pathlib import Path
from typing import Optional

import pandas as pd

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"


def is_main_board(code) -> bool:
    """
    判断是否为沪深主板股票

    沪市主板: 600xxx, 601xxx, 603xxx, 605xxx
    深市主板: 000xxx, 001xxx, 002xxx, 003xxx

    排除:
    - 科创板: 688xxx
    - 创业板: 300xxx, 301xxx
    - 北交所: 8xxxxx, 4xxxxx
    """
    # 转换为字符串并补齐6位
    code = str(code).zfill(6)

    if not code or len(code) < 3:
        return False

    prefix = code[:3]

    # 沪市主板
    if prefix in ["600", "601", "603", "605"]:
        return True

    # 深市主板
    if prefix in ["000", "001", "002", "003"]:
        return True

    return False


def get_exchange(code) -> str:
    """根据股票代码判断交易所"""
    # 转换为字符串并补齐6位
    code = str(code).zfill(6)

    if not code:
        return ""

    prefix = code[:3]
    if prefix in ["600", "601", "603", "605", "688"]:
        return "沪市主板" if prefix != "688" else "科创板"
    elif prefix in ["000", "001", "002", "003", "300", "301"]:
        return "深市主板" if prefix not in ["300", "301"] else "创业板"
    else:
        return "其他"


def load_csv_data(filename: str) -> Optional[pd.DataFrame]:
    """加载CSV数据文件"""
    filepath = DATA_DIR / filename
    if not filepath.exists():
        return None
    try:
        return pd.read_csv(filepath, encoding="utf-8-sig")
    except Exception:
        return None


def save_csv_data(df: pd.DataFrame, filename: str) -> bool:
    """保存数据到CSV文件"""
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        filepath = DATA_DIR / filename
        df.to_csv(filepath, index=False, encoding="utf-8-sig")
        return True
    except Exception:
        return False


def append_csv_row(row_data: dict, filename: str) -> bool:
    """追加单行数据到CSV文件"""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        filepath = DATA_DIR / filename

        # 文件存在则追加，不存在则创建
        if filepath.exists():
            df_existing = pd.read_csv(filepath, encoding="utf-8-sig")
            df_new = pd.DataFrame([row_data])
            df_combined = pd.concat([df_existing, df_new], ignore_index=True)
        else:
            df_combined = pd.DataFrame([row_data])

        df_combined.to_csv(filepath, index=False, encoding="utf-8-sig")
        return True
    except Exception:
        return False


def load_existing_codes(filename: str) -> set[str]:
    """读取CSV中已存在的股票代码"""
    filepath = DATA_DIR / filename
    if not filepath.exists():
        return set()

    try:
        df = pd.read_csv(filepath, encoding="utf-8-sig")
        if "股票代码" not in df.columns:
            return set()
        # 统一转为6位字符串
        codes = set(str(c).zfill(6) for c in df["股票代码"].dropna())
        return codes
    except Exception:
        return set()


def setup_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """设置日志器"""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        # 文件处理器
        fh = logging.FileHandler(
            LOGS_DIR / "dividend.log",
            encoding="utf-8"
        )
        fh.setLevel(level)

        # 控制台处理器
        ch = logging.StreamHandler()
        ch.setLevel(level)

        # 格式化
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)

        logger.addHandler(fh)
        logger.addHandler(ch)

    return logger
