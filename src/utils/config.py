"""
配置加载工具
"""
import yaml
from pathlib import Path
from typing import Any

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"

# 配置缓存
_config_cache: dict | None = None
_config_file: Path | None = None


def load_config(config_path: str = "config/app.yaml") -> dict:
    """
    加载配置文件

    Args:
        config_path: 配置文件路径（相对于项目根目录）

    Returns:
        配置字典
    """
    global _config_cache, _config_file

    full_path = PROJECT_ROOT / config_path

    if _config_file == full_path and _config_cache is not None:
        return _config_cache

    if not full_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {full_path}")

    with open(full_path, "r", encoding="utf-8") as f:
        _config_cache = yaml.safe_load(f)
        _config_file = full_path

    return _config_cache


def get_config() -> dict:
    """
    获取配置

    Returns:
        配置字典
    """
    if _config_cache is None:
        load_config()
    return _config_cache


class AppConfig:
    """
    应用配置访问器
    提供类型安全的配置访问方法
    """

    @staticmethod
    def get_server_host() -> str:
        """获取服务器主机地址"""
        return get_config()["app"]["server"]["host"]

    @staticmethod
    def get_server_port() -> int:
        """获取服务器端口"""
        return get_config()["app"]["server"]["port"]

    @staticmethod
    def get_csv_file() -> Path:
        """获取 CSV 文件路径"""
        filename = get_config()["app"]["data"]["csv_file"]
        use_date_dir = get_config()["app"]["data"].get("date_dir", False)

        if use_date_dir:
            # 使用月度目录和日期后缀
            from src.utils.helpers import DATA_DIR, get_current_date_dir, get_date_path
            return get_date_path(filename, get_current_date_dir())
        else:
            # 原有逻辑：直接使用配置的路径
            return PROJECT_ROOT / filename

    @staticmethod
    def get_encoding() -> str:
        """获取 CSV 文件编码"""
        return get_config()["app"]["data"]["encoding"]

    @staticmethod
    def get_log_level() -> str:
        """获取日志级别"""
        return get_config()["app"]["logging"]["level"]

    @staticmethod
    def get_log_console() -> bool:
        """是否输出到控制台"""
        return get_config()["app"]["logging"]["console"]

    @staticmethod
    def get_log_file() -> bool:
        """是否输出到文件"""
        return get_config()["app"]["logging"]["file"]

    @staticmethod
    def get_log_dir() -> Path:
        """获取日志目录"""
        dirname = get_config()["app"]["logging"]["dir"]
        return PROJECT_ROOT / dirname

    @staticmethod
    def get_default_page_size() -> int:
        """获取默认分页大小"""
        return get_config()["app"]["pagination"]["default_page_size"]

    @staticmethod
    def get_max_page_size() -> int:
        """获取最大分页大小"""
        return get_config()["app"]["pagination"]["max_page_size"]

    @staticmethod
    def get_all() -> dict:
        """获取完整配置"""
        return get_config()