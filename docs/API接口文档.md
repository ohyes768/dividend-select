# A股高股息率TOP50查询工具 - API接口文档

## 1. 概述

本文档描述项目中所有对外暴露的 API 接口，包括类、方法和函数的调用规范。

**文档版本**: v1.5
**生成时间**: 2026-03-14
**状态**: 与代码实现同步

## API 变更记录

| 日期 | 版本 | 变更内容 |
|------|------|----------|
| 2026-03-14 | v1.5 | 新增实时股价查询接口和股票行业/概念信息查询接口；PE接口新增批量查询参数 |
| 2026-03-13 | v1.4 | M120 接口新增收盘价和偏离度字段 |
| 2026-03-13 | v1.3 | 新增 PE 数据获取 API 端点：获取股票市盈率、市净率等估值指标 |
| 2026-03-13 | v1.2 | 新增 M120 API 端点：获取股息率>3的股票的120日均线数据 |
| 2026-03-12 | v1.1 | 新增 Web API 端点；数据模型新增季度数据；移除分页功能 |
| 2026-03-10 | v1.0 | 初始版本 |

---

## 2. 数据模块 (src/data/)

### 2.1 IndexHoldingsFetcher - 红利指数持仓获取器

**位置**: `src/data/fetcher.py`

#### 2.1.1 初始化

```python
def __init__(self, use_local: bool = False)
```

**参数**:
- `use_local` (bool): 是否使用本地已有数据，默认 False

**示例**:
```python
# 使用API获取数据
fetcher = IndexHoldingsFetcher(use_local=False)

# 使用本地数据
fetcher = IndexHoldingsFetcher(use_local=True)
```

#### 2.1.2 获取单个指数持仓

```python
def fetch_index_holdings(self, index_code: str) -> Optional[pd.DataFrame]
```

**参数**:
- `index_code` (str): 指数代码，如 "000922"

**返回**:
- `pd.DataFrame` | `None`: 包含"股票代码"、"股票名称"列的 DataFrame

**支持的红利指数**:
| 代码 | 名称 |
|------|------|
| 000922 | 中证红利 |
| 932315 | 中证红利质量 |
| 932309 | 红利增长 |
| 931468 | 红利质量 |

#### 2.1.3 获取所有红利指数持仓

```python
def fetch_all_holdings(self) -> pd.DataFrame
```

**返回**:
- `pd.DataFrame`: 汇总后的 DataFrame，包含以下列：
  - 交易所
  - 股票代码
  - 股票名称
  - 来源指数
  - 来源指数代码
  - 纳入指数数量

#### 2.1.4 获取筛选后的股票列表

```python
def get_stock_list(self, min_dividend_count: int = 5) -> list[StockBasicInfo]
```

**参数**:
- `min_dividend_count` (int): 最小分红次数阈值，默认 5

**返回**:
- `list[StockBasicInfo]`: 筛选后的股票基本信息列表

**筛选条件**:
1. 沪深主板股票（排除科创板、创业板、北交所）
2. 历史累计分红次数 > min_dividend_count

---

### 2.2 BoardMappingFetcher - 板块映射获取器

**位置**: `src/data/board_fetcher.py`

#### 2.2.1 初始化

```python
def __init__(self)
```

**依赖文件**:
- `data/红利指数持仓汇总.csv` (输入)
- `data/个股板块映射.csv` (输出)

#### 2.2.2 更新板块映射

```python
def update(self, show_progress: bool = True) -> bool
```

**参数**:
- `show_progress` (bool): 是否显示进度信息，默认 True

**返回**:
- `bool`: 是否成功

**处理流程**:
1. 从 `红利指数持仓汇总.csv` 读取股票列表
2. 使用 efinance API 查询每只股票的概念板块和行业板块
3. 保存到 `个股板块映射.csv`

**输出格式**:
| 列名 | 说明 |
|------|------|
| 股票代码 | 6位股票代码 |
| 股票简称 | 股票名称 |
| 概念板块 | 分号分隔的概念板块列表 |
| 行业板块 | 分号分隔的行业板块列表 |

---

### 2.3 BoardInfoLoader - 板块信息加载器

**位置**: `src/data/board_loader.py`

#### 2.3.1 初始化

```python
def __init__(self)
```

**依赖文件**:
- `data/个股板块映射.csv`
- `data/个股申万行业映射.csv`

#### 2.3.2 获取单只股票板块信息

```python
def get_board_info(self, stock_code: str) -> BoardInfo
```

**参数**:
- `stock_code` (str): 股票代码

**返回**:
- `BoardInfo`: 板块信息对象

#### 2.3.3 批量获取板块信息

```python
def get_all_board_info(self, stock_codes: list[str]) -> dict[str, BoardInfo]
```

**参数**:
- `stock_codes` (list[str]): 股票代码列表

**返回**:
- `dict[str, BoardInfo]`: {股票代码: 板块信息}

---

### 2.4 数据模型 (src/data/models.py)

#### 2.4.1 StockBasicInfo

```python
@dataclass
class StockBasicInfo:
    code: str              # 股票代码
    name: str              # 股票名称
    exchange: str          # 交易所（沪市主板/深市主板）
    source_index: str      # 来源指数
    dividend_count: int    # 历史累计分红次数
```

#### 2.4.2 YearlyDividendData

```python
@dataclass
class YearlyDividendData:
    year: int                      # 年份
    avg_price: float               # 年平均股价
    dividend: float                # 年分红金额（元/股）
    dividend_times: int            # 年分红次数
    dividend_yield: float          # 年股息率 (%)
```

#### 2.4.3 QuarterlyDividendData

```python
@dataclass
class QuarterlyDividendData:
    year: int                      # 年份
    quarter: int                   # 季度 (1-4)
    avg_price: float               # 季度平均股价
    dividend: Optional[float]      # 季度分红金额（元/股）
    dividend_yield: Optional[float] # 季度股息率 (%)
```

#### 2.4.4 PriceVolatilityData

```python
@dataclass
class PriceVolatilityData:
    high_price: float          # 最高价
    low_price: float           # 最低价
    high_change_pct: float     # 最高价相对平均股价涨幅 (%)
    low_change_pct: float      # 最低价相对平均股价跌幅 (%)
```

#### 2.4.5 BoardInfo

```python
@dataclass
class BoardInfo:
    concept_boards: str        # 概念板块（分号分隔）
    industry_boards: str       # 行业板块（分号分隔）
    sw_level1: str             # 申万一级行业
    sw_level2: str             # 申万二级行业
    sw_level3: str             # 申万三级行业
```

#### 2.4.6 StockResult

```python
@dataclass
class StockResult:
    # 基本信息
    code: str
    name: str
    exchange: str
    source_index: str

    # 行业信息
    concept_boards: str = ""
    industry_boards: str = ""
    sw_level1: str = ""
    sw_level2: str = ""
    sw_level3: str = ""

    # 近3年年度数据
    yearly_data: dict[int, YearlyDividendData] = field(default_factory=dict)
    avg_price_3y: float = 0.0      # 近3年平均股价
    avg_yield_3y: float = 0.0      # 近3年平均股息率

    # 近4季度数据
    quarterly_data: dict[str, QuarterlyDividendData] = field(default_factory=dict)

    # 2025年波动数据
    volatility: Optional[PriceVolatilityData] = None

    def to_dict(self) -> dict:     # 转换为字典，用于CSV导出
```

---

## 3. 核心模块 (src/core/)

### 3.1 DividendCalculator - 股息率计算器

**位置**: `src/core/calculator.py`

#### 3.1.1 初始化

```python
def __init__(self)
```

**特性**:
- 自动缓存价格数据和分红数据
- 后复权价格计算股息率

#### 3.1.2 计算单只股票

```python
def calculate_stock(self, stock: StockBasicInfo) -> StockResult
```

**参数**:
- `stock` (StockBasicInfo): 股票基本信息

**返回**:
- `StockResult`: 完整的计算结果

**计算内容**:
1. 近3年（2023-2025）年度股息率
2. 近4季度（2025Q1-Q4）季度股息率
3. 2025年股价波动数据
4. 近3年平均股价和平均股息率

#### 3.1.3 批量计算

```python
def calculate_all(
    self,
    stock_list: list[StockBasicInfo],
    limit: int = 0,
    on_complete: Optional[Callable[[StockResult], None]] = None,
) -> list[StockResult]
```

**参数**:
- `stock_list` (list[StockBasicInfo]): 股票列表
- `limit` (int): 限制处理的股票数量，0表示不限制
- `on_complete` (Callable): 每完成一个计算的回调函数

**返回**:
- `list[StockResult]`: 计算结果列表

**特性**:
- 每只股票处理间隔 1.5 秒（避免 API 限流）
- 支持 on_complete 回调实现增量写入

---

## 4. 工具模块 (src/utils/)

### 4.1 helpers.py - 工具函数

**位置**: `src/utils/helpers.py`

#### 4.1.1 is_main_board

```python
def is_main_board(code) -> bool
```

**说明**: 判断是否为沪深主板股票

**主板规则**:
- 沪市主板: 600xxx, 601xxx, 603xxx, 605xxx
- 深市主板: 000xxx, 001xxx, 002xxx, 003xxx

**排除**:
- 科创板: 688xxx
- 创业板: 300xxx, 301xxx
- 北交所: 8xxxxx, 4xxxxx

#### 4.1.2 get_exchange

```python
def get_exchange(code) -> str
```

**说明**: 根据股票代码判断交易所

**返回值**:
- "沪市主板"
- "深市主板"
- "科创板"
- "创业板"
- "其他"

#### 4.1.3 load_csv_data

```python
def load_csv_data(filename: str) -> Optional[pd.DataFrame]
```

**说明**: 从 data 目录加载 CSV 文件

#### 4.1.4 save_csv_data

```python
def save_csv_data(df: pd.DataFrame, filename: str) -> bool
```

**说明**: 保存 DataFrame 到 data 目录的 CSV 文件

#### 4.1.5 append_csv_row

```python
def append_csv_row(row_data: dict, filename: str) -> bool
```

**说明**: 追加单行数据到 CSV 文件（用于增量写入）

#### 4.1.6 load_existing_codes

```python
def load_existing_codes(filename: str) -> set[str]
```

**说明**: 读取 CSV 中已存在的股票代码（用于断点续传）

#### 4.1.7 setup_logger

```python
def setup_logger(name: str, level: int = logging.INFO) -> logging.Logger
```

**说明**: 设置日志器，同时输出到文件和控制台

---

## 5. 展示模块 (display_results.py)

### 5.1 数据展示工具

**位置**: `display_results.py`

**用途**: 加载并展示 `data/近3年股息率汇总.csv` 中的股息率数据，支持多维度筛选和排序。

#### 5.1.1 命令行参数

```bash
uv run python display_results.py [选项]
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--top N` | 显示TOP N只股票 | 50 |
| `--min-yield X` | 最小股息率筛选(%) | 0 |
| `--industry NAME` | 按申万一级行业筛选 | 无 |

#### 5.1.2 核心函数

##### load_data()
```python
def load_data() -> pd.DataFrame
```

**说明**: 从 `data/近3年股息率汇总.csv` 加载数据

**返回**: DataFrame 或空DataFrame（文件不存在时）

---

##### display_top_stocks()
```python
def display_top_stocks(df: pd.DataFrame, top_n: int)
```

**说明**: 显示TOP N股票列表

**输出格式**:
```
排名  代码      名称      3年均值     2025      2024      2023      申万一级行业
```

---

##### display_statistics()
```python
def display_statistics(df: pd.DataFrame)
```

**说明**: 显示统计信息

**输出内容**:
- 股票总数
- 股息率范围
- 股息率中位数
- 股息率均值
- 股息率分布 (>= 8%, >= 6%, >= 5%, >= 4%)

---

##### display_industry_distribution()
```python
def display_industry_distribution(df: pd.DataFrame)
```

**说明**: 显示申万一级行业分布

**输出内容**:
- 行业名称
- 股票数量
- 占比

---

##### display_index_distribution()
```python
def display_index_distribution(df: pd.DataFrame)
```

**说明**: 显示来源指数分布

**输出内容**:
- 指数名称
- 股票数量
- 平均股息率

#### 5.1.3 使用示例

```bash
# 默认显示TOP50
uv run python display_results.py

# 显示TOP20
uv run python display_results.py --top 20

# 筛选股息率>=5%
uv run python display_results.py --min-yield 5

# 筛选银行股
uv run python display_results.py --industry 银行
```

---

## 6. 主程序接口 (main.py)

### 6.1 命令行参数

```bash
uv run python main.py [选项]
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--use-local` | 使用本地已有数据，跳过API获取 | False |
| `--limit N` | 限制处理的股票数量（测试用） | 0 |
| `--min-dividend N` | 最小分红次数阈值 | 5 |

### 6.2 使用示例

```bash
# 完整运行（API获取持仓+更新板块映射+API获取分红次数）
uv run python main.py

# 使用本地数据运行（推荐）
uv run python main.py --use-local

# 测试运行（限制3只股票）
uv run python main.py --use-local --limit 3

# 使用脚本运行
./scripts/run-local.sh
./scripts/test-run.sh
```

---

## 7. Web API 端点 (src/api/)

项目提供基于 FastAPI 的 Web API 服务，用于前端查询股息率数据。

### 7.1 服务启动

**启动方式**:
```bash
# 使用脚本启动
./scripts/dev.sh

# 或直接使用 uvicorn
uv run uvicorn src.main:app --reload --port 8000
```

**API 基础路径**: `http://localhost:8000/api`

### 7.2 端点列表

#### 7.2.1 健康检查

**端点**: `GET /api/health`

**说明**: 检查 API 服务状态

**响应**:
```json
{
  "status": "ok",
  "message": "Service is running"
}
```

---

#### 7.2.2 获取股票列表

**端点**: `GET /api/stocks`

**说明**: 获取股票列表（支持筛选、排序，无分页）

**查询参数**:

| 参数 | 类型 | 必填 | 说明 | 默认值 |
|------|------|------|------|--------|
| `min_yield` | float | 否 | 最小股息率(%) | - |
| `max_yield` | float | 否 | 最大股息率(%) | - |
| `exchange` | string | 否 | 交易所筛选 | - |
| `industry` | string | 否 | 行业筛选 | - |
| `index` | string | 否 | 来源指数筛选 | - |
| `sort_by` | string | 否 | 排序字段 | `avg_yield_3y` |
| `sort_order` | string | 否 | 排序方向(asc/desc) | `desc` |

**排序字段选项**:
- `avg_yield_3y` - 近3年平均股息率
- `yield_2025` - 2025年股息率
- `yield_2024` - 2024年股息率
- `yield_2023` - 2023年股息率
- `high_price_2025` - 2025年最高价
- `low_price_2025` - 2025年最低价
- `high_change_pct_2025` - 2025年最高涨幅(%)
- `low_change_pct_2025` - 2025年最低跌幅(%)

**响应**:
```json
{
  "total": 150,
  "items": [
    {
      "code": "600000",
      "name": "浦发银行",
      "exchange": "沪市主板",
      "industry": "银行",
      "source_index": "中证红利",
      "avg_yield_3y": 6.5,
      "yield_2025": 5.8,
      "yield_2024": 6.2,
      "yield_2023": 7.5,
      "high_price_2025": 12.5,
      "low_price_2025": 8.2,
      "high_change_pct_2025": 15.2,
      "low_change_pct_2025": -24.1,
      "quarterly": {
        "q1": {
          "avg_price": 10.5,
          "dividend": 0.32,
          "yield_pct": 3.0
        },
        "q2": null,
        "q3": null,
        "q4": null
      }
    }
  ]
}
```

---

#### 7.2.3 获取股票详情

**端点**: `GET /api/stocks/{code}`

**说明**: 获取单只股票详情（含季度数据）

**路径参数**:
- `code` - 股票代码（6位数字）

**响应**:
```json
{
  "code": "600000",
  "name": "浦发银行",
  "exchange": "沪市主板",
  "industry": "银行",
  "source_index": "中证红利",
  "avg_yield_3y": 6.5,
  "yield_2025": 5.8,
  "yield_2024": 6.2,
  "yield_2023": 7.5,
  "high_price_2025": 12.5,
  "low_price_2025": 8.2,
  "high_change_pct_2025": 15.2,
  "low_change_pct_2025": -24.1,
  "quarterly": {
    "q1": {
      "avg_price": 10.5,
      "dividend": 0.32,
      "yield_pct": 3.0
    },
    "q2": {
      "avg_price": 11.2,
      "dividend": 0.31,
      "yield_pct": 2.8
    },
    "q3": null,
    "q4": null
  }
}
```

---

#### 7.2.4 获取统计信息

**端点**: `GET /api/stats`

**说明**: 获取数据统计信息

**响应**:
```json
{
  "total_stocks": 150,
  "avg_yield_3y": 4.2,
  "median_yield_3y": 3.8,
  "max_yield_3y": 8.5,
  "min_yield_3y": 1.2,
  "industry_distribution": {
    "银行": 25,
    "煤炭": 15,
    "钢铁": 10,
    "交通运输": 12
  },
  "index_distribution": {
    "中证红利": 80,
    "中证红利质量": 35,
    "红利增长": 20,
    "红利质量": 15
  }
}
```

---

#### 7.2.5 获取 M120 股票列表

**端点**: `GET /api/m120`

**说明**: 批量获取股息率>3的股票的120日均线数据，同时返回最新收盘价和偏离度。适用于 n8n 定时调用。

**查询参数**:

| 参数 | 类型 | 必填 | 说明 | 默认值 |
|------|------|------|------|--------|
| `min_yield` | float | 否 | 最小股息率(%) | 3.0 |
| `sort_by` | string | 否 | 排序字段 | `avg_yield_3y` |
| `sort_order` | string | 否 | 排序方向(asc/desc) | `desc` |

**响应**:
```json
{
  "total": 80,
  "items": [
    {
      "code": "600000",
      "name": "浦发银行",
      "avg_yield_3y": 6.5,
      "m120": 9.85,
      "close": 10.20,
      "deviation": 3.55
    }
  ],
  "last_updated": "2026-03-13T10:30:00"
}
```

**字段说明**:
- `m120`: 120日均线值
- `close`: 最新收盘价
- `deviation`: 收盘价与M120的偏离度(%)，计算公式：(close - m120) / m120 * 100

---

#### 7.2.6 刷新 M120 数据

**端点**: `POST /api/m120/refresh`

**说明**: 刷新所有股息率>3的股票的120日均线数据。该接口耗时较长，建议在非高峰期调用。

**响应**:
```json
{
  "success": true,
  "message": "M120 数据刷新完成，成功更新 80 只股票",
  "count": 80
}
```

---

#### 7.2.7 获取 PE 数据

**端点**: `GET /api/pe`

**说明**: 获取股票 PE/PB 数据。

**查询参数**:

| 参数 | 类型 | 必填 | 说明 | 默认值 |
|------|------|------|------|--------|
| `code` | string | 否 | 股票代码（查询单只股票） | - |
| `codes` | string | 否 | 股票代码列表，逗号分隔（批量查询） | - |
| `force_refresh` | boolean | 否 | 是否强制刷新缓存（已废弃） | false |

**注意**:
- `code` 和 `codes` 参数不能同时使用
- 不传任何参数时返回所有股票的 PE 数据（使用缓存，1小时有效期）
- 传入 `code` 参数时返回指定股票的 PE 数据
- 传入 `codes` 参数时（如 "600000,600001,600002"）返回批量查询结果

**响应**:
```json
{
  "total": 5000,
  "items": [
    {
      "code": "600000",
      "name": "浦发银行",
      "pe": 5.2,
      "pb": 0.6,
      "market_cap": 2500000.0,
      "circulation_market_cap": 2450000.0
    }
  ],
  "last_updated": "2026-03-13T10:30:00"
}
```

---

#### 7.2.8 获取实时股价

**端点**: `POST /api/realtime/price`

**说明**: 根据股票代码和 M120 值获取最新收盘价和偏离度。用于 n8n 定时调用，获取股票的实时价格数据。

**请求体**:
```json
{
  "code": "600000",
  "m120": 9.85
}
```

**请求参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `code` | string | 是 | 股票代码（6位数字） |
| `m120` | float | 是 | 120日均线值 |

**响应**:
```json
{
  "code": "600000",
  "close": 10.20,
  "deviation": 3.55,
  "timestamp": "2026-03-14T15:00:00"
}
```

**字段说明**:
- `close`: 最新收盘价
- `deviation`: 收盘价与M120的偏离度(%)，计算公式：(close - m120) / m120 * 100
- `timestamp`: 数据获取时间

---

#### 7.2.9 批量获取股票行业/概念信息

**端点**: `POST /api/stocks/info`

**说明**: 批量查询股票的申万行业、概念板块、行业板块等信息。

**请求体**:
```json
{
  "codes": ["600000", "600001", "600002"]
}
```

**请求参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `codes` | array<string> | 是 | 股票代码列表（至少1个） |

**响应**:
```json
{
  "items": [
    {
      "code": "600000",
      "exchange": "沪市主板",
      "sw_level1": "银行",
      "sw_level2": "银行",
      "sw_level3": "股份制银行",
      "concept_board": "高股息;中证红利",
      "industry_board": "银行"
    }
  ],
  "total": 3
}
```

**字段说明**:
- `exchange`: 交易所（沪市主板/深市主板）
- `sw_level1/2/3`: 申万一/二/三级行业
- `concept_board`: 概念板块（分号分隔）
- `industry_board`: 行业板块

---

### 7.3 数据模型 (src/api/models.py)

#### 7.3.1 DividendStock

```python
class DividendStock(BaseModel):
    code: str                      # 股票代码
    name: str                      # 股票名称
    exchange: Optional[str]        # 交易所
    industry: Optional[str]        # 行业
    source_index: Optional[str]    # 来源指数
    avg_yield_3y: Optional[float]  # 近3年平均股息率(%)
    yield_2025: Optional[float]    # 2025年股息率(%)
    yield_2024: Optional[float]    # 2024年股息率(%)
    yield_2023: Optional[float]    # 2023年股息率(%)
    high_price_2025: Optional[float]   # 2025年最高价
    low_price_2025: Optional[float]    # 2025年最低价
    high_change_pct_2025: Optional[float]   # 2025年最高涨幅(%)
    low_change_pct_2025: Optional[float]    # 2025年最低跌幅(%)
    quarterly: Optional[QuarterlyData]   # 季度数据
```

#### 7.3.2 QuarterlyData

```python
class QuarterlyData(BaseModel):
    q1: Optional[Quarter]    # 第一季度
    q2: Optional[Quarter]    # 第二季度
    q3: Optional[Quarter]    # 第三季度
    q4: Optional[Quarter]    # 第四季度
```

#### 7.3.3 Quarter

```python
class Quarter(BaseModel):
    avg_price: Optional[float]   # 平均股价
    dividend: Optional[float]    # 分红金额(元/股)
    yield_pct: Optional[float]   # 股息率(%)
```

#### 7.3.4 StockListResponse

```python
class StockListResponse(BaseModel):
    total: int                       # 总记录数
    items: list[DividendStock]       # 股票列表
```

#### 7.3.5 StockDetailResponse

```python
class StockDetailResponse(BaseModel):
    stock: DividendStock    # 股票详情
```

#### 7.3.6 StatsResponse

```python
class StatsResponse(BaseModel):
    total_stocks: int                           # 股票总数
    avg_yield_3y: Optional[float]               # 近3年平均股息率
    median_yield_3y: Optional[float]            # 近3年中位数股息率
    max_yield_3y: Optional[float]               # 近3年最大股息率
    min_yield_3y: Optional[float]               # 近3年最小股息率
    industry_distribution: dict[str, int]       # 行业分布
    index_distribution: dict[str, int]          # 指数分布
```

#### 7.3.7 M120Stock

```python
class M120Stock(BaseModel):
    code: str                      # 股票代码
    name: str                      # 股票名称
    avg_yield_3y: Optional[float]  # 3年平均股息率(%)
    m120: Optional[float]          # 120日均线
    close: Optional[float]         # 最新收盘价
    deviation: Optional[float]     # 收盘价与M120的偏离度(%)
```

#### 7.3.8 M120ListResponse

```python
class M120ListResponse(BaseModel):
    total: int                       # 总记录数
    items: list[M120Stock]           # 股票列表
    last_updated: Optional[str]      # 数据最后更新时间
```

#### 7.3.9 StockPE

```python
class StockPE(BaseModel):
    code: str                          # 股票代码
    name: str                          # 股票名称
    pe: Optional[float]                # 市盈率(PE)
    pb: Optional[float]                # 市净率(PB)
    market_cap: Optional[float]        # 总市值(万元)
    circulation_market_cap: Optional[float]  # 流通市值(万元)
```

#### 7.3.10 StockPEResponse

```python
class StockPEResponse(BaseModel):
    total: int                       # 总记录数
    items: list[StockPE]             # 股票PE列表
    last_updated: Optional[str]      # 数据最后更新时间
```

#### 7.3.11 RealtimePriceRequest

```python
class RealtimePriceRequest(BaseModel):
    code: str              # 股票代码
    m120: float            # 120日均线值
```

#### 7.3.12 RealtimePriceResponse

```python
class RealtimePriceResponse(BaseModel):
    code: str                          # 股票代码
    close: Optional[float]             # 最新收盘价
    deviation: Optional[float]         # 偏离度(%)
    timestamp: Optional[str]           # 数据获取时间
```

#### 7.3.13 StockInfo

```python
class StockInfo(BaseModel):
    code: str                          # 股票代码
    exchange: Optional[str]            # 交易所
    sw_level1: Optional[str]           # 申万一级行业
    sw_level2: Optional[str]           # 申万二级行业
    sw_level3: Optional[str]           # 申万三级行业
    concept_board: Optional[str]       # 概念板块
    industry_board: Optional[str]      # 行业板块
```

#### 7.3.14 StockInfoRequest

```python
class StockInfoRequest(BaseModel):
    codes: list[str]         # 股票代码列表（至少1个）
```

#### 7.3.15 StockInfoResponse

```python
class StockInfoResponse(BaseModel):
    items: list[StockInfo]   # 股票信息列表
    total: int               # 总记录数
```

---

## 8. 服务模块 (src/services/)

### 8.1 PEDataService - PE数据服务

**位置**: `src/services/pe_service.py`

#### 8.1.1 初始化

```python
def __init__(self)
```

**特性**:
- 内置1小时缓存机制
- 自动从 akshare 获取全市场 PE/PB 数据

#### 8.1.2 获取所有PE数据

```python
def fetch_all_pe_data(self, force_refresh: bool = False) -> pd.DataFrame
```

**参数**:
- `force_refresh` (bool): 是否强制刷新缓存

**返回**:
- `pd.DataFrame`: 包含以下列的 DataFrame
  - `code`: 股票代码
  - `name`: 股票名称
  - `pe`: 市盈率
  - `pb`: 市净率
  - `market_cap`: 总市值(万元)
  - `circulation_market_cap`: 流通市值(万元)

#### 8.1.3 根据代码列表获取PE数据

```python
def get_pe_by_codes(self, codes: list[str], force_refresh: bool = False) -> pd.DataFrame
```

**参数**:
- `codes` (list[str]): 股票代码列表
- `force_refresh` (bool): 是否强制刷新缓存

#### 8.1.4 获取单只股票PE数据

```python
def get_pe_by_code(self, code: str, force_refresh: bool = False) -> Optional[pd.Series]
```

**参数**:
- `code` (str): 股票代码
- `force_refresh` (bool): 是否强制刷新缓存

**返回**:
- `pd.Series` | `None`: 股票PE数据 Series

#### 8.1.5 清除缓存

```python
def clear_cache(self)
```

---

### 8.2 M120Service - M120数据服务

**位置**: `src/services/m120_service.py`

#### 8.2.1 初始化

```python
def __init__(self)
```

**特性**:
- 从 akshare 获取股票历史价格数据
- 计算 120 日均线（MA120）
- 获取最新收盘价并计算与 M120 的偏离度

#### 8.2.2 计算单只股票M120数据

```python
def calculate_m120(self, code: str) -> Optional[dict]
```

**参数**:
- `code` (str): 6位股票代码

**返回**:
- `dict` | `None`: 包含以下字段的字典
  - `m120`: 120日均线值
  - `close`: 最新收盘价
  - `deviation`: 收盘价与M120的偏离度(%) = (close - m120) / m120 * 100

#### 8.2.3 批量更新M120数据

```python
def update_m120_data(self, codes: list[str], show_progress: bool = True) -> int
```

**参数**:
- `codes` (list[str]): 股票代码列表
- `show_progress` (bool): 是否显示进度

**返回**:
- `int`: 成功更新的数量

#### 8.2.4 读取M120数据

```python
def read_m120_data(self) -> dict[str, dict]
```

**返回**:
- `dict[str, dict]`: {股票代码: {"m120": float, "close": float, "deviation": float}} 字典

#### 8.2.5 获取文件修改时间

```python
def get_file_mtime(self) -> Optional[float]
```

**返回**:
- `float` | `None`: Unix 时间戳，文件不存在返回 None

#### 8.2.6 检查文件是否存在

```python
def check_file_exists(self) -> bool
```

**返回**:
- `bool`: 文件是否存在

---

### 8.3 RealtimePriceService - 实时股价服务

**位置**: `src/services/realtime_service.py`

#### 8.3.1 初始化

```python
def __init__(self)
```

**特性**:
- 从 akshare 获取股票实时分时数据
- 返回最新收盘价
- 根据收盘价和 M120 计算偏离度

#### 8.3.2 获取实时收盘价

```python
def get_realtime_close(self, code: str) -> Optional[float]
```

**参数**:
- `code` (str): 6位股票代码

**返回**:
- `float` | `None`: 最新收盘价，失败返回 None

#### 8.3.3 计算偏离度

```python
def calculate_deviation(self, close: float, m120: float) -> Optional[float]
```

**参数**:
- `close` (float): 最新收盘价
- `m120` (float): 120日均线值

**返回**:
- `float` | `None`: 偏离度(%) = (close - m120) / m120 * 100

#### 8.3.4 获取服务单例

```python
def get_realtime_service() -> RealtimePriceService
```

**返回**:
- `RealtimePriceService`: 服务实例单例

---

### 8.4 StockInfoService - 股票信息服务

**位置**: `src/services/stock_info_service.py`

#### 8.4.1 初始化

```python
def __init__(self, data_reader)
```

**参数**:
- `data_reader` (DataReader): DataReader 实例

**特性**:
- 从本地数据文件批量查询股票的申万行业信息
- 批量查询股票的概念板块信息
- 批量查询股票的行业板块信息

#### 8.4.2 批量获取股票信息

```python
def get_stocks_info(self, codes: list[str]) -> dict[str, dict]
```

**参数**:
- `codes` (list[str]): 股票代码列表

**返回**:
- `dict[str, dict]`: {股票代码: {
    "sw_level1": str,
    "sw_level2": str,
    "sw_level3": str,
    "concept_board": str,
    "industry_board": str,
    "exchange": str,
}} 字典

#### 8.4.3 获取单只股票信息

```python
def get_stock_info(self, code: str) -> Optional[dict]
```

**参数**:
- `code` (str): 股票代码

**返回**:
- `dict` | `None`: 股票信息字典，如果不存在返回 None

#### 8.4.4 获取服务单例

```python
def get_stock_info_service(data_reader) -> StockInfoService
```

**参数**:
- `data_reader` (DataReader): DataReader 实例

**返回**:
- `StockInfoService`: 服务实例单例

---

## 9. 数据源依赖

### 9.1 akshare API

| API | 用途 |
|-----|------|
| `ak.index_stock_cons_weight_csindex()` | 获取中证指数成分股 |
| `ak.stock_zh_a_hist()` | 获取股票历史价格（后复权） |
| `ak.stock_history_dividend_detail()` | 获取股票分红明细 |
| `ak.stock_zh_a_spot_em()` | 获取A股实时行情（PE/PB等估值指标） |

### 9.2 efinance API

| API | 用途 |
|-----|------|
| `ef.stock.get_base_info()` | 获取股票基本信息（行业板块） |
| `ef.stock.get_belong_board()` | 获取股票所属概念板块 |

---

## 10. 输出文件

### 10.1 中间文件

| 文件 | 说明 | 生成方式 |
|------|------|----------|
| `红利指数持仓汇总.csv` | 四个红利指数的成分股汇总 | API获取或本地加载 |
| `股票分红次数汇总.csv` | 股票历史分红次数统计 | API获取或本地加载 |
| `个股板块映射.csv` | 股票概念板块和行业板块映射 | efinance API更新 |
| `个股申万行业映射.csv` | 股票申万三级分类 | 外部提供 |

### 10.2 最终输出

| 文件 | 说明 |
|------|------|
| `近3年股息率汇总.csv` | 完整的分析结果（增量写入） |
| `M120数据.csv` | 股息率>3的股票的120日均线数据（由 API 刷新） |

---

## 11. 错误处理

### 11.1 异常处理策略

| 场景 | 处理策略 |
|------|----------|
| 网络中断 | 记录警告，跳过该股票 |
| API限流 | 自动延时重试（1.5秒间隔） |
| 数据异常 | 使用默认值或标记为空 |
| 文件不存在 | 使用本地数据或提示错误 |

### 11.2 日志输出

- 日志文件: `logs/server.log`
- 日志级别: INFO
- 同时输出到控制台和文件

---

**文档结束**
