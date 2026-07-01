"""
FavoritesService 单元测试
"""
import json
from pathlib import Path

import pytest

from src.services.favorites_service import FavoritesService


@pytest.fixture
def svc(tmp_path: Path) -> FavoritesService:
    """每个测试用独立 tmp_path 构造一个 FavoritesService"""
    file_path = tmp_path / "favorites.json"
    return FavoritesService(file_path=file_path)


class TestInit:
    """启动加载 / 文件容错"""

    def test_init_empty_file(self, tmp_path: Path):
        """文件不存在时启动应创建空 v1 结构，且 total=0"""
        file_path = tmp_path / "favorites.json"
        assert not file_path.exists()
        svc = FavoritesService(file_path=file_path)
        # 文件应被自动创建
        assert file_path.exists()
        data = svc.get_all()
        assert data["version"] == 1
        assert data["codes"] == []
        assert data["items"] == []
        assert data["notify"]["enabled"] is False
        assert data["total"] == 0 if "total" in data else True  # service 不算 total，路由层算

    def test_init_existing_valid_file(self, tmp_path: Path):
        """文件存在且 version=1 时正确加载"""
        file_path = tmp_path / "favorites.json"
        file_path.write_text(json.dumps({
            "version": 1,
            "updated_at": "2026-06-15T10:00:00",
            "codes": ["000001", "600000"],
            "items": [
                {"code": "000001", "added_at": "2026-06-15T10:00:00", "note": "测试"},
            ],
            "notify": {"enabled": False, "rules": [], "last_notified_at": None},
        }, ensure_ascii=False), encoding="utf-8")
        svc = FavoritesService(file_path=file_path)
        data = svc.get_all()
        assert data["codes"] == ["000001", "600000"]
        assert data["items"][0]["note"] == "测试"

    def test_init_corrupt_file(self, tmp_path: Path):
        """JSON 损坏时备份为 .corrupt-*.json 并初始化为空"""
        file_path = tmp_path / "favorites.json"
        file_path.write_text("not valid json", encoding="utf-8")
        svc = FavoritesService(file_path=file_path)
        # 损坏文件应被重命名为备份
        backup_files = list(tmp_path.glob(".favorites.json.corrupt-*"))
        assert len(backup_files) == 1
        # 备份内容应是原损坏内容
        assert backup_files[0].read_text(encoding="utf-8") == "not valid json"
        # 新文件应是空 v1
        assert file_path.exists()
        new_data = json.loads(file_path.read_text(encoding="utf-8"))
        assert new_data["version"] == 1
        assert new_data["codes"] == []
        # 内存数据也是空 v1
        data = svc.get_all()
        assert data["codes"] == []

    def test_init_wrong_version(self, tmp_path: Path):
        """version=2 时抛 RuntimeError（不静默回退）"""
        file_path = tmp_path / "favorites.json"
        file_path.write_text(json.dumps({
            "version": 2,
            "updated_at": "2026-06-15T10:00:00",
            "codes": [],
            "items": [],
            "notify": {},
        }, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(RuntimeError, match="schema \u7248\u672c"):
            FavoritesService(file_path=file_path)

    def test_init_missing_fields(self, tmp_path: Path):
        """老 v1 文件缺 notify 字段时补齐"""
        file_path = tmp_path / "favorites.json"
        file_path.write_text(json.dumps({
            "version": 1,
            "updated_at": "2026-06-15T10:00:00",
            "codes": ["000001"],
            "items": [{"code": "000001", "added_at": "2026-06-15T10:00:00", "note": None}],
            # notify 字段缺失
        }, ensure_ascii=False), encoding="utf-8")
        svc = FavoritesService(file_path=file_path)
        data = svc.get_all()
        assert "notify" in data
        assert data["notify"]["enabled"] is False
        assert data["notify"]["rules"] == []


class TestAdd:
    """添加收藏"""

    def test_add_new_code(self, svc: FavoritesService):
        """新 code 加入后 codes / items 都更新"""
        data = svc.add("000001")
        assert "000001" in data["codes"]
        assert len(data["items"]) == 1
        assert data["items"][0]["code"] == "000001"
        assert data["items"][0]["note"] is None

    def test_add_existing_code_no_note(self, svc: FavoritesService):
        """已存在 code 不传 note，状态不变（幂等）"""
        svc.add("000001")
        first_data = svc.get_all()
        first_updated_at = first_data["updated_at"]
        first_added_at = first_data["items"][0]["added_at"]
        # 再加一次，不传 note
        data = svc.add("000001")
        assert data["codes"] == ["000001"]
        assert len(data["items"]) == 1
        # added_at 不变，updated_at 也不变
        assert data["items"][0]["added_at"] == first_added_at
        assert data["updated_at"] == first_updated_at

    def test_add_existing_code_with_note(self, svc: FavoritesService):
        """已存在 code 传 note，更新该 item 的 note 字段"""
        svc.add("000001", note="初始备注")
        data = svc.add("000001", note="新备注")
        assert data["codes"] == ["000001"]
        assert data["items"][0]["note"] == "新备注"


class TestRemove:
    """移除收藏"""

    def test_remove_existing_code(self, svc: FavoritesService):
        """已存在 code 移除后从 codes 和 items 都消失"""
        svc.add("000001")
        svc.add("600000")
        data = svc.remove("000001")
        assert data["codes"] == ["600000"]
        assert len(data["items"]) == 1
        assert data["items"][0]["code"] == "600000"

    def test_remove_nonexistent_code(self, svc: FavoritesService):
        """删除不存在的 code 不报错（幂等）"""
        svc.add("000001")
        data = svc.remove("999999")
        assert data["codes"] == ["000001"]


class TestNormalizeCode:
    """code 规范化"""

    def test_normalize_code_6digits(self, svc: FavoritesService):
        """'1' 应被补齐为 '000001'"""
        data = svc.add("1")
        assert "000001" in data["codes"]

    def test_normalize_code_invalid(self, svc: FavoritesService):
        """'abc' / '' 应抛 ValueError"""
        with pytest.raises(ValueError, match="\u80a1\u7968\u4ee3\u7801\u683c\u5f0f\u9519\u8bef"):
            svc.add("abc")
        with pytest.raises(ValueError):
            svc.add("")


class TestHas:
    """has() 方法"""

    def test_has_method(self, svc: FavoritesService):
        """has(code) 返回正确 bool"""
        svc.add("000001")
        assert svc.has("000001") is True
        assert svc.has("1") is True  # 也会被规范化
        assert svc.has("600000") is False


class TestUpdateNote:
    """update_note()"""

    def test_update_note_success(self, svc: FavoritesService):
        """更新已收藏 code 的备注"""
        svc.add("000001")
        item = svc.update_note("000001", "我的底仓")
        assert item["code"] == "000001"
        assert item["note"] == "\u6211\u7684\u5e95\u4ed3"

    def test_update_note_not_favorited(self, svc: FavoritesService):
        """未收藏的 code 抛 KeyError"""
        with pytest.raises(KeyError):
            svc.update_note("999999", "\u4e0d\u4f1a\u66f4\u65b0")


class TestAtomicWrite:
    """原子写 / 文件格式"""

    def test_atomic_rename_no_leftover(self, svc: FavoritesService):
        """写完后 .tmp 文件应被 os.replace 清理，不残留"""
        svc.add("000001")
        # 查找任何 .tmp 文件
        tmp_files = list(svc.file_path.parent.glob(f"{svc.file_path.name}.tmp"))
        assert len(tmp_files) == 0

    def test_file_format_indent_2(self, svc: FavoritesService):
        """文件 indent=2，git diff 友好"""
        svc.add("000001")
        content = svc.file_path.read_text(encoding="utf-8")
        # 应该有换行+缩进
        assert "\n  " in content  # 2 空格缩进
