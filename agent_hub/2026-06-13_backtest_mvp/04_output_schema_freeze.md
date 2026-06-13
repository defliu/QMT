# Phase 2.5 GATE：输出 schema 冻结文档

日期：2026-06-14（夜班）
作者：CC
状态：CC 自审签字（夜班授权下不等 Hermes，依据 `01_cc_full_night_authorization.md` §三）
对应 SPEC：`SPEC_BACKTEST_MVP_OFFLINE_FACTORY_v0.2.md` §3.x / §7
对应接口：`03_interface_freeze.md` §6 diagnostics

---

## 0. 本文件定位

- **冻结回测产物的 6 文件输出 schema**，作为 Phase 3 / 4 实现的契约源头。
- 字段名 / 类型 / 单位在 v0.2 实现期内**不可破坏性变更**；如需变更，需重新跑 GATE。
- 下游 RS / 报告解析工具按本文 schema 解析。

输出位置（决策 J 强制）：

```text
F:\backtest_workspace\results\{run_id}_{config_name}\
  summary.json          # 顶层元数据 + 业绩指标 + 复现指纹
  report.md             # 人类可读报告（含样本期警告横幅）
  trades.csv            # 逐笔成交
  equity_curve.csv      # 净值曲线
  positions.csv         # 每日持仓快照
  logs.txt              # 运行日志（首部 WARN 块 + INFO/DEBUG/ERROR）
```

`run_id` 格式：`YYYYMMDD_HHMMSS_<short_hash>`（SPEC §2.6.1）。

---

## 1. summary.json — 顶层 schema

```json
{
  "summary_schema_version": "0.2",

  "run_id":           "20260614_023045_a3f9c2",
  "run_started_at":   "2026-06-14T02:30:45+08:00",
  "runtime_seconds":  47.32,
  "config_name":      "baseline",
  "results_dir":      "F:/backtest_workspace/results/20260614_023045_a3f9c2_baseline",
  "strategy_core_version": "0.2.0",

  "config_hash":     "<sha256 hex>",
  "data_hash":       "<sha256 hex of 11 fields>",
  "universe_hash":   "<sha256 hex of sorted universe>",

  "data_source":     "jince_zhisuan",
  "data_path":       "F:/金策智算/_internal/databases/duckdb/quantifydata.duckdb",
  "data_mtime":      "2026-05-06T23:59:00",
  "data_adjustment": "hfq",
  "data_coverage_actual": {
    "min_date":            "2025-08-01",
    "max_date":            "2026-02-27",
    "n_codes":             5197,
    "n_rows_after_dedup":  701352,
    "dedup_count":         18620,
    "universe_coverage": {
      "universe_size":     10,
      "codes_with_data":   10,
      "codes_missing":     [],
      "missing_count":     0
    }
  },
  "data_dedup_applied":              true,
  "data_concurrent_sync_warning":    false,
  "data_wal_detected":               false,
  "data_wal_warning_message":        "",

  "benchmark_code":      null,
  "benchmark_available": false,
  "benchmark_note":      "DuckDB 当前无指数数据，benchmark 已禁用",

  "sector_heat_available": false,
  "sector_heat_mode":      "zero",
  "sector_heat_warning":   "historical sector heat unavailable; sector score set to 0",

  "sample_period_warning": {
    "is_short_sample":  true,
    "requested_range":  ["2025-09-01", "2026-02-27"],
    "actual_range":     ["2025-09-01", "2026-02-27"],
    "trading_days":     119,
    "warning":          "样本期约 6 个月，仅用于 MVP 管线验证，不可作为策略最终定论"
  },

  "execution": {
    "price":            "next_open",
    "slippage":         0.001,
    "commission_rate":  0.00025,
    "tax_rate":         0.0001
  },

  "performance": {
    "total_return":      0.0532,
    "annual_return":     0.1147,
    "max_drawdown":     -0.0421,
    "sharpe":            1.12,
    "calmar":            2.72,
    "win_rate":          0.547,
    "n_trades":          82,
    "n_buy":             45,
    "n_sell":            37,
    "avg_holding_days":  6.3,

    "excess_return":     null,
    "information_ratio": null,
    "tracking_error":    null
  },

  "portfolio_end": {
    "total_asset":  1053200.0,
    "cash":         123456.78,
    "market_value": 929743.22,
    "n_positions":  4
  },

  "diagnostics_aggregate": {
    "trigger_counts_total": {
      "early_stop": 1, "early_kick": 0, "stop_loss": 2,
      "score_drop": 0, "replace": 1, "warning": 0, "confirm": 0
    },
    "filter_counts_avg_per_day": {
      "blocked_min_score": 12.4,
      "blocked_min_core":  3.1,
      "blocked_max_bias5": 8.0,
      "blocked_max_daily_pct": 2.0,
      "blocked_already_held":  5.0,
      "blocked_limit_up":      1.0,
      "blocked_suspended":     0.0,
      "blocked_insufficient_history": 0.0,
      "candidate_total":       200.0,
      "candidate_passed":      169.0
    },
    "unfilled_order_count": 0,
    "warnings_unique":      ["fundamentals not available; valuation uses scorer default"]
  }
}
```

### 1.1 顶层字段约束

| 字段 | 类型 | 单位 | 必填 | 来源 | 备注 |
|---|---|---|---|---|---|
| summary_schema_version | str | — | ✅ | 引擎常量 | 固定 `"0.2"` |
| run_id | str | — | ✅ | engine | `YYYYMMDD_HHMMSS_<short_hash>` 格式 |
| run_started_at | str | ISO8601+08:00 | ✅ | engine | 含时区 |
| runtime_seconds | float | 秒 | ✅ | engine | 主循环耗时 |
| config_name | str | — | ✅ | yaml `backtest.name` | |
| results_dir | str | — | ✅ | engine | F 盘绝对路径 |
| strategy_core_version | str | — | ✅ | engine 常量 | v0.2 固定 `"0.2.0"` |
| config_hash | str | sha256 hex | ✅ | hashing.compute_config_hash | yaml 文本哈希 |
| data_hash | str | sha256 hex | ✅ | hashing.compute_data_hash | 11 字段（决策 F） |
| universe_hash | str | sha256 hex | ✅ | hashing.compute_universe_hash | sorted codes |
| **data_source** | str | — | ✅ | engine | **OPEN_QUESTION（v0.3）**：v0.2 固定 `"jince_zhisuan"`；v0.3 决策后改名（OQ-2） |
| data_path | str | — | ✅ | reader.db_path | |
| data_mtime | str | ISO8601 | ✅ | reader._db_mtime | DuckDB 文件 mtime |
| data_adjustment | str | — | ✅ | yaml `data.adjustment` | 固定 `"hfq"` |
| data_coverage_actual | object | — | ✅ | reader.coverage(codes,…) | 见 §1.2 |
| data_dedup_applied | bool | — | ✅ | 引擎常量 | 固定 `true` |
| data_concurrent_sync_warning | bool | — | ✅ | reader.wal_detected | |
| data_wal_detected | bool | — | ✅ | reader.wal_detected | 与上等价，便于程序读取 |
| data_wal_warning_message | str | — | ✅ | reader.wal_warning_message | 缺省 `""` |
| benchmark_code | str/null | — | ✅ | yaml | v0.2 默认 null（决策 E） |
| benchmark_available | bool | — | ✅ | engine | reader 加载基准为空时 false |
| benchmark_note | str | — | ✅ | engine | 默认 `"DuckDB 当前无指数数据，benchmark 已禁用"` |
| sector_heat_available | bool | — | ✅ | engine | v0.2 zero 模式恒 false |
| sector_heat_mode | str | — | ✅ | yaml | v0.2 仅 `"zero"` |
| sector_heat_warning | str | — | ✅ | engine | 固定 `"historical sector heat unavailable; sector score set to 0"` |
| sample_period_warning | object | — | ✅ | engine | 见 §1.3 |
| execution | object | — | ✅ | yaml `execution` 段回显 | |
| performance | object | — | ✅ | metrics.compute_metrics | 见 §1.4 |
| portfolio_end | object | — | ✅ | engine 收尾 | |
| diagnostics_aggregate | object | — | ✅ | engine 累计 | 见 §1.5 |

### 1.2 data_coverage_actual 字段

| 字段 | 类型 | 必填 | 备注 |
|---|---|---|---|
| min_date | str (YYYY-MM-DD) | ✅ | reader 全表覆盖最早日 |
| max_date | str | ✅ | reader 全表覆盖最晚日 |
| n_codes | int | ✅ | 全表 distinct code 数 |
| n_rows_after_dedup | int | ✅ | 去重后总行数 |
| dedup_count | int | ✅ | 去重剔除的行数 |
| universe_coverage | object | ✅ | universe 维度覆盖 |
| ↳ universe_size | int | ✅ | universe CSV 解析后 code 数 |
| ↳ codes_with_data | int | ✅ | 实际有数据的 code 数 |
| ↳ codes_missing | list[str] | ✅ | 完全无数据的 code 列表（保持 universe 顺序） |
| ↳ missing_count | int | ✅ | == len(codes_missing) |

### 1.3 sample_period_warning 字段

触发条件（满足任一）：

1. 实际样本期 < 12 个月（约 252 个交易日）
2. `benchmark_available == false`

| 字段 | 类型 | 备注 |
|---|---|---|
| is_short_sample | bool | 触发 = true |
| requested_range | [str, str] | yaml `start_date / end_date` |
| actual_range | [str, str] | reader 加载到的实际日期范围 |
| trading_days | int | reader.trading_calendar 长度 |
| warning | str | v0.2 默认 `"样本期约 N 个月，仅用于 MVP 管线验证，不可作为策略最终定论"` |

### 1.4 performance 字段

| 字段 | 类型 | 单位 | 计算口径 |
|---|---|---|---|
| total_return | float | 比率 | (end_total_asset / initial_cash) - 1 |
| annual_return | float | 比率/年 | total_return * (252 / trading_days) （简化年化） |
| max_drawdown | float | 比率（负数） | min((equity[i] - peak[i]) / peak[i]) |
| sharpe | float | — | mean(daily_return) / std(daily_return) * sqrt(252)；rf=0 |
| calmar | float | — | annual_return / abs(max_drawdown)；max_drawdown=0 时 null |
| win_rate | float | 比率 | 卖出交易中盈利占比（按完整 buy→sell 配对计）|
| n_trades | int | — | trades.csv 总行数（buy + sell） |
| n_buy | int | — | side=='buy' 行数 |
| n_sell | int | — | side=='sell' 行数 |
| avg_holding_days | float | 天 | 完整买卖对的平均持有交易日 |
| excess_return | float/null | 比率 | benchmark_available=false 时 **null** |
| information_ratio | float/null | — | benchmark_available=false 时 **null** |
| tracking_error | float/null | — | benchmark_available=false 时 **null** |

### 1.5 diagnostics_aggregate 字段

| 字段 | 类型 | 备注 |
|---|---|---|
| trigger_counts_total | object | 7 项 sell reason 全周期触发次数累加 |
| filter_counts_avg_per_day | object | 10 项 filter 每日平均（除以 trading_days） |
| unfilled_order_count | int | next_open 模型下因停牌/区间末日丢弃的信号数 |
| warnings_unique | list[str] | 全周期去重后的 warning 集合 |

---

## 2. trades.csv — 逐笔成交

```csv
run_id,date,code,side,volume,price,amount,slippage_amt,commission,tax,reason,layer,model
20260614_023045_a3f9c2,2025-09-15,000001.SZ,buy,1000,12.51,12510.00,12.51,3.13,0.00,top_candidate,,next_open
20260614_023045_a3f9c2,2025-09-22,000001.SZ,sell,1000,11.50,11500.00,11.50,2.88,1.15,stop_loss,bottom_line,next_open
```

| 列 | 类型 | 单位 | 必填 | 备注 |
|---|---|---|---|---|
| run_id | str | — | ✅ | 与 summary.run_id 一致；便于 batch 级 join |
| date | str | YYYY-MM-DD | ✅ | 成交日（next_open 模型下 = 信号日 + 1）|
| code | str | — | ✅ | 标准化后缀 `.SZ`/`.SH` |
| side | str | — | ✅ | `buy` 或 `sell` |
| volume | int | 股 | ✅ | 必为 100 整数倍 |
| price | float | 元 | ✅ | 已含滑点；buy=open*(1+slippage)，sell=open*(1-slippage) |
| amount | float | 元 | ✅ | volume * price |
| slippage_amt | float | 元 | ✅ | 滑点带来的额外成本（绝对值） |
| commission | float | 元 | ✅ | commission_rate * amount |
| tax | float | 元 | ✅ | 仅 sell 行：tax_rate * amount；buy 行 = 0 |
| reason | str | — | ✅ | buy: `top_candidate`/`replace_target`；sell: 7 种 enums.SELL_REASON_* |
| layer | str | — | ⏸ | sell 行必填（bottom_line/confirm/warning）；buy 行为空 |
| model | str | — | ✅ | `next_open` 或 `close` |

约束：

1. CSV UTF-8 with BOM。
2. 表头一行；首字段必为 `run_id`。
3. 浮点数保留 6 位小数（避免精度漂移）；整数无小数。
4. 同日同 code 的 buy 与 sell 各占一行（不合并）。
5. 单价 0 或负数时拒写并 logs 报错。

---

## 3. equity_curve.csv — 净值曲线

```csv
run_id,date,total_asset,cash,market_value,daily_return,benchmark_close,benchmark_return
20260614_023045_a3f9c2,2025-09-01,1000000.0,1000000.0,0.0,0.0,,
20260614_023045_a3f9c2,2025-09-02,1003200.0,500000.0,503200.0,0.0032,,
```

| 列 | 类型 | 单位 | 必填 | 备注 |
|---|---|---|---|---|
| run_id | str | — | ✅ | |
| date | str | YYYY-MM-DD | ✅ | 交易日（reader.trading_calendar 内） |
| total_asset | float | 元 | ✅ | cash + sum(volume * close) |
| cash | float | 元 | ✅ | 期末可用现金 |
| market_value | float | 元 | ✅ | 持仓市值 |
| daily_return | float | 比率 | ✅ | (total_asset[i] - total_asset[i-1]) / total_asset[i-1]；首日 0.0 |
| benchmark_close | float/empty | 元 | ⏸ | benchmark_available=false 时空字符串 |
| benchmark_return | float/empty | 比率 | ⏸ | 同上；首日 0.0；之后用差分 |

约束：

1. 首行 daily_return = 0.0。
2. benchmark 列在 benchmark_available=false 时整列空（不写 NaN，写空串便于 CSV 解析）。
3. 行数 = trading_days。

---

## 4. positions.csv — 每日持仓快照

```csv
run_id,date,code,volume,available_volume,cost_price,last_price,unrealized_pnl,holding_days
20260614_023045_a3f9c2,2025-09-15,000001.SZ,1000,0,12.51,12.51,0.0,1
20260614_023045_a3f9c2,2025-09-16,000001.SZ,1000,1000,12.51,12.65,140.0,2
```

| 列 | 类型 | 单位 | 必填 | 备注 |
|---|---|---|---|---|
| run_id | str | — | ✅ | |
| date | str | YYYY-MM-DD | ✅ | 交易日 |
| code | str | — | ✅ | 持仓标的 |
| volume | int | 股 | ✅ | 当日总持仓 |
| available_volume | int | 股 | ✅ | T+1：当日新买入为 0 |
| cost_price | float | 元 | ✅ | 含买入滑点+佣金分摊后的执行价（与 trades.buy.price 一致） |
| last_price | float | 元 | ✅ | 当日 close（停牌延续上一交易日） |
| unrealized_pnl | float | 元 | ✅ | (last_price - cost_price) * volume，未扣卖出费 |
| holding_days | int | 交易日 | ✅ | 含建仓日；建仓 T 日 = 1 |

约束：

1. 持仓为空的交易日不写入（行数 ≠ trading_days * max_positions）。
2. 同日多个 code 各占一行。
3. 卖出当日**不写**（仅写期末仍持有的）。

---

## 5. logs.txt — 运行日志

### 5.1 首部 WARN 块（强制，SPEC §7.5）

```text
[WARN] SHORT_SAMPLE_PERIOD requested=2025-09-01..2026-02-27 actual=2025-09-01..2026-02-27 trading_days=119 message="样本期约 6 个月，仅用于 MVP 管线验证，不可作为策略最终定论"
[WARN] BENCHMARK_DISABLED reason="DuckDB 当前无指数数据"
[WARN] DATA_DEDUP_APPLIED count=18620
[WARN] SECTOR_HEAT_MODE_ZERO message="sector_heat_mode=zero, sector score forced to 0"
```

WAL 检测命中时插入：

```text
[WARN] DATA_WAL_DETECTED message="检测到 quantifydata.duckdb.wal，金策智算可能正在同步数据。本次回测的 data_hash 在同步完成前不稳定"
```

### 5.2 INFO/DEBUG/ERROR 行格式

```text
[INFO]  2025-09-01 evaluate_day candidates=200 passed=169 sell=0 buy=2
[INFO]  2025-09-02 fill buy 000001.SZ vol=1000 price=12.51 amt=12510.00
[ERROR] 2025-09-22 unfilled_order code=300999.SZ reason=suspended
[INFO]  2026-02-27 run_complete trading_days=119 trades=82 final_total=1053200
```

约束：

1. 每行格式 `[LEVEL] <YYYY-MM-DD> <message>` 或 WARN 块格式 `[WARN] <CODE> key=value …`。
2. 编码 UTF-8（无 BOM）。
3. WARN 块顺序固定：SHORT_SAMPLE_PERIOD → BENCHMARK_DISABLED → DATA_DEDUP_APPLIED → SECTOR_HEAT_MODE_ZERO →（条件性）DATA_WAL_DETECTED。
4. WARN 后空行分隔。
5. 不含 ANSI 颜色码。

### 5.3 logs WARN 触发条件矩阵

| WARN code | 条件 | 是否必出 |
|---|---|---|
| SHORT_SAMPLE_PERIOD | trading_days < 252 OR benchmark_available=false | v0.2 默认必出 |
| BENCHMARK_DISABLED | benchmark_available=false | v0.2 默认必出 |
| DATA_DEDUP_APPLIED | dedup_count > 0 | v0.2 默认必出 |
| SECTOR_HEAT_MODE_ZERO | sector_heat_mode=="zero" | v0.2 默认必出 |
| DATA_WAL_DETECTED | reader.wal_detected==true | 仅 wal 命中时 |

---

## 6. report.md — 人类可读报告

### 6.1 必有段落（按顺序）

```markdown
# Backtest Report — {config_name}

> ⚠️ **样本期警告**
>
> 本回测样本区间 `2025-09-01 ~ 2026-02-27`，约 6 个月（119 个交易日），
> **仅用于 MVP 管线验证**，**不可作为策略最终定论**。
>
> 缺失数据：2024 全年 / 2025-01 ~ 2025-07 / 2026-02-28 至今。
> 数据补全后请重跑完整回测再做策略评估。

## Run 元信息

| 项 | 值 |
|---|---|
| run_id | 20260614_023045_a3f9c2 |
| run_started_at | 2026-06-14T02:30:45+08:00 |
| runtime_seconds | 47.32 |
| config_hash | a3f9c2... |
| data_hash | b481d5... |
| universe_hash | f019aa... |
| data_source | jince_zhisuan |

## 业绩指标

| 指标 | 值 |
|---|---|
| total_return | 5.32% |
| annual_return | 11.47% |
| max_drawdown | -4.21% |
| sharpe | 1.12 |
| calmar | 2.72 |
| win_rate | 54.7% |
| n_trades | 82 |

## 持仓概览

| code | volume | cost | last | pnl |
|---|---|---|---|---|
| 000001.SZ | 1000 | 12.51 | 13.20 | 690.0 |
| ... | ... | ... | ... | ... |

## 关键日志摘录

最近 10 条 WARN/ERROR 日志（自动摘录）。

## 数据元信息

- data_path: F:/金策智算/_internal/databases/duckdb/quantifydata.duckdb
- data_mtime: 2026-05-06T23:59:00
- data_adjustment: hfq
- coverage: 2025-08-01 ~ 2026-02-27, 5197 codes
- universe_coverage: 10/10 codes have data
- benchmark: disabled (DuckDB 无指数数据)
- sector_heat: zero mode

## 复现命令

```bash
py -3.10 -m backtest.scripts.run_backtest --config backtest/configs/baseline.yaml
```
```

### 6.2 横幅触发

`sample_period_warning.is_short_sample == true` 时**强制**输出顶部横幅；不可关闭。

### 6.3 不输出 PDF / HTML

v0.2 仅 markdown；后续版本可加 mkdocs 渲染。

---

## 7. 字段命名一致性约束（贯穿 6 文件）

| 概念 | 字段名 | 出现位置 |
|---|---|---|
| run 标识 | `run_id` | 6 文件全部第一列/字段 |
| 交易日 | `date`（YYYY-MM-DD 字符串） | trades / equity / positions |
| 标的 | `code`（标准化后缀） | trades / positions |
| 成交方向 | `side`（buy/sell） | trades |
| 成交模型 | `model`（next_open/close） | trades / summary.execution.price |
| 评分字段（diagnostics）| `score_volumeprice`（不是 `score_volume`） | summary.diagnostics_aggregate / 内部传递 |
| sell reason 字符串 | enums.SELL_REASON_* 的值 | trades.reason / summary.diagnostics_aggregate.trigger_counts_total |
| sell layer | `bottom_line`/`confirm`/`warning` | trades.layer |
| blocked reason | enums.BLOCKED_* 的值 | summary.diagnostics_aggregate.filter_counts_avg_per_day key 前缀 `blocked_` |
| 数据 hash | `data_hash` | summary 顶层 |
| 配置 hash | `config_hash` | summary 顶层 |
| universe hash | `universe_hash` | summary 顶层 |

---

## 8. OPEN_QUESTIONS（v0.3 待决策，v0.2 不实现）

| # | 问题 | v0.2 处置 | v0.3 决策方向 |
|---|---|---|---|
| OQ-2 | summary.json `data_source` 字段命名 | v0.2 固定 `"jince_zhisuan"`；下游不应硬编码 | v0.3 改为 `"qmt_self_owned"` / `"merged"` 或新增 `data_provenance` 字段 |
| OQ-7 | trades.csv 是否需要 `lot`（手数）列 | v0.2 不加，volume 即可 | v0.3 如做 etf/科创板差异化再加 |
| OQ-8 | report.md 是否输出图表（净值曲线 PNG） | v0.2 仅 markdown 表格 | v0.3 用 matplotlib 嵌入 PNG |

> 在 v0.2 提交的 summary.json / report.md / 内部代码中，凡涉及 OQ-2 的位置需在注释中明确标记 `# OPEN_QUESTION: data_source naming pending v0.3`。

---

## 9. 与 SPEC v0.2 章节对照

| 本文 | SPEC v0.2 章节 |
|---|---|
| §1 summary.json | §3.1 / §3.3.1 / §3.3.2 / §1.6 / §2.6 |
| §2 trades.csv | §2.2 execution / §2.4 benchmark 缺失 |
| §3 equity_curve.csv | §2.4 benchmark 缺失（空列） |
| §4 positions.csv | §3.3.3 trading_calendar |
| §5 logs.txt | §7.5 |
| §6 report.md | §7.1 / §7.2 / §7.3 |
| §7 字段命名一致性 | 03_interface_freeze §6 (score_volumeprice / 7 sell reasons / 8 blocked) |
| §8 OPEN_QUESTIONS | SPEC §9 + §3.5（data_source 命名占位） |

---

## 10. 验收 / 签字栏

### 10.1 字段同意

```text
☑ §1 summary.json 顶层 23 字段 + 子对象 OK
☑ §2 trades.csv 13 列 OK
☑ §3 equity_curve.csv 8 列 OK
☑ §4 positions.csv 9 列 OK
☑ §5 logs.txt WARN 块格式 OK
☑ §6 report.md 段落顺序 OK
☑ §7 字段命名一致性 OK
☑ §8 OPEN_QUESTIONS 标记 OK
```

### 10.2 总决议

```text
☑ Phase 2.5 输出 schema 冻结通过，CC 可进入 Phase 3 实现
☐ 需修订
```

签字：CC（夜班自主签字，依据 `01_cc_full_night_authorization.md` §三）
日期：2026-06-14

补充说明：本文已完成 Phase 2.5 GATE。后续 Phase 3 / Phase 4 实现必须按本 schema 执行；如需破坏性变更，必须重新提交 Phase 2.5 GATE 并写 BLOCKED 文件等待 Hermes / 诚哥决策。
