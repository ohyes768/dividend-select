"""
工具函数
"""
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from shutil import move

import pandas as pd

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"


def get_current_date_dir() -> str:
    """
    获取当前日期目录名（YYYY-MM格式）

    Returns:
        格式如 "2025-01" 的日期字符串
    """
    return datetime.now().strftime("%Y-%m")


def get_filename_with_date_suffix(filename: str, date_str: str | None = None) -> str:
    """
    为文件名添加日期后缀

    Args:
        filename: 原文件名（如：红利指数持仓汇总.csv）
        date_str: 日期字符串（YYYY-MM格式），默认使用当前日期

    Returns:
        带日期后缀的文件名（如：红利指数持仓汇总_2025-01.csv）
    """
    if date_str is None:
        date_str = get_current_date_dir()

    name, ext = filename.rsplit('.', 1)
    return f"{name}_{date_str}.{ext}"


def get_date_path(filename: str, date_str: Optional[str] = None) -> Path:
    """
    获取日期目录下的文件路径

    Args:
        filename: 文件名（会自动添加日期后缀）
        date_str: 日期字符串（YYYY-MM格式），默认使用当前日期

    Returns:
        完整的文件路径
    """
    if date_str is None:
        date_str = get_current_date_dir()
    filename_with_suffix = get_filename_with_date_suffix(filename, date_str)
    return DATA_DIR / date_str / filename_with_suffix


def save_csv_to_date_dir(df: pd.DataFrame, filename: str, date_str: Optional[str] = None) -> bool:
    """
    保存CSV文件到日期目录

    Args:
        df: DataFrame数据
        filename: 文件名
        date_str: 日期字符串（YYYY-MM格式），默认使用当前日期

    Returns:
        是否保存成功
    """
    try:
        if date_str is None:
            date_str = get_current_date_dir()
        filepath = DATA_DIR / date_str / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(filepath, index=False, encoding="utf-8-sig")
        return True
    except Exception:
        return False


def move_file_to_date_dir(filename: str, date_str: Optional[str] = None) -> bool:
    """
    将当前目录下的文件移动到日期目录

    Args:
        filename: 文件名
        date_str: 日期字符串（YYYY-MM格式），默认使用当前日期

    Returns:
        是否移动成功
    """
    try:
        if date_str is None:
            date_str = get_current_date_dir()
        src = DATA_DIR / filename
        dst = DATA_DIR / date_str / filename

        if not src.exists():
            return False

        dst.parent.mkdir(parents=True, exist_ok=True)
        move(src, dst)
        return True
    except Exception:
        return False


def move_all_data_files(date_str: Optional[str] = None) -> bool:
    """
    将当前目录下的所有数据文件移动到日期目录

    移动文件列表：
    - 红利指数持仓汇总.csv
    - 股票分红次数汇总.csv
    - 个股板块映射.csv
    - M120数据.csv
    - PE数据.csv
    - 近3年股息率汇总.csv

    Args:
        date_str: 日期字符串（YYYY-MM格式），默认使用当前日期

    Returns:
        是否全部移动成功
    """
    files_to_move = [
        "红利指数持仓汇总.csv",
        "股票分红次数汇总.csv",
        "个股板块映射.csv",
        "M120数据.csv",
        "PE数据.csv",
        "近3年股息率汇总.csv",
    ]

    success = True
    for filename in files_to_move:
        if not move_file_to_date_dir(filename, date_str):
            success = False
            logger = logging.getLogger(__name__)
            logger.warning(f"移动文件失败: {filename}")

    return success


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


def load_csv_data(filename: str, date_str: Optional[str] = None) -> Optional[pd.DataFrame]:
    """
    加载CSV数据文件
    自动添加日期后缀，优先从当前目录读取，不存在则从月度目录读取

    Args:
        filename: 文件名（如：红利指数持仓汇总.csv）
        date_str: 日期字符串（YYYY-MM格式），None则使用当前月份

    Returns:
        DataFrame数据，失败返回None
    """
    # 添加日期后缀
    filename_with_suffix = get_filename_with_date_suffix(filename, date_str)

    # 先尝试从当前目录读取
    filepath = DATA_DIR / filename_with_suffix
    if filepath.exists():
        try:
            return pd.read_csv(filepath, encoding="utf-8-sig")
        except Exception:
            pass

    # 不存在则从月度目录读取
    if date_str is None:
        date_str = get_current_date_dir()
    filepath = DATA_DIR / date_str / filename_with_suffix
    if filepath.exists():
        try:
            return pd.read_csv(filepath, encoding="utf-8-sig")
        except Exception:
            pass

    return None


def save_csv_data(df: pd.DataFrame, filename: str, date_str: Optional[str] = None, add_date_column: bool = False) -> bool:
    """
    保存数据到CSV文件
    自动添加日期后缀，如果指定date_str，则保存到月度目录，否则保存到当前目录

    Args:
        df: DataFrame数据
        filename: 文件名
        date_str: 日期字符串（YYYY-MM格式），None则保存到当前目录
        add_date_column: 是否添加日期列（用于M120和PE数据）

    Returns:
        是否保存成功
    """
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)

        # 添加日期后缀
        filename_with_suffix = get_filename_with_date_suffix(filename, date_str)

        # 如果需要添加日期列
        if add_date_column:
            df = df.copy()
            df["日期"] = date_str if date_str else get_current_date_dir()

        if date_str:
            filepath = DATA_DIR / date_str / filename_with_suffix
        else:
            filepath = DATA_DIR / filename_with_suffix

        filepath.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(filepath, index=False, encoding="utf-8-sig")
        return True
    except Exception:
        return False


def append_csv_row(row_data: dict, filename: str, date_str: Optional[str] = None) -> bool:
    """
    追加单行数据到CSV文件
    自动添加日期后缀，如果指定date_str，则追加到月度目录，否则追加到当前目录

    Args:
        row_data: 行数据字典
        filename: 文件名
        date_str: 日期字符串（YYYY-MM格式），None则追加到当前目录

    Returns:
        是否追加成功
    """
    try:
        # 添加日期后缀
        filename_with_suffix = get_filename_with_date_suffix(filename, date_str)

        if date_str:
            filepath = DATA_DIR / date_str / filename_with_suffix
        else:
            filepath = DATA_DIR / filename_with_suffix
        filepath.parent.mkdir(parents=True, exist_ok=True)

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


def load_existing_codes(filename: str, date_str: Optional[str] = None) -> set[str]:
    """
    读取CSV中已存在的股票代码
    自动添加日期后缀，优先从当前目录读取，不存在则从月度目录读取

    Args:
        filename: 文件名
        date_str: 日期字符串（YYYY-MM格式），None则使用当前月份

    Returns:
        股票代码集合
    """
    # 添加日期后缀
    filename_with_suffix = get_filename_with_date_suffix(filename, date_str)

    # 先尝试从当前目录读取
    filepath = DATA_DIR / filename_with_suffix
    if not filepath.exists():
        if date_str is None:
            date_str = get_current_date_dir()
        filepath = DATA_DIR / date_str / filename_with_suffix

    if not filepath.exists():
        return set()

    try:
        df = pd.read_csv(filepath, encoding="utf-8-sig")
    except Exception:
        return set()

    if "股票代码" not in df.columns:
        return set()

    # 统一转为6位字符串
    codes = set(str(c).zfill(6) for c in df["股票代码"].dropna())
    return codes


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
