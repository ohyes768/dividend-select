"""
AlertService 触发逻辑单元测试

只测纯逻辑：_find_hit_level（最严重档位选择），不依赖 FastAPI / 文件 IO / 网络。
"""
from datetime import date
from pathlib import Path
from typing import Optional

import pytest

from src.services.alert_service import AlertService, LEVEL_META


class _DummyFavorites:
    def get_all(self):
        return {"items": [], "codes": []}


class _DummyM120:
    def read_m120_with_deviation(self):
        return {}


class _DummyPE:
    def read_pe_data(self):
        return {}


class _DummyNotifier:
    def __init__(self):
        self.sent = []

    def send_alerts(self, triggered):
        self.sent.append(triggered)
        return True


def _make_service(tmp_path: Path) -> AlertService:
    """构造一个不依赖 favorites/m120/pe 数据的 AlertService，只测内部逻辑"""
    return AlertService(
        favorites_service=_DummyFavorites(),
        m120_service=_DummyM120(),
        pe_service=_DummyPE(),
        data_reader=None,
        notifier=_DummyNotifier(),
        history_path=tmp_path / "alert_history.json",
    )


# ========== _find_hit_level ==========


def test_no_levels_returns_none(tmp_path):
    svc = _make_service(tmp_path)
    assert svc._find_hit_level(10.0, {}) is None


def test_buy_trigger_heavy(tmp_path):
    """现价 <= 重仓价 → 命中重仓档（severity 最高）"""
    svc = _make_service(tmp_path)
    levels = {
        "heavy_position":  {"price": 9.0, "pe": 5.0},
        "add_position":    {"price": 10.0, "pe": 6.0},
        "reduce_position": {"price": 12.0, "pe": 8.0},
        "full_exit":       {"price": 14.0, "pe": 10.0},
    }
    # 现价 8.5 同时 ≤ 9.0 和 10.0 → 应取 severity=2 的 heavy
    hit = svc._find_hit_level(8.5, levels)
    assert hit is not None
    assert hit["key"] == "heavy_position"
    assert hit["price"] == 9.0
    assert hit["pe"] == 5.0


def test_buy_trigger_add_only(tmp_path):
    """现价 ≤ 加仓但 > 重仓 → 命中加仓"""
    svc = _make_service(tmp_path)
    levels = {
        "heavy_position":  {"price": 9.0},
        "add_position":    {"price": 10.0},
        "reduce_position": {"price": 12.0},
        "full_exit":       {"price": 14.0},
    }
    hit = svc._find_hit_level(9.5, levels)
    assert hit is not None
    assert hit["key"] == "add_position"


def test_sell_trigger_full_exit(tmp_path):
    """现价 ≥ 全卖价 → 命中全卖档（severity 最高）"""
    svc = _make_service(tmp_path)
    levels = {
        "heavy_position":  {"price": 9.0},
        "add_position":    {"price": 10.0},
        "reduce_position": {"price": 12.0},
        "full_exit":       {"price": 14.0},
    }
    # 现价 14.5 同时 ≥ 12 和 14 → 取 severity=2 的 full_exit
    hit = svc._find_hit_level(14.5, levels)
    assert hit is not None
    assert hit["key"] == "full_exit"


def test_sell_takes_priority_over_buy(tmp_path):
    """同时命中买卖时，卖优先（先止盈再加仓）"""
    svc = _make_service(tmp_path)
    levels = {
        "heavy_position":  {"price": 100.0},  # 现价 50 < 100 命中 buy
        "add_position":    {"price": 80.0},   # 现价 50 < 80 命中 buy
        "reduce_position": {"price": 40.0},   # 现价 50 > 40 命中 sell
        # 不配 full_exit，避免 reduce 被 severity 盖过
    }
    hit = svc._find_hit_level(50.0, levels)
    assert hit is not None
    assert hit["key"] == "reduce_position"  # 卖优先于买


def test_no_trigger_in_middle(tmp_path):
    """现价处于加仓和减仓之间 → 不触发"""
    svc = _make_service(tmp_path)
    levels = {
        "heavy_position":  {"price": 9.0},
        "add_position":    {"price": 10.0},
        "reduce_position": {"price": 12.0},
        "full_exit":       {"price": 14.0},
    }
    assert svc._find_hit_level(11.0, levels) is None


def test_partial_levels_only_buy(tmp_path):
    """只配置了买入档位时的触发"""
    svc = _make_service(tmp_path)
    levels = {
        "heavy_position": {"price": 9.0},
        "add_position":   {"price": 10.0},
    }
    hit = svc._find_hit_level(9.5, levels)
    assert hit is not None
    assert hit["key"] == "add_position"


def test_invalid_price_skipped(tmp_path):
    """price=0 / None / 负数 → 跳过"""
    svc = _make_service(tmp_path)
    levels = {
        "heavy_position":  {"price": 0},
        "add_position":    {"price": None},
        "reduce_position": {"price": -1},
        "full_exit":       {"price": 14.0},
    }
    # 现价 15 ≥ 14 命中 full_exit，其他都被跳过
    hit = svc._find_hit_level(15.0, levels)
    assert hit is not None
    assert hit["key"] == "full_exit"


def test_equal_price_triggers(tmp_path):
    """现价 == 档位价也算命中（>= / <=）"""
    svc = _make_service(tmp_path)
    levels = {
        "add_position":    {"price": 10.0},
        "reduce_position": {"price": 12.0},
    }
    # 现价 10 ≤ 10 → 加仓命中
    assert svc._find_hit_level(10.0, levels)["key"] == "add_position"
    # 现价 12 ≥ 12 → 减仓命中
    assert svc._find_hit_level(12.0, levels)["key"] == "reduce_position"


# ========== 历史防抖 ==========


def test_already_recorded_same_day(tmp_path):
    """同一日同一档位不重复记录"""
    svc = _make_service(tmp_path)
    today = date.today().isoformat()
    assert not svc._already_recorded(today, "000001", "heavy_position")
    svc._record(today, "000001", "heavy_position")
    assert svc._already_recorded(today, "000001", "heavy_position")


def test_different_level_same_day_allowed(tmp_path):
    """同一日不同档位可以分别记录"""
    svc = _make_service(tmp_path)
    today = date.today().isoformat()
    svc._record(today, "000001", "heavy_position")
    assert not svc._already_recorded(today, "000001", "add_position")
    svc._record(today, "000001", "add_position")
    assert svc._already_recorded(today, "000001", "add_position")


def test_different_code_same_day_allowed(tmp_path):
    """同一日不同股票可以分别记录"""
    svc = _make_service(tmp_path)
    today = date.today().isoformat()
    svc._record(today, "000001", "heavy_position")
    assert not svc._already_recorded(today, "000002", "heavy_position")


def test_history_persistence(tmp_path):
    """历史文件保存后能再次加载"""
    svc1 = _make_service(tmp_path)
    today = date.today().isoformat()
    svc1._record(today, "000001", "heavy_position")
    svc1._save_history_locked()

    # 重新加载
    svc2 = _make_service(tmp_path)
    assert svc2._already_recorded(today, "000001", "heavy_position")


def test_cleanup_old_history(tmp_path):
    """清理超过 N 天的历史"""
    svc = _make_service(tmp_path)
    # 写一条 100 天前的记录
    old_day = "2020-01-01"
    svc._record(old_day, "000001", "heavy_position")
    assert svc._already_recorded(old_day, "000001", "heavy_position")

    removed = svc.cleanup_old_history(keep_days=30)
    assert removed == 1
    assert not svc._already_recorded(old_day, "000001", "heavy_position")


# ========== LEVEL_META 完整性 ==========


def test_level_meta_keys():
    """4 档元数据完整"""
    assert set(LEVEL_META.keys()) == {
        "heavy_position",
        "add_position",
        "reduce_position",
        "full_exit",
    }


def test_level_meta_directions():
    """2 买 2 卖"""
    buys = [k for k, m in LEVEL_META.items() if m["direction"] == "buy"]
    sells = [k for k, m in LEVEL_META.items() if m["direction"] == "sell"]
    assert len(buys) == 2
    assert len(sells) == 2
