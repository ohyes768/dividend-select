"""
辅助数据刷新公共工具
"""
import glob
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from ...utils.helpers import DATA_DIR

REFRESH_INTERVAL_DAYS = 90


def file_mtime_iso(path: Path) -> Optional[str]:
    """返回文件最后修改时间的 ISO 格式字符串"""
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat()


def days_since_update(path: Path) -> Optional[int]:
    """返回距上次文件修改的天数"""
    if not path.exists():
        return None
    return (datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)).days


def current_quarter() -> str:
    """返回当前季度字符串，格式:2026Q1"""
    now = datetime.now()
    quarter = (now.month - 1) // 3 + 1
    return f"{now.year}Q{quarter}"


def find_latest_aux_file(prefix: str) -> Optional[Path]:
    """
    在 DATA_DIR 下 glob 找 prefix_*.csv 中 mtime 最新的一份。

    同前缀多份季度后缀文件并存时，取最近修改的那一份作为"活跃文件"。
    文件不存在时返回 None。

    Args:
        prefix: 文件前缀，如"股东户数汇总"会匹配 "股东户数汇总_*.csv"
    """
    pattern = str(DATA_DIR / f"{prefix}_*.csv")
    matches = glob.glob(pattern)
    if not matches:
        return None
    return Path(max(matches, key=os.path.getmtime))


def aux_file_path(prefix: str, quarter: Optional[str] = None) -> Path:
    """
    生成当前季度对应的活跃文件路径（写盘时用）。

    同季度多次刷新 → 写入同一文件（覆盖）。
    跨季度首次刷新 → 创建新文件，旧文件保留为历史。

    Args:
        prefix: 文件前缀
        quarter: 季度字符串（如"2026Q1"），None 时取当前季度

    Returns:
        DATA_DIR/prefix_YYYYQn.csv 形式的 Path
    """
    q = quarter or current_quarter()
    return DATA_DIR / f"{prefix}_{q}.csv"