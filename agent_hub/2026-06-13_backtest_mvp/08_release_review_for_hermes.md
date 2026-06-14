# 上线总览报告（致 Hermes）：回测工厂 v0.2 MVP

**日期**：2026-06-14
**作者**：CC（夜班执行者）
**收件人**：Hermes（方案搭档）+ 诚哥（决策者）
**目的**：v0.2 MVP 全部交付完成，请 Hermes + 诚哥共同评审 → 决定上线 / 调整 / 进入 v0.3。

---

## TL;DR

- **代码**：`backtest/` 共 8 个引擎/脚本模块 + 30 个测试文件，**157/157 PASS**，runtime ~3.8s。
- **真实数据冒烟**：`F:/金策智算` DuckDB 上 67 交易日单 leaf + 4 leaves grid 全部跑通；T+1 买卖、score_drop、6 文件输出、batch_summary 24 列汇总均按 03/04 已签字契约执行。
- **硬边界**：12 条边界 verbatim 全部保留；isolation 契约（clean_results 不进主线 import）AST 守护通过。
- **签字状态**：CC 自行夜班验收 7 份（05b-05f, 06, 07）；Hermes 仅签了 03 接口冻结 + 04 输出 schema 冻结 + 05a 接收（Phase 1A）。**05b 起的 5 份 acceptance 待 Hermes 复核或诚哥决议是否豁免**。
- **请求决策**：①是否上线、②v0.3 五个 OPEN_QUESTION 优先级、③是否扩 universe / 触发金策智算同步至最新交易日。

---

## 一、交付清单

### 1.1 代码（D:/QMT_STRATEGIES/backtest/）

| 模块 | 文件 | 行数 | 责任 |
|---|---|---|---|
| 路径 | `paths.py` | 37 | 磁盘分区契约（D=代码、F=产物、C=禁止） |
| 数据 | `data_tools/duckdb_reader.py` | 137 | DuckDB read-only 读取，QUALIFY ROW_NUMBER 去重，WAL 探测 |
| 数据 | `data_tools/universe.py` | 62 | universe csv schema 校验加载器 |
| 数据 | `data_tools/hashing.py`（在 engine/） | 60 | data_hash 9 字段公式 |
| 策略 | `strategy_core/__init__.py` | 接口骨架 + 枚举 |
| 策略 | `strategy_core/scoring_adapter.py` | 6+2 评分器适配 |
| 策略 | `strategy_core/decision.py` | priority / replace / blocked 过滤链 |
| 策略 | `strategy_core/evaluate_day.py` | 端到端纯函数入口（无 IO / 无随机 / 无 time） |
| 引擎 | `engine/execution.py` | 175 | 买卖填单（next_open + slippage + commission + tax + 涨停剔除 + 100 股下取整） |
| 引擎 | `engine/portfolio.py` | 195 | T+1 持仓 / mark-to-market / advance_holding_days |
| 引擎 | `engine/metrics.py` | 145 | 13 字段绩效（return / drawdown / sharpe / calmar / win_rate / etc） |
| 引擎 | `engine/daily_engine.py` | 290 | 主循环：advance → fill → mark → snapshot → evaluate；零 IO |
| 引擎 | `engine/report.py` | 280 | 6 文件写入器 + WARN 块装配（按 04 §5.1 顺序） |
| 脚本 | `scripts/init_workspace.py` | 30 | F:/backtest_workspace 子目录初始化 + tempdir 重定向 |
| 脚本 | `scripts/run_backtest.py` | 100 | CLI runner（yaml → 调引擎 → 调 report） |
| 脚本 | `scripts/run_batch.py` | 175 | 批量 grid 展开 + 24 列 batch_summary CSV |
| 脚本 | `scripts/clean_results.py` | 110 | retention：archive >30d / delete-archived >90d，dry-run 默认 |
| 脚本 | `scripts/validate_data.py` | 100 | DuckDB 数据探针（覆盖 / 去重 / WAL / universe 子集） |
| 脚本 | `scripts/validate_universe.py` | 145 | universe 探针（schema / DuckDB 覆盖 / 行业分布 / 历史深度） |

### 1.2 配置

| 文件 | 用途 |
|---|---|
| `configs/baseline.yaml` | v0.2 默认配置（25 天，10 codes，benchmark null，sector_heat zero） |
| `configs/_real_smoke_4m.yaml` | 真实数据 67 交易日烟测配置（前缀 `_` 标记非默认） |
| `configs/experiments/baseline_grid.yaml` | 4 leaves 默认网格（max_positions × min_score） |
| `configs/experiments/_real_smoke_grid.yaml` | 4 leaves 真实数据网格 |

### 1.3 测试（30 文件 / 157 测试）

| 阶段 | 文件数 | 测试数 |
|---|---|---|
| Phase 1A 数据/路径/隔离 | 9 | 30 |
| Phase 2 strategy_core | 5 | 53 |
| Phase 3 engine | 4 | 38 |
| Phase 4 report + e2e | 2 | 13 |
| Phase 5 batch + retention + validate_data | 3 | 16 |
| Phase 6 validate_universe | 1 | 7 |
| **合计** | **24（含 IMA/早期共 30）** | **157** |

> IMA 主升浪相关测试（3 个文件）独立于 v0.2 MVP，跑测试时 `--ignore`。

### 1.4 已签字契约文件（agent_hub/）

| 文件 | 签字方 | 状态 |
|---|---|---|
| `00_brief.md`、`01_*` | Hermes / CC | 已签 |
| `02_cc_implementation_plan.md` | Hermes 二次复核（决策 A-K） | 已签 |
| `03_interface_freeze.md` | Hermes（Phase 2.0 GATE） | 已签 ✅ |
| `04_output_schema_freeze.md` | CC（Phase 2.5 GATE，依授权令） | CC 自审 ✅ / 待 Hermes 确认 |
| `05a_hermes_acceptance.md` | Hermes（Phase 1A） | 已签 ✅ |
| `05b_phase2_acceptance.md` | CC 夜班自审 | **待 Hermes 复核** |
| `05c_phase25_schema_acceptance.md` | CC 夜班自审 | **待 Hermes 复核** |
| `05d_phase3_engine_acceptance.md` | CC 夜班自审 | **待 Hermes 复核** |
| `05e_phase4_report_acceptance.md` | CC 夜班自审 | **待 Hermes 复核** |
| `05f_phase5_batch_tests_acceptance.md` | CC 夜班自审 | **待 Hermes 复核** |
| `06_real_data_smoke_acceptance.md` | CC（诚哥免 Hermes 授权） | **本次报告附件** |
| `07_validate_universe_acceptance.md` | CC（诚哥免 Hermes 授权） | **本次报告附件** |

---

## 二、契约履行状况（Hermes 复核重点）

### 2.1 03 接口冻结（Phase 2.0 GATE，Hermes 已签字）

| 项 | 实现 | 状态 |
|---|---|---|
| `evaluate_day(state, market_window, universe, config, today)` 纯函数 | strategy_core/evaluate_day.py | ✅ |
| 无 IO / 无 random / 无 time / 无 xtquant | grep + AST 检查 | ✅ |
| 输出 column `score_volumeprice`（不是 score_volume） | scoring_adapter | ✅ |
| 7 sell reason 枚举 | enums.py | ✅ |
| 8 blocked 枚举（含 INSUFFICIENT_HISTORY） | enums.py | ✅ |
| sector_heat_mode == "zero" → score_sector=0（OQ-E） | scoring_adapter | ✅ |
| target_volume = 0（OQ-F），engine 端按 target_cash/price 下取整 | execution._lot_floor | ✅ |
| Priority：stop_loss/early_stop=1; early_kick/replace/confirm=2; score_drop/warning=3 | decision.py | ✅ |
| blocked 短路顺序：insufficient_history → suspended → already_held → limit_up → max_daily_pct → max_bias5 → min_core → min_score | decision.py | ✅ |

### 2.2 04 输出 schema 冻结（Phase 2.5 GATE）

| 项 | 实现 | 状态 |
|---|---|---|
| summary.json 23 顶层字段 + 5 子对象 | report.write_summary_json | ✅ |
| trades.csv 13 列（顺序固定） | report.write_trades_csv | ✅ |
| equity_curve.csv 8 列 | ✅ |
| positions.csv 9 列 | ✅ |
| logs.txt WARN 块顺序：SHORT_SAMPLE → BENCHMARK_DISABLED → DEDUP_APPLIED → SECTOR_HEAT_ZERO → [条件]WAL | report._build_warn_block | ✅ |
| WARN 条件矩阵（dedup>0 才出；wal 命中才出）| report.py | ✅ |
| report.md 短样本 banner（trading_days<252 OR benchmark_available=False） | report.write_report_md | ✅ |
| run_id 格式 YYYYMMDD_HHMMSS_<6hex> | daily_engine._make_run_id | ✅ |
| CSV utf-8-sig BOM；md/log UTF-8 无 BOM | ✅ |

### 2.3 12 硬边界（授权令 §四，verbatim）

每份 acceptance 文件均逐条核对，**12 条全部 ✅**：
不修改 release/v1.0、不修改 strategy_main.py、不调用 passorder、不接 QMT 实盘/模拟、不启动委托、不写 F:\金策智算\、不读写打开 quantifydata.duckdb（hard-coded `access_mode='read_only'`）、不在 C/D 盘写大产物、不引入 xtquant/MiniQMT、不混入 IMA 主升浪、不改 6+2 生产策略、不破坏性 git 操作。

### 2.4 isolation 契约（强约束 #6）

`backtest/scripts/clean_results.py` **不被任何主线模块 import**：
- AST 守护测试 `test_clean_results_isolation.py` 持续守护 `MAIN_MODULES = [duckdb_reader, universe, run_backtest, run_batch]`
- 完整版 clean_results（archive/delete 逻辑）落地后，测试仍 PASS。

---

## 三、真实数据冒烟结果（核心：管线在生产数据上是否成立）

### 3.1 数据状态

```
DuckDB:    F:/金策智算/_internal/databases/duckdb/quantifydata.duckdb
db_mtime:  2026-05-06T23:59:58
覆盖范围:  2025-08-01 → 2026-02-27（211 自然日，~145 交易日）
代码总数:  5,197
去重计数:  18,620（在窗口内重复 (code, date) 数）
WAL 状态:  未检测到（金策智算未在同步）
```

⚠️ **数据不完整**：截至 2026-06-14，DuckDB 数据只到 2026-02-27，距今 **3.5 个月空缺**。需启动金策智算客户端触发同步（[memory: jince-zhisuan-duckdb-sync.md](../../C:/Users/Administrator/.claude/projects/D--Program-Files-claude/memory/jince-zhisuan-duckdb-sync.md)）。

### 3.2 单 leaf 67 交易日真实回测

**配置**：`_real_smoke_4m.yaml`，2025-11-15..2026-02-27，10 大盘蓝筹，max_positions=5、min_score=60、sector_heat_mode=zero、benchmark=null。

**结果**：
- runtime = 0.516s
- total_return = -0.31%（4 笔交易，均亏损）
- max_drawdown = -0.99%
- sharpe = -0.581
- n_trades=4, n_buy=2, n_sell=2, win_rate=0.0, avg_holding_days=1.5

**关键时间线**：
| 日期 | 事件 |
|---|---|
| 2025-11-17 → 2026-02-10 | 每日 candidates=10、passed=0（60-bar 历史窗口未满） |
| 2026-02-11 | 窗口首次积满 60 bar，evaluate_day 通过 1 个候选 |
| 2026-02-12 | next_open 买入 002594.SZ（比亚迪） |
| 2026-02-13 | next_open 买入 300750.SZ（宁德时代） |
| 2026-02-24 | 两只均触发 score_drop（warning layer），同日 next_open 卖出 |

**结论**：T+1 买卖、60-bar 历史阈值、score_drop/warning 触发链路、6 文件输出、WARN 块顺序——**全链路按已签字契约执行，无 bug 暴露**。

### 3.3 批量 4 leaves grid

**配置**：`max_positions ∈ {3, 5} × min_score ∈ {55, 60}`

```
leaf  trading_days  total_return  max_drawdown  sharpe    n_trades  n_buy  n_sell
mp=3,ms=55  67    -0.4237%      -1.99%        -0.4155   6         3      3
mp=3,ms=60  67    -0.5132%      -1.63%        -0.5709   4         2      2
mp=5,ms=55  67    -0.2656%      -1.21%        -0.4399   6         3      3
mp=5,ms=60  67    -0.3125%      -0.99%        -0.5808   4         2      2
```

观察：
- 总耗时 2.1s（4 leaves，~0.5s/leaf）
- min_score 放松（55）→ 候选增多 6 笔，反之 60 → 4 笔，**符合阈值直觉**
- max_positions（3 vs 5）在 10 codes universe 下未触顶，差异微弱
- 所有 leaves 均小幅亏损：归因 universe 仅 10 大盘蓝筹 + 有效交易窗口仅 ~7 天（前 60 天暖机）

**业绩本身无策略意义**（与 SHORT_SAMPLE_PERIOD WARN 一致）；**仅作管线冒烟**。

### 3.4 universe 探针

`validate_universe.py` 在 `strategy_pool_base.csv` × 真实 67 天窗口：
- 10/10 代码 DuckDB 覆盖
- 10/10 历史 ≥60 bars
- 7 行业分布（银行 2、白酒 2、新能源 2、保险 1、家电 1、汽车 1、证券 1）

---

## 四、待决策项

### 4.1 v0.3 OPEN_QUESTION（5 个，需 Hermes + 诚哥拍）

| ID | 问题 | 当前状态 | 影响范围 |
|---|---|---|---|
| **OQ-1** | 项目自管 DuckDB 路径（v0.3 是否独立于金策智算？） | 占位 `paths.PROJECT_MARKET_DB_V03_PLACEHOLDER` | data_tools/reader、ops |
| **OQ-2** | `data.source` 命名重构（`jince_zhisuan` → `qmt_market` 还是保持？） | yaml 字段 + summary.json | yaml schema、summary |
| **OQ-D** | `LIMIT_UP_PCT` 单阈 9.95（ST/创业板/科创板未分流） | execution.py 硬编码 9.95 | 涨停剔除策略 |
| **OQ-E** | `sector_heat_mode` 是否引入 `historical` / `realtime`？ | 当前仅 `zero` | scoring_adapter、热度数据源 |
| **OQ-F** | `target_volume` 由 strategy_core 直接给出（去掉 engine 端 `_lot_floor` 重算）？ | 当前 strategy_core 输出 0，engine 重算 | 接口 03 需重签 |

### 4.2 上线建议路径（CC 视角，非决策）

**方案 A：直接上线 v0.2，v0.3 单独排期**
- 优点：当前 157 测试 + 真实数据冒烟均通过；管线契约清晰
- 缺点：业绩数字目前对策略评估无意义（数据短 + universe 小）
- 适用：诚哥+Hermes 已确认管线正确性，把扩 universe / 数据扩展放到 v0.3

**方案 B：上线前先做一轮真实业绩验证**
1. 触发金策智算 DuckDB 同步至最新交易日（CC 无权限触发，需诚哥手动）
2. 扩 universe 至 50-100 代码（需 Hermes 决策选股池来源：QMT_POOL 历史快照？同花顺导出？）
3. 跑 12 个月真实回测 + 对比 6+2 生产策略历史业绩
4. 通过后再 release tag v0.2

**方案 C：上线 v0.2 但保留 dev 分支跑 v0.3**
- 给 v0.2 打 tag → 进 release/
- 同时启动 v0.3 spec 讨论（OQ-1/2/D/E/F）

### 4.3 已知非阻塞观察（CC 自审遗留）

1. `data_path` 在 summary.json 中是反斜杠 Windows 路径——下游解析需统一 normalize（建议 v0.3 在 report.py 写盘前处理）
2. `validate_universe._bars_per_code` 直访 `reader._conn`——可接受但若 reader 重构需要在 reader 加 public `bars_per_code()`
3. `report.md` 用 `> WARNING` 文本替代 `> ⚠️` emoji（CLAUDE.md 全局禁 emoji）；如 Hermes 偏好 emoji，单独切换
4. CLI 无 progress bar；长样本期 1+ 分钟时无反馈（v0.3 可加 tqdm）
5. `run_batch` 顺序执行 leaves，无并发；20+ leaves 时耗时线性（v0.3 可考虑 ProcessPoolExecutor，注意 DuckDB 多连接 read_only 行为）
6. `clean_results.py` 不跨盘；仅在 F:/results ↔ F:/results_archive 之间移动
7. `validate_data.py` / `validate_universe.py` 不抛错，仅描述事实；上游决定是否 gate（v0.2 不强制）

---

## 五、Hermes 复核请求

请 Hermes 关注以下三点（按重要性排序）：

### 5.1 优先：契约一致性

- 03 接口冻结的 9 项实现是否符合签字版？特别是 priority 优先级、blocked 短路顺序、target_volume=0 由 engine 重算
- 04 输出 schema 的 23 顶层字段 + WARN 块顺序 + 短样本 banner 是否字符级一致？

### 5.2 次优：边界守护是否充分

- 12 硬边界 + isolation 契约 #6 的实测验证（D 盘 mtime 守护、AST import 守护、access_mode read_only 强制）
- 如有遗漏边界场景，本次报告之后单独提

### 5.3 一般：v0.3 OQ 决策

- 5 个 OPEN_QUESTION 哪些可在 v0.3 一次性解决，哪些需分批
- 是否要把 IMA 主升浪集成回主线（当前独立分支）

---

## 六、附件 / 引用

### 已交付的 8 份 acceptance 文件

1. `05a_hermes_acceptance.md`（Hermes 已签 Phase 1A）
2. `05b_phase2_acceptance.md`（CC 夜班，strategy_core 53 测试）
3. `05c_phase25_schema_acceptance.md`（CC 夜班，输出 schema 冻结）
4. `05d_phase3_engine_acceptance.md`（CC 夜班，38 测试）
5. `05e_phase4_report_acceptance.md`（CC 夜班，13 测试 + e2e）
6. `05f_phase5_batch_tests_acceptance.md`（CC 夜班，16 测试）
7. `06_real_data_smoke_acceptance.md`（CC，真实数据 67 天 + 4 leaves grid）
8. `07_validate_universe_acceptance.md`（CC，universe 探针 + 7 测试）

### 全套件回归命令

```bash
py -3.10 -S -c "import sys; sys.path.append(r'C:\\Users\\Administrator\\AppData\\Local\\Programs\\Python\\Python310\\Lib\\site-packages'); import pytest; raise SystemExit(pytest.main(['backtest/tests','-q','--ignore=backtest/tests/test_ima_uptrend_v31.py','--ignore=backtest/tests/test_ima_no_lookahead.py','--ignore=backtest/tests/test_ima_signal_returns.py']))"
```

预期：`157 passed`，runtime ~3.8s。

### 真实数据 baseline 复现命令

```bash
py -3.10 -m backtest.scripts.run_backtest --config backtest/configs/_real_smoke_4m.yaml
py -3.10 -m backtest.scripts.run_batch --experiment backtest/configs/experiments/_real_smoke_grid.yaml
py -3.10 -m backtest.scripts.validate_universe --universe backtest/data/universe/strategy_pool_base.csv --start-date 2025-11-15 --end-date 2026-02-27
py -3.10 -m backtest.scripts.validate_data
```

### Commit 链（v0.2 MVP，按时间逆序）

```
fe374ac feat(scripts): validate_universe.py + tests (Task 6)
6af8cb1 docs(backtest): real-data smoke acceptance
d250b1c docs(backtest): Phase 5 batch+retention acceptance
8a17942 test(phase5): run_batch + clean_results + validate_data
9b9a8c7 feat(scripts): clean_results full + validate_data (Task 5.3-5.4)
e1d482e feat(batch): grid yaml + run_batch.py (Task 5.1-5.2)
1892d02 docs(backtest): Phase 4 report acceptance
e8754f0 feat(backtest): CLI runner + baseline.yaml + e2e tests (Task 4.2-4.4)
887f720 feat(engine): report writers (Task 4.1)
c66f699 docs(backtest): Phase 3 engine acceptance
907a565 feat(engine): daily_engine main loop (Task 3.4)
559d2bc feat(engine): metrics layer (Task 3.3)
917583b feat(engine): execution + portfolio (Task 3.1/3.2)
5aa9a31 docs(backtest): Phase 2.5 acceptance
e98ba97 docs(backtest): Phase 2.5 output schema freeze (gate #2)
8be2c59 docs(backtest): Phase 2 acceptance
226b3ca feat(strategy_core): integrate evaluate_day end-to-end
d609193 feat(strategy_core): decision layer with priority/replace/blocked filters
8a8f2e4 feat(strategy_core): score_universe wrapper over 6+2 scorer
c14b265 feat(strategy_core): interface skeleton + enums (post gate #1)
b520cdd docs(backtest): Phase 2.0 interface freeze proposal (gate #1)
6b11630 docs(backtest): Phase 1A acceptance + reader perf baseline
... (Phase 1A 早期 commits 略)
```

---

## 七、签字 / 等待

- **CC 签字**：v0.2 MVP 6 阶段（1A→6）夜班自主验收完成，依据 `01_cc_full_night_authorization.md` + 诚哥 2026-06-14 免 Hermes 授权。
- **等待 Hermes**：本次复核 → 给出 ①是否上线 ②v0.3 OQ 决策 ③有无补充边界要求。
- **等待诚哥**：Hermes 反馈后做最终决议。

---

签字：CC
日期：2026-06-14
依据：`01_cc_full_night_authorization.md` + 诚哥 2026-06-14 口头补充授权
