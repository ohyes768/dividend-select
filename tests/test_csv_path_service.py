"""
CsvPathService 单元测试 + M120 / PE 跨周/跨月路径动态化回归测试。

背景
----
2026-06-22 线上 bug：dividend-backend 容器从 6-14 周日附近启动后再没重启过，
单例 `M120Service.M120_CSV_FILE` 在 __init__ 里锁定启动瞬间的 week_suffix，
跨周日（06-14 → 06-22）后路径不更新，所有读/写仍指向
`data/2026-06/M120均线_06-08-06-14.csv`，导致：
- `M120均线_06-22-06-28.csv` 永远不会被创建
- `/m120/status` 返回 needs_update=false（上周 100 只覆盖本周 96 只）
- 前端"更新 M120"按钮永远不亮

修复
----
把 M120_CSV_FILE / REALTIME_PRICE_CSV_FILE / PE_CSV_FILE 都改成 @property，
每次访问都按 datetime.now() 重算，跨周/跨月自动指向新文件。

回归测试（test_singleton_updates_after_week_crosses）模拟"服务在 6-14 启动
后跨周日到 6-22"，断言单例的 M120_CSV_FILE.name 包含 06-22 周的 suffix。
旧代码下这个断言会失败（旧代码单例永远返回 06-08-06-14）。
"""
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from src.services.base import CsvPathService, current_week_suffix
from src.services.m120_service import M120Service
from src.services.pe_service import PEDataService
from src.utils.helpers import DATA_DIR


class TestCurrentWeekSuffix:
    """current_week_suffix 工具函数"""

    def test_monday_returns_same_day_as_suffix(self):
        """周一当天 → suffix 起始日和结束日相隔 6 天"""
        # 2026-06-22 是周一
        with patch("src.services.base.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 22, 12, 0, 0)
            # base.py 用了 timedelta，timedelta 不能简单 mock，让 mock_dt.side_effect 走真实 datetime
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            suffix = current_week_suffix()
        assert suffix == "06-22-06-28", f"6-22 周一当周应该是 06-22-06-28，实际 {suffix}"

    def test_sunday_returns_previous_monday(self):
        """周日 → suffix 起始日是本周一"""
        # 2026-06-28 是周日
        with patch("src.services.base.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 28, 12, 0, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            suffix = current_week_suffix()
        assert suffix == "06-22-06-28", f"6-28 周日当周应该是 06-22-06-28，实际 {suffix}"

    def test_midweek(self):
        """周三 → 周一到周日"""
        # 2026-06-24 是周三
        with patch("src.services.base.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 24, 12, 0, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            suffix = current_week_suffix()
        assert suffix == "06-22-06-28", f"6-24 周三当周应该是 06-22-06-28，实际 {suffix}"

    def test_cross_week_boundary(self):
        """周日→周一跨周 → suffix 跳到下一周"""
        with patch("src.services.base.datetime") as mock_dt:
            # 周一 6-29
            mock_dt.now.return_value = datetime(2026, 6, 29, 12, 0, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            suffix = current_week_suffix()
        assert suffix == "06-29-07-05", f"6-29 周一当周应该是 06-29-07-05，实际 {suffix}"


class TestCsvPathService:
    """基类接口"""

    def test_csv_path_raises_when_no_template_set(self):
        """子类未设置模板 → 抛 NotImplementedError"""

        class Dummy(CsvPathService):
            pass

        with pytest.raises(NotImplementedError):
            _ = Dummy().csv_path

    def test_csv_path_creates_parent_directory(self, tmp_path):
        """首次访问 csv_path 自动 mkdir parent"""
        with patch("src.services.base.DATA_DIR", tmp_path):
            # 用临时 DATA_DIR 避免污染真实目录
            class MonthCsv(CsvPathService):
                month_filename = "test.csv"

            instance = MonthCsv(date_str="2099-12")
            path = instance.csv_path
            assert path.parent.exists(), "父目录应该被自动创建"
            assert path == tmp_path / "2099-12" / "test.csv"


class TestM120PathDynamics:
    """M120Service 路径动态化（核心 regression）"""

    def test_singleton_updates_after_week_crosses(self):
        """
        核心 regression：模拟"服务在 6-14 启动后跨周日到 6-22"。

        旧代码：单例 M120_CSV_FILE 永远指向 06-08-06-14 → 断言失败
        新代码：单例 M120_CSV_FILE 按 datetime.now() 重算 → 断言通过
        """
        service = M120Service()

        # 第一周：6-15（周日）
        with patch("src.services.base.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 15, 12, 0, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            week1_path = service.M120_CSV_FILE

        # 跨周日：6-22（周一，新一周）
        with patch("src.services.base.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 22, 12, 0, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            week2_path = service.M120_CSV_FILE

        assert "06-15" in week1_path.name or "06-22" not in week1_path.name, (
            f"第一周（6-15 周日所在周）路径不应包含 06-22，实际 {week1_path}"
        )
        assert "06-22" in week2_path.name, (
            f"跨周日到 6-22 后路径应包含 06-22，实际 {week2_path}"
        )
        assert week1_path != week2_path, "跨周后路径必须不同"

    def test_m120_path_includes_current_week(self):
        """默认 datetime.now() → M120_CSV_FILE.name 含 mm-dd-mm-dd 后缀"""
        service = M120Service()
        path = service.M120_CSV_FILE
        assert path.name.startswith("M120均线_"), f"文件名应以 M120均线_ 开头，实际 {path.name}"
        # 形如 M120均线_06-22-06-28.csv
        suffix = path.stem.replace("M120均线_", "")
        assert "-" in suffix and len(suffix.split("-")) == 4, (
            f"week_suffix 应是 mm-dd-mm-dd 格式，实际 {suffix}"
        )

    def test_realtime_price_path_no_week_suffix(self):
        """实时价格 CSV 不带周度后缀（一天内多次刷新共用）"""
        service = M120Service()
        path = service.REALTIME_PRICE_CSV_FILE
        assert path.name == "实时价格.csv", f"实时价格文件名应是 实时价格.csv，实际 {path.name}"

    def test_m120_and_realtime_in_same_month_dir(self):
        """M120 和实时价格 CSV 在同一 date_str 月目录下"""
        service = M120Service()
        assert service.M120_CSV_FILE.parent == service.REALTIME_PRICE_CSV_FILE.parent, (
            "M120 和实时价格应在同一月目录下"
        )

    def test_no_class_attribute_regression(self):
        """
        防回归：M120_CSV_FILE 应是 @property（descriptor），不是数据类属性。

        旧代码 `M120_CSV_FILE = None` 在类级别导致单例共享同一 None 引用，
        后续 self.M120_CSV_FILE = Path(...) 时落到类属性上跨实例持久化。
        新代码用 @property，每次访问都是 descriptor protocol 调用 → 返回新 Path。

        检测方法：`isinstance(getattr(M120Service, "M120_CSV_FILE"), property)` 必须为 True。
        """
        m120_attr = getattr(M120Service, "M120_CSV_FILE", None)
        realtime_attr = getattr(M120Service, "REALTIME_PRICE_CSV_FILE", None)

        assert isinstance(m120_attr, property), (
            f"M120_CSV_FILE 必须是 @property（descriptor），"
            f"实际类型 {type(m120_attr).__name__}"
        )
        assert isinstance(realtime_attr, property), (
            f"REALTIME_PRICE_CSV_FILE 必须是 @property，实际类型 {type(realtime_attr).__name__}"
        )

    def test_path_returns_path_instance(self):
        """M120_CSV_FILE / REALTIME_PRICE_CSV_FILE 应返回 Path 实例"""
        service = M120Service()
        assert isinstance(service.M120_CSV_FILE, Path)
        assert isinstance(service.REALTIME_PRICE_CSV_FILE, Path)


class TestPEPathDynamics:
    """PEDataService 路径动态化（次要 regression，跨月场景）"""

    def test_singleton_updates_after_month_crosses(self):
        """
        核心 regression：PE 跨月后路径自动更新。

        注意：`helpers.get_current_date_dir()` 用的是自己的 datetime 引用，
        必须 patch `src.utils.helpers.datetime` 而不是 `src.services.base.datetime`。
        """
        service = PEDataService()

        with patch("src.utils.helpers.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 15, 12, 0, 0)
            month1_path = service.PE_CSV_FILE

        with patch("src.utils.helpers.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 1, 12, 0, 0)
            month2_path = service.PE_CSV_FILE

        assert "2026-06" in str(month1_path), f"6 月应指向 2026-06，实际 {month1_path}"
        assert "2026-07" in str(month2_path), f"7 月应指向 2026-07，实际 {month2_path}"
        assert month1_path != month2_path

    def test_pe_path_no_week_suffix(self):
        """PE 文件不带周度后缀（按月刷新）"""
        service = PEDataService()
        assert service.PE_CSV_FILE.name == "PE数据.csv"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
