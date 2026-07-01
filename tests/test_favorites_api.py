"""
Favorites API 集成测试
"""
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.services.favorites_service import FavoritesService


@pytest.fixture
def client(tmp_path: Path):
    """每个测试用独立 tmp_path 构造 favorites 文件，通过 set_instance 覆盖 lifespan 单例"""
    # 关键：先 reset 单例，避免之前测试残留的真实 data/favorites.json 单例被复用
    FavoritesService._instance = None

    file_path = tmp_path / "favorites.json"
    svc = FavoritesService(file_path=file_path)
    # 在 lifespan 启动前，把单例指向测试 svc
    # 这样 lifespan 里的 FavoritesService.get_instance() 返回的就是测试实例
    FavoritesService._instance = svc

    with TestClient(app) as c:
        yield c

    # 清理
    FavoritesService._instance = None
    from src.api import routes
    routes.favorites_service = None


class TestGet:
    """GET /favorites"""

    def test_get_empty(self, client: TestClient):
        """GET /favorites 返回 total=0"""
        resp = client.get("/api/dividend/favorites")
        assert resp.status_code == 200
        body = resp.json()
        assert body["version"] == 1
        assert body["total"] == 0
        assert body["codes"] == []
        assert body["items"] == []
        assert body["notify"]["enabled"] is False


class TestAdd:
    """POST /favorites/{code}"""

    def test_add_returns_full_list(self, client: TestClient):
        """POST 后响应含完整最新列表"""
        client.post("/api/dividend/favorites/000001")
        resp = client.post("/api/dividend/favorites/600000")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert "000001" in body["codes"]
        assert "600000" in body["codes"]

    def test_add_invalid_code_400(self, client: TestClient):
        """POST /favorites/abc 返回 400"""
        resp = client.post("/api/dividend/favorites/abc")
        assert resp.status_code == 400
        assert "\u80a1\u7968\u4ee3\u7801\u683c\u5f0f\u9519\u8bef" in resp.json()["detail"]


class TestRemove:
    """DELETE /favorites/{code}"""

    def test_remove_returns_full_list(self, client: TestClient):
        """DELETE 后响应含最新列表"""
        client.post("/api/dividend/favorites/000001")
        client.post("/api/dividend/favorites/600000")
        resp = client.delete("/api/dividend/favorites/000001")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["codes"] == ["600000"]

    def test_remove_invalid_code_400(self, client: TestClient):
        """DELETE /favorites/abc 返回 400（非数字）"""
        resp = client.delete("/api/dividend/favorites/abc")
        assert resp.status_code == 400


class TestUpdateNote:
    """PUT /favorites/{code}/note"""

    def test_update_note_success(self, client: TestClient):
        """PUT /favorites/{code}/note 返回新 item"""
        client.post("/api/dividend/favorites/000001")
        resp = client.put(
            "/api/dividend/favorites/000001/note",
            json={"note": "\u4e2d\u56fd\u5e73\u5b89"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == "000001"
        assert body["note"] == "\u4e2d\u56fd\u5e73\u5b89"

    def test_update_note_not_favorited_404(self, client: TestClient):
        """PUT 不在收藏的 code 返回 404"""
        resp = client.put(
            "/api/dividend/favorites/999999/note",
            json={"note": "x"},
        )
        assert resp.status_code == 404


class TestConcurrency:
    """并发安全"""

    def test_concurrent_add(self, client: TestClient):
        """50 个线程同时 POST 不同 code，全部成功且 list 大小为 50"""
        codes = [f"{(i + 1):06d}" for i in range(50)]
        results = []
        errors = []

        def post_one(code: str):
            try:
                resp = client.post(f"/api/dividend/favorites/{code}")
                results.append(resp.status_code)
            except Exception as e:
                errors.append(str(e))

        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(post_one, c) for c in codes]
            for f in as_completed(futures):
                f.result()

        # 所有 POST 都成功
        assert len(errors) == 0, f"errors: {errors}"
        assert all(s == 200 for s in results), f"non-200 status: {results}"

        # 最终 GET 应有 50 个 code
        resp = client.get("/api/dividend/favorites")
        body = resp.json()
        assert body["total"] == 50
        assert set(body["codes"]) == set(codes)
