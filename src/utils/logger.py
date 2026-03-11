"""
日志配置工具
"""
import logging
from pathlib import Path

from src.utils.config import AppConfig


def setup_logger(name: str, level: str | int = None) -> logging.Logger:
    """
    设置日志器

    Args:
        name: 日志器名称
        level: 日志级别（可选，默认从配置读取）

    Returns:
        配置好的日志器
    """
    # 从配置获取日志级别
    if level is None:
        level_str = AppConfig.get_log_level()
        level = getattr(logging, level_str.upper(), logging.INFO)

    # 获取日志目录
    log_dir = AppConfig.get_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)

    # 创建日志器
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # 避免重复添加处理器
    if logger.handlers:
        return logger

    # 格式化器
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 控制台处理器
    if AppConfig.get_log_console():
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # 文件处理器
    if AppConfig.get_log_file():
        file_handler = logging.FileHandler(
            log_dir / "server.log",
            encoding="utf-8"
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger