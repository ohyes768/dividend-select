"""
东财 emweb 板块 fetcher
数据源: https://emweb.eastmoney.com/PC_HSF10/CoreConception/PageAjax
替代 efinance.get_base_info / efinance.get_belong_board

为什么不用 efinance:
- 调 push2.eastmoney.com/api/qt/slist/get，频繁被本机 IP 段封
- 创业板/科创板 secid 解析常挂
- 单只 1s+，144 只需 2-3 分钟

为什么不用 slist/get:
- 实测返回 {rc: 102, data: null}，对单只股票无数据

实测 emweb.eastmoney.com/PC_HSF10/CoreConception/PageAjax:
- 10/10 全部 200 OK
- 单只 ~200ms
- 返回 GBK 编码的 JSON（含 ssbk 数组，每只股票 28-34 个板块）
- 无需 cookie/token
"""
import json
import re
import time
from pathlib import Path
from typing import List, Set, Tuple

import requests

from ..utils.helpers import DATA_DIR, setup_logger

logger = setup_logger(__name__)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0"
REFERER = "https://emweb.eastmoney.com/PC_HSF10/CoreConception/Index?type=web&code="
SLIST_URL = "https://emweb.eastmoney.com/PC_HSF10/CoreConception/PageAjax"

# 模块级 Session（连接复用，避免每只股票重新 TLS 握手）
_session: requests.Session | None = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": UA})
    return _session

# 动态标签（直接丢弃）
DYNAMIC_TAGS: Set[str] = {
    "昨日涨停", "昨日高振幅", "昨日高换手", "昨日涨停_含一字",
    "昨日首板", "最近多板", "今日涨停", "连板", "炸板",
    "地天板", "天地板", "昨日连板",
}

# 后缀/特征直接丢弃（指数/地域/风格/交易特征）
DROP_SUFFIX_PATTERNS = [
    re.compile(r"^.*_$"),                # 以 _ 结尾（指数成分，如 HS300_）
    re.compile(r".*(富时罗素|标准普尔|MSCI).*"),
    re.compile(r".*(沪股通|深股通).*"),
    re.compile(r".*(融资融券|证金持股|机构重仓).*"),
    re.compile(r".*板块$"),              # 地域板块
    re.compile(r".*(风格|大盘股|权重股|行业龙头|价值股|百元股).*"),
]

# 申万行业关键词（从 sw-mapping CSV 加载，缓存）
_sw_industry_keywords: Set[str] = set()


def _load_sw_industry_keywords() -> Set[str]:
    """从 sw-mapping CSV 加载申万一二三级行业名作为关键词字典"""
    global _sw_industry_keywords
    if _sw_industry_keywords:
        return _sw_industry_keywords
    matches = sorted(Path(DATA_DIR).glob("个股申万行业映射_*.csv"), reverse=True)
    if not matches:
        return _sw_industry_keywords
    try:
        import pandas as pd
        df = pd.read_csv(matches[0], encoding="utf-8-sig", dtype=str)
        for col in ["一级行业", "二级行业", "三级行业"]:
            if col in df.columns:
                values = df[col].dropna().unique()
                for v in values:
                    if v and v.strip() and v != "nan":
                        _sw_industry_keywords.add(v.strip())
        logger.debug(f"加载申万关键词 {len(_sw_industry_keywords)} 个 from {matches[0].name}")
    except Exception as e:
        logger.warning(f"加载申万关键词失败: {e}")
    return _sw_industry_keywords


def _is_drop(board_name: str) -> bool:
    """是否应直接丢弃（指数/地域/风格/交易特征）"""
    if board_name in DYNAMIC_TAGS:
        return True
    for pat in DROP_SUFFIX_PATTERNS:
        if pat.match(board_name):
            return True
    return False


def _classify(board_name: str, is_precise) -> str:
    """分类: 'concept' | 'industry' | 'skip'"""
    if _is_drop(board_name):
        return "skip"
    # emweb 返回 IS_PRECISE 是字符串 "0"/"1" 或 null；统一转字符串比较
    if str(is_precise) == "1":
        return "concept"
    sw_keywords = _load_sw_industry_keywords()
    if board_name in sw_keywords:
        return "industry"
    # 模糊匹配二级/三级（Ⅱ vs II 罗马数字）
    for kw in sw_keywords:
        if kw and (kw.replace("Ⅱ", "II") == board_name or kw.replace("II", "Ⅱ") == board_name):
            return "industry"
    return "concept"  # 默认归为概念


def _to_secid(code: str) -> str:
    """6位代码 → 东财 secid 前缀（SH/SZ/BJ）

    注意：不能用 `"04" in first` 写法（首位 '0' 是深圳 SZ，不是北交所 BJ）
    - 4/8 开头 → 北交所 BJ
    - 6/9/5/7 开头 → 上海 SH
    - 0/1/2/3 开头 → 深圳 SZ
    """
    first = code[0]
    if first in ("4", "8"):
        return f"BJ{code}"
    if first in ("6", "9", "5", "7"):
        return f"SH{code}"
    return f"SZ{code}"


def fetch_boards_for_stock(code: str, max_retries: int = 3, timeout: int = 15) -> Tuple[List[str], List[str]]:
    """
    获取单只股票的板块信息。

    Args:
        code: 6位股票代码
        max_retries: 最大重试次数（指数退避）
        timeout: 单次请求超时（秒）

    Returns:
        (概念板块列表, 行业板块列表) - 任一失败返回 ([], [])
    """
    secid = _to_secid(code)
    session = _get_session()
    params = {"code": secid}
    # Referer 每次都不同（不同 secid），单独传
    referer = f"{REFERER}{secid}"

    ssbk: List[dict] = []
    for attempt in range(max_retries):
        try:
            resp = session.get(SLIST_URL, params=params, headers={"Referer": referer}, timeout=timeout)
            raw = resp.content
            if raw.startswith(b"\xef\xbb\xbf"):
                raw = raw[3:]
            # emweb header 撒谎为 utf-8，实际内容可能是 GBK；用 errors="replace" 容错
            text = raw.decode("utf-8", errors="replace")
            data = json.loads(text)
            ssbk = data.get("ssbk") or []
            break
        except (requests.RequestException, json.JSONDecodeError) as e:
            if attempt == max_retries - 1:
                logger.debug(f"fetch {code} 失败: {e}")
                return [], []
            time.sleep(2 ** attempt)
    else:
        return [], []

    concepts: List[str] = []
    industries: List[str] = []
    for item in ssbk:
        name = (item.get("BOARD_NAME") or "").strip()
        if not name:
            continue
        kind = _classify(name, item.get("IS_PRECISE"))
        if kind == "concept":
            concepts.append(name)
        elif kind == "industry":
            industries.append(name)
    return concepts, industries