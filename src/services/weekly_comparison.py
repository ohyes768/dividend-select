"""
周排名对比服务：存档与对比计算
"""
import csv
from pathlib import Path
from typing import Optional


# 假设与 routes.py 相同的 PROJECT_ROOT
PROJECT_ROOT = Path(__file__).parent.parent.parent
SNAPSHOT_DIR = PROJECT_ROOT / "data" / "snapshots"

# 同一周内多次调 API 时，只在距上次 snapshot 至少 5 天才存档（保证周对比）
SNAPSHOT_MIN_INTERVAL_DAYS = 5


def _get_snapshot_path(date_str: str) -> Path:
    """获取指定日期的 snapshot 文件路径"""
    return SNAPSHOT_DIR / f"rankings_{date_str}.csv"


def should_save_snapshot(today_str: str) -> bool:
    """判断今天是否应该保存 snapshot。
    同一周内多次调 API，只在距上次 snapshot >= 5 天时才存档。
    """
    if not SNAPSHOT_DIR.exists():
        return True
    csv_files = sorted(SNAPSHOT_DIR.glob("rankings_*.csv"), reverse=True)
    if not csv_files:
        return True
    from datetime import datetime
    try:
        d_today = datetime.strptime(today_str, "%Y-%m-%d")
    except ValueError:
        return True
    for f in csv_files:
        # 从文件名 rankings_2026-06-05.csv 提取日期
        date_part = f.stem.replace("rankings_", "")
        try:
            d_prev = datetime.strptime(date_part, "%Y-%m-%d")
            delta = (d_today - d_prev).days
            # 跳过今天/未来，找到最近一个已保存的
            if delta < 0:
                continue
            return delta >= SNAPSHOT_MIN_INTERVAL_DAYS
        except ValueError:
            continue
    return True


def _get_previous_snapshot_path(today_str: Optional[str] = None) -> Optional[Path]:
    """获取最近一周的 snapshot 文件路径（按文件名倒序，跳过今天）
       today_str: 今天日期 YYYY-MM-DD，用于排除今天刚保存的 snapshot
    """
    if not SNAPSHOT_DIR.exists():
        return None
    csv_files = sorted(SNAPSHOT_DIR.glob("rankings_*.csv"), reverse=True)
    for f in csv_files:
        # 跳过今天的文件
        if today_str and f.name == f"rankings_{today_str}.csv":
            continue
        return f
    return None


def save_snapshot(top_curr: list, top_3y: list, date_str: str, ratio_map: dict,
                  full_yield_map: dict = None, full_3y_map: dict = None) -> None:
    """
    保存本周排名快照到 CSV。
    写入**全部股票**（不只 TOP10）的完整排名，让下周可以算出任意股票的排名变动（包括 #89 → #88）。

    top_curr: 实时股息率TOP10列表
    top_3y: 近3年均值TOP10列表
    date_str: 本周日期 YYYY-MM-DD
    ratio_map: 所有股票的 M120比值 {股票名称: ratio}
    full_yield_map: 所有股票的实时股息率 {股票名称: yield_curr}（用于算全量排名）
    full_3y_map: 所有股票的近3年均值 {股票名称: yield_3y_avg}（用于算全量排名）
    """
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = _get_snapshot_path(date_str)

    full_yield_map = full_yield_map or {}
    full_3y_map = full_3y_map or {}

    # 计算全量实时股息率排名
    sorted_yield = sorted(
        [(name, y) for name, y in full_yield_map.items() if y is not None],
        key=lambda x: x[1],
        reverse=True,
    )
    yield_rank_map = {name: i+1 for i, (name, _) in enumerate(sorted_yield)}

    # 计算全量近3年均值排名
    sorted_3y = sorted(
        [(name, y) for name, y in full_3y_map.items() if y is not None],
        key=lambda x: x[1],
        reverse=True,
    )
    rank_3y_map = {name: i+1 for i, (name, _) in enumerate(sorted_3y)}

    # 计算 M120比值排名（从 ratio_map 整体算）
    sorted_by_ratio = sorted(
        [(name, ratio) for name, ratio in ratio_map.items() if ratio is not None],
        key=lambda x: x[1],
        reverse=True,
    )
    ratio_rank_map = {name: i+1 for i, (name, _) in enumerate(sorted_by_ratio)}

    # 写全部股票
    all_names = sorted(
        set(ratio_map.keys()) | set(yield_rank_map.keys()) | set(rank_3y_map.keys())
    )
    rows = []
    for name in all_names:
        rows.append({
            "股票名称": name,
            "实时股息率": full_yield_map.get(name),
            "M120比值": ratio_map.get(name),
            "实时股息率排名": yield_rank_map.get(name),
            "近3年均值排名": rank_3y_map.get(name),
            "M120比值排名": ratio_rank_map.get(name),
        })

    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["股票名称", "实时股息率", "M120比值", "实时股息率排名", "近3年均值排名", "M120比值排名"])
        writer.writeheader()
        writer.writerows(rows)


def load_previous_snapshot(today_str: Optional[str] = None) -> Optional[dict]:
    """
    读取最近一周的 snapshot，返回 dict:
    {股票名称: {yield_curr, ratio, rank_ry, rank_ratio}}

    today_str: 今天日期 YYYY-MM-DD，用于排除今天刚保存的 snapshot

    如果没有历史文件，返回 None。
    """
    prev_path = _get_previous_snapshot_path(today_str)
    if prev_path is None:
        return None

    result = {}
    with open(prev_path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name = row["股票名称"].strip()
            result[name] = {
                "yield_curr": float(row["实时股息率"]) if row.get("实时股息率") else None,
                "ratio": float(row["M120比值"]) if row.get("M120比值") else None,
                "rank_ry": int(row["实时股息率排名"]) if row.get("实时股息率排名") else None,
                "rank_3y": int(row["近3年均值排名"]) if row.get("近3年均值排名") else None,
                "rank_ratio": int(row["M120比值排名"]) if row.get("M120比值排名") else None,
            }
    return result


def compute_changes(top_curr: list, top_3y: list, prev: Optional[dict]) -> tuple:
    """
    给 top_curr 和 top_3y 每条记录追加排名变动字段。

    prev: load_previous_snapshot() 的返回值，或 None

    返回: (top_curr_enriched, top_3y_enriched)
    每条记录追加:
      - prev_rank_ry, rank_delta_ry
      - prev_rank_ratio, rank_delta_ratio
    """
    def _delta(curr_rank, prev_rank):
        if prev_rank is None or curr_rank is None:
            return None
        return prev_rank - curr_rank  # 正数=上升（排名数字变小）

    def _format_delta(delta):
        if delta is None:
            return None
        if delta > 0:
            return f"↑{delta}"
        elif delta < 0:
            return f"↓{abs(delta)}"
        else:
            return "—"

    def _format_ratio_delta(curr_ratio, prev_ratio):
        """M120比值变动：显示 ±0.05 格式"""
        if curr_ratio is None or prev_ratio is None:
            return None
        delta = round(curr_ratio - prev_ratio, 3)
        if abs(delta) < 0.001:
            return "—"
        if delta > 0:
            return f"+{delta:.3f}"
        else:
            return f"{delta:.3f}"

    # 构建 name -> ratio_rank 映射（从 top_curr+top_3y 整体算）
    all_by_ratio = {}
    for r in top_curr + top_3y:
        if r.get("ratio") is not None:
            all_by_ratio[r["name"]] = r["ratio"]
    sorted_ratio = sorted(all_by_ratio.items(), key=lambda x: x[1], reverse=True)
    ratio_rank = {name: i+1 for i, (name, _) in enumerate(sorted_ratio)}

    # enrich top_curr
    top_curr_enr = []
    for r in top_curr:
        name = r["name"]
        p = prev.get(name) if prev else {}
        prev_ry = p.get("rank_ry") if p else None
        prev_ratio = p.get("ratio") if p else None
        prev_ratio_rank = p.get("rank_ratio") if p else None
        delta_ry = _delta(r["rank"], prev_ry)
        ratio_delta_display = _format_ratio_delta(r.get("ratio"), prev_ratio)
        top_curr_enr.append({
            **r,
            "prev_rank_ry": prev_ry,
            "rank_delta_ry": delta_ry,
            "rank_delta_ry_display": _format_delta(delta_ry),
            "is_new_ry": prev_ry is None,
            "prev_ratio": prev_ratio,
            "ratio_delta_display": ratio_delta_display,
            "is_new_ratio": prev_ratio is None,
        })

    # enrich top_3y
    top_3y_enr = []
    for r in top_3y:
        name = r["name"]
        p = prev.get(name) if prev else {}
        prev_ry = p.get("rank_ry") if p else None
        prev_ratio = p.get("ratio") if p else None
        ratio_delta_display = _format_ratio_delta(r.get("ratio"), prev_ratio)
        # 实时排名变动：本周实时排名 vs 上周实时排名
        rank_realtime = r.get("rank_realtime")
        delta_realtime = _delta(rank_realtime, prev_ry)
        top_3y_enr.append({
            **r,
            "prev_rank_realtime": prev_ry,
            "rank_delta_realtime": delta_realtime,
            "rank_delta_realtime_display": _format_delta(delta_realtime),
            "is_new_realtime": prev_ry is None,
            "prev_ratio": prev_ratio,
            "ratio_delta_display": ratio_delta_display,
            "is_new_ratio": prev_ratio is None,
        })

    return top_curr_enr, top_3y_enr