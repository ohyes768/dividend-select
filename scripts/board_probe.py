"""临时探测脚本：批量验证 A~F 候选方案是否能跑通板块查询。"""
import json
import time
import sys

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0"
REFERER = "https://quote.eastmoney.com/"


def hr(title):
    print(f"\n===== {title} =====", flush=True)


def eastmoney_industry_name():
    """东方财富 push2 行业板块列表"""
    hr("A1. eastmoney push2 行业板块列表")
    url = "https://17.push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1", "pz": "100", "po": "1", "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2", "invt": "2", "fid": "f3",
        "fs": "m:90 t:2 f:!50",
        "fields": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f26,f22,f33,f11,f62,f128,f136,f115,f152,f124,f107,f104,f105,f140,f141,f207,f208,f209,f222",
    }
    r = requests.get(url, params=params, headers={"User-Agent": UA, "Referer": REFERER}, timeout=15)
    data = r.json()
    rows = (data.get("data") or {}).get("diff") or []
    print(f"status={r.status_code} rc={data.get('rc')} total={len(rows)}")
    if rows:
        sample = rows[0]
        # f12=板块代码, f14=板块名称
        print("sample:", {"f12": sample.get("f12"), "f14": sample.get("f14")})
    return rows


def eastmoney_concept_name():
    """东方财富 push2 概念板块列表"""
    hr("A2. eastmoney push2 概念板块列表")
    url = "https://17.push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1", "pz": "200", "po": "1", "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2", "invt": "2", "fid": "f3",
        "fs": "m:90 t:3 f:!50",
        "fields": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f26,f22,f33,f11,f62,f128,f136,f115,f152,f124,f107,f104,f105,f140,f141,f207,f208,f209,f222",
    }
    r = requests.get(url, params=params, headers={"User-Agent": UA, "Referer": REFERER}, timeout=15)
    data = r.json()
    rows = (data.get("data") or {}).get("diff") or []
    print(f"status={r.status_code} rc={data.get('rc')} total={len(rows)}")
    if rows:
        print("sample:", {"f12": rows[0].get("f12"), "f14": rows[0].get("f14")})
    return rows


def eastmoney_concept_cons(board_code):
    """某概念板块下的成分股"""
    hr(f"A3. eastmoney push2 概念成分股(b:{board_code})")
    url = "https://29.push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1", "pz": "200", "po": "1", "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2", "invt": "2", "fid": "f3",
        "fs": f"b:{board_code} f:!50",
        "fields": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f22,f11,f62,f128,f136,f115,f152,f45",
    }
    r = requests.get(url, params=params, headers={"User-Agent": UA, "Referer": REFERER}, timeout=15)
    data = r.json()
    rows = (data.get("data") or {}).get("diff") or []
    print(f"status={r.status_code} rc={data.get('rc')} total={len(rows)}")
    if rows:
        print("sample:", {"f12": rows[0].get("f12"), "f14": rows[0].get("f14")})
    return rows


def eastmoney_stock_panel(stock_code):
    """个股 F10 板块信息（f100/f102 关联板块）
    URL: https://emweb.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax?code=SH600519
    """
    hr(f"D1. eastmoney F10 stock panel: {stock_code}")
    # 600519 SH; 000001 SZ
    secid = stock_code
    url = f"https://emweb.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax"
    params = {"code": secid}
    r = requests.get(url, params=params, headers={"User-Agent": UA, "Referer": f"https://emweb.eastmoney.com/PC_HSF10/CompanySurvey/Index?type=web&code={secid}"}, timeout=15)
    print(f"status={r.status_code} len={len(r.text)}")
    # 试图找板块名
    import re
    names = set(re.findall(r"[\u4e00-\u9fa5]{2,15}板块", r.text))
    print("命中*板块 关键词:", list(names)[:10])
    return r.text[:2000]


def sina_industry_list():
    hr("E1. sina industry list (industry_1_2)")
    # 行业分类树根
    url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
    params = {"node": "industry_1_2", "sort": "code", "asc": "0", "num": "100", "_s_r_a": "page"}
    r = requests.get(url, params=params, headers={"User-Agent": UA, "Referer": "https://vip.stock.finance.sina.com.cn/"}, timeout=15)
    print(f"status={r.status_code} len={len(r.text)}")
    print(r.text[:500])
    return r.text


def sina_industry_node(parent):
    hr(f"E2. sina industry child node: {parent}")
    url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
    params = {"node": parent, "num": "100"}
    r = requests.get(url, params=params, headers={"User-Agent": UA, "Referer": "https://vip.stock.finance.sina.com.cn/"}, timeout=15)
    print(f"status={r.status_code} len={len(r.text)}")
    print(r.text[:500])
    return r.text


def sina_stock_hybg(code):
    """新浪个股的"行业归属/概念"页: 实际接口是
    https://vip.stock.finance.sina.com.cn/corp/go.php/vCB_AllNewsStock/symbol/sb000001/Page/1.phtml
    这里试"行业"页
    """
    hr(f"E3. sina stock industry/concept: {code}")
    market = "sh" if code.startswith(("6", "9", "5", "7", "8")) else "sz"
    url = f"https://vip.stock.finance.sina.com.cn/corp/go.php/vCI_CorpOtherInfo/menuNum/2/stockid/{code}/p/{market}.phtml"
    r = requests.get(url, headers={"User-Agent": UA}, timeout=15)
    print(f"status={r.status_code} len={len(r.text)}")
    import re
    # 找行业/概念相关字段
    industries = re.findall(r"所属行业[\s\S]{0,40}?>([\u4e00-\u9fa5（）A-Za-z0-9]+)<", r.text)
    print("所属行业 hits:", industries[:5])
    concepts = re.findall(r"概念[\s\S]{0,80}", r.text)
    print("概念片段:", [c[:50] for c in concepts[:3]])
    return r.text


def tencent_industry(code):
    hr(f"F1. tencent stock industry: {code}")
    market = "sh" if code.startswith(("6", "9", "5", "7", "8")) else "sz"
    # 腾讯个股 F10 行业页接口
    url = f"https://stockapp.finance.qq.com/cstock1/cctrl?mod=stockdata&type=industry&code={market}{code}"
    r = requests.get(url, headers={"User-Agent": UA, "Referer": "https://gu.qq.com/"}, timeout=15)
    print(f"status={r.status_code} len={len(r.text)}")
    print(r.text[:500])
    return r.text


def pywencai_industry(code):
    hr("C. pywencai 板块查询")
    import pywencai
    try:
        df = pywencai.get(query=f"{code}所属概念板块,所属行业,申万行业,申万二级,申万三级", query_type="stock")
        print("shape:", df.shape, "cols:", list(df.columns)[:20])
        if not df.empty:
            print(df.iloc[0].to_dict())
        return df
    except Exception as e:
        print("err:", type(e).__name__, str(e)[:200])
        return None


if __name__ == "__main__":
    # 探测顺序：东财行业→东财概念→东财成分股（拿一个示例概念 id）→sina→tencent→pywencai
    try:
        ind_rows = eastmoney_industry_name()
    except Exception as e:
        print("eastmoney_industry_name failed:", e)
        ind_rows = []
    try:
        con_rows = eastmoney_concept_name()
    except Exception as e:
        print("eastmoney_concept_name failed:", e)
        con_rows = []
    if con_rows:
        try:
            eastmoney_concept_cons(con_rows[0].get("f12"))
        except Exception as e:
            print("concept_cons failed:", e)
    for code in ["600519", "000001", "601398"]:
        try:
            eastmoney_stock_panel(code)
        except Exception as e:
            print(f"eastmoney panel {code} failed:", e)
        try:
            sina_stock_hybg(code)
        except Exception as e:
            print(f"sina {code} failed:", e)
        try:
            tencent_industry(code)
        except Exception as e:
            print(f"tencent {code} failed:", e)
    try:
        sina_industry_list()
    except Exception as e:
        print("sina industry_list failed:", e)
    try:
        sina_industry_node("industry_1_2")
    except Exception as e:
        print("sina child failed:", e)
    try:
        pywencai_industry("600519")
    except Exception as e:
        print("pywencai failed:", e)
