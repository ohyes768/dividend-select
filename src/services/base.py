"""
服务基类。

CsvPathService: 动态计算 CSV 路径，避免"启动时快照"导致服务跨周/跨月后路径不更新。

背景
----
旧实现里 M120Service / PEDataService 都在 __init__ 里把 CSV 路径赋值成
`self.M120_CSV_FILE = ...`，worker 单例跨过周日后再读/写，永远指向启动
瞬间算出的那个文件名。

修复
----
把路径改成 @property，每次访问都按 `datetime.now()` 重算。
"""
from datetime import datetime, timedelta
from pathlib import Path

from src.utils.helpers import DATA_DIR, get_current_date_dir


def current_week_suffix() -> str:
    """
    当前时刻所在周的 周一到周日 后缀（mm-dd-mm-dd）。

    一周从周一开始，周日结束。
    """
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return f"{monday.strftime('%m-%d')}-{sunday.strftime('%m-%d')}"


class CsvPathService:
    """
    基类：CSV 路径用 @property 动态计算 `datetime.now()`，
    避免任何"启动时快照"导致跨周/跨月后路径不更新。

    子类覆盖 _csv_path() 返回当前时刻对应的完整路径。
    子类可重写 _week_suffix() 决定是否走周度后缀（默认 False → 走月度）。
    """

    # 子类重写：周度文件名模板（含 {} 占位符）；月度文件名直接给完整文件名
    # M120 子类：`"M120均线_{}.csv"`
    # PE 子类：`None`（月度场景直接给完整文件名）
    week_filename_template: str | None = None
    # 月度文件名（无周度后缀时使用）
    month_filename: str | None = None
    # 子目录名（默认空 = data/{date_str} 下；子类可改成 e.g. "fhps"）
    subdir: str = ""

    def __init__(self, date_str: str | None = None):
        """
        Args:
            date_str: 日期字符串（YYYY-MM格式），None 时取当前月。
                     仅用于测试或历史回放场景；生产应传 None 走实时。
        """
        self.date_str = date_str

    def _resolve_date_str(self) -> str:
        return self.date_str if self.date_str else get_current_date_dir()

    def _csv_path(self) -> Path:
        date_str = self._resolve_date_str()
        if self.week_filename_template:
            filename = self.week_filename_template.format(current_week_suffix())
        elif self.month_filename:
            filename = self.month_filename
        else:
            raise NotImplementedError("子类必须设置 week_filename_template 或 month_filename")
        path = DATA_DIR / date_str / self.subdir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def csv_path(self) -> Path:
        """当前时刻对应的 CSV 完整路径（动态计算）。"""
        return self._csv_path()
