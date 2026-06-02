#!/usr/bin/env python3
"""Generate dividend one-pager suite:
   - dividend_one_pager_a4.html   (横向A4总览页，4块并排)
   - dividend_slide01.html         (竖版1080x1920 · 实时TOP10表格)
   - dividend_slide02.html         (竖版1080x1920 · 实时TOP10柱状图)
   - dividend_slide03.html         (竖版1080x1920 · 近3年均值TOP10表格)
   - dividend_slide04.html         (竖版1080x1920 · 近3年均值TOP10柱状图)
"""
import csv, sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8-sig')
DATA_DIR = Path(__file__).parent / "data" / "2026-06"


def read_csv(path):
    with open(path, encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


fin_rows    = read_csv(DATA_DIR / "财务指标汇总_2026-06.csv")
yield_rows = read_csv(DATA_DIR / "近3年股息率汇总_2026-06.csv")
price_rows = read_csv(DATA_DIR / "实时价格.csv")
m120_rows  = read_csv(DATA_DIR / "M120均线_06-01-06-07.csv")

def norm(code): return code.strip().zfill(6)

fin_map = {}
for r in fin_rows:
    code = norm(r["股票代码"])
    def fv(v):
        try: return float(v) if v else None
        except: return None
    fin_map[code] = {
        "ry": fv(r.get("2025年股息率(%)","")),
        "ay": fv(r.get("3年平均股息率(%)","")),
        "kf": fv(r.get("扣非净利润同比","")),
        "cg": fv(r.get("3年复合增长率","")),
    }

yield_map = {}
for r in yield_rows:
    code = norm(r["股票代码"])
    def fv(v):
        try: return float(v) if v else None
        except: return None
    yield_map[code] = {
        "name": r["股票名称"].strip(),
        "ind": r["交易所"].strip(),
        "ry": fv(r.get("2025年股息率(%)","")),   # CSV里的（基于年均价）
        "ay": fv(r.get("3年平均股息率(%)","")),
        "div": fv(r.get("2025年分红(元/股)","")),
    }

price_map = {}
for r in price_rows:
    code = norm(r["股票代码"])
    try: price_map[code] = float(r.get("实时价格") or r.get("昨日收盘", ""))
    except: pass

m120_map = {}
for r in m120_rows:
    code = norm(r["股票代码"])
    try: m120_map[code] = float(r["M120"])
    except: pass

merged = {}
for code, yd in yield_map.items():
    fd = fin_map.get(code, {})
    prev = price_map.get(code)
    m120 = m120_map.get(code)
    ratio = round(prev / m120, 3) if (prev and m120 and m120 != 0) else None
    # 实时股息率 = 分红/昨收
    div = yd.get("div")
    realtime_ry = round(div / prev * 100, 2) if (div and prev) else yd["ry"]
    merged[code] = {
        "name": yd["name"],
        "ind": yd["ind"],
        "ry": realtime_ry,   # 实时股息率（用昨收计算）
        "ay": yd["ay"],
        "kf": fd.get("kf"),
        "cg": fd.get("cg"),
        "ratio": ratio,
    }

by_ry = sorted([m for m in merged.values() if m["ry"] and m["ay"]], key=lambda x: x["ry"], reverse=True)
by_ay = sorted([m for m in merged.values() if m["ay"]], key=lambda x: x["ay"], reverse=True)

for i, m in enumerate(by_ry, 1): m["rank_ry"] = i
for i, m in enumerate(by_ay, 1): m["rank_ay"] = i

T10_ry = by_ry[:10]
T10_ay = by_ay[:10]

def pct(v): return "—" if v is None else f"{v:.2f}%"


# ─────────────────────────────────────────────────────────────────────────────
# A4 总览页 SVG（2块柱状图，viewBox 480×200）
# ─────────────────────────────────────────────────────────────────────────────
def make_svg_a4(stocks, viewBox="0 0 480 200"):
    BAR_W, STEP, BASE_X = 24, 42, 52
    MN, MX = 0.78, 1.25
    YBASE, YSCALE = 160, 200/(MX-MN)
    def yp(r): return YBASE - (r-MN)*YSCALE

    bars=grid_svg=labels=base_svg=""
    for i, st in enumerate(stocks):
        cx = BASE_X + i*STEP
        r  = st.get("ratio") if st.get("ratio") is not None else 1.0
        yt = yp(r); h = YBASE-yt
        col = "#1B365D" if r>=1.0 else "#B2B1AC"
        bars += f'<rect x="{cx-BAR_W//2}" y="{yt}" width="{BAR_W}" height="{h}" fill="{col}" rx="2"/>\n'
        bars += f'<text x="{cx}" y="{yt-4}" fill="#141413" font-size="7" text-anchor="middle">{r:.3f}</text>\n'
        nm = st["name"]; dv = f'{st.get("ry") or st.get("ay",0):.2f}%'
        labels += f'<text x="{cx}" y="178" fill="#504e49" font-size="6.5" text-anchor="middle" transform="rotate(-35 {cx} 178)">{nm}</text>\n'
        labels += f'<text x="{cx}" y="190" fill="#504e49" font-size="5.5" text-anchor="middle" transform="rotate(-35 {cx} 190)">{dv}</text>\n'

    for r_ in [0.80,0.85,0.90,0.95,1.00,1.05,1.10,1.15,1.20,1.25]:
        y = yp(r_)
        grid_svg += f'<line x1="40" y1="{y}" x2="476" y2="{y}" stroke="#e8e7e1" stroke-width="0.5"/>\n'
        grid_svg += f'<text x="34" y="{y+4}" fill="#6b6a64" font-size="6" text-anchor="end">{r_:.2f}</text>\n'
    by = yp(1.00)
    base_svg = f'<line x1="40" y1="{by}" x2="476" y2="{by}" stroke="#1B365D" stroke-width="0.8" stroke-dasharray="4 3"/>\n'
    base_svg += f'<text x="468" y="{by+4}" fill="#1B365D" font-size="6" text-anchor="end">M120=1</text>\n'

    return (f'<svg viewBox="{viewBox}" xmlns="http://www.w3.org/2000/svg" style="width:100%;display:block;">\n'
            f'<rect width="100%" height="100%" fill="#f5f4ed"/>\n'
            f'<line x1="40" y1="{YBASE}" x2="476" y2="{YBASE}" stroke="#141413" stroke-width="0.7"/>\n'
            f'{grid_svg}{base_svg}{bars}{labels}\n'
            f'<text x="10" y="100" fill="#6b6a64" font-size="6" text-anchor="middle" transform="rotate(-90 10 100)" letter-spacing="0.1em">昨收/M120</text>\n</svg>')


# ─────────────────────────────────────────────────────────────────────────────
# 竖版1080x1920 SVG（放大3×，viewBox 480×600）
# ─────────────────────────────────────────────────────────────────────────────
def make_svg_vertical(stocks):
    BAR_W, STEP, BASE_X = 52, 86, 88
    MN, MX = 0.78, 1.25
    YBASE, YSCALE = 540, 400/(MX-MN)
    def yp(r): return YBASE - (r-MN)*YSCALE

    bars=grid_svg=labels=base_svg=""
    for i, st in enumerate(stocks):
        cx = BASE_X + i*STEP
        r  = st.get("ratio") if st.get("ratio") is not None else 1.0
        yt = yp(r); h = YBASE-yt
        col = "#1B365D" if r>=1.0 else "#B2B1AC"
        bars += f'<rect x="{cx-BAR_W//2}" y="{yt}" width="{BAR_W}" height="{h}" fill="{col}" rx="4"/>\n'
        bars += f'<text x="{cx}" y="{yt-8}" fill="#141413" font-size="22" text-anchor="middle" font-weight="500">{r:.3f}</text>\n'
        nm = st["name"]; dv = f'{st.get("ry") or st.get("ay",0):.2f}%'
        labels += f'<text x="{cx}" y="608" fill="#504e49" font-size="22" text-anchor="middle" transform="rotate(-45 {cx} 608)">{nm}</text>\n'
        labels += f'<text x="{cx}" y="640" fill="#504e49" font-size="18" text-anchor="middle" transform="rotate(-45 {cx} 640)">{dv}</text>\n'

    for r_ in [0.80,0.90,0.95,1.00,1.05,1.10,1.15,1.20,1.25]:
        y = yp(r_)
        grid_svg += f'<line x1="60" y1="{y}" x2="970" y2="{y}" stroke="#e8e7e1" stroke-width="1"/>\n'
        grid_svg += f'<text x="50" y="{y+8}" fill="#6b6a64" font-size="20" text-anchor="end">{r_:.2f}</text>\n'
    by = yp(1.00)
    base_svg = f'<line x1="60" y1="{by}" x2="970" y2="{by}" stroke="#1B365D" stroke-width="2" stroke-dasharray="8 6"/>\n'
    base_svg += f'<text x="965" y="{by+10}" fill="#1B365D" font-size="20" text-anchor="end">M120=1</text>\n'

    return (f'<svg viewBox="0 0 1040 720" xmlns="http://www.w3.org/2000/svg" style="width:100%;display:block;">\n'
            f'<rect width="100%" height="100%" fill="#f5f4ed"/>\n'
            f'<line x1="60" y1="{YBASE}" x2="970" y2="{YBASE}" stroke="#141413" stroke-width="1.5"/>\n'
            f'{grid_svg}{base_svg}{bars}{labels}\n'
            f'<text x="20" y="350" fill="#6b6a64" font-size="20" text-anchor="middle" transform="rotate(-90 20 350)" letter-spacing="2">昨收/M120</text>\n</svg>')


# ─────────────────────────────────────────────────────────────────────────────
# 旧版 one_pager HTML（保持 dividend_one_pager.html 模板视觉，实时列用实时价口径）
# ─────────────────────────────────────────────────────────────────────────────
def make_svg_old(stocks):
    """旧版 480x270 柱状图，复用 dividend_one_pager.html 模板的视觉。"""
    BAR_W, STEP, BASE_X = 28, 42, 52
    MN, MX = 0.80, 1.25
    Y_M120 = 126.38297872340426
    YSCALE = 425.531914893617
    YBASE = 220.0
    def yp(r): return Y_M120 - (r-1.0)*YSCALE

    bars=grid_svg=labels=base_svg=""
    for i, st in enumerate(stocks):
        cx = BASE_X + i*STEP
        r  = st.get("ratio") if st.get("ratio") is not None else 1.0
        yt = yp(r); h = YBASE-yt
        col = "#1B365D" if r>=1.0 else "#B2B1AC"
        bars += f'<rect x="{cx-BAR_W//2}" y="{yt}" width="{BAR_W}" height="{h}" fill="{col}" rx="2"/>\n'
        bars += f'<text x="{cx}" y="{yt-4}" fill="#141413" font-size="8" text-anchor="middle">{r:.3f}</text>\n'
        nm = st["name"]; dv = f'{st.get("ry") or st.get("ay",0):.2f}%'
        labels += f'<text x="{cx}" y="238" fill="#504e49" font-size="7.5" text-anchor="middle" transform="rotate(-35 {cx} 238)">{nm}</text>\n'
        labels += f'<text x="{cx}" y="250" fill="#504e49" font-size="6.5" text-anchor="middle" transform="rotate(-35 {cx} 250)">{dv}</text>\n'

    for r_ in [0.80,0.85,0.90,0.95,1.00,1.05,1.10,1.15,1.20,1.25]:
        y = yp(r_)
        grid_svg += f'<line x1="40" y1="{y}" x2="466" y2="{y}" stroke="#e8e7e1" stroke-width="0.5"/>\n'
        grid_svg += f'<text x="34" y="{y+4}" fill="#6b6a64" font-size="8" text-anchor="end">{r_:.2f}</text>\n'
    by = yp(1.00)
    base_svg = f'<line x1="40" y1="{by}" x2="466" y2="{by}" stroke="#1B365D" stroke-width="0.8" stroke-dasharray="4 3"/>\n'
    base_svg += f'<text x="468" y="{by+4}" fill="#1B365D" font-size="7">M120基准 1.00</text>\n'

    return (f'<svg viewBox="0 0 480 270" xmlns="http://www.w3.org/2000/svg" style="width:100%;display:block;">\n'
            f'<rect width="100%" height="100%" fill="#f5f4ed"/>\n'
            f'<line x1="40" y1="{YBASE}" x2="466" y2="{YBASE}" stroke="#141413" stroke-width="0.7"/>\n'
            f'{grid_svg}{base_svg}{bars}{labels}\n'
            f'<text x="10" y="125" fill="#6b6a64" font-size="7" text-anchor="middle" transform="rotate(-90 10 125)" letter-spacing="0.1em">昨日收盘/M120</text>\n</svg>')


def row_old_ry(): return "".join(
    f'<tr><td>{i+1}</td><td>{s["name"]}</td><td class="num">{pct(s["ry"])}</td>'
    f'<td class="num">{pct(s["ay"])}</td><td class="num"><span class="tag">#{s["rank_ay"]}</span></td>'
    f'<td>{s["ind"]}</td></tr>'
    for i,s in enumerate(T10_ry))

def row_old_ay(): return "".join(
    f'<tr><td>{i+1}</td><td>{s["name"]}</td><td class="num">{pct(s["ay"])}</td>'
    f'<td class="num">{pct(s["ry"])}</td><td class="num"><span class="tag">#{s["rank_ry"]}</span></td>'
    f'<td>{s["ind"]}</td></tr>'
    for i,s in enumerate(T10_ay))


OLD_CSS = """
@font-face{font-family:"TsangerJinKai02";src:url("../fonts/TsangerJinKai02-W04.ttf") format("truetype"),url("https://cdn.jsdelivr.net/gh/tw93/Kami@main/assets/fonts/TsangerJinKai02-W04.ttf") format("truetype");font-weight:400;font-style:normal;}
@page{size:A4;margin:10mm 14mm;background:#f5f4ed;}
*{box-sizing:border-box;margin:0;padding:0;}
:root{--p:#f5f4ed;--nb:#141413;--dw:#3d3d3a;--br:#1B365D;--bd:#e8e6dc;--bds:#e5e3d8;--tb:#E4ECF5;--serif:"TsangerJinKai02","Source Han Seric SC","Noto Serif CJK SC",Georgia,serif;}
html,body{background:var(--p);}
@media screen{body{max-width:210mm;margin:0 auto;padding:10mm 14mm;}.four-grid{grid-template-columns:1fr 1fr;gap:10pt;}}
@media(max-width:600px){body{padding:6pt;font-size:9pt;}.four-grid{grid-template-columns:1fr;gap:8pt;}.header{flex-direction:column;gap:6pt;}}
body{color:var(--nb);font-family:var(--serif);font-size:8.5pt;line-height:1.4;}
.header{border-left:2.5pt solid var(--br);border-radius:1.5pt;padding-left:7pt;margin-bottom:8pt;display:flex;align-items:flex-end;justify-content:space-between;gap:16pt;}
.title-block{flex:1;}
.eyebrow{font-size:7.5pt;color:var(--br);letter-spacing:1pt;text-transform:uppercase;margin-bottom:2pt;}
h1{font-family:var(--serif);font-size:18pt;font-weight:500;line-height:1.15;margin-bottom:3pt;}
.subtitle{font-size:9pt;color:#504e49;line-height:1.4;}
.meta{font-size:7.5pt;color:#6b6a64;text-align:right;line-height:1.4;white-space:nowrap;}
.four-grid{display:grid;gap:10pt;margin-bottom:8pt;}
section{break-inside:avoid;}
h2{font-family:var(--serif);font-size:11pt;font-weight:500;margin-bottom:4pt;border-left:1.8pt solid var(--br);padding-left:5pt;}
h2 .sub{font-size:7.5pt;color:#6b6a64;font-weight:400;margin-left:4pt;}
table{width:100%;border-collapse:collapse;font-size:7.5pt;margin:0;break-inside:avoid;}
table th{text-align:left;font-weight:500;color:var(--dw);padding:2pt 4pt;border-bottom:0.8pt solid var(--bd);}
table td{padding:1.5pt 4pt;border-bottom:0.3pt solid var(--bds);vertical-align:top;line-height:1.35;}
table td.num{text-align:right;font-variant-numeric:tabular-nums;}
table th.num{text-align:right;}
table.compact th,table.compact td{padding:1.5pt 4pt;font-size:7pt;line-height:1.35;}
.tag{display:inline-block;background:var(--tb);color:var(--br);font-size:6.5pt;font-weight:500;padding:0.5pt 3pt;border-radius:2pt;letter-spacing:0.2pt;}
figure{margin:4pt 0 0 0;break-inside:avoid;}
figcaption{font-size:7.5pt;color:#504e49;margin-top:3pt;line-height:1.4;}
.footer{margin-top:6pt;padding-top:4pt;border-top:0.3pt dotted var(--bd);font-size:7.5pt;color:#6b6a64;display:flex;justify-content:space-between;letter-spacing:0.2pt;}
"""

svg_old_ry = make_svg_old(T10_ry)
svg_old_ay = make_svg_old(T10_ay)

html_one_pager = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A股高股息率TOP10分析</title>
<style>{OLD_CSS}</style>
</head>
<body>

<div class="header">
  <div class="title-block">
    <div class="eyebrow">A股 · 股息率分析</div>
    <h1>高股息率TOP10排名全景</h1>
    <div class="subtitle">实时 vs 近3年平均股息率 · 扣非净利润同比 vs 3年复合增长率</div>
  </div>
  <div class="meta">144只股票<br>样本覆盖</div>
</div>

<div class="four-grid">

  <section>
    <h2>实时股息率TOP10<span class="sub">近3年均值 &amp; 排名 &amp; 行业</span></h2>
    <table class="compact">
      <thead><tr><th>#</th><th>股票</th><th class="num">实时</th><th class="num">近3年均值</th><th class="num">近3年排名</th><th>行业</th></tr></thead>
      <tbody>{row_old_ry()}</tbody>
    </table>
  </section>

  <section>
    <h2>实时股息率TOP10<span class="sub">昨日收盘 / M120 比值</span></h2>
    <figure>{svg_old_ry}</figure>
    <figcaption>柱高=昨日收盘/M120比值（蓝色≥1.00，灰色&lt;1.00，蓝色虚线=M120基准）</figcaption>
  </section>

  <section>
    <h2>近3年均值TOP10<span class="sub">实时股息率 &amp; 排名 &amp; 行业</span></h2>
    <table class="compact">
      <thead><tr><th>#</th><th>股票</th><th class="num">近3年均值</th><th class="num">实时</th><th class="num">实时排名</th><th>行业</th></tr></thead>
      <tbody>{row_old_ay()}</tbody>
    </table>
  </section>

  <section>
    <h2>近3年均值TOP10<span class="sub">昨日收盘 / M120 比值</span></h2>
    <figure>{svg_old_ay}</figure>
    <figcaption>柱高=昨日收盘/M120比值（蓝色≥1.00，灰色&lt;1.00，蓝色虚线=M120基准）</figcaption>
  </section>

</div>

<div class="footer">
  <span>数据来源：dividend-select · 近3年股息率汇总 &amp; 财务指标汇总 &amp; M120均线</span>
  <span>2026-05 · 仅供投资参考，不构成投资建议</span>
</div>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────────────────────
# A4 总览页 HTML
# ─────────────────────────────────────────────────────────────────────────────
svg_a4_ry = make_svg_a4(T10_ry)
svg_a4_ay = make_svg_a4(T10_ay)

A4_CSS = """
@font-face{font-family:"TsangerJinKai02";src:url("../fonts/TsangerJinKai02-W04.ttf") format("truetype"),url("https://cdn.jsdelivr.net/gh/tw93/Kami@main/assets/fonts/TsangerJinKai02-W04.ttf") format("truetype");font-weight:400;font-style:normal;}
@font-face{font-family:"TsangerJinKai02";src:url("../fonts/TsangerJinKai02-W05.ttf") format("truetype"),url("https://cdn.jsdelivr.net/gh/tw93/Kami@main/assets/fonts/TsangerJinKai02-W05.ttf") format("truetype");font-weight:500;font-style:normal;}
@page{size:A4;margin:10mm 14mm;background:#f5f4ed;}
*{{box-sizing:border-box;margin:0;padding:0;}}
:root{{--p:#f5f4ed;--nb:#141413;--dw:#3d3d3a;--br:#1B365D;--bd:#e8e6dc;--bds:#e5e3d8;--tb:#E4ECF5;--serif:"TsangerJinKai02","Source Han Seric SC","Noto Serif CJK SC",Georgia,serif;}}
html,body{{background:var(--p);}}
@media screen{{body{{max-width:210mm;margin:0 auto;padding:10mm 14mm;}}.four-grid{{grid-template-columns:1fr 1fr;gap:10pt;}}}}
@media(max-width:600px){{body{{padding:6pt;font-size:9pt;}}.four-grid{{grid-template-columns:1fr;gap:8pt;}}.header{{flex-direction:column;gap:6pt;}}}}
body{{color:var(--nb);font-family:var(--serif);font-size:8.5pt;line-height:1.4;}}
.header{{border-left:2.5pt solid var(--br);border-radius:1.5pt;padding-left:7pt;margin-bottom:8pt;display:flex;align-items:flex-end;justify-content:space-between;gap:16pt;}}
.title-block{{flex:1;}}
.eyebrow{{font-size:7.5pt;color:var(--br);letter-spacing:1pt;text-transform:uppercase;margin-bottom:2pt;}}
h1{{font-family:var(--serif);font-size:18pt;font-weight:500;line-height:1.15;margin-bottom:3pt;}}
.subtitle{{font-size:9pt;color:#504e49;line-height:1.4;}}
.meta{{font-size:7.5pt;color:#6b6a64;text-align:right;line-height:1.4;white-space:nowrap;}}
.four-grid{{display:grid;gap:10pt;margin-bottom:8pt;}}
section{{break-inside:avoid;}}
h2{{font-family:var(--serif);font-size:11pt;font-weight:500;margin-bottom:4pt;border-left:1.8pt solid var(--br);padding-left:5pt;}}
h2 .sub{{font-size:7.5pt;color:#6b6a64;font-weight:400;margin-left:4pt;}}
table{{width:100%;border-collapse:collapse;font-size:7.5pt;margin:0;break-inside:avoid;}}
table th{{text-align:left;font-weight:500;color:var(--dw);padding:2pt 4pt;border-bottom:0.8pt solid var(--bd);}}
table td{{padding:1.5pt 4pt;border-bottom:0.3pt solid var(--bds);vertical-align:top;line-height:1.35;}}
table td.num{{text-align:right;font-variant-numeric:tabular-nums;}}
table th.num{{text-align:right;}}
table.compact th,table.compact td{{padding:1.5pt 4pt;font-size:7pt;line-height:1.35;}}
.tag{{display:inline-block;background:var(--tb);color:var(--br);font-size:6.5pt;font-weight:500;padding:0.5pt 3pt;border-radius:2pt;letter-spacing:0.1pt;}}
figure{{margin:4pt 0 0 0;break-inside:avoid;}}
figcaption{{font-size:7.5pt;color:#504e49;margin-top:3pt;line-height:1.4;}}
.footer{{margin-top:8pt;padding-top:6pt;border-top:0.5pt solid var(--bd);font-size:7pt;color:#6b6a64;line-height:1.6;letter-spacing:0.1pt;}}
"""

def row1(): return "".join(
    f'<tr><td>{i+1}</td><td>{s["name"]}</td><td class="num">{pct(s["ry"])}</td>'
    f'<td class="num">{pct(s["ay"])}</td><td class="num"><span class="tag">#{s["rank_ay"]}</span></td>'
    f'<td>{s["ind"]}</td><td class="num">{pct(s["kf"])}</td><td class="num">{pct(s["cg"])}</td></tr>'
    for i,s in enumerate(T10_ry))

def row3(): return "".join(
    f'<tr><td>{i+1}</td><td>{s["name"]}</td><td class="num">{pct(s["ay"])}</td>'
    f'<td class="num">{pct(s["ry"])}</td><td class="num"><span class="tag">#{s["rank_ry"]}</span></td>'
    f'<td>{s["ind"]}</td><td class="num">{pct(s["kf"])}</td><td class="num">{pct(s["cg"])}</td></tr>'
    for i,s in enumerate(T10_ay))

html_a4 = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A股高股息率TOP10分析</title>
<style>{A4_CSS}</style>
</head>
<body>

<div class="header">
  <div class="title-block">
    <div class="eyebrow">A股 · 股息率分析</div>
    <h1>高股息率TOP10排名全景</h1>
    <div class="subtitle">实时 vs 近3年平均股息率 · 扣非净利润同比 vs 3年复合增长率</div>
  </div>
  <div class="meta">2026-06-01</div>
</div>

<div class="four-grid">

  <section>
    <h2>实时股息率TOP10<span class="sub">近3年均值 &amp; 排名 &amp; 行业 &amp; 扣非同比 &amp; 3年CAGR</span></h2>
    <table class="compact">
      <thead><tr><th>#</th><th>股票</th><th class="num">实时</th><th class="num">近3年均值</th><th class="num">近3年排名</th><th>行业</th><th class="num">扣非同比</th><th class="num">3年CAGR</th></tr></thead>
      <tbody>{row1()}</tbody>
    </table>
  </section>

  <section>
    <h2>实时TOP10<span class="sub">昨收/M120比值</span></h2>
    <figure>{svg_a4_ry}</figure>
    <figcaption>蓝色≥1.00，灰色&lt;1.00，蓝色虚线=M120基准</figcaption>
  </section>

  <section>
    <h2>近3年均值TOP10<span class="sub">实时股息率 &amp; 排名 &amp; 行业 &amp; 扣非同比 &amp; 3年CAGR</span></h2>
    <table class="compact">
      <thead><tr><th>#</th><th>股票</th><th class="num">近3年均值</th><th class="num">实时</th><th class="num">实时排名</th><th>行业</th><th class="num">扣非同比</th><th class="num">3年CAGR</th></tr></thead>
      <tbody>{row3()}</tbody>
    </table>
  </section>

  <section>
    <h2>近3年均值TOP10<span class="sub">昨收/M120比值</span></h2>
    <figure>{svg_a4_ay}</figure>
    <figcaption>蓝色≥1.00，灰色&lt;1.00，蓝色虚线=M120基准</figcaption>
  </section>

</div>

<div class="footer">
  数据来源：dividend-select · 144只高股息A股样本<br>
  2026-06-01 · 仅供投资参考，不构成投资建议
</div>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────────────────────
# 竖版 HTML（共用的 viewport=1080×1920 CSS）
# ─────────────────────────────────────────────────────────────────────────────
def vert_css(font_scale=1.0):
    """Generate scaled CSS for vertical 1080x1920 layout.
       font_scale factor scales pt sizes (default 4× from A4 8.5pt).
    """
    fs = font_scale
    return f"""
@font-face{{font-family:"TsangerJinKai02";src:url("../fonts/TsangerJinKai02-W04.ttf") format("truetype"),url("https://cdn.jsdelivr.net/gh/tw93/Kami@main/assets/fonts/TsangerJinKai02-W04.ttf") format("truetype");font-weight:400;font-style:normal;}}
@font-face{{font-family:"TsangerJinKai02";src:url("../fonts/TsangerJinKai02-W05.ttf") format("truetype"),url("https://cdn.jsdelivr.net/gh/tw93/Kami@main/assets/fonts/TsangerJinKai02-W05.ttf") format("truetype");font-weight:500;font-style:normal;}}
*{{box-sizing:border-box;margin:0;padding:0;}}
:root{{--p:#f5f4ed;--nb:#141413;--dw:#3d3d3a;--br:#1B365D;--bd:#e8e6dc;--bds:#e5e3d8;--tb:#E4ECF5;--serif:"TsangerJinKai02","Source Han Seric SC","Noto Serif CJK SC",Georgia,serif;}}
html,body{{background:var(--p);width:1080px;height:1920px;}}
body{{color:var(--nb);font-family:var(--serif);font-size:{8.5*fs:.1f}pt;line-height:1.4;letter-spacing:{.2*fs:.1f}pt;}}
.header{{border-left:{2.5*fs:.1f}pt solid var(--br);border-radius:{1.5*fs:.1f}pt;padding-left:{8*fs:.1f}pt;margin-bottom:{12*fs:.1f}pt;display:flex;align-items:flex-end;justify-content:space-between;gap:{30*fs:.1f}pt;}}
.title-block{{flex:1;}}
.eyebrow{{font-size:{7.5*fs:.1f}pt;color:var(--br);letter-spacing:{1*fs:.1f}pt;text-transform:uppercase;margin-bottom:{2*fs:.1f}pt;}}
h1{{font-family:var(--serif);font-size:{18*fs:.1f}pt;font-weight:500;line-height:1.15;margin-bottom:{4*fs:.1f}pt;}}
.subtitle{{font-size:{9*fs:.1f}pt;color:#504e49;line-height:1.4;}}
.meta{{font-size:{7.5*fs:.1f}pt;color:#6b6a64;text-align:right;line-height:1.4;white-space:nowrap;}}
h2{{font-family:var(--serif);font-size:{11*fs:.1f}pt;font-weight:500;margin-bottom:{6*fs:.1f}pt;border-left:{1.8*fs:.1f}pt solid var(--br);padding-left:{5*fs:.1f}pt;}}
h2 .sub{{font-size:{7.5*fs:.1f}pt;color:#6b6a64;font-weight:400;margin-left:{4*fs:.1f}pt;}}
table{{width:100%;border-collapse:collapse;font-size:{7.5*fs:.1f}pt;margin:0;break-inside:avoid;}}
table th{{text-align:left;font-weight:500;color:var(--dw);padding:{2*fs:.1f}pt {4*fs:.1f}pt;border-bottom:{0.8*fs:.1f}pt solid var(--bd);}}
table td{{padding:{1.5*fs:.1f}pt {4*fs:.1f}pt;border-bottom:{0.3*fs:.1f}pt solid var(--bds);vertical-align:top;line-height:1.35;}}
table td.num{{text-align:right;font-variant-numeric:tabular-nums;}}
table th.num{{text-align:right;}}
table.compact th,table.compact td{{padding:{1.5*fs:.1f}pt {4*fs:.1f}pt;font-size:{7*fs:.1f}pt;line-height:1.35;}}
.tag{{display:inline-block;background:var(--tb);color:var(--br);font-size:{6.5*fs:.1f}pt;font-weight:500;padding:{0.5*fs:.1f}pt {3*fs:.1f}pt;border-radius:{2*fs:.1f}pt;letter-spacing:{0.1*fs:.1f}pt;}}
figure{{margin:{6*fs:.1f}pt 0 0 0;break-inside:avoid;}}
figcaption{{font-size:{7.5*fs:.1f}pt;color:#504e49;margin-top:{3*fs:.1f}pt;line-height:1.4;}}
.footer{{margin-top:{16*fs:.1f}pt;padding-top:{6*fs:.1f}pt;border-top:0.5pt solid var(--bd);font-size:{8*fs:.1f}pt;color:#6b6a64;line-height:1.7;letter-spacing:{0.1*fs:.1f}pt;}}
.content{{padding:0 {20*fs:.1f}pt;}}
"""


def build_vert_table_html(title, eyebrow, subtitle, table_rows, footer_left, footer_right):
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=1080,height=1920">
<title>{title}</title>
<style>{vert_css(4.0)}</style>
</head>
<body>

<div class="header">
  <div class="title-block">
    <div class="eyebrow">{eyebrow}</div>
    <h1>{title}</h1>
    <div class="subtitle">{subtitle}</div>
  </div>
  <div class="meta">2026-06-01</div>
</div>

<div class="content">
{table_rows}
</div>

<div class="footer">
  <span>{footer_left}</span>
  <span>{footer_right}</span>
</div>
</body>
</html>"""


def build_vert_chart_html(title, eyebrow, subtitle, svg_content, caption, footer_left, footer_right):
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=1080,height=1920">
<title>{title}</title>
<style>{vert_css(4.0)}</style>
</head>
<body>

<div class="header">
  <div class="title-block">
    <div class="eyebrow">{eyebrow}</div>
    <h1>{title}</h1>
    <div class="subtitle">{subtitle}</div>
  </div>
  <div class="meta">2026-06-01</div>
</div>

<div class="content">
<h2>昨收/M120比值<span class="sub">蓝色≥1.00，灰色&lt;1.00</span></h2>
<figure>{svg_content}</figure>
<figcaption>{caption}</figcaption>
</div>

<div class="footer">
  <span>{footer_left}</span>
  <span>{footer_right}</span>
</div>
</body>
</html>"""


def make_table_rows(stocks, cols):
    """Build table rows HTML from stocks list.
       cols: list of (label, key) tuples.
    """
    rows = ""
    for i, s in enumerate(stocks):
        cells = [f"<td>{i+1}</td>"]
        for label, key in cols:
            if key == "rank_ry" or key == "rank_ay":
                rank_val = s.get(key, "")
                cells.append(f'<td class="num"><span class="tag">#{rank_val}</span></td>')
            else:
                v = s.get(key)
                if key in ("ry", "ay", "kf", "cg"):
                    cells.append(f'<td class="num">{pct(v)}</td>')
                else:
                    cells.append(f'<td>{v or "—"}</td>')
        rows += "<tr>" + "".join(cells) + "</tr>"
    return rows


# Table column definitions
RY_COLS = [
    ("#", None),
    ("股票", "name"),
    ("实时", "ry"),
    ("近3年均值", "ay"),
    ("近3年排名", "rank_ay"),
    ("行业", "ind"),
    ("扣非同比", "kf"),
    ("3年CAGR", "cg"),
]
AY_COLS = [
    ("#", None),
    ("股票", "name"),
    ("近3年均值", "ay"),
    ("实时", "ry"),
    ("实时排名", "rank_ry"),
    ("行业", "ind"),
    ("扣非同比", "kf"),
    ("3年CAGR", "cg"),
]

def make_table_html(stocks, cols, title, eyebrow, subtitle):
    rows_html = make_table_rows(stocks, cols)
    th_cells = "".join(f"<th>{c[0]}</th>" for c in cols)
    th_cells = th_cells.replace('<th>#</th>', '<th>#</th>')
    # fix: first th is #, not num
    table_html = f"""<h2>{title}<span class="sub">{eyebrow}</span></h2>
    <table class="compact">
      <thead><tr>{th_cells}</tr></thead>
      <tbody>{rows_html}</tbody>
    </table>"""
    return build_vert_table_html(
        title, eyebrow, subtitle, table_html,
        "数据来源：dividend-select · 144只高股息A股样本",
        "2026-06-01 · 仅供投资参考，不构成投资建议"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Slide 1: 实时TOP10 table
# ─────────────────────────────────────────────────────────────────────────────
html_slide01 = make_table_html(T10_ry, RY_COLS,
    "实时股息率TOP10",
    "近3年均值 &amp; 排名 &amp; 行业 &amp; 扣非同比 &amp; 3年CAGR",
    "实时 vs 近3年平均股息率"
)

# ─────────────────────────────────────────────────────────────────────────────
# Slide 2: 实时TOP10 chart
# ─────────────────────────────────────────────────────────────────────────────
svg_vert_ry = make_svg_vertical(T10_ry)
html_slide02 = build_vert_chart_html(
    "实时股息率TOP10", "A股 · 股息率分析",
    "昨收/M120比值 · 蓝色≥1.00，灰色&lt;1.00",
    svg_vert_ry,
    "蓝色表示价格站上M120均线，蓝色虚线为M120基准线",
    "数据来源：dividend-select · 144只高股息A股样本",
    "2026-06-01 · 仅供投资参考，不构成投资建议"
)

# ─────────────────────────────────────────────────────────────────────────────
# Slide 3: 近3年均值TOP10 table
# ─────────────────────────────────────────────────────────────────────────────
html_slide03 = make_table_html(T10_ay, AY_COLS,
    "近3年均值TOP10",
    "实时股息率 &amp; 排名 &amp; 行业 &amp; 扣非同比 &amp; 3年CAGR",
    "实时 vs 近3年平均股息率"
)

# ─────────────────────────────────────────────────────────────────────────────
# Slide 4: 近3年均值TOP10 chart
# ─────────────────────────────────────────────────────────────────────────────
svg_vert_ay = make_svg_vertical(T10_ay)
html_slide04 = build_vert_chart_html(
    "近3年均值TOP10", "A股 · 股息率分析",
    "昨收/M120比值 · 蓝色≥1.00，灰色&lt;1.00",
    svg_vert_ay,
    "蓝色表示价格站上M120均线，蓝色虚线为M120基准线",
    "数据来源：dividend-select · 144只高股息A股样本",
    "2026-06-01 · 仅供投资参考，不构成投资建议"
)


# ─────────────────────────────────────────────────────────────────────────────
# 轮播 HTML（4个竖版1080x1920 slide，CSS+JS内嵌）
# ─────────────────────────────────────────────────────────────────────────────
CAROUSEL_CSS = """
@font-face{font-family:"TsangerJinKai02";src:url("../fonts/TsangerJinKai02-W04.ttf") format("truetype"),url("https://cdn.jsdelivr.net/gh/tw93/Kami@main/assets/fonts/TsangerJinKai02-W04.ttf") format("truetype");font-weight:400;font-style:normal;}
@font-face{font-family:"TsangerJinKai02";src:url("../fonts/TsangerJinKai02-W05.ttf") format("truetype"),url("https://cdn.jsdelivr.net/gh/tw93/Kami@main/assets/fonts/TsangerJinKai02-W05.ttf") format("truetype");font-weight:500;font-style:normal;}
* { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --p:#f5f4ed;--nb:#141413;--dw:#3d3d3a;--br:#1B365D;
  --bd:#e8e6dc;--bds:#e5e3d8;--tb:#E4ECF5;--ol:#504e49;--st:#6b6a64;
  --serif:"TsangerJinKai02","Source Han Seric SC","Noto Serif CJK SC","Songti SC","STSong",Georgia,serif;
}
html,body{background:#141413;width:1080px;height:1920px;overflow:hidden;}
body{color:var(--nb);font-family:var(--serif);font-size:34pt;line-height:1.4;letter-spacing:.2pt;}
.carousel{position:relative;width:1080px;height:1920px;overflow:hidden;background:var(--p);}
.slide{position:absolute;top:0;left:0;width:100%;height:100%;opacity:0;transition:opacity .6s;background:var(--p);overflow:hidden;}
.slide.active{opacity:1;}
.header{border-left:6pt solid var(--br);border-radius:4pt;padding-left:20pt;margin-bottom:24pt;display:flex;align-items:flex-end;justify-content:space-between;gap:40pt;}
.title-block{flex:1;}
.eyebrow{font-size:28pt;color:var(--br);letter-spacing:3pt;margin-bottom:6pt;}
h1{font-family:var(--serif);font-size:58pt;font-weight:500;line-height:1.15;margin-bottom:10pt;}
.subtitle{font-size:32pt;color:var(--ol);line-height:1.4;}
.meta{font-size:28pt;color:var(--st);text-align:right;line-height:1.4;}
h2{font-family:var(--serif);font-size:34pt;font-weight:500;margin-bottom:14pt;border-left:5pt solid var(--br);padding-left:14pt;}
h2 .sub{font-size:26pt;color:var(--st);font-weight:400;margin-left:10pt;}
table{width:100%;border-collapse:collapse;font-size:28pt;margin:0;break-inside:avoid;}
table th{text-align:left;font-weight:500;color:var(--dw);padding:6pt 10pt;border-bottom:2pt solid var(--bd);}
table td{padding:5pt 10pt;border-bottom:1pt solid var(--bds);vertical-align:top;line-height:1.35;}
table td.num{text-align:right;font-variant-numeric:tabular-nums;}
table th.num{text-align:right;}
td.name,td.ind{max-width:180px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.tag{display:inline-block;background:var(--tb);color:var(--br);font-size:20pt;font-weight:500;padding:1pt 6pt;border-radius:6pt;letter-spacing:.3pt;}
figure{margin:8pt 0 0;break-inside:avoid;}
figcaption{font-size:26pt;color:var(--ol);margin-top:8pt;}
.footer{position:absolute;bottom:0;left:0;right:0;padding:20pt 24pt 24pt;border-top:1pt solid var(--bd);font-size:22pt;color:var(--st);line-height:1.8;letter-spacing:.3pt;background:var(--p);}
.content{padding:0 20pt;}
.dots{position:absolute;bottom:110pt;left:50%;transform:translateX(-50%);display:flex;gap:12pt;z-index:10;}
.dot{width:12pt;height:12pt;border-radius:50%;background:var(--bd);transition:background .3s;}
.dot.active{background:var(--br);}
.slide-label{position:absolute;top:20pt;right:20pt;font-size:22pt;color:var(--st);letter-spacing:1pt;z-index:10;}
"""[1:]

CAROUSEL_JS = """
(function(){
  var slides=document.querySelectorAll('.slide'),dots=document.querySelectorAll('.dot'),cur=0,tid;
  function show(i){slides.forEach(function(s,j){s.classList.toggle('active',j===i)});dots.forEach(function(d,j){d.classList.toggle('active',j===i)});cur=i;}
  function next(){show((cur+1)%4);}
  function start(){tid=setInterval(next,4000);}
  function stop(){clearInterval(tid);}
  dots.forEach(function(d){d.addEventListener('click',function(){stop();show(+d.dataset.index);start();});});
  var c=document.getElementById('carousel'),tx=0;
  c.addEventListener('touchstart',function(e){tx=e.touches[0].clientX;stop();},{passive:true});
  c.addEventListener('touchend',function(e){var dx=e.changedTouches[0].clientX-tx;if(dx<-50)show((cur+1)%4);else if(dx>50)show((cur-1+4)%4);start();},{passive:true});
  document.addEventListener('keydown',function(e){if(e.key==='ArrowRight'||e.key==='ArrowDown'){stop();show((cur+1)%4);start();}else if(e.key==='ArrowLeft'||e.key==='ArrowUp'){stop();show((cur-1+4)%4);start();}});
  start();
})();
"""[1:]

def build_carousel():
    rows1 = row1()
    rows3 = row3()
    svg1 = make_svg_vertical(T10_ry)
    svg2 = make_svg_vertical(T10_ay)
    return CAROUSEL_CSS, rows1, rows3, svg1, svg2


def generate_carousel_html():
    css, rows1, rows3, svg1, svg2 = build_carousel()
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=1080,height=1920">
<title>A股高股息率TOP10轮播</title>
<style>{css}</style>
</head>
<body>
<div class="carousel" id="carousel">

  <div class="slide active" id="slide1">
    <div class="slide-label">1 / 4</div>
    <div class="content">
      <div class="header">
        <div class="title-block">
          <div class="eyebrow">A股 · 股息率分析</div>
          <h1>实时股息率TOP10</h1>
                  </div>
        <div class="meta">2026-06-01</div>
      </div>
      <h2>实时股息率TOP10<span class="sub">近3年均值 &amp; 排名 &amp; 行业 &amp; 扣非同比 &amp; 3年CAGR</span></h2>
      <table>
        <thead><tr><th>#</th><th>股票</th><th class="num">实时</th><th class="num">近3年均值</th><th class="num">近3年排名</th><th>行业</th><th class="num">扣非同比</th><th class="num">3年CAGR</th></tr></thead>
        <tbody>{rows1}</tbody>
      </table>
    </div>
    <div class="footer">
      数据来源：dividend-select · 144只高股息A股样本<br>
      2026-06-01 · 仅供投资参考，不构成投资建议
    </div>
  </div>

  <div class="slide" id="slide2">
    <div class="slide-label">2 / 4</div>
    <div class="content">
      <div class="header">
        <div class="title-block">
          <div class="eyebrow">A股 · 股息率分析</div>
          <h1>实时股息率TOP10</h1>
                  </div>
        <div class="meta">2026-06-01</div>
      </div>
      <h2>昨收/M120比值<span class="sub">蓝色≥1.00，灰色&lt;1.00</span></h2>
      <figure>{svg1}</figure>
      <figcaption>蓝色表示价格站上M120均线，蓝色虚线为M120基准线</figcaption>
    </div>
    <div class="footer">
      数据来源：dividend-select · 144只高股息A股样本<br>
      2026-06-01 · 仅供投资参考，不构成投资建议
    </div>
  </div>

  <div class="slide" id="slide3">
    <div class="slide-label">3 / 4</div>
    <div class="content">
      <div class="header">
        <div class="title-block">
          <div class="eyebrow">A股 · 股息率分析</div>
          <h1>近3年均值TOP10</h1>
          <div class="subtitle"></div>
        </div>
        <div class="meta">2026-06-01</div>
      </div>
      <h2>近3年均值TOP10<span class="sub">实时股息率 &amp; 排名 &amp; 行业 &amp; 扣非同比 &amp; 3年CAGR</span></h2>
      <table>
        <thead><tr><th>#</th><th>股票</th><th class="num">近3年均值</th><th class="num">实时</th><th class="num">实时排名</th><th>行业</th><th class="num">扣非同比</th><th class="num">3年CAGR</th></tr></thead>
        <tbody>{rows3}</tbody>
      </table>
    </div>
    <div class="footer">
      数据来源：dividend-select · 144只高股息A股样本<br>
      2026-06-01 · 仅供投资参考，不构成投资建议
    </div>
  </div>

  <div class="slide" id="slide4">
    <div class="slide-label">4 / 4</div>
    <div class="content">
      <div class="header">
        <div class="title-block">
          <div class="eyebrow">A股 · 股息率分析</div>
          <h1>近3年均值TOP10</h1>
                  </div>
        <div class="meta">2026-06-01</div>
      </div>
      <h2>昨收/M120比值<span class="sub">蓝色≥1.00，灰色&lt;1.00</span></h2>
      <figure>{svg2}</figure>
      <figcaption>蓝色表示价格站上M120均线，蓝色虚线为M120基准线</figcaption>
    </div>
    <div class="footer">
      数据来源：dividend-select · 144只高股息A股样本<br>
      2026-06-01 · 仅供投资参考，不构成投资建议
    </div>
  </div>

  <div class="dots">
    <div class="dot active" data-index="0"></div>
    <div class="dot" data-index="1"></div>
    <div class="dot" data-index="2"></div>
    <div class="dot" data-index="3"></div>
  </div>
</div>
<script>{CAROUSEL_JS}</script>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────────────────────
# Write all 6 files
# ─────────────────────────────────────────────────────────────────────────────
html_carousel = generate_carousel_html()
base = Path(__file__).parent
(base / "dividend_one_pager_a4.html").write_text(html_a4, encoding="utf-8")
(base / "dividend_slide01.html").write_text(html_slide01, encoding="utf-8")
(base / "dividend_slide02.html").write_text(html_slide02, encoding="utf-8")
(base / "dividend_slide03.html").write_text(html_slide03, encoding="utf-8")
(base / "dividend_slide04.html").write_text(html_slide04, encoding="utf-8")
(base / "dividend_carousel.html").write_text(html_carousel, encoding="utf-8")
(base / "dividend_one_pager.html").write_text(html_one_pager, encoding="utf-8")
print(f"Done: 7 files written to {base}")


def show(title, lst):
    print(f"\n-- {title} --")
    for i,s in enumerate(lst):
        r = f"ratio={s['ratio']:.3f}" if s.get("ratio") else "ratio=N/A"
        print(f"  {i+1}. {s['name']} ry={pct(s['ry'])} ay={pct(s['ay'])} kf={pct(s['kf'])} cg={pct(s['cg'])} {r} {s['ind']}")

show("实时TOP10", T10_ry)
show("近3年均值TOP10", T10_ay)