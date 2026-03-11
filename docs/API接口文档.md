# A股高股息率TOP50查询工具 - API接口文档

## 1. 概述

本文档描述项目中所有对外暴露的 API 接口，包括类、方法和函数的调用规范。

**文档版本**: v1.0
**生成时间**: 2026-03-10
**状态**: 与代码实现同步

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

## 7. 数据源依赖

### 7.1 akshare API

| API | 用途 |
|-----|------|
| `ak.index_stock_cons_weight_csindex()` | 获取中证指数成分股 |
| `ak.stock_zh_a_hist()` | 获取股票历史价格（后复权） |
| `ak.stock_history_dividend_detail()` | 获取股票分红明细 |

### 7.2 efinance API

| API | 用途 |
|-----|------|
| `ef.stock.get_base_info()` | 获取股票基本信息（行业板块） |
| `ef.stock.get_belong_board()` | 获取股票所属概念板块 |

---

## 8. 输出文件

### 8.1 中间文件

| 文件 | 说明 | 生成方式 |
|------|------|----------|
| `红利指数持仓汇总.csv` | 四个红利指数的成分股汇总 | API获取或本地加载 |
| `股票分红次数汇总.csv` | 股票历史分红次数统计 | API获取或本地加载 |
| `个股板块映射.csv` | 股票概念板块和行业板块映射 | efinance API更新 |
| `个股申万行业映射.csv` | 股票申万三级分类 | 外部提供 |

### 8.2 最终输出

| 文件 | 说明 |
|------|------|
| `近3年股息率汇总.csv` | 完整的分析结果（增量写入） |

---

## 9. 错误处理

### 9.1 异常处理策略

| 场景 | 处理策略 |
|------|----------|
| 网络中断 | 记录警告，跳过该股票 |
| API限流 | 自动延时重试（1.5秒间隔） |
| 数据异常 | 使用默认值或标记为空 |
| 文件不存在 | 使用本地数据或提示错误 |

### 9.2 日志输出

- 日志文件: `logs/dividend.log`
- 日志级别: INFO
- 同时输出到控制台和文件

---

**文档结束**
