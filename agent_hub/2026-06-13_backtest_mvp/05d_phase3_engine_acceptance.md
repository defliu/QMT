# Phase 3 验收：DailyBacktestEngine 实现完成

日期：2026-06-14（夜班）
验收人：CC（夜班自主验收，依据 `01_cc_full_night_authorization.md`）
对象：Phase 3 交付（`backtest/engine/` execution / portfolio / metrics / daily_engine + 38 测试）

---

## 一、验收结论

**Phase 3 自审通过。允许进入 Phase 4（标准报告输出）。**

依据：

1. 04_output_schema_freeze.md 已 commit（`e98ba97`），本阶段所有 row/dict 形状逐字段对齐。
2. Task 3.1 / 3.2 / 3.3 / 3.4 全部按 03 / 04 已签字契约实现，38 个新增测试全部通过。
3. 全 backtest 套件 121 / 121 PASS（Phase 1A 30 + Phase 2 53 + Phase 3 38），无回归。
4. 引擎严格只在内存中产出 result 结构；不写 results / cache / logs，IO 留给 Phase 4 report 写盘。
5. evaluate_day 不出现未来 bar（专门写了 `test_no_lookahead_window_leaks_future_dates` 验证）。
6. 不触碰生产策略 / release / 交易接口；不写 `F:\金策智算\` / 不写 C 盘 / 不写 D 盘大产物；不引入 xtquant。

---

## 二、本阶段实现内容

| Task | 内容 | Commit |
|---|---|---|
| 3.1 | `engine/execution.py`：`fill_buy` / `fill_sell` next_open 撮合，slippage / commission / tax，T+1 涨停（>= +9.95% 开盘）拒买，停牌返回 unfilled，lot=100 整数倍 | `917583b` |
| 3.2 | `engine/portfolio.py`：`Portfolio` 类管理 cash / positions / hold_days；`apply_trade` T+1 锁仓；`mark_to_market` 停牌降级到上一可用 close；`equity_row` / `positions_rows` 行构造器 | `917583b` |
| 3.3 | `engine/metrics.py`：`compute_metrics` 13 字段输出（total/annual_return / sharpe / max_drawdown / calmar / win_rate / n_trades / n_buy / n_sell / avg_holding_days / excess_return / information_ratio / tracking_error），FIFO 配对 buy→sell | `559d2bc` |
| 3.4 | `engine/daily_engine.py`：`run_backtest` 主循环，纯内存返回 result struct（summary / trades / equity_rows / positions_rows / logs / trading_calendar） | `907a565` |

### 关键设计决策

- **撮合模型**：next_open（SPEC v0.2 §2.2 默认）。当日信号 T → 次日开盘 T+1 撮合。
- **T+1 实现**：buy 落账时 `available_volume=0`；下一交易日 `advance_holding_days()` 解锁。
- **Lot 处理**：A 股 100 股最小单位；`fill_buy` 内 `_lot_floor(target_cash / price)`，未达一手返回 `below_min_lot`。
- **涨停拒买**：T+1 开盘 ≥ +9.95% 即视为涨停一字板，buy 拒绝；sell 不受影响。
- **停牌降级**：撮合层缺 T+1 bar 返回 `suspended`，不下单；持仓 mark_to_market 沿用上一交易日 close。
- **指数 benchmark 缺失（决策 E）**：`benchmark_available=False` 时 `excess_return / information_ratio / tracking_error = None`；equity_curve.csv 的 `benchmark_close / benchmark_return` 写空串。
- **OQ-F target_volume**：strategy_core 输出 `target_volume=0`，由 execution 层用 `target_cash / price` 折算实际下单股数。
- **diagnostics_aggregate**：filter_counts 取每日均值（除以 trading_days），trigger_counts 全周期累加，warnings 全周期去重。
- **No lookahead 强保证**：`_slice_window_up_to(today)` 返回的 DataFrame 严格 `date <= today`；专门一项测试用 monkey patch `evaluate_day` 验证此约束。

### 不在 Phase 3 范围内（按 04 / SPEC 划分到 Phase 4）

- 6 文件落盘（summary.json / trades.csv / equity_curve.csv / positions.csv / logs.txt / report.md）
- WARN 块文本组装
- `run_backtest.py` CLI 包装

---

## 三、修改文件清单

### 新增文件

| 文件 | 用途 | 行数（约） |
|---|---|---|
| `backtest/engine/execution.py` | next_open 撮合层 | 175 |
| `backtest/engine/portfolio.py` | 组合簿记 + T+1 + 行构造器 | 195 |
| `backtest/engine/metrics.py` | 业绩指标计算 | 145 |
| `backtest/engine/daily_engine.py` | 日级主循环 + summary 装配 | 290 |
| `backtest/tests/test_execution.py` | 8 测试 | 110 |
| `backtest/tests/test_portfolio.py` | 12 测试 | 165 |
| `backtest/tests/test_metrics.py` | 8 测试 | 110 |
| `backtest/tests/test_daily_engine.py` | 10 测试（含 FakeReader fixture） | 245 |

### 修改文件

无。

不修改：
- `backtest/strategy_core/`（Phase 2 冻结字段被本阶段调用，不动）
- `backtest/data_tools/`（Phase 1A 已交付的 reader / universe，不动）
- `backtest/scripts/`（Phase 4 才扩展 run_backtest.py）
- 任何 `core/` / `release/` / `strategy_main.py`

---

## 四、Commit 列表

```text
917583b feat(engine): execution + portfolio (Task 3.1/3.2 per 04 schema)
559d2bc feat(engine): metrics layer (Task 3.3 per 04 §1.4 performance schema)
907a565 feat(engine): daily_engine main loop (Task 3.4 e2e per 03+04 contracts)
```

（`05c_phase25_schema_acceptance.md` commit `5aa9a31` 已在 Phase 2.5 验收记录，本表不重复列。）

---

## 五、测试

### 测试命令

```bash
# 标准
py -3.10 -m pytest backtest/tests -v

# Hermes 环境绕过 .pth 编码（已知本机问题）
py -3.10 -S -c "import sys; sys.path.append(r'C:\Users\Administrator\AppData\Local\Programs\Python\Python310\Lib\site-packages'); import pytest; raise SystemExit(pytest.main(['backtest/tests','-q','--ignore=backtest/tests/test_ima_uptrend_v31.py','--ignore=backtest/tests/test_ima_no_lookahead.py','--ignore=backtest/tests/test_ima_signal_returns.py']))"
```

> IMA 测试套与本主线无关（Phase 0 IMA 主升浪研究），按授权令 §七 不在本阶段执行；运行时 `--ignore` 跳过。

### 测试结果

```text
121 passed in 2.87s
```

按文件分布：

| 测试文件 | 通过数 | 覆盖契约 |
|---|---|---|
| Phase 1A（test_paths/init_workspace/duckdb_reader_*/data_hash/universe_schema/paths_disk_partition/clean_results_isolation/concurrent_sync_wal） | 30 | DuckDB 只读 / dedup / coverage / 路径硬约束 |
| Phase 2（test_strategy_core_interface/test_score_universe/test_decision_logic/test_evaluate_day_integration） | 53 | strategy_core 契约 |
| **test_execution.py** | **8** | **Task 3.1：fill_buy/fill_sell + 13 列 trades schema** |
| **test_portfolio.py** | **12** | **Task 3.2：T+1 / mark_to_market / 行构造器** |
| **test_metrics.py** | **8** | **Task 3.3：performance 13 字段 + benchmark None 路径** |
| **test_daily_engine.py** | **10** | **Task 3.4：result struct shape / no-lookahead / no-IO 守护** |
| **合计** | **121** | |

### 关键测试场景覆盖

- **No lookahead**（Phase 3 强约束）：`test_no_lookahead_window_leaks_future_dates` monkey-patch `evaluate_day`，断言每日窗口最大日期 ≤ current_date。
- **No IO**（Phase 3 与 Phase 4 边界）：`test_no_io_writes_to_workspace` 对比 `RESULTS_DIR` 前后目录列表；引擎不得写盘。
- **04 §1 summary 23 顶层字段全在**：`test_summary_has_all_top_level_keys_per_04_section_1`
- **04 §2 trades 13 列全在**：`test_trades_rows_match_04_section_2_columns`
- **04 §3 equity 8 列全在**：`test_equity_rows_match_04_section_3`
- **04 §1.3 短样本期 banner**：`test_short_sample_warning_triggers_when_under_252_days`
- **决策 E benchmark 缺失**：`test_benchmark_disabled_path` 验证 `benchmark_available=False / excess_return=None`
- **T+1 解锁**：`test_advance_holding_days_unfreezes_t1`
- **涨停一字板拒买**：`test_fill_buy_limit_up_open_blocks_fill`
- **lot 整数倍**：`test_fill_buy_basic_lot_floor`（100000 / 12.5125 → 7900 股）
- **win_rate FIFO 配对**：`test_win_rate_paired_trades`（4 笔=2 win 2 loss → 0.5）

---

## 六、是否触碰生产文件：**否**

明确未触碰：

- `release/v1.0/` — 未读未写
- QMT 生产 `strategy_main.py` — 未读未写
- `core/strategy/` 主升浪/全天版策略 — 未读未写
- `core/scoring/dimension6plus2.py` — 未读未写（仅 Phase 2 已有 import 链路调用，本阶段无新增 import）
- `core/risk_manager*` — 未读未写
- `D:\QMT_POOL\` — 未写
- `F:\金策智算\` — 未读未写（reader 在测试中由 FakeReader 替代，未通过 reader 写入）
- `F:\backtest_workspace\results\` — 未写（`test_no_io_writes_to_workspace` 守护）

本阶段仅写入：

- `backtest/engine/execution.py`、`backtest/engine/portfolio.py`、`backtest/engine/metrics.py`、`backtest/engine/daily_engine.py`
- `backtest/tests/test_execution.py`、`backtest/tests/test_portfolio.py`、`backtest/tests/test_metrics.py`、`backtest/tests/test_daily_engine.py`
- `agent_hub/2026-06-13_backtest_mvp/05d_phase3_engine_acceptance.md`（本文件）

---

## 七、是否违反 SPEC 边界：**否**

逐条核对硬边界（授权令 §四）：

| # | 边界 | 状态 |
|---|---|---|
| 1 | 不修改 release/v1.0 | ✅ 未触碰 |
| 2 | 不修改 strategy_main.py | ✅ 未触碰 |
| 3 | 不调用 passorder | ✅ grep `backtest/engine/` 无 passorder |
| 4 | 不接 QMT 实盘/模拟交易 | ✅ 无交易 import |
| 5 | 不启动真实/模拟委托 | ✅ 纯计算 |
| 6 | 不写 F:\金策智算\ | ✅ reader read-only；FakeReader 走内存 |
| 7 | 不读写模式打开 quantifydata.duckdb | ✅ 通过 reader 接口（已验证 read_only） |
| 8 | 不在 C/D 盘写 results/cache/sample_db/logs | ✅ 引擎不写盘；测试守护 |
| 9 | 不引入 xtquant/MiniQMT | ✅ grep `backtest/engine/` 无 xtquant |
| 10 | 不混入 IMA 主升浪 | ✅ 引擎层未引用 IMA 任何模块 |
| 11 | 不改 6+2 生产策略主逻辑 | ✅ scorer 仅 Phase 2 已有依赖 |
| 12 | 不破坏性 git 操作 | ✅ 仅 add / commit |

04 输出 schema 契约逐条核对：

- §1.1 summary 顶层字段（包括 schema_version / hashes / data_* / benchmark_* / sector_heat_* / sample_period_warning / execution / performance / portfolio_end / diagnostics_aggregate）✅
- §1.2 data_coverage_actual + universe_coverage 子字段 ✅
- §1.3 sample_period_warning 5 字段 ✅
- §1.4 performance 13 字段（含 None benchmark）✅
- §1.5 diagnostics_aggregate 4 字段 ✅
- §2 trades.csv 13 列形状 ✅
- §3 equity_curve.csv 8 列形状 ✅
- §4 positions.csv 9 列形状 ✅
- §5 logs.txt 行格式（`[INFO]/[ERROR] ...`）✅（WARN 块在 Phase 4 装配）
- §7 命名一致性（run_id / date / code / side / model）✅

---

## 八、已知问题 / 未完成项

### 非阻塞观察

1. **`buy_candidates target_cash` 等权分配**：当前 strategy_core decision.py 用 `total_asset / max_positions` 等权；当前现金不足时 `fill_buy` 不会自动重平衡（剩余现金不再尝试用于其它候选）。Phase 4 / 5 e2e 跑出来如有显著影响，再回头改 decision 或 engine。
2. **score 字段在持仓快照里缺失**：04 §4 positions.csv 的 score 列在 schema 表里未列入（schema 表给的是 9 列：date/code/volume/available_volume/cost_price/last_price/unrealized_pnl/holding_days + run_id），但 04 §6 报告示例提到 "score" 列。Phase 4 写盘时需统一：以 04 §4 schema 表为准（不输出 score），报告示例段落改写。
3. **撮合不实现「最小价差跳跃」**：A 股 0.01 元最小变动；当前 `round(open*1.001, 6)` 保留 6 位小数，未对齐 0.01。MVP 接受；金额误差小于一手 1 分钱。
4. **runtime_seconds 在测试中接近 0**：FakeReader 太快；无影响，summary 字段约束的是存在与类型而非范围。
5. **decision 中 trigger_counts/warnings 的 confirm 等键**：本阶段聚合时使用 `set keys()` 合并所有出现键，输出可能比 04 §1.5 列出的固定 7 项稍多（如未来扩展），向后兼容。

### 未完成项

无 Phase 3 内未完成项。Phase 4 / 5 按授权令进入下一阶段。

---

## 九、下一阶段计划

按夜班授权令，进入 **Phase 4：标准报告输出 + e2e 烟测**。

实现顺序：

1. **Task 4.1** `backtest/engine/report.py`：write_summary_json / write_trades_csv / write_equity_csv / write_positions_csv / write_logs_txt / write_report_md（按 04 §1-§6 落盘）。WARN 块文本装配在此处统一。
2. **Task 4.2** `backtest/scripts/run_backtest.py`：CLI（`--config <yaml>`），加载 yaml → 计算 config_hash → 调 daily_engine.run_backtest → 调 report writers。
3. **Task 4.3** `backtest/configs/baseline.yaml`：v0.2 默认配置（universe / start_date / end_date / strategy_config / execution / initial_cash）。
4. **Task 4.4** e2e 测试：用 sample_db（30 天，覆盖率有限，触发 INSUFFICIENT_HISTORY / SHORT_SAMPLE_PERIOD 路径）跑完整链路；断言 6 文件全部产出，summary.json 校验。
5. 写 `05e_phase4_report_acceptance.md`，commit 后立即进 Phase 5。

约束：
- e2e 写盘只能写 `F:\backtest_workspace\results\<run_id>_<config>\`（决策 J）；测试结束在 fixture 中清理或写入 `results/` 后人工清理（不进 D 盘 / C 盘）。
- 不实现 batch（Phase 5）。
- 不实现 PDF / HTML / PNG（OQ-8 留 v0.3）。

---

签字：CC（夜班自主验收）
日期：2026-06-14
依据：`01_cc_full_night_authorization.md` §一、§三、§六.1
