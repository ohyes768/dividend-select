"""
收藏股票服务
负责股票收藏列表的加载、增删、持久化

数据存储: data/favorites.json
线程安全: threading.Lock (intra-process, 单 uvicorn worker 足够)
写入策略: 原子写（tmp + os.replace），防崩溃损坏
"""
import copy
import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class FavoritesService:
    """
    收藏股票服务（单例）

    JSON schema (v1):
    {
        "version": 1,
        "updated_at": "2026-07-01T12:34:56.789012",
        "codes": ["000001", "600000"],
        "items": [
            {"code": "000001", "added_at": "2026-06-15T08:00:00", "note": null}
        ],
        "notify": {"enabled": false, "rules": [], "last_notified_at": null}
    }

    未来扩展:
        v2 接入通知时，调用 subscribe() / mark_notified() 即可，favorites.json 已是唯一真相源。
    """

    # 单例
    _instance: Optional["FavoritesService"] = None
    _instance_lock = threading.Lock()

    # JSON schema 版本号（升级时 +1）
    SCHEMA_VERSION = 1

    def __init__(self, file_path: Optional[Path] = None):
        """
        Args:
            file_path: 收藏文件路径，None 则用 backend/dividend-select/data/favorites.json
        """
        if file_path is None:
            # src/services/favorites_service.py → 上 3 级 → backend/dividend-select/data/
            self.file_path = Path(__file__).parent.parent.parent / "data" / "favorites.json"
        else:
            self.file_path = file_path
        self._lock = threading.Lock()
        self._data: dict = {}
        self._ensure_loaded()

    @classmethod
    def get_instance(cls) -> "FavoritesService":
        """进程级单例（thread-safe）"""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（仅用于测试）"""
        with cls._instance_lock:
            cls._instance = None

    # ========== 公共 API（路由层调用） ==========

    def get_all(self) -> dict:
        """获取完整收藏数据（深拷贝返回，避免外部修改内部状态）"""
        with self._lock:
            return copy.deepcopy(self._data)

    def has(self, code: str) -> bool:
        """检查 code 是否在收藏中（O(1)）"""
        code = self._normalize_code(code)
        with self._lock:
            return code in self._data.get("codes", [])

    def add(self, code: str, note: Optional[str] = None) -> dict:
        """
        添加股票到收藏（幂等：已存在不重复加，note 已存在则更新）

        Returns:
            更新后的完整收藏数据
        """
        code = self._normalize_code(code)
        with self._lock:
            now_iso = datetime.now().isoformat()
            existing_idx = self._data["codes"].index(code) if code in self._data["codes"] else -1

            if existing_idx >= 0:
                # 已存在：仅当 note 非 None 时更新该 item
                if note is not None:
                    self._data["items"][existing_idx]["note"] = note
                    self._data["updated_at"] = now_iso
                    self._save()
                return copy.deepcopy(self._data)

            # 新增
            self._data["codes"].append(code)
            self._data["items"].append({
                "code": code,
                "added_at": now_iso,
                "note": note,
            })
            self._data["updated_at"] = now_iso
            self._save()
            return copy.deepcopy(self._data)

    def remove(self, code: str) -> dict:
        """
        从收藏中移除（幂等：不存在也直接返回）

        Returns:
            更新后的完整收藏数据
        """
        code = self._normalize_code(code)
        with self._lock:
            if code not in self._data["codes"]:
                return copy.deepcopy(self._data)
            self._data["codes"] = [c for c in self._data["codes"] if c != code]
            self._data["items"] = [it for it in self._data["items"] if it["code"] != code]
            self._data["updated_at"] = datetime.now().isoformat()
            self._save()
            return copy.deepcopy(self._data)

    def update_note(self, code: str, note: Optional[str]) -> dict:
        """
        更新单条收藏的备注

        Returns:
            更新后的 FavoriteItem dict

        Raises:
            ValueError: code 格式不合法
            KeyError: code 不在收藏中
        """
        code = self._normalize_code(code)
        with self._lock:
            if code not in self._data["codes"]:
                raise KeyError(f"{code} 不在收藏中")
            for item in self._data["items"]:
                if item["code"] == code:
                    item["note"] = note
                    break
            self._data["updated_at"] = datetime.now().isoformat()
            self._save()
            for item in self._data["items"]:
                if item["code"] == code:
                    return dict(item)
            raise KeyError(f"{code} 不在收藏中")  # 理论上不应触发

    # ========== v2 占位方法（通知功能接入时实现） ==========

    def subscribe(self, code: str, rule: dict) -> dict:
        """
        [v2] 为单只股票订阅一条通知规则。
        当前 v1 调用直接 raise NotImplementedError。
        """
        raise NotImplementedError("通知功能尚未实现，v2 接入")

    def mark_notified(self, codes: list) -> None:
        """
        [v2] 标记一批股票已发送过通知，更新 notify.last_notified_at。
        当前 v1 调用直接 raise NotImplementedError。
        """
        raise NotImplementedError("通知功能尚未实现，v2 接入")

    # ========== 内部方法 ==========

    @staticmethod
    def _normalize_code(code: str) -> str:
        """
        规范化股票代码：转 str、补齐 6 位、校验纯数字

        Raises:
            ValueError: code 为空、非数字或超过 6 位
        """
        if code is None:
            raise ValueError("code 不能为空")
        code_str = str(code).strip()
        if not code_str or not code_str.isdigit() or len(code_str) > 6:
            raise ValueError(f"股票代码格式错误: {code_str}")
        return code_str.zfill(6)

    def _ensure_loaded(self) -> None:
        """启动时加载文件到内存（含损坏恢复、版本校验、字段补齐）"""
        if not self.file_path.exists():
            logger.info(f"收藏文件不存在，初始化空结构: {self.file_path}")
            self._data = self._default_data()
            self._save()
            return

        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                self._data = json.load(f)
        except json.JSONDecodeError as e:
            # 损坏：备份 + 重新初始化
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_path = self.file_path.with_name(f".favorites.json.corrupt-{timestamp}")
            try:
                self.file_path.rename(backup_path)
                logger.error(
                    f"收藏文件 JSON 损坏，已备份至 {backup_path}: {e}",
                    exc_info=True,
                )
            except OSError as rename_err:
                logger.error(
                    f"收藏文件损坏且备份失败: rename_err={rename_err}, original_err={e}",
                    exc_info=True,
                )
            self._data = self._default_data()
            self._save()
            return

        # 版本校验（不静默回退）
        file_version = self._data.get("version")
        if file_version != self.SCHEMA_VERSION:
            raise RuntimeError(
                f"收藏文件 schema 版本 {file_version} 不被支持，"
                f"需要 {self.SCHEMA_VERSION}。请手动升级或删除文件后重启。"
            )

        # 字段补齐（兼容老 v1 文件缺字段）
        self._data.setdefault("updated_at", datetime.now().isoformat())
        self._data.setdefault("codes", [])
        self._data.setdefault("items", [])
        self._data.setdefault("notify", self._default_data()["notify"])

    def _default_data(self) -> dict:
        """v1 默认空结构"""
        return {
            "version": self.SCHEMA_VERSION,
            "updated_at": datetime.now().isoformat(),
            "codes": [],
            "items": [],
            "notify": {
                "enabled": False,
                "rules": [],
                "last_notified_at": None,
            },
        }

    def _save(self) -> None:
        """原子写：tmp 文件 + os.replace（防崩溃损坏）"""
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.file_path.with_name(self.file_path.name + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, self.file_path)
