"""A 股交易日历判断（akshare 拉取 + 本地缓存）"""

import json
from datetime import date, timedelta
from pathlib import Path

import akshare as ak

from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# 缓存路径（相对工作目录）
_DEFAULT_CACHE_PATH = Path("data/trading_calendar_cache.json")
_CACHE_TTL_DAYS = 30


def is_trading_day(d: date | None = None, cache_path: Path | None = None) -> bool:
    """判断给定日期（默认今天）是否 A 股交易日。

    降级策略：
    - 缓存有效 → 直接用
    - 缓存过期 → 尝试刷新；拉失败时退回旧缓存
    - 无缓存 + 拉取失败 → 返回 True + warn（宁错杀不放过）
    """
    d = d or date.today()
    path = Path(cache_path) if cache_path else _DEFAULT_CACHE_PATH
    cal = _load_or_refresh(path)
    if cal is None:
        logger.warning("交易日历不可用，默认按交易日处理")
        return True
    return d.isoformat() in cal


def _load_or_refresh(cache_path: Path) -> set[str] | None:
    """返回交易日日期字符串集合（YYYY-MM-DD）。失败返回 None。"""
    cache = _load_cache(cache_path)
    today = date.today()

    # 缓存有效
    if cache is not None:
        cached_at_str = cache.get("cached_at")
        dates_list = cache.get("dates", [])
        if cached_at_str and dates_list:
            try:
                cached_at = date.fromisoformat(cached_at_str)
                if (today - cached_at).days < _CACHE_TTL_DAYS:
                    return set(dates_list)
            except ValueError:
                pass  # cached_at 损坏，走刷新

    # 刷新
    fresh_dates = _fetch_from_akshare()
    if fresh_dates is not None:
        _save_cache(cache_path, fresh_dates)
        return fresh_dates

    # 拉失败时退回旧缓存（即使过期）
    if cache is not None and cache.get("dates"):
        logger.warning("akshare 拉取失败，使用过期缓存")
        return set(cache["dates"])

    return None


def _load_cache(cache_path: Path) -> dict | None:
    try:
        if not cache_path.exists():
            return None
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"读取交易日历缓存失败: {e}")
        return None


def _save_cache(cache_path: Path, dates: set[str]) -> None:
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "cached_at": date.today().isoformat(),
            "dates": sorted(dates),
        }
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"写入交易日历缓存失败: {e}")


def _fetch_from_akshare() -> set[str] | None:
    """从 akshare 拉取交易日历。失败返回 None。"""
    try:
        # tool_trade_date_hist_sina 返回 DataFrame，列名 trade_date，每行一个 Timestamp
        df = ak.tool_trade_date_hist_sina()
        if df is None or df.empty:
            logger.warning("akshare 返回空交易日历")
            return None
        # 兼容列名差异
        col = "trade_date" if "trade_date" in df.columns else df.columns[0]
        dates = set()
        for v in df[col]:
            try:
                if hasattr(v, "strftime"):
                    dates.add(v.strftime("%Y-%m-%d"))
                else:
                    # 字符串 / 其他
                    dates.add(str(v)[:10])
            except Exception:
                continue
        logger.info(f"交易日历拉取成功，共 {len(dates)} 个交易日")
        return dates
    except Exception as e:
        logger.warning(f"akshare 拉取交易日历失败: {e}")
        return None
