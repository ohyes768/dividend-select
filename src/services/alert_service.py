"""
挡位监控服务

职责:
1. 扫描所有收藏 + 已配置 alerts 的股票，比对现价 vs 4 档价格
2. 触发的写入 alert_history.json（按日期分桶，每日每档最多记一次）
3. 调用 DingTalkNotifier 汇总推送 markdown

调用时机:
    每次 /api/dividend/realtime/refresh 刷新完股价后追加一次 check_all()，
    也可以通过 POST /api/dividend/favorites/alerts/check 手动触发。

数据源:
    - favorites_service.get_all()    → 收藏列表 + alerts 配置
    - m120_service.read_m120_with_deviation() → 现价（realtime / close）
    - pe_service.read_pe_data()      → 当前 PE（推送时展示）
    - data_reader (可选)             → 股票名称（m120/pe 数据源没名称）
"""
import json
import os
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from src.services.dingtalk_notifier import DingTalkNotifier
from src.services.favorites_service import FavoritesService
from src.services.m120_service import M120Service
from src.services.pe_service import PEDataService
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


# 档位元数据（顺序无关，每档独立判断）
# severity: 同方向命中多档时取最严重的
LEVEL_META = {
    "heavy_position":  {"label": "重仓档", "emoji": "🟢", "direction": "buy",  "severity": 2},
    "add_position":    {"label": "加仓档", "emoji": "🟡", "direction": "buy",  "severity": 1},
    "reduce_position": {"label": "减仓档", "emoji": "🟠", "direction": "sell", "severity": 1},
    "full_exit":       {"label": "全卖档", "emoji": "🔴", "direction": "sell", "severity": 2},
}


class AlertService:
    """
    挡位监控服务（单例，通过 init_alert_service() 在 main.py lifespan 初始化）
    """

    def __init__(
        self,
        favorites_service: FavoritesService,
        m120_service: M120Service,
        pe_service: PEDataService,
        data_reader: Optional[object] = None,
        notifier: Optional[DingTalkNotifier] = None,
        history_path: Optional[Path] = None,
    ):
        self.favorites = favorites_service
        self.m120 = m120_service
        self.pe = pe_service
        self.data_reader = data_reader
        self.notifier = notifier or DingTalkNotifier()
        self.history_path = history_path or (
            Path(__file__).parent.parent.parent / "data" / "alert_history.json"
        )
        self._lock = threading.Lock()
        self._history: dict = {"version": 1, "days": {}}
        self._load_history()

    # ========== 主入口 ==========

    def check_all(self) -> dict:
        """
        扫所有 alerts，比对现价，触发写历史 + 推钉钉。

        每日只调用一次（由 realtime/refresh 接口或 cron 触发），
        历史按日期分桶，天然防抖（每日每档最多记一次）。

        Returns:
            {
                "checked_at": ISO,
                "scanned": int,            # 扫描的股票数
                "triggered": list[dict],   # 命中的档位（已写历史）
                "pushed": bool,            # 钉钉是否推送成功
                "push_error": str | None,
            }
        """
        result = {
            "checked_at": datetime.now().isoformat(),
            "scanned": 0,
            "triggered": [],
            "pushed": False,
            "push_error": None,
        }

        try:
            data = self.favorites.get_all()
            realtime_data = self.m120.read_m120_with_deviation() or {}
            pe_data = self.pe.read_pe_data() or {}
            name_map = self._build_name_map(data["items"], realtime_data)

            today = date.today().isoformat()
            triggered = []

            for item in data["items"]:
                alerts = item.get("alerts")
                if not alerts or not alerts.get("enabled"):
                    continue
                levels = alerts.get("levels") or {}
                if not levels:
                    continue

                code = item["code"]
                rt = realtime_data.get(code)
                if not rt:
                    continue

                price = rt.get("realtime") or rt.get("close")
                if price is None or price <= 0:
                    continue

                result["scanned"] += 1

                hit = self._find_hit_level(price, levels)
                if hit is None:
                    continue

                # 防抖：今日此股此档已记过则跳过
                if self._already_recorded(today, code, hit["key"]):
                    continue

                triggered.append(
                    {
                        "code": code,
                        "name": name_map.get(code, code),
                        "level_key": hit["key"],
                        "level_label": LEVEL_META[hit["key"]]["label"],
                        "level_emoji": LEVEL_META[hit["key"]]["emoji"],
                        "direction": LEVEL_META[hit["key"]]["direction"],
                        "level_price": hit["price"],
                        "level_pe": hit["pe"],
                        "current_price": price,
                        "current_pe": pe_data.get(code, {}).get("pe") if pe_data else None,
                        "distance_pct": round((price - hit["price"]) / hit["price"] * 100, 2),
                        "strategy": alerts.get("strategy"),
                        "star_rating": alerts.get("star_rating"),
                        "doc_url": alerts.get("doc_url"),
                        "triggered_at": datetime.now().isoformat(),
                    }
                )
                self._record(today, code, hit["key"])

            # 推送
            if triggered:
                try:
                    result["pushed"] = self.notifier.send_alerts(triggered)
                except Exception as e:
                    result["push_error"] = str(e)
                    logger.error(f"推送钉钉失败: {e}", exc_info=True)

            result["triggered"] = triggered
            return result

        except Exception as e:
            logger.error(f"挡位检查失败: {e}", exc_info=True)
            result["push_error"] = str(e)
            return result

    # ========== 状态查询 ==========

    def get_today_records(self) -> list:
        """今日触发记录列表"""
        today = date.today().isoformat()
        with self._lock:
            return list(self._history.get("days", {}).get(today, []))

    def get_records_by_date(self, day_iso: str) -> list:
        """指定日期的触发记录"""
        with self._lock:
            return list(self._history.get("days", {}).get(day_iso, []))

    def cleanup_old_history(self, keep_days: int = 30) -> int:
        """删除超过 keep_days 天的历史，返回删除的天数"""
        cutoff = (date.today() - timedelta(days=keep_days)).isoformat()
        with self._lock:
            days = self._history.setdefault("days", {})
            removed = [d for d in days if d < cutoff]
            for d in removed:
                del days[d]
            if removed:
                self._save_history_locked()
        return len(removed)

    # ========== 内部方法 ==========

    def _find_hit_level(self, price: float, levels: dict) -> Optional[dict]:
        """
        找最严重的命中档位（一次只命中一个，先卖后买）。

        - 卖出方向：现价 >= 档位价 → 取 severity 最高的（全卖 > 减仓）
        - 买入方向：现价 <= 档位价 → 取 severity 最高的（重仓 > 加仓）
        - 同次扫描只返回一个（卖优先于买，避免同时给出买卖信号）
        """
        sell_hits = []
        buy_hits = []

        for key, meta in LEVEL_META.items():
            level = levels.get(key)
            if not level or not level.get("price"):
                continue
            try:
                level_price = float(level["price"])
            except (TypeError, ValueError):
                continue
            level_pe_raw = level.get("pe")
            level_pe = float(level_pe_raw) if isinstance(level_pe_raw, (int, float)) else None

            if meta["direction"] == "sell" and price >= level_price:
                sell_hits.append(
                    {"key": key, "price": level_price, "pe": level_pe, "severity": meta["severity"]}
                )
            elif meta["direction"] == "buy" and price <= level_price:
                buy_hits.append(
                    {"key": key, "price": level_price, "pe": level_pe, "severity": meta["severity"]}
                )

        if sell_hits:
            return max(sell_hits, key=lambda x: x["severity"])
        if buy_hits:
            return max(buy_hits, key=lambda x: x["severity"])
        return None

    def _build_name_map(self, items: list, realtime_data: dict) -> dict:
        """从 data_reader / favorites items 构造 code → name 映射"""
        name_map: dict[str, str] = {}
        # 1. data_reader 有完整股票列表（含 name）则优先
        if self.data_reader is not None:
            try:
                method = getattr(self.data_reader, "get_all_stocks", None)
                if callable(method):
                    stocks = method()
                    for s in stocks:
                        if isinstance(s, dict):
                            n = s.get("name")
                            if n:
                                name_map[str(s.get("code", "")).zfill(6)] = n
            except Exception:
                pass
        # 2. favorites items 没有 name 字段，跳过
        return name_map

    def _already_recorded(self, today: str, code: str, level_key: str) -> bool:
        with self._lock:
            today_records = self._history.get("days", {}).get(today, [])
            for record in today_records:
                if record.get("code") == code and record.get("level_key") == level_key:
                    return True
            return False

    def _record(self, today: str, code: str, level_key: str) -> None:
        with self._lock:
            days = self._history.setdefault("days", {})
            days.setdefault(today, []).append(
                {
                    "code": code,
                    "level_key": level_key,
                    "recorded_at": datetime.now().isoformat(),
                }
            )
            self._save_history_locked()

    def _load_history(self) -> None:
        if not self.history_path.exists():
            self._history = {"version": 1, "days": {}}
            return
        try:
            with open(self.history_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict) or "days" not in loaded:
                raise ValueError("alert_history.json 结构异常")
            self._history = loaded
        except Exception as e:
            logger.error(f"alert_history.json 损坏，重新初始化: {e}")
            backup = self.history_path.with_name(
                f".alert_history.json.corrupt-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            )
            try:
                self.history_path.rename(backup)
            except OSError:
                pass
            self._history = {"version": 1, "days": {}}

    def _save_history_locked(self) -> None:
        """调用方必须已持有 self._lock"""
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.history_path.with_suffix(".json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self._history, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, self.history_path)


# ========== 全局单例管理（与 pe_service.py 一致的模式） ==========

_alert_service: Optional[AlertService] = None


def init_alert_service(
    favorites_service: FavoritesService,
    m120_service: M120Service,
    pe_service: PEDataService,
    data_reader: Optional[object] = None,
    notifier: Optional[DingTalkNotifier] = None,
) -> AlertService:
    """在 main.py lifespan 中调用一次，初始化全局 AlertService"""
    global _alert_service
    _alert_service = AlertService(
        favorites_service=favorites_service,
        m120_service=m120_service,
        pe_service=pe_service,
        data_reader=data_reader,
        notifier=notifier,
    )
    return _alert_service


def get_alert_service() -> AlertService:
    """路由层拿 AlertService 的入口"""
    if _alert_service is None:
        raise RuntimeError("AlertService 尚未初始化，请检查 main.py lifespan")
    return _alert_service
