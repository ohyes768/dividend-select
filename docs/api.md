# dividend-select 接口文档

**服务地址**: `http://localhost:8092`

**基础路径**: `/api`

---

## 功能说明

股息率筛选服务提供 A 股高股息率股票的查询和技术指标分析功能。

---

## 接口列表

| 序号 | 端点 | 方法 | 功能 |
|------|------|------|------|
| 1 | `/` | GET | 服务信息 |
| 2 | `/health` | GET | 健康检查 |
| 3 | `/stocks` | GET | 获取股票列表 |
| 4 | `/stocks/{code}` | GET | 获取股票详情 |
| 5 | `/stats` | GET | 获取统计信息 |
| 6 | `/pe` | GET | 获取 PE/PB 数据 |
| 7 | `/pe/update` | POST | 更新 PE/PB 数据 |
| 8 | `/m120` | GET | 获取 M120 数据 |
| 9 | `/m120/refresh` | POST | 刷新 M120 数据 |
| 10 | `/m120/status` | GET | 获取 M120 数据状态 |
| 11 | `/board` | GET | 获取板块信息 |
| 12 | `/board/refresh` | POST | 刷新板块映射 |
| 13 | `/realtime-price` | POST | 获取实时价格 |
| 14 | `/realtime/refresh` | POST | 批量刷新实时价格 |
| 15 | `/stocks/info` | POST | 批量获取股票信息 |
| 16 | `/dividend/refresh` | POST | 刷新股息率数据 |
| 17 | `/dividend/status` | GET | 获取股息率数据状态 |

---

## 1. 服务信息

### 请求

| 属性 | 值 |
|------|-----|
| 方法 | GET |
| 路径 | `/` |

### 响应

```json
{
  "service": "dividend-select",
  "version": "1.0.0",
  "description": "A股高股息率TOP50查询工具 API",
  "docs": "/docs",
  "health": "/health"
}
```

---

## 2. 健康检查

### 请求

| 属性 | 值 |
|------|-----|
| 方法 | GET |
| 路径 | `/health` |

### 响应

```json
{
  "status": "healthy",
  "service": "dividend-select",
  "version": "1.0.0",
  "csv_exists": true,
  "total_records": 150
}
```

---

## 3. 获取股票列表

查询符合条件的股票列表。

### 请求

| 属性 | 值 |
|------|-----|
| 方法 | GET |
| 路径 | `/stocks` |

### 查询参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| min_yield | float | 5.0 | 最小股息率(%) |
| max_yield | float | - | 最大股息率(%) |
| exchange | string | - | 交易所筛选 |
| industry | string | - | 行业筛选 |
| index | string | - | 指数筛选 |
| sort_by | string | avg_yield_3y | 排序字段 |
| sort_order | string | desc | 排序方向(asc/desc) |

### 响应

```json
{
  "total": 36,
  "last_updated": "2026-05-27T20:00:00",
  "items": [
    {
      "code": "601857",
      "name": "中国石油",
      "exchange": "沪市主板",
      "source_index": "中证红利",
      "sw_level1": "石油石化",
      "sw_level2": "石油开采",
      "sw_level3": "油田服务",
      "concept_board": "中字头;央企改革;天然气",
      "industry_board": "石油石化",
      "avg_price_2025": 10.5,
      "dividend_2025": 0.5,
      "dividend_count_2025": 2,
      "yield_2025": 4.8,
      "avg_price_2024": 10.2,
      "dividend_2024": 0.45,
      "dividend_count_2024": 2,
      "yield_2024": 4.4,
      "avg_price_2023": 9.8,
      "dividend_2023": 0.4,
      "dividend_count_2023": 2,
      "yield_2023": 4.1,
      "avg_price_3y": 10.17,
      "avg_yield_3y": 4.43,
      "high_price_2025": 12.5,
      "low_price_2025": 8.2,
      "high_change_pct_2025": 22.9,
      "low_change_pct_2025": -19.4,
      "quarterly": {
        "q1": { "avg_price": 10.5, "dividend": 0.25, "yield_pct": 2.4 },
        "q2": { "avg_price": 10.6, "dividend": 0.25, "yield_pct": 2.4 },
        "q3": null,
        "q4": null
      }
    }
  ]
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| avg_price_xxxx | float | xxxx年平均股价（元） |
| dividend_xxxx | float | xxxx年分红金额（元/股） |
| dividend_count_xxxx | int | xxxx年分红次数 |
| yield_xxxx | float | xxxx年股息率(%) |
| avg_price_3y | float | 近3年平均股价 |
| avg_yield_3y | float | 近3年平均股息率(%) |
| quarterly | object | 近4个季度股息数据 |
| quarterly.q1~q4 | object | 季度数据，含 avg_price/dividend/yield_pct |
| shareholder_count | int | 股东户数 |
| shareholder_change_pct | float | 股东人数增幅(%) |
| per_share_holding | float | 人均持股数量 |
| gross_profit_margin | float | 主营业务利润率(%) |
| net_profit_margin | float | 净利率(%) |
| roe | float | 加权净资产收益率(%) |
| debt_asset_ratio | float | 资产负债率(%) |

---

## 4. 获取股票详情

获取单只股票的详细信息（含季度数据）。

### 请求

| 属性 | 值 |
|------|-----|
| 方法 | GET |
| 路径 | `/stocks/{code}` |

### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| code | string | 股票代码 |

### 响应

```json
{
  "data": {
    "code": "601857",
    "name": "中国石油",
    "exchange": "沪市主板",
    "source_index": "中证红利",
    "avg_yield_3y": 4.43,
    "yield_2025": 4.8,
    "yield_2024": 4.4,
    "yield_2023": 4.1
  },
  "quarterly": {
    "q1": { "avg_price": 10.5, "dividend": 0.25, "yield_pct": 2.4 },
    "q2": { "avg_price": 10.6, "dividend": 0.25, "yield_pct": 2.4 },
    "q3": null,
    "q4": null
  }
}
```

---

## 5. 获取统计信息

获取数据统计信息。

### 请求

| 属性 | 值 |
|------|-----|
| 方法 | GET |
| 路径 | `/stats` |

### 响应

```json
{
  "total_stocks": 150,
  "yield_stats": {
    "max": 8.5,
    "min": 1.2,
    "median": 4.2,
    "mean": 4.3
  },
  "yield_distribution": {
    "above_6": 25,
    "above_5": 50,
    "above_4": 80,
    "above_3": 120
  },
  "industry_distribution": {
    "银行": 30,
    "煤炭": 15,
    "钢铁": 10
  },
  "index_distribution": {
    "中证红利": 80,
    "中证红利质量": 35,
    "红利增长": 20
  },
  "csv_last_modified": "2026-05-27T20:00:00"
}
```

---

## 6. 获取 PE/PB 数据

获取股票的市盈率和市净率数据。

### 请求

| 属性 | 值 |
|------|-----|
| 方法 | GET |
| 路径 | `/pe` |

### 查询参数

| 参数 | 类型 | 说明 |
|------|------|------|
| code | string | 单只股票代码 |
| codes | string | 多只股票代码（逗号分隔） |
| force_refresh | bool | 是否强制刷新缓存（已废弃） |

> **注意**: 不传参数时返回空列表，避免返回全市场数据。

### 响应

```json
{
  "total": 2,
  "items": [
    {
      "code": "601857",
      "name": "中国石油",
      "pe": 6.69,
      "pb": 1.05,
      "market_cap": 1200000.0,
      "circulation_market_cap": 800000.0
    }
  ],
  "last_updated": "2026-05-27T12:00:00"
}
```

---

## 7. 更新 PE/PB 数据

从 akshare 获取最新的 PE/PB 数据并保存。

### 请求

| 属性 | 值 |
|------|-----|
| 方法 | POST |
| 路径 | `/pe/update` |

### 响应

```json
{
  "success": true,
  "count": 4500,
  "message": "PE 数据更新完成，共 4500 条记录"
}
```

> **注意**: 该操作可能需要 10-30 秒。

---

## 8. 获取 M120 数据

获取股票的 120 日均线、收盘价和偏离度数据。

### 请求

| 属性 | 值 |
|------|-----|
| 方法 | GET |
| 路径 | `/m120` |

### 查询参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| min_yield | float | 5.0 | 最小股息率(%) |
| sort_by | string | avg_yield_3y | 排序字段 |
| sort_order | string | desc | 排序方向(asc/desc) |

### 响应

```json
{
  "total": 35,
  "items": [
    {
      "code": "601857",
      "name": "中国石油",
      "avg_yield_3y": 4.43,
      "m120": 9.85,
      "close": 12.05,
      "deviation": 22.38
    }
  ],
  "last_updated": "2026-05-27T12:00:00"
}
```

### 字段说明

- `m120`: 120日均线值
- `close`: 昨日收盘价
- `deviation`: 收盘价与M120的偏离度(%)，公式：`(close - m120) / m120 * 100`

---

## 9. 刷新 M120 数据

获取所有股息率 > 3% 的股票的 M120 数据。

### 请求

| 属性 | 值 |
|------|-----|
| 方法 | POST |
| 路径 | `/m120/refresh` |

### 响应

```json
{
  "success": true,
  "message": "M120 数据刷新完成，成功更新 80 只股票",
  "count": 80
}
```

> **注意**: 该接口耗时较长，建议在非高峰期调用。

---

## 10. 获取 M120 数据状态

检查 M120 数据文件状态和文件是否存在。

### 请求

| 属性 | 值 |
|------|-----|
| 方法 | GET |
| 路径 | `/m120/status` |

### 响应

```json
{
  "file_exists": true,
  "last_updated": "2026-05-27T12:00:00",
  "total_records": 80
}
```

---

## 11. 获取板块信息

获取股票的概念板块和行业板块信息。

### 请求

| 属性 | 值 |
|------|-----|
| 方法 | GET |
| 路径 | `/board` |

### 查询参数

| 参数 | 类型 | 说明 |
|------|------|------|
| code | string | 单只股票代码 |
| codes | string | 多只股票代码（逗号分隔） |

> **注意**: 不传参数时返回空列表，避免返回全市场数据。

### 响应

```json
{
  "total": 2,
  "items": [
    {
      "code": "000333",
      "name": "美的集团",
      "concept_board": "AH股;HS300_;MSCI中国;人形机器人;价值股;家用电器;智能家居;...",
      "industry_board": "白色家电"
    }
  ],
  "last_updated": "2026-05-27T12:00:00"
}
```

---

## 12. 刷新板块映射

获取所有红利指数持仓股票的概念板块和行业板块信息，并保存到CSV文件。

### 请求

| 属性 | 值 |
|------|-----|
| 方法 | POST |
| 路径 | `/board/refresh` |

### 响应

```json
{
  "success": true,
  "message": "板块映射刷新完成",
  "stats": {
    "total_stocks": 150,
    "success_count": 145,
    "failed_count": 5,
    "file_path": "data/2026-05/个股板块映射.csv",
    "start_time": "2026-05-27T10:00:00",
    "end_time": "2026-05-27T10:03:30"
  }
}
```

### 注意事项

- 该接口耗时较长（约3-5分钟，取决于股票数量），建议每周或每月更新一次
- 并发调用时会返回 409 Conflict 错误

---

## 13. 获取实时价格

获取单只股票的实时收盘价和偏离度。

### 请求

| 属性 | 值 |
|------|-----|
| 方法 | POST |
| 路径 | `/realtime-price` |

### 请求体

```json
{
  "code": "601919",
  "m120": 14.80
}
```

### 响应

```json
{
  "code": "601919",
  "close": 15.78,
  "deviation": 6.6,
  "timestamp": "2026-05-27T10:30:00"
}
```

---

## 14. 批量获取股票信息

批量获取股票的行业/概念信息。

### 请求

| 属性 | 值 |
|------|-----|
| 方法 | POST |
| 路径 | `/stocks/info` |

### 请求体

```json
{
  "codes": ["601919", "601857"]
}
```

### 响应

```json
{
  "total": 2,
  "items": [
    {
      "code": "601919",
      "exchange": "沪市主板",
      "sw_level1": "交通运输",
      "sw_level2": "航运",
      "sw_level3": "港口",
      "concept_board": "一带一路;长三角一体化",
      "industry_board": "交通运输;港口"
    }
  ]
}
```

---

## 15. 刷新股息率数据

获取红利指数持仓、计算股息率并保存。支持增量更新（断点续传）。

### 请求

| 属性 | 值 |
|------|-----|
| 方法 | POST |
| 路径 | `/dividend/refresh` |

### 请求体

```json
{
  "min_dividend": 5
}
```

### 请求参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| min_dividend | int | 5 | 最小分红次数阈值 |

### 响应

```json
{
  "success": true,
  "message": "刷新完成，成功更新 20 只股票",
  "stats": {
    "total_processed": 150,
    "new_or_updated": 20,
    "skipped": 130,
    "file_path": "data/2026-05/近3年股息率汇总.csv",
    "start_time": "2026-05-27T10:00:00",
    "end_time": "2026-05-27T10:02:30"
  }
}
```

### 注意事项

- 该接口耗时较长（30秒-5分钟），建议在非高峰期调用
- 支持增量更新，自动跳过已处理的股票
- 并发调用时会返回 409 Conflict 错误

---

## 16. 获取股息率数据状态

检查股息率数据文件状态，判断是否需要更新。

### 请求

| 属性 | 值 |
|------|-----|
| 方法 | GET |
| 路径 | `/dividend/status` |

### 响应

```json
{
  "needs_update": false,
  "last_updated": "2026-05-27T20:00:00",
  "file_exists": true
}
```

### 字段说明

- `needs_update`: 是否需要更新（当月已更新过则不需要）
- `last_updated`: 上次更新时间
- `file_exists`: 文件是否存在

---

## 17. 批量刷新实时价格

批量刷新所有股息率 >= 4% 股票的实时价格。使用批量接口，一次API调用获取所有股票实时价格。

### 请求

| 属性 | 值 |
|------|-----|
| 方法 | POST |
| 路径 | `/realtime/refresh` |

### 响应

```json
{
  "success": true,
  "message": "实时价格刷新完成，成功更新 80 只股票",
  "count": 80
}
```

### 注意事项

- 该接口使用 comrms 批量接口，一次API调用获取所有股票实时价格
- 每日调用一次即可更新实时价格数据

---

## 前端 API 代理

前端通过 Next.js API Routes 代理请求到本服务，避免跨域问题。

| 前端路径 | 代理目标 |
|---------|---------|
| `/api/dividend/*` | `http://localhost:8092/api/*` |