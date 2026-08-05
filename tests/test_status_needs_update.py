"""
GET /dividend/status 的 needs_update 行为测试

覆盖 FR-1：删 or not holdings_complete 后，主按钮 needs_update 不再受持仓覆盖度影响。
旧 commit 423d2fe 临时把 holdings_complete 加进 needs_update，本任务取消该绑定。
持仓覆盖度由 /dividend/index-holdings/refresh 单指数重试入口负责。
"""
import sys
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, "src")

from src.api import routes as routes_module
from src.utils import helpers


# 8 个红利指数（按 DIVIDEND_INDEXES + ALT_API_INDEXES 顺序，测试用简化的 8 个 code）
ALL_INDEX_CODES = [
    "000922",  # 中证红利
    "932315",  # 中证红利质量
    "932309",  # 红利增长
    "931468",  # 红利质量
    "000015",  # 上证红利
    "000825",  # 中证国企红利
    "399324",  # 深证红利
    "H30089",  # 红利低波100
]
MISSING_INDEX = "931468"  # 模拟"单指数刷新挂了一只"
PRESENT_INDEXES = [c for c in ALL_INDEX_CODES if c != MISSING_INDEX]


@pytest.fixture
def fake_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把 DATA_DIR/LOGS_DIR 重定向到 tmp，避免触碰生产 data/"""
    project_root = tmp_path / "fake_project"
    project_root.mkdir()
    monkeypatch.setattr(helpers, "PROJECT_ROOT", project_root)
    fake_data = project_root / "data"
    fake_data.mkdir()
    monkeypatch.setattr(helpers, "DATA_DIR", fake_data)
    monkeypatch.setattr(helpers, "LOGS_DIR", project_root / "logs")
    # routes.py 顶部 from src.utils.helpers import save_csv_data, DATA_DIR, ...
    monkeypatch.setattr(routes_module, "DATA_DIR", fake_data)
    return fake_data


@pytest.fixture
def fixed_date_str(monkeypatch: pytest.MonkeyPatch) -> str:
    """固定 get_current_date_dir 返回 '2026-08'，避免受系统时间影响

    注意：routes.py::get_dividend_status 函数内 `from src.utils.helpers import ... get_current_date_dir`
    是函数级 import；这里 patch helpers 模块层的同名函数即可。
    """
    monkeypatch.setattr(helpers, "get_current_date_dir", lambda: "2026-08")
    return "2026-08"


@pytest.fixture
def client(fake_data_dir: Path, fixed_date_str: str) -> TestClient:
    """TestClient 走 lifespan（lifespan 内各服务初始化都会失败 CSV 检查但不会抛错）"""
    from src.main import app
    with TestClient(app) as c:
        yield c


def _write_csv(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def _make_holdings_csv(present_indexes: list[str], stocks_per_index: int = 5) -> pd.DataFrame:
    """构造 holdings CSV：每个指数贡献 stocks_per_index 个 stock code"""
    rows = []
    for code in present_indexes:
        for i in range(stocks_per_index):
            stock_code = f"{100000 + i:06d}"
            rows.append({
                "交易所": "沪市主板",
                "股票代码": stock_code,
                "股票名称": f"测试股票{i}",
                "来源指数": f"指数{code}",
                "来源指数代码": code,
            })
    return pd.DataFrame(rows)


class TestNeedsUpdateNoHoldingsOverride:
    """FR-1 测试：completed == target 时，即使持仓覆盖度不全，needs_update 也应为 False"""

    def test_needs_update_false_when_completed_equals_target_but_one_index_missing(
        self, client: TestClient, fake_data_dir: Path, fixed_date_str: str
    ):
        """持仓缺一只指数（931468）+ completed == target 都满足

        旧逻辑：needs_update = completed < target or not holdings_complete
             = False or True = True  ❌
        新逻辑：needs_update = completed < target
             = False                ✅
        """
        # 1. 准备汇总 CSV：144 行
        yield_codes = [f"{100000 + i:06d}" for i in range(144)]
        dividend_df = pd.DataFrame({"股票代码": yield_codes})
        _write_csv(
            fake_data_dir / fixed_date_str / f"近3年股息率汇总_{fixed_date_str}.csv",
            dividend_df,
        )

        # 2. 准备 持仓 CSV：缺失 931468（7/8 指数）+ 一些 stock 列（行数不影响 completed_count）
        holdings_df = _make_holdings_csv(PRESENT_INDEXES, stocks_per_index=5)
        _write_csv(
            fake_data_dir / fixed_date_str / f"红利指数持仓汇总_{fixed_date_str}.csv",
            holdings_df,
        )

        # 3. 准备 prefilter CSV：144 行 = target_count
        prefilter_df = pd.DataFrame({"股票代码": yield_codes})
        _write_csv(
            fake_data_dir / fixed_date_str / f"prefilter_stock_list_{fixed_date_str}.csv",
            prefilter_df,
        )

        # 触发
        resp = client.get("/api/dividend/dividend/status")
        assert resp.status_code == 200, resp.text
        data = resp.json()

        # 核心验证：needs_update 由对比 1 决定，不受 holdings_complete 影响
        assert data["needs_update"] is False, (
            f"FR-1 修复后，completed={data['completed_count']} "
            f"target={data['target_count']}，持仓缺一只指数不影响 needs_update，"
            f"实际 {data['needs_update']}"
        )
        assert data["completed_count"] == data["target_count"] == 144

        # 持仓覆盖度仍正确报告（这是给 IndexStatusPopover 用的，不该失效）
        assert data["holdings_status"]["holdings_complete"] is False
        assert MISSING_INDEX in data["holdings_status"]["missing_index_codes"]

    def test_needs_update_true_when_completed_below_target_holdings_complete(
        self, client: TestClient, fake_data_dir: Path, fixed_date_str: str
    ):
        """completed < target + 持仓齐：needs_update 应为 True（基本对照）"""
        # 汇总 100 行，prefilter 144 行 → completed < target → needs_update=True
        yield_codes = [f"{100000 + i:06d}" for i in range(100)]
        _write_csv(
            fake_data_dir / fixed_date_str / f"近3年股息率汇总_{fixed_date_str}.csv",
            pd.DataFrame({"股票代码": yield_codes}),
        )

        # 持仓齐全（8/8）
        holdings_df = _make_holdings_csv(ALL_INDEX_CODES, stocks_per_index=5)
        _write_csv(
            fake_data_dir / fixed_date_str / f"红利指数持仓汇总_{fixed_date_str}.csv",
            holdings_df,
        )

        prefilter_df = pd.DataFrame({"股票代码": [f"{200000 + i:06d}" for i in range(144)]})
        _write_csv(
            fake_data_dir / fixed_date_str / f"prefilter_stock_list_{fixed_date_str}.csv",
            prefilter_df,
        )

        resp = client.get("/api/dividend/dividend/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["needs_update"] is True
        assert data["completed_count"] == 100
        assert data["target_count"] == 144
        assert data["holdings_status"]["holdings_complete"] is True
