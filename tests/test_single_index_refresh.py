"""
POST /dividend/index-holdings/refresh 单指数刷接口测试

覆盖 FR-2 + FR-4：
- 单指数刷成功后本地重算 prefilter，不调 akshare
- 接口响应含 prefilter_resynced + prefilter_error 字段
- prefilter 重算失败时 API 仍返回 success=true + prefilter_resynced=false，
  让前端徽章能区分"持仓+prefilter 都成功"与"持仓成功但 prefilter 失败"
"""
import sys
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, "src")

from src.api import routes as routes_module
from src.utils import helpers


DATE_STR = "2026-08"


def _write_csv(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


@pytest.fixture
def fake_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把 DATA_DIR/LOGS_DIR 重定向到 tmp"""
    project_root = tmp_path / "fake_project"
    project_root.mkdir()
    monkeypatch.setattr(helpers, "PROJECT_ROOT", project_root)
    fake_data = project_root / "data"
    fake_data.mkdir()
    monkeypatch.setattr(helpers, "DATA_DIR", fake_data)
    monkeypatch.setattr(helpers, "LOGS_DIR", project_root / "logs")
    monkeypatch.setattr(routes_module, "DATA_DIR", fake_data)
    return fake_data


@pytest.fixture
def fixed_date(monkeypatch: pytest.MonkeyPatch) -> None:
    """固定 get_current_date_dir 返回 DATE_STR"""
    monkeypatch.setattr(helpers, "get_current_date_dir", lambda: DATE_STR)


@pytest.fixture
def client(fake_data_dir: Path, fixed_date: None) -> TestClient:
    from src.main import app
    with TestClient(app) as c:
        yield c


def _make_holdings_csv(codes_per_index: dict[str, list[str]]) -> pd.DataFrame:
    """构造 holdings CSV，每个指数贡献自己一组 stock code

    codes_per_index: {指数代码: [股票代码列表]}
    """
    rows = []
    for idx_code, stock_codes in codes_per_index.items():
        for i, stock_code in enumerate(stock_codes):
            rows.append({
                "交易所": "沪市主板",
                "股票代码": stock_code,
                "股票名称": f"测试{idx_code}-{i}",
                "来源指数": f"指数{idx_code}",
                "来源指数代码": idx_code,
            })
    return pd.DataFrame(rows)


def _make_fhps_csv(codes: list[str]) -> pd.DataFrame:
    """构造 fhps 全市场预案 CSV（仅含股票代码一列即可；列名兼容）"""
    return pd.DataFrame({"股票代码": codes, "财年": [2025] * len(codes)})


class TestSingleIndexRefreshPrefilter:
    """FR-2 + FR-4 测试"""

    def test_prefilter_resynced_true_when_holdings_refresh_succeeds(
        self, client: TestClient, fake_data_dir: Path
    ):
        """持仓刷成功 + 本地重算成功 → response prefilter_resynced=true + prefilter CSV 写盘"""
        target_index = "000922"
        # holdings CSV：含 target_index 的 5 只股票 + 其他指数
        holdings_df = _make_holdings_csv({
            target_index: ["100001", "100002", "100003", "100004", "100005"],
            "932315": ["200001", "200002", "200003"],
        })
        _write_csv(fake_data_dir / DATE_STR / f"红利指数持仓汇总_{DATE_STR}.csv", holdings_df)

        # fhps CSV：主板 + 在 fhps = 全部（所有 holdings 股票都在 fhps）
        all_holding_codes = ["100001", "100002", "100003", "100004", "100005",
                             "200001", "200002", "200003"]
        _write_csv(fake_data_dir / "fhps" / "fhps_20251231.csv",
                   _make_fhps_csv(all_holding_codes))

        # patch IndexHoldingsFetcher.replace_one_holdings（按"src.data.IndexHoldingsFetcher"路径）
        # 单指数刷后再次写 holdings 不影响本次测试，因为我们断言 prefilter 已完成
        from src.data import IndexHoldingsFetcher
        mock_result = {
            "code": target_index, "name": "中证红利",
            "success": True, "constituents_count": 5, "error": None,
        }
        with pytest.MonkeyPatch.context() as mpatch:
            mpatch.setattr(
                IndexHoldingsFetcher, "replace_one_holdings",
                lambda self, code: mock_result,
            )
            resp = client.post(
                "/api/dividend/dividend/index-holdings/refresh",
                json={"code": target_index},
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()

        # 接口响应扩字段
        assert data["success"] is True
        assert data["code"] == target_index
        assert data["prefilter_resynced"] is True
        assert data["prefilter_error"] is None

        # prefilter CSV 被写出
        prefilter_path = fake_data_dir / DATE_STR / f"prefilter_stock_list_{DATE_STR}.csv"
        assert prefilter_path.exists(), f"应写 {prefilter_path}"
        df = pd.read_csv(prefilter_path, dtype={"股票代码": str})
        assert df["股票代码"].tolist() == sorted(all_holding_codes)

    def test_prefilter_failure_does_not_fail_api(
        self, client: TestClient, fake_data_dir: Path, caplog
    ):
        """持仓刷成功 + 本地重算失败（缺 fhps 缓存） → API 仍 success=true + prefilter_resynced=false + prefilter_error 有内容

        同时验证关键约定：单指数 API 整体不因 prefilter 失败而抛错，前端拿到 partial 状态。
        """
        target_index = "000922"
        # holdings CSV 存在
        holdings_df = _make_holdings_csv({
            target_index: ["100001", "100002", "100003", "100004", "100005"],
        })
        _write_csv(fake_data_dir / DATE_STR / f"红利指数持仓汇总_{DATE_STR}.csv", holdings_df)

        # 不写 fhps CSV，让 _resync_prefilter_after_index_refresh 抛 FileNotFoundError

        from src.data import IndexHoldingsFetcher
        mock_result = {
            "code": target_index, "name": "中证红利",
            "success": True, "constituents_count": 5, "error": None,
        }
        with pytest.MonkeyPatch.context() as mpatch:
            mpatch.setattr(
                IndexHoldingsFetcher, "replace_one_holdings",
                lambda self, code: mock_result,
            )
            resp = client.post(
                "/api/dividend/dividend/index-holdings/refresh",
                json={"code": target_index},
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()

        # 持仓成功 + prefilter 失败
        assert data["success"] is True
        assert data["prefilter_resynced"] is False
        assert data["prefilter_error"], "prefilter_error 应非空"
        assert "fhps" in data["prefilter_error"].lower() or "No such file" in data["prefilter_error"], \
            f"错误信息应提及 fhps 缺失，实际: {data['prefilter_error']}"

        # prefilter CSV 不应被写（避免脏数据）
        prefilter_path = fake_data_dir / DATE_STR / f"prefilter_stock_list_{DATE_STR}.csv"
        # 注意：这里如果测试初始化时已存在 prefilter CSV 则不会被覆盖（_persist 只写自己的 df）
        # _resync_prefilter 内部抛异常前还没走到 _persist，写盘未发生
        assert not prefilter_path.exists(), "重算失败时不应写 prefilter CSV"

    def test_no_akshare_call_during_local_resync(
        self, client: TestClient, fake_data_dir: Path
    ):
        """重算 prefilter 完全本地（pd.read_csv），不应触发 akshare.* 任何调用

        通过 monkeypatching akshare 整个模块的属性访问来验证
        """
        target_index = "000922"
        # holdings + fhps 都准备好
        holdings_df = _make_holdings_csv({
            target_index: ["100001", "100002", "100003", "100004", "100005"],
        })
        _write_csv(fake_data_dir / DATE_STR / f"红利指数持仓汇总_{DATE_STR}.csv", holdings_df)
        _write_csv(fake_data_dir / "fhps" / "fhps_20251231.csv",
                   _make_fhps_csv(["100001", "100002", "100003", "100004", "100005"]))

        from src.data import IndexHoldingsFetcher
        mock_result = {
            "code": target_index, "name": "中证红利",
            "success": True, "constituents_count": 5, "error": None,
        }

        # 我们只关心 _resync_prefilter_after_index_refresh 不调 akshare
        # 拦截：删掉 akshare 的几个常见入口；访问则抛错
        import akshare as ak
        with pytest.MonkeyPatch.context() as mpatch:
            # 拦截 akshare 函数让访问抛错
            def _boom(*args, **kwargs):
                raise AssertionError("禁止调用 akshare！应纯本地重算")

            for fn_name in [
                "stock_fhps_em", "index_stock_cons_weight_csindex",
                "stock_history_dividend", "stock_dividend_cninfo",
            ]:
                if hasattr(ak, fn_name):
                    mpatch.setattr(ak, fn_name, _boom)
                    # 同时拦截 src.data 视图（如果已被 import）
                    try:
                        import src.data.fetcher as fetcher_mod
                        if hasattr(fetcher_mod, "ak"):
                            # fetcher_mod.ak 是 akshare alias
                            pass  # 跳过：实际是 module-level `import akshare as ak`
                    except ImportError:
                        pass

            mpatch.setattr(
                IndexHoldingsFetcher, "replace_one_holdings",
                lambda self, code: mock_result,
            )
            resp = client.post(
                "/api/dividend/dividend/index-holdings/refresh",
                json={"code": target_index},
            )

        # 如果本地重算调了 akshare，foo() 会抛 AssertionError，响应会是 500
        # 现在通过：prefilter_resynced=true 且 response 200
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["success"] is True
        assert data["prefilter_resynced"] is True
        assert data["prefilter_error"] is None
