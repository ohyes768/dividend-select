"""
_persist_prefilter_stock_list 单元测试

覆盖：
- 接受 StockBasicInfo-like 对象（duck typing 取 .code）
- 接受纯 str list
- 内部 zfill(6) 保留前导 0
- 写盘调用 save_csv_data 并透传 date_str + filename="prefilter_stock_list.csv"
- 空 list → raise ValueError（不写空文件，与 commit 3c1dce4 行为一致）
- 不去重（dedup 是调用方职责）
- 真实写盘：monkeypatch 重定向 DATA_DIR/LOGS_DIR 到 tmp_path，不污染生产 data/
"""
import sys
from dataclasses import dataclass
from unittest.mock import patch

import pandas as pd
import pytest

# 复用 test_fetcher.py 的 sys.path 模式：测试不是以包形式运行
sys.path.insert(0, "src")

from src.api.routes import _persist_prefilter_stock_list  # noqa: E402


@dataclass
class StubStock:
    """模拟 StockBasicInfo（dataclass，duck typing）"""
    code: str


class TestPersistPrefilterStockList:
    """FR-3 新抽函数测试"""

    @patch("src.api.routes.save_csv_data")
    def test_stock_basic_info_list(self, mock_save):
        """传入 list[StubStock] 时正确取 .code、构造 DataFrame、调用 save"""
        stocks = [
            StubStock(code="1"),         # 前导 0
            StubStock(code="601318"),
            StubStock(code="000001"),
        ]
        _persist_prefilter_stock_list(stocks, date_str="2026-08")

        mock_save.assert_called_once()
        args, _ = mock_save.call_args
        df_arg, filename_arg, date_str_arg = args

        assert filename_arg == "prefilter_stock_list.csv"
        assert date_str_arg == "2026-08"

        assert list(df_arg.columns) == ["股票代码"]
        assert len(df_arg) == 3
        assert df_arg["股票代码"].tolist() == ["000001", "601318", "000001"]

    @patch("src.api.routes.save_csv_data")
    def test_string_list_input(self, mock_save):
        """传入 list[str] 时直接用 str，无需 .code 属性"""
        codes = ["1", "601318", "000001", "600000"]
        _persist_prefilter_stock_list(codes, date_str="2026-08")

        mock_save.assert_called_once()
        df_arg = mock_save.call_args[0][0]
        assert df_arg["股票代码"].tolist() == ["000001", "601318", "000001", "600000"]

    @patch("src.api.routes.save_csv_data")
    def test_zfill_preserves_leading_zeros(self, mock_save):
        """短 code 被 zfill(6) 补前导 0；已 6 位的不变"""
        codes = ["1", "90", "000001", "601318"]
        _persist_prefilter_stock_list(codes, date_str="2026-08")

        df_arg = mock_save.call_args[0][0]
        assert df_arg["股票代码"].tolist() == ["000001", "000090", "000001", "601318"]

    @patch("src.api.routes.save_csv_data")
    def test_empty_raises_value_error(self, mock_save):
        """空 list 应 raise 且不应调 save_csv_data（不写空文件）"""
        with pytest.raises(ValueError, match="prefilter stock_list 为空"):
            _persist_prefilter_stock_list([], date_str="2026-08")

        mock_save.assert_not_called()

    @patch("src.api.routes.save_csv_data")
    def test_does_not_dedupe(self, mock_save):
        """函数本身不去重——dedup 是调用方职责（fetcher.get_stock_list 已 dedup）"""
        codes = ["601318", "601318", "000001", "000001"]
        _persist_prefilter_stock_list(codes, date_str="2026-08")

        df_arg = mock_save.call_args[0][0]
        assert len(df_arg) == 4
        assert df_arg["股票代码"].tolist() == ["601318", "601318", "000001", "000001"]

    @patch("src.api.routes.save_csv_data")
    def test_mixed_input_types(self, mock_save):
        """混合 StockBasicInfo 和 str 的 list 也能处理"""
        items = [
            StubStock(code="601318"),
            "000001",
            StubStock(code="1"),
        ]
        _persist_prefilter_stock_list(items, date_str="2026-08")

        df_arg = mock_save.call_args[0][0]
        assert df_arg["股票代码"].tolist() == ["601318", "000001", "000001"]

    @patch("src.api.routes.save_csv_data")
    def test_date_str_passes_through(self, mock_save):
        """date_str 透传给 save_csv_data（影响最终路径）"""
        _persist_prefilter_stock_list(["000001"], date_str="2025-12")

        _, filename_arg, date_str_arg = mock_save.call_args[0]
        assert filename_arg == "prefilter_stock_list.csv"
        assert date_str_arg == "2025-12"


class TestPersistPrefilterIntegration:
    """真实写盘——monkeypatch 重定向 PROJECT_ROOT/DATA_DIR/LOGS_DIR 到 tmp，让真 save_csv_data 写 tmp。"""

    def test_real_csv_writes_correctly(self, tmp_path, monkeypatch):
        """端到端：构造 stub 写入 tmp_path → 读回 → 验证内容"""
        from src.utils import helpers
        from src.api import routes as routes_module

        # PROJECT_ROOT 是 helpers.py 顶部按 __file__ 计算的固定值，要重定向
        project_root = tmp_path / "fake_project"
        project_root.mkdir()
        monkeypatch.setattr(helpers, "PROJECT_ROOT", project_root)
        monkeypatch.setattr(helpers, "DATA_DIR", project_root / "data")
        monkeypatch.setattr(helpers, "LOGS_DIR", project_root / "logs")
        # routes.py 顶部 from src.utils.helpers import save_csv_data, DATA_DIR, ...;
        # 这里 DATA_DIR 是 routes 模块的引用（虽然 routes 自己不直接用，但保持一致）
        monkeypatch.setattr(routes_module, "DATA_DIR", project_root / "data")

        codes = ["1", "601318", "000001"]
        _persist_prefilter_stock_list(codes, date_str="2026-08")

        # save_csv_data(filename="prefilter_stock_list.csv", date_str="2026-08")
        # 真实路径：DATA_DIR / "2026-08" / "prefilter_stock_list_2026-08.csv"
        csv_path = project_root / "data" / "2026-08" / "prefilter_stock_list_2026-08.csv"
        assert csv_path.exists(), f"应写 {csv_path}"

        df = pd.read_csv(csv_path, dtype={"股票代码": str})
        assert list(df.columns) == ["股票代码"]
        assert df["股票代码"].tolist() == ["000001", "601318", "000001"]
