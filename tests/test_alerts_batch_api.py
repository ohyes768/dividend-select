"""
Batch Alerts API 集成测试

覆盖 POST /api/dividend/favorites/alerts/batch：
- happy path（已收藏 / 未收藏自动加）
- 部分失败
- token 校验（缺失 / 错误 / 服务端未配置）
- Pydantic 校验（updates 超限 / price ≤ 0）
- enabled 默认 true
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.services.favorites_service import FavoritesService


BATCH_URL = "/api/dividend/favorites/alerts/batch"


def _make_levels(h: float, a: float, r: float, f: float,
                 pe: float | None = None, pb: float | None = None) -> dict:
    """构造 4 档 levels dict"""
    base = {"heavy_position": {"price": h}, "add_position": {"price": a},
            "reduce_position": {"price": r}, "full_exit": {"price": f}}
    if pe is not None:
        for lv in base.values():
            lv["pe"] = pe
    if pb is not None:
        for lv in base.values():
            lv["pb"] = pb
    return base


def _make_update(code: str, levels: dict | None = None, enabled: bool | None = None) -> dict:
    item = {"code": code, "levels": levels or _make_levels(10, 12, 15, 18)}
    if enabled is not None:
        item["enabled"] = enabled
    return item


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    """独立 tmp favorites.json + AGENT_API_TOKEN=test-token"""
    FavoritesService._instance = None
    svc = FavoritesService(file_path=tmp_path / "favorites.json")
    FavoritesService._instance = svc

    monkeypatch.setenv("AGENT_API_TOKEN", "test-token")

    with TestClient(app) as c:
        yield c

    FavoritesService._instance = None
    from src.api import routes
    routes.favorites_service = None


@pytest.fixture
def client_no_token(tmp_path: Path, monkeypatch):
    """服务端未配置 AGENT_API_TOKEN（env 不存在）"""
    FavoritesService._instance = None
    svc = FavoritesService(file_path=tmp_path / "favorites.json")
    FavoritesService._instance = svc

    monkeypatch.delenv("AGENT_API_TOKEN", raising=False)

    with TestClient(app) as c:
        yield c

    FavoritesService._instance = None
    from src.api import routes
    routes.favorites_service = None


def _token_headers(token: str = "test-token") -> dict:
    return {"X-API-Token": token}


# ========== Happy path ==========


class TestHappy:

    def test_batch_already_favorite(self, client: TestClient):
        """code 已在 favorites → 直接更新挡位"""
        client.post("/api/dividend/favorites/600000")  # 先加收藏
        resp = client.post(BATCH_URL, json={"updates": [_make_update("600000")]},
                           headers=_token_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"results": [{"code": "600000", "ok": True, "error": None}],
                        "success_count": 1, "fail_count": 0}

        # 验证挡位写入
        fav = client.get("/api/dividend/favorites").json()
        item = next(it for it in fav["items"] if it["code"] == "600000")
        assert item["alerts"]["enabled"] is True
        assert item["alerts"]["levels"]["heavy_position"]["price"] == 10.0

    def test_batch_auto_add_favorite(self, client: TestClient):
        """code 不在 favorites → 自动加入 + 设挡位"""
        resp = client.post(BATCH_URL, json={"updates": [_make_update("600000")]},
                           headers=_token_headers())
        assert resp.status_code == 200
        assert resp.json()["results"][0]["ok"] is True

        # 自动加入了 favorites
        fav = client.get("/api/dividend/favorites").json()
        assert "600000" in fav["codes"]
        assert len(fav["codes"]) == 1

    def test_batch_multiple_with_pe_pb(self, client: TestClient):
        """多条 + pe/pb 写入"""
        updates = [
            _make_update("600000", _make_levels(10, 12, 15, 18, pe=8.5, pb=1.2)),
            _make_update("000001", _make_levels(11, 13, 16, 19)),
        ]
        resp = client.post(BATCH_URL, json={"updates": updates},
                           headers=_token_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert body["success_count"] == 2
        assert body["fail_count"] == 0

        # 验证 pe/pb 写入
        fav = client.get("/api/dividend/favorites").json()
        item = next(it for it in fav["items"] if it["code"] == "600000")
        assert item["alerts"]["levels"]["heavy_position"]["pe"] == 8.5
        assert item["alerts"]["levels"]["heavy_position"]["pb"] == 1.2


# ========== 部分失败 ==========


class TestPartialFailure:

    def test_invalid_code_skipped(self, client: TestClient):
        """1 条 code 非法（abc 非数字）+ 1 条合法 → 非法那条 fail，合法那条 ok"""
        updates = [
            _make_update("abc"),     # _normalize_code 会抛 ValueError
            _make_update("600000"),
        ]
        resp = client.post(BATCH_URL, json={"updates": updates},
                           headers=_token_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert body["success_count"] == 1
        assert body["fail_count"] == 1
        # 找到 fail 那条
        fail = next(r for r in body["results"] if not r["ok"])
        assert fail["code"] == "abc"
        assert "格式错误" in fail["error"]


# ========== Token 校验 ==========


class TestToken:

    def test_missing_token_401(self, client: TestClient):
        """不带 X-API-Token → 401"""
        resp = client.post(BATCH_URL, json={"updates": [_make_update("600000")]})
        assert resp.status_code == 401

    def test_wrong_token_401(self, client: TestClient):
        """错 token → 401"""
        resp = client.post(BATCH_URL, json={"updates": [_make_update("600000")]},
                           headers=_token_headers("wrong-token"))
        assert resp.status_code == 401

    def test_no_env_token_503(self, client_no_token: TestClient):
        """服务端未配 AGENT_API_TOKEN → 503"""
        resp = client_no_token.post(
            BATCH_URL,
            json={"updates": [_make_update("600000")]},
            headers=_token_headers("any-token"),
        )
        assert resp.status_code == 503
        assert "AGENT_API_TOKEN" in resp.json()["detail"]


# ========== Pydantic 校验 ==========


class TestValidation:

    def test_updates_over_limit_422(self, client: TestClient):
        """updates 101 条 → 422"""
        updates = [_make_update(str(i).zfill(6)) for i in range(101)]
        resp = client.post(BATCH_URL, json={"updates": updates},
                           headers=_token_headers())
        assert resp.status_code == 422

    def test_invalid_price_422(self, client: TestClient):
        """price=0 → 422（Pydantic gt=0）"""
        updates = [_make_update("600000", _make_levels(0, 12, 15, 18))]
        resp = client.post(BATCH_URL, json={"updates": updates},
                           headers=_token_headers())
        assert resp.status_code == 422

    def test_empty_updates_422(self, client: TestClient):
        """空 updates → 422"""
        resp = client.post(BATCH_URL, json={"updates": []},
                           headers=_token_headers())
        assert resp.status_code == 422


# ========== 默认值 ==========


class TestDefaults:

    def test_enabled_defaults_true(self, client: TestClient):
        """不传 enabled → favorites.json 里 enabled=true"""
        resp = client.post(BATCH_URL, json={"updates": [_make_update("600000")]},
                           headers=_token_headers())
        assert resp.status_code == 200

        fav = client.get("/api/dividend/favorites").json()
        item = next(it for it in fav["items"] if it["code"] == "600000")
        assert item["alerts"]["enabled"] is True

    def test_enabled_false_honored(self, client: TestClient):
        """传 enabled=false → 写入 false"""
        resp = client.post(
            BATCH_URL,
            json={"updates": [_make_update("600000", enabled=False)]},
            headers=_token_headers(),
        )
        assert resp.status_code == 200

        fav = client.get("/api/dividend/favorites").json()
        item = next(it for it in fav["items"] if it["code"] == "600000")
        assert item["alerts"]["enabled"] is False
