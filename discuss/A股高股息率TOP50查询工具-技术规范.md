# A股高股息率TOP50查询工具 - 技术规范文档

## 1. 概述

### 1.1 背景
用户需要一个Python命令行工具，能够快速获取A股市场上股息率排名前50的股票信息，并展示详细的分红计划。该工具主要用于投资决策参考，帮助用户识别高股息收益的优质标的。

### 1.2 目标
- **核心目标**：获取沪深主板市场股息率TOP50股票并展示分红计划
- **附加目标**：显示3年股息率趋势、公司基本信息、行业分类等辅助信息
- **非目标**：不提供投资建议、不包含实时行情推送、不支持Web界面

### 1.3 目标用户
个人投资者，用于快速筛选高股息股票进行投资分析。

## 2. 功能需求

### 2.1 核心功能

| 功能 | 描述 | 优先级 |
|------|------|--------|
| 股票数据获取 | 从akshare获取沪深主板股票列表及分红数据 | P0 |
| 股息率计算 | 基于最新年度分红和后复权收盘价计算股息率 | P0 |
| TOP50排名 | 按股息率从高到低排序，取前50名 | P0 |
| 分红计划展示 | 分组展示每只股票的详细分红信息 | P0 |
| 异常股票过滤 | 排除ST、停牌、退市风险等问题股票 | P0 |
| 3年趋势展示 | 显示近3年股息率变化趋势（↗↘→） | P1 |
| 辅助信息展示 | 显示公司名称、股价、市值、行业、市盈率 | P1 |

### 2.2 用户故事

**场景1：日常筛选高股息股票**
1. 用户运行 `python main.py`
2. 程序显示进度提示（获取数据、计算中...）
3. 终端以表格形式展示TOP50股票列表
4. 用户查看股息率排名和分红计划
5. 根据信息进行投资决策

**场景2：查看具体分红信息**
1. 用户在股票列表中找到感兴趣的股票
2. 查看下方的分红详情分组
3. 了解具体的分红金额、比例、日期等信息

### 2.3 功能依赖关系

```
数据获取 → 数据清洗 → 股息率计算 → 排名筛选 → 格式化输出
    ↓
分红数据获取 → 分红信息整理 → 分组展示
    ↓
历史数据获取 → 3年趋势计算 → 趋势展示
```

## 3. 技术决策

### 3.1 技术栈

| 类别 | 选择 | 理由 |
|------|------|------|
| 语言 | Python 3.11+ | 数据处理生态丰富 |
| 数据源 | akshare | 免费开源、数据全面、社区活跃 |
| 表格输出 | tabulate | 支持多种表格风格、轻量级 |
| 配置管理 | YAML | 人类可读、易于修改 |
| 依赖管理 | uv + pyproject.toml | 快速、现代、符合用户规范 |
| 测试框架 | pytest | Python标准测试框架 |

**依赖库清单**：
```
akshare          # 财经数据获取
pyyaml          # 配置文件解析
tabulate        # 表格格式化输出
pytest          # 单元测试
```

### 3.2 架构设计

#### 模块划分

```
dividend/
├── main.py                 # 程序入口
├── config/
│   ├── __init__.py
│   └── settings.yaml       # 配置文件
├── data/
│   ├── __init__.py
│   ├── fetcher.py          # 数据获取模块
│   ├── processor.py        # 数据处理模块
│   └── models.py           # 数据模型定义
├── display/
│   ├── __init__.py
│   └── formatter.py        # 输出格式化模块
└── tests/
    ├── __init__.py
    └── test_*.py           # 单元测试
```

#### 数据流向

```
用户启动 → main.py
    ↓
读取配置 → settings.yaml
    ↓
数据获取 → fetcher.fetch_stock_list()
           fetcher.fetch_dividend_data()
           fetcher.fetch_historical_data()
    ↓
数据处理 → processor.calculate_dividend_yield()
           processor.filter_stocks()
           processor.rank_stocks()
    ↓
格式化输出 → formatter.format_table()
           formatter.format_dividend_details()
    ↓
终端展示 → 用户查看结果
```

#### 关键接口设计

```python
# data/fetcher.py
class StockDataFetcher:
    def fetch_stock_list(self, market: str) -> list[StockInfo]
    def fetch_dividend_data(self, stock_code: str) -> DividendPlan
    def fetch_historical_yield(self, stock_code: str, years: int) -> list[float]

# data/processor.py
class StockDataProcessor:
    def calculate_dividend_yield(self, stock: StockInfo) -> float
    def filter_abnormal_stocks(self, stocks: list[StockInfo]) -> list[StockInfo]
    def rank_by_dividend_yield(self, stocks: list[StockInfo]) -> list[StockInfo]

# display/formatter.py
class TableFormatter:
    def format_stock_table(self, stocks: list[StockInfo]) -> str
    def format_dividend_group(self, stocks: list[StockInfo]) -> str
    def format_trend_symbol(self, trend: str) -> str
```

### 3.3 方案权衡记录

| 决策点 | 备选方案 | 最终选择 | 理由 | 潜在风险 |
|--------|----------|----------|------|----------|
| 数据源 | tushare/akshare/eastmoney | akshare | 免费、开源、数据全 | API可能限流 |
| 复权处理 | 复权/不复权 | 后复权 | 更准确反映真实收益率 | 计算复杂度略高 |
| 多次分红 | 累计/最近一次/年度 | 累计计算 | 反映真实年度分红总额 | 需要汇总多次数据 |
| 异常处理 | 自动降级/快速失败/缓存 | 快速失败 | 确保数据准确性 | 网络波动时体验差 |
| 进度提示 | 需要/不需要 | 需要 | 用户了解程序运行状态 | 增加代码复杂度 |

## 4. 数据设计

### 4.1 数据模型

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class StockInfo:
    """股票基本信息"""
    stock_code: str       # 股票代码
    stock_name: str       # 股票名称
    market: str           # 市场（沪市/深市）
    industry: str         # 行业分类
    market_cap: float     # 市值（亿元）
    current_price: float  # 当前股价（后复权）
    pe_ratio: float       # 市盈率
    dividend_yield: float # 股息率（%）

@dataclass
class DividendRecord:
    """单笔分红记录"""
    amount_per_share: float      # 每股分红金额
    dividend_ratio: float        # 分红比例（%）
    record_date: Optional[str]   # 股权登记日
    ex_date: Optional[str]       # 除权除息日
    pay_date: Optional[str]      # 派息日
    dividend_type: str           # 分红方式（现金/股票）

@dataclass
class DividendPlan:
    """分红计划（完整信息）"""
    stock_code: str
    year: int
    records: list[DividendRecord]
    total_amount: float          # 累计分红金额
    policy_note: Optional[str]   # 分红政策说明

@dataclass
class TrendData:
    """趋势数据"""
    stock_code: str
    yields: list[float]          # 近3年股息率
    trend_symbol: str            # 趋势符号（↗/↘/→）
```

### 4.2 数据字典

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| stock_code | str | 股票代码，6位数字 | "600519" |
| stock_name | str | 股票名称 | "贵州茅台" |
| market | str | 市场标识 | "沪市主板" |
| dividend_yield | float | 股息率，百分比 | 5.23 |
| trend_symbol | str | 趋势符号 | "↗" |

### 4.3 状态管理

本应用为无状态命令行工具，无需持久化状态管理。

## 5. UI/UX 设计

### 5.1 界面设计

#### 股票列表表格

```
┌──────────┬──────────┬────────┬──────────┬────────┬──────────┬──────────┐
│ 排名     │ 股票代码 │ 股票名称│ 股息率(%)│ 市值(亿)│ 行业     │ 3年趋势  │
├──────────┼──────────┼────────┼──────────┼────────┼──────────┼──────────┤
│ 1        │ 600XXX   │ XX银行 │ 8.52     │ 15230  │ 银行     │ ↗        │
│ 2        │ 000XXX   │ XX煤炭 │ 7.83     │ 890    │ 煤炭     │ →        │
└──────────┴──────────┴────────┴──────────┴────────┴──────────┴──────────┘
```

#### 分红详情分组

```
=== 分红计划详情 ===

[600XXX] XX银行
├── 2023年度分红
│   ├── 分红方式: 现金分红
│   ├── 分红金额: 10派5.2元
│   ├── 分红比例: 52%
│   ├── 股权登记日: 2024-06-15
│   ├── 除权除息日: 2024-06-16
│   └── 派息日: 2024-06-20
└── 分红政策: 每年分红比例不低于30%

[000XXX] XX煤炭
├── 2023年度分红
│   ├── 分红方式: 现金分红
│   ├── 分红金额: 10派3.8元
│   ├── 分红比例: 38%
│   └── 关键日期: 暂未公布
└── 数据说明: 部分数据暂未公布
```

#### 元数据展示

```
---
数据更新时间: 2024-03-09 15:30:00
数据来源: akshare
统计信息: 共筛选 4850 只股票，排除 127 只异常股票
---
```

### 5.2 交互设计

#### 进度提示

```
[1/5] 正在获取股票列表...
[2/5] 正在获取分红数据...
[3/5] 正在计算股息率...
[4/5] 正在排名筛选...
[5/5] 正在格式化输出...
```

#### 错误提示

```
错误: 获取股票数据失败
原因: 连接超时（5秒）
提示: 请检查网络连接后重试
```

### 5.3 响应式设计

终端表格宽度自适应：
- 自动检测终端宽度
- 超长文本自动截断
- 支持中文对齐

## 6. 非功能需求

### 6.1 性能要求

| 指标 | 要求 |
|------|------|
| 响应时间 | < 30秒（含数据获取） |
| 单次API超时 | 5秒 |
| 重试次数 | 3次 |
| 重试间隔 | 2秒 |

### 6.2 安全要求

| 要求 | 说明 |
|------|------|
| 输入验证 | 配置文件参数校验 |
| 数据验证 | 必填字段非空检查 |
| 异常处理 | 所有异常被捕获并友好提示 |

### 6.3 可维护性

| 要求 | 说明 |
|------|------|
| 代码规范 | 遵循PEP 8 |
| 类型注解 | 所有公共函数添加类型注解 |
| 测试覆盖 | 核心逻辑单元测试覆盖率 > 70% |
| 文档 | 关键函数添加docstring |

## 7. 边缘情况与错误处理

### 7.1 异常场景

| 场景 | 处理策略 |
|------|----------|
| 网络中断 | 自动重试3次，失败后快速失败 |
| API限流 | 等待2秒后重试 |
| 数据异常 | 标记为"-"或"暂无数据"，继续处理 |
| 配置错误 | 提示配置文件错误并退出 |

### 7.2 边界条件

| 条件 | 处理方式 |
|------|----------|
| 股票数量 < 50 | 显示所有可用股票 |
| 无分红数据 | 标记"暂无数据" |
| 股息率 = 0 | 正常显示，不排除 |
| 股息率 > 100% | 数据异常，标记并排除 |

### 7.3 降级策略

| 场景 | 策略 |
|------|------|
| akshare完全不可用 | 快速失败，提示错误 |
| 部分数据缺失 | 标记缺失，继续运行 |
| 终端过窄 | 调整表格布局 |

## 8. 实施计划

### 8.1 开发阶段

1. **项目初始化** (阶段1)
   - 创建目录结构
   - 配置pyproject.toml
   - 创建配置文件模板

2. **数据模块开发** (阶段2)
   - 实现StockDataFetcher
   - 实现StockDataProcessor
   - 定义数据模型

3. **展示模块开发** (阶段3)
   - 实现TableFormatter
   - 实现进度提示
   - 实现错误提示

4. **主程序集成** (阶段4)
   - 实现main.py
   - 集成各模块
   - 端到端测试

5. **测试与完善** (阶段5)
   - 编写单元测试
   - 修复bug
   - 完善文档

### 8.2 测试策略

**单元测试**：
- `test_fetcher.py`: 测试数据获取逻辑
- `test_processor.py`: 测试股息率计算和过滤
- `test_formatter.py`: 测试表格格式化

**测试用例**：
- 正常数据获取
- 网络异常处理
- 数据缺失处理
- ST股票过滤
- 排序正确性

### 8.3 部署计划

**运行环境**：
- Python 3.11+
- 网络连接（访问akshare API）

**运行步骤**：
```bash
# 1. 安装依赖
uv sync

# 2. 运行程序
python main.py
```

## 9. 风险与依赖

### 9.1 技术风险

| 风险 | 等级 | 缓解措施 |
|------|------|----------|
| akshare API限流 | 中 | 重试机制、5秒超时 |
| 数据结构变化 | 中 | 版本锁定、异常捕获 |
| 计算准确性 | 高 | 后复权处理、数据验证 |

### 9.2 外部依赖

| 依赖 | 风险 | 应对 |
|------|------|------|
| akshare | API变更 | 定期更新、监控公告 |
| 网络连接 | 不稳定 | 重试机制 |
| Python环境 | 兼容性 | 指定最低版本3.11+ |

## 10. 附录

### 10.1 用户访谈记录

#### 关键决策点

1. **数据源选择**
   - 用户选择：akshare
   - 理由：免费开源，无需积分

2. **复权处理**
   - 用户选择：需要后复权
   - 理由：准确反映真实收益率

3. **异常处理**
   - 用户选择：快速失败
   - 理由：确保数据准确性

4. **多次分红**
   - 用户选择：累计计算
   - 理由：反映真实年度分红总额

#### 放弃的方案

- tushare：需要积分，成本高
- eastmoney：爬虫方式不稳定
- Web界面：需求是命令行工具

### 10.2 参考资料与灵感来源

- [akshare官方文档](https://akshare.akfamily.xyz/)
- [A股分红数据说明](https://www.eastmoney.com/)
- PEP 8 Python代码风格指南

### 10.3 术语表

| 术语 | 说明 |
|------|------|
| 股息率 | 每股分红 ÷ 股价 × 100% |
| 后复权 | 以除权后的价格为基准，向前调整历史价格 |
| 除权除息日 | 分红后股价下调的日期 |
| TTM | Trailing Twelve Months，最近12个月 |
| ST股票 | 特别处理股票，存在退市风险 |

---

**文档版本**: v1.0
**生成时间**: 2024-03-09
**状态**: 待用户确认后开始实施
