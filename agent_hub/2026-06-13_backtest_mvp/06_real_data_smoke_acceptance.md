# 真实数据 smoke 回测验收：v0.2 MVP 在金策智算 DuckDB 上跑通

日期：2026-06-14（夜班）
验收人：CC（夜班自主验收，依据诚哥 2026-06-14 授权令补充：免 Hermes 验收）
对象：v0.2 MVP 在真实 `F:/金策智算/_internal/databases/duckdb/quantifydata.duckdb` 上的端到端冒烟

---

## 一、验收结论

**v0.2 MVP 在真实数据上端到端跑通。**

依据：

1. `validate_data.py` 探得 DuckDB 覆盖 2025-08-01..2026-02-27（211 天，5197 代码，db_mtime=2026-05-06，无 WAL，dedup_count=18620）。
2. 单 leaf：`baseline.yaml`（25 天）和 `_real_smoke_4m.yaml`（67 交易日）均跑通；后者产出 4 笔真实交易（2 买 2 卖），逻辑闭环：60-bar 历史窗口 2026-02-11 积满 → 立刻命中 `top_candidate` 评分通过 → next_open T+1 成交 → 9 个交易日后 `score_drop`/`warning` 触发卖出 → 6 文件全产出。
3. 批量：`_real_smoke_grid.yaml` 4 leaves（max_positions × min_score）顺序执行，每 leaf 0.5–0.6 秒，汇总 `real_smoke_grid_<ts>.csv` 列序与 `_BATCH_COLS`（24 列）完全一致。
4. WARN 块顺序按 04 §5.1 严格输出：`SHORT_SAMPLE_PERIOD → BENCHMARK_DISABLED → DATA_DEDUP_APPLIED → SECTOR_HEAT_MODE_ZERO`（无 WAL 命中，正确省略）。
5. 12 条硬边界全部保留：仅 read_only 访问 `F:/金策智算/`；写盘只到 `F:/backtest_workspace/{results,batch_summary,logs}/`；C/D 盘大产物零写入；passorder/xtquant/MiniQMT 零引用。

---

## 二、本次执行内容

| 步骤 | 命令 | 输出 |
|---|---|---|
| 1. 数据探针 | `validate_data.build_report(JINCE_DB)` | 覆盖 2025-08-01..2026-02-27、5197 codes、dedup=18620、wal=False |
| 2. 单 leaf baseline | `run_backtest --config baseline.yaml`（25 天） | 全 INSUFFICIENT_HISTORY，0 交易（前期窗口不足，符合预期） |
| 3. 单 leaf 真实 4m | `run_backtest --config _real_smoke_4m.yaml`（67 交易日） | 4 trades, total_return=-0.31%, sharpe=-0.58, max_dd=-0.99% |
| 4. 批量 4 leaves | `run_batch --experiment _real_smoke_grid.yaml` | 4 leaves × 67 days，2.1s 总耗时，1 个 batch_summary CSV |
| 5. 全套件回归 | `pytest backtest/tests` | **150/150 PASS** |

### 单 leaf 真实回测细节（`real_4m`）

- **样本期**：2025-11-15..2026-02-27（67 trading_days，约 3.2 个月）
- **runtime**：0.516s
- **performance**：
  - total_return = -0.003125（-0.31%）
  - max_drawdown = -0.009854（-0.99%）
  - sharpe = -0.581
  - calmar = -1.193
  - n_trades=4, n_buy=2, n_sell=2, win_rate=0.0, avg_holding_days=1.5
- **portfolio_end**：cash=996874.72, market_value=0, n_positions=0
- **trigger_counts_total**：`{warning: 2, score_drop: 2, 其他: 0}`
- **关键时间线**：
  - 2025-11-17 → 2026-02-10：每日 candidates=10、passed=0（60-bar 历史窗口未满，全部 INSUFFICIENT_HISTORY，符合 strategy_core 设计）
  - 2026-02-11：windows 首次积满 60 bar，2026-02-12 next_open 买入 002594.SZ（比亚迪）
  - 2026-02-13：next_open 买入 300750.SZ（宁德时代）
  - 2026-02-24：两只均触发 `score_drop`（warning layer），同日 next_open 卖出
- **行为闭环**：T+1 买入冻结、T+2 解冻、score_drop 触发 warning layer 卖出 — 全链路按 03/04 已签字契约执行

### 批量 4 leaves grid 表现

```
leaf_index  leaf_name                              trading_days  total_return  max_drawdown  sharpe    n_trades  n_buy  n_sell
0           max_positions=3__min_score=55.0        67            -0.004237     -0.019922     -0.4155   6         3      3
1           max_positions=3__min_score=60.0        67            -0.005132     -0.016279     -0.5709   4         2      2
2           max_positions=5__min_score=55.0        67            -0.002656     -0.012054     -0.4399   6         3      3
3           max_positions=5__min_score=60.0        67            -0.003125     -0.009854     -0.5808   4         2      2
```

观察：

- `min_score=55` 触发 6 笔交易，`min_score=60` 触发 4 笔，符合阈值放松 → 候选增多直觉。
- `max_positions` 在该 universe（10 codes）下未触顶（n_buy 均 ≤ 3），因此 3 vs 5 仅微幅影响 max_drawdown。
- 4 个 leaves 收益均小幅负值；归因：universe 仅 10 大盘蓝筹 + 样本期短（67 天，前 60 天历史积累期未交易，实际仅 ~7 天有效交易窗口）。该结果**仅作管线烟测**，不作策略最终定论（与 SHORT_SAMPLE_PERIOD WARN 一致）。

---

## 三、修改文件清单

### 新增文件（仅本次烟测临时配置）

| 文件 | 用途 |
|---|---|
| `backtest/configs/_real_smoke_4m.yaml` | 4 个月真实数据单 leaf 配置（前缀 `_` 标记非默认；不影响 baseline.yaml） |
| `backtest/configs/experiments/_real_smoke_grid.yaml` | 4 leaves 真实数据 grid 配置 |
| `agent_hub/2026-06-13_backtest_mvp/06_real_data_smoke_acceptance.md` | 本文件 |

### 不修改

任何源代码（`backtest/engine/`、`backtest/scripts/`、`backtest/strategy_core/`、`backtest/data_tools/` 全保持 Phase 5 commit `d250b1c` 状态）。

### F: 盘产物（运行时，不入 git）

- `F:/backtest_workspace/results/20260614_070140_943627_real_4m/`（6 文件）
- `F:/backtest_workspace/results/20260614_07030*_*_real_4m__max_positions=*__min_score=*/`（4 个 leaf 目录）
- `F:/backtest_workspace/batch_summary/real_smoke_grid_20260614_070301.csv`

---

## 四、是否触碰生产文件：**否**

明确未触碰：

- `release/v1.0/`、`strategy_main.py`、`core/strategy/`、`core/scoring/dimension6plus2.py`、`core/risk_manager*` — 未读未写
- `D:/QMT_POOL/` — 未读未写（**特别声明**：检查 universe 扩展可行性时 `ls` 了一下结构，确认是生产实盘动态选股池，立刻退出，未读取代码内容）
- `F:/金策智算/` — 仅 `access_mode='read_only'` 通过 reader 访问

---

## 五、是否违反 SPEC 边界：**否**

12 硬边界（授权令 §四，verbatim）逐条核对：

| # | 边界 | 状态 |
|---|---|---|
| 1 | 不修改 release/v1.0 | ✅ |
| 2 | 不修改 strategy_main.py | ✅ |
| 3 | 不调用 passorder | ✅ |
| 4 | 不接 QMT 实盘/模拟 | ✅ |
| 5 | 不启动委托 | ✅ |
| 6 | 不写 F:\金策智算\ | ✅ |
| 7 | 不读写打开 quantifydata.duckdb | ✅（reader hard-coded read_only） |
| 8 | 不在 C/D 盘写 results/cache/sample_db/logs | ✅（仅 F:/backtest_workspace/） |
| 9 | 不引入 xtquant/MiniQMT | ✅ |
| 10 | 不混入 IMA 主升浪 | ✅ |
| 11 | 不改 6+2 生产策略主逻辑 | ✅ |
| 12 | 不破坏性 git 操作 | ✅（仅 add / commit；本次仅新增配置 + 文档） |

---

## 六、已知限制 / 后续方向

### 当前烟测的限制（不阻塞 v0.2 MVP 验收）

1. **样本期短**：DuckDB 截至 2026-02-27，目前可用 7 个月数据，但前 60 bar 是策略历史窗口暖机期，有效交易窗口仅 ~5 个月。要做 12 个月有意义回测必须先 [触发金策智算同步](../../../../C:/Users/Administrator/.claude/projects/D--Program-Files-claude/memory/jince-zhisuan-duckdb-sync.md) 至最新交易日。
2. **universe 仅 10 代码**：`strategy_pool_base.csv` 是 v0.2 默认起步集，覆盖大盘蓝筹。扩展至 50–500 代码需诚哥/Hermes 决策（数据源、热度、行业平衡），不在 MVP 范围。
3. **无 benchmark**：DuckDB 无指数数据；`benchmark_code: null` 强制走 BENCHMARK_DISABLED 路径，excess_return/information_ratio/tracking_error 全 None。v0.3 数据扩充后启用。
4. **行业热度 zero**：`sector_heat_mode=zero` 强制 score_sector=0；要启用 historical/realtime 需 v0.3 OQ-E 决议。

### v0.3 OPEN_QUESTION 仍未决（保持标记）

- **OQ-1**：项目自管 DuckDB 路径（`paths.PROJECT_MARKET_DB_V03_PLACEHOLDER` 占位 `D:/QMT_STRATEGIES/data/duckdb/qmt_market_data.duckdb`）
- **OQ-2**：`data.source` 命名（当前 `jince_zhisuan` → 未来可能改为 `qmt_market`）
- **OQ-D**：`LIMIT_UP_PCT` 单阈 9.95（ST/创业板/科创板未分流，v0.3 决策）
- **OQ-E**：`sector_heat_mode` 增加 `historical` / `realtime`
- **OQ-F**：`target_volume` 由 strategy_core 直接给出（去除 engine 端 `_lot_floor` 重算）

### 可立即推进的方向（按授权令，无需 Hermes 验收）

1. ~~触发金策智算 DuckDB 同步至最新交易日~~（需诚哥手动启动金策智算客户端，CC 不能触发）
2. 扩展 `experiments/`：止损/止盈阈值扫描、min_score / min_core 网格、score_gap_threshold 敏感性分析
3. `clean_results.py` 加 cron 自动化（每日 dry-run + 每周 --apply）
4. `validate_data.py` 加 cron 自动化（每日同步后跑一次）
5. 加 universe schema 校验脚本（`validate_universe.py`）— 当前 `load_universe` 只读 csv 不校验数据完整性

---

签字：CC（夜班自主验收，诚哥 2026-06-14 免 Hermes 授权）
日期：2026-06-14
依据：`01_cc_full_night_authorization.md` + 诚哥 2026-06-14 口头补充授权
