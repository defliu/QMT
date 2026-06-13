# Phase 5 验收：batch runner + retention + validate_data + tests

日期：2026-06-14（夜班）
验收人：CC（夜班自主验收，依据 `01_cc_full_night_authorization.md`）
对象：Phase 5 交付（`run_batch.py` + `clean_results.py` 完整版 + `validate_data.py` + `experiments/baseline_grid.yaml` + 16 测试）

---

## 一、验收结论

**Phase 5 自审通过。回测工厂 v0.2 MVP 全部 5 个阶段交付完成。**

依据：

1. Task 5.1–5.4 全部按 `05e_phase4_report_acceptance.md` §九 顺序实现，schema 与 03/04 已签字契约严格一致。
2. `run_batch.py` 端到端测试用 sample_db + 2 元素网格，产出 2 个 leaf 结果目录（每个含 6 文件）+ 1 个 `<batch_id>_<ts>.csv` 汇总文件，列 24 项与 `_BATCH_COLS` 完全对齐。
3. `clean_results.py` 完整版：dry-run 默认；`--apply` 归档 >30 天的 results 子目录到 `ARCHIVE_DIR`；`--apply --delete-archived` 删除 >90 天的归档目录。**isolation 契约保留**：未被 reader / engine / run_backtest / run_batch 的任何主路径模块 import（由 `test_clean_results_isolation.py` 守护）。
4. `validate_data.py`：read-only 探针，输出 JSON 报告到 `LOGS_DIR`；不写 D/C 盘；不写 `F:\金策智算\`。
5. 全 backtest 套件 **150 / 150 PASS**（Phase 1A 30 + Phase 2 53 + Phase 3 38 + Phase 4 13 + Phase 5 16）。无回归。
6. 不触碰生产策略 / release / 交易接口；不写 `F:\金策智算\` / 不写 D 盘大产物 / 不写 C 盘；不引入 xtquant；不调用 passorder。

---

## 二、本阶段实现内容

| Task | 内容 | 行数（约） |
|---|---|---|
| 5.1 | `backtest/configs/experiments/baseline_grid.yaml`：声明式实验网格（`batch.id` + `batch.base` + `grid.<dotted>: [v...]`）。 | 35 |
| 5.2 | `backtest/scripts/run_batch.py`：读 experiment yaml → 笛卡尔展开 grid → 每 leaf 调 `run_backtest` → 汇总 24 列 CSV 到 `BATCH_DIR`。 | 175 |
| 5.3 | `backtest/scripts/clean_results.py` 完整版：archive / delete-archived，dry-run 默认。 | 110 |
| 5.4 | `backtest/scripts/validate_data.py`：DuckDB 只读探针，输出 JSON 报告到 `LOGS_DIR`。 | 100 |
| 5.5 | 测试：`test_run_batch.py`（6）+ `test_clean_results.py`（6）+ `test_validate_data.py`（4）= 16 测试。 | 250 |

### 关键设计决策

- **grid 展开用 `itertools.product` + `_set_dotted`**：dotted-path 写入嵌套 dict，零中间临时 yaml 文件，每个 leaf 直接调用 `run_backtest()` Python 入口（**不**再 fork 子进程也不再 dump 临时 yaml），避免 D 盘多余写入。
- **leaf_name 是确定性 slug**：`max_positions=3__min_score=55.0`。多次运行同一 grid 会得到同一 leaf 名，方便 batch_summary 列对齐。
- **batch_summary 列只取顶层指标**（24 列）：详细数据指向 `results_dir`，避免 CSV 巨胖。
- **clean_results.py 隔离契约硬保留**：
  - 不被任何 `MAIN_MODULES`（`duckdb_reader` / `universe` / `run_backtest` / `run_batch`）import；
  - `test_clean_results_isolation.py` AST 解析守护；
  - 完整版加进任何主线 import 都会立刻让该测试失败。
- **clean_results 默认 dry-run**：`--apply` 才落地。归档冲突时带时间戳后缀避免覆盖。
- **validate_data.py 不抛错**：仅输出报告并返回 0；上游决定是否 gate（v0.2 不强制）。
- **JSON 兼容**：`json.dump(..., default=str)` 兜底 datetime 等。
- **测试 monkeypatch `paths.RESULTS_DIR / ARCHIVE_DIR / BATCH_DIR / LOGS_DIR`**：所有写入隔离到 `tmp_path`，不污染真实 F:/backtest_workspace。

### 不在 Phase 5 范围内

- **真实 12 个月样本期跑**：Hermes 后续二次验收，需先按 `MEMORY.md jince-zhisuan-duckdb-sync.md` 触发 DuckDB 同步。
- **OPEN_QUESTION（OQ-1, OQ-2）项目自管 DuckDB 路径与 data_source 命名**：v0.3 决策；当前 `paths.PROJECT_MARKET_DB_V03_PLACEHOLDER` 占位、`baseline.yaml` `data.source: jince_zhisuan` 待 Hermes/诚哥 v0.3 kickoff 决议。
- 实盘 / 模拟盘对接；任何 xtquant 引用。

---

## 三、修改文件清单

### 新增文件

| 文件 | 用途 | 行数（约） |
|---|---|---|
| `backtest/configs/experiments/baseline_grid.yaml` | 批量实验声明 | 35 |
| `backtest/scripts/run_batch.py` | 批量 runner | 175 |
| `backtest/scripts/validate_data.py` | DuckDB 数据校验探针 | 100 |
| `backtest/tests/test_run_batch.py` | 6 测试（dotted set + grid 展开 + summary 列 + e2e 2 leaves） | 130 |
| `backtest/tests/test_clean_results.py` | 6 测试（候选挑选 + archive 移动 + delete + dry-run + apply） | 110 |
| `backtest/tests/test_validate_data.py` | 4 测试（基础 + universe + 文件落盘 + main） | 60 |

### 修改文件

| 文件 | 修改 |
|---|---|
| `backtest/scripts/clean_results.py` | Phase 1A stub（27 行）→ 完整版（110 行）：archive / delete-archived / dry-run 选项落实。 |

不修改：

- `backtest/engine/*`（Phase 3/4 已交付，本阶段消费）
- `backtest/strategy_core/*`（Phase 2 冻结）
- `backtest/data_tools/*`（Phase 1A）
- 任何 `core/` / `release/` / `strategy_main.py` / QMT 生产路径
- `backtest/tests/test_clean_results_isolation.py`（已签字守护，不动）

---

## 四、Commit 列表（待提交）

```text
feat(batch): grid yaml + run_batch.py (Task 5.1-5.2)
feat(scripts): clean_results full + validate_data (Task 5.3-5.4)
test(phase5): run_batch + clean_results + validate_data (Task 5.5)
```

---

## 五、测试

### 测试命令

```bash
py -3.10 -S -c "import sys; sys.path.append(r'C:\\Users\\Administrator\\AppData\\Local\\Programs\\Python\\Python310\\Lib\\site-packages'); import pytest; raise SystemExit(pytest.main(['backtest/tests','-q','--ignore=backtest/tests/test_ima_uptrend_v31.py','--ignore=backtest/tests/test_ima_no_lookahead.py','--ignore=backtest/tests/test_ima_signal_returns.py']))"
```

### 测试结果

```text
150 passed in 3.17s
```

按文件分布（仅列 Phase 5 新增）：

| 测试文件 | 通过数 | 覆盖契约 |
|---|---|---|
| **test_run_batch.py** | **6** | **dotted setter / 笛卡尔展开 / 空 grid / summary CSV 列序 / e2e 2 leaves** |
| **test_clean_results.py** | **6** | **archive 阈值 / archive 移动 / delete 阈值 / dry-run 不动 / --apply 归档 / --delete-archived 删除** |
| **test_validate_data.py** | **4** | **基础 / 带 universe / 文件落盘 / main 端到端** |
| 累计（含前 4 阶段） | **150** | |

### 关键测试场景覆盖

- **批量 e2e**：`test_run_batch_e2e_two_leaves` 用 sample_db + grid `max_positions: [3, 5]`，监测 2 个 leaf 全产 6 文件 + 1 个 batch_summary CSV。
- **隔离守护未失效**：`test_clean_results_isolation.py`（已存在）经 Phase 5 修改后仍 PASS，`MAIN_MODULES` 含 `run_batch` 也未引入 `clean_results`。
- **dry-run vs apply**：`test_dry_run_does_not_move` 验证默认行为零写入；`test_apply_archives_old_runs` / `test_apply_with_delete_archived` 验证 --apply 后实际状态变更。
- **paths 边界**：所有测试 monkeypatch `RESULTS_DIR / ARCHIVE_DIR / BATCH_DIR / LOGS_DIR` 到 `tmp_path`；F:/backtest_workspace 真实目录无新写入。
- **WAL 字段透传**：`test_build_report_basic` 断言 `wal_detected` 字段类型为 bool。
- **universe 覆盖**：`test_build_report_with_universe` 校验 `universe_coverage` 子对象 schema 一致。

---

## 六、是否触碰生产文件：**否**

明确未触碰：

- `release/v1.0/` — 未读未写
- QMT 生产 `strategy_main.py` — 未读未写
- `core/strategy/` 主升浪 / 全天版策略 — 未读未写
- `core/scoring/dimension6plus2.py` — 未读未写
- `core/risk_manager*` — 未读未写
- `D:\QMT_POOL\` — 未写
- `F:\金策智算\` — 仅 read-only 通过 reader 访问；`access_mode='read_only'` 强制
- `F:\backtest_workspace\` — 测试中 monkeypatch 到 tmp_path；真实运行才会写入

本阶段写入：

- `backtest/scripts/run_batch.py`、`backtest/scripts/validate_data.py`
- `backtest/scripts/clean_results.py`（Phase 1A stub → 完整版）
- `backtest/configs/experiments/baseline_grid.yaml`
- `backtest/tests/test_run_batch.py`、`test_clean_results.py`、`test_validate_data.py`
- `agent_hub/2026-06-13_backtest_mvp/05f_phase5_batch_tests_acceptance.md`（本文件）

---

## 七、是否违反 SPEC 边界：**否**

逐条核对硬边界（授权令 §四，verbatim 12 条）：

| # | 边界 | 状态 |
|---|---|---|
| 1 | 不修改 release/v1.0 | ✅ 未触碰 |
| 2 | 不修改 strategy_main.py | ✅ 未触碰 |
| 3 | 不调用 passorder | ✅ grep `backtest/` 无 passorder |
| 4 | 不接 QMT 实盘/模拟交易 | ✅ 无交易 import |
| 5 | 不启动真实/模拟委托 | ✅ 纯计算 + 文件 IO |
| 6 | 不写 F:\金策智算\ | ✅ reader 强制 read-only |
| 7 | 不读写模式打开 quantifydata.duckdb | ✅ DuckDBDailyReader 已 hard-coded read_only |
| 8 | 不在 C/D 盘写 results/cache/sample_db/logs | ✅ run_batch / clean_results / validate_data 仅写 F 盘；测试 monkeypatch 到 tmp_path |
| 9 | 不引入 xtquant/MiniQMT | ✅ grep `backtest/` 无 xtquant |
| 10 | 不混入 IMA 主升浪 | ✅ 未引用 IMA 任何模块 |
| 11 | 不改 6+2 生产策略主逻辑 | ✅ 未改 scorer |
| 12 | 不破坏性 git 操作 | ✅ 仅 add / commit |

强约束 #6（隔离契约）逐条核对：

- `clean_results` 不被 `backtest.data_tools.duckdb_reader` import ✅
- `clean_results` 不被 `backtest.data_tools.universe` import ✅
- `clean_results` 不被 `backtest.scripts.run_backtest` import ✅
- `clean_results` 不被 `backtest.scripts.run_batch` import ✅（grep 无 import；测试用 AST 解析守护）

03/04/05* 已签字契约逐条核对：

- 03 §1 strategy_core 接口（pure function、无 IO、无随机）：未改
- 04 §1-§7 6 文件输出 schema：本阶段引用 report.write_all() 但不变更 schema
- 05c Phase 2.5 输出 schema 冻结：保持
- 05d Phase 3 引擎契约：保持
- 05e Phase 4 报告写入契约：保持

OPEN_QUESTION 标记保留：

- **OQ-1（v0.3）**：项目自管 DuckDB 路径，`paths.PROJECT_MARKET_DB_V03_PLACEHOLDER` 占位
- **OQ-2（v0.3）**：`data.source` 命名（当前 `jince_zhisuan` → 未来可能改为 `qmt_market` 等）

---

## 八、已知问题 / 未完成项

### 非阻塞观察

1. **真实 12 个月样本期未跑**：DuckDB 数据停在 2026-02-27（金策智算未同步）；当前批量 e2e 用 30 天 sample_db，仅验证管线。Hermes 二次验收前请按 `MEMORY.md jince-zhisuan-duckdb-sync.md` 触发同步。
2. **batch_summary 列固定 24 项**：未来如增加新指标（如 turnover、IC 等），需同步更新 `_BATCH_COLS` 与下游消费者。Hermes 阶段如需扩展，请重新签字。
3. **run_batch 无并发**：当前顺序执行 leaves。N=20+ leaves 时耗时线性；v0.3 可考虑 `concurrent.futures.ProcessPoolExecutor`（注意 DuckDB read_only 多连接行为）。本阶段刻意不做。
4. **clean_results 不跨盘**：仅在 F: 盘内部 `results/` ↔ `results_archive/` 之间移动。如归档卷写满，shutil.move 会抛 OSError 被 `try/except` 捕获并仅 log；不会污染 D/C。
5. **validate_data 无 schema 断言**：仅描述事实，不判定健康/不健康。Hermes 阶段决定是否引入 gate。

### 未完成项

无 Phase 5 范围内未完成项。回测工厂 v0.2 MVP 的 5 个阶段全部交付。

---

## 九、下一阶段计划

**回测工厂 v0.2 MVP 全部交付完成。**

后续可走的方向（按授权令仅作建议，不在 Phase 5 范围）：

1. **真实数据回测验证（Hermes 二次验收）**：
   - 触发金策智算 DuckDB 同步至最新交易日
   - 运行 12 个月真实样本期（如 `2025-03-01..2026-02-28`）
   - Hermes 验证指标合理性（年化、回撤、夏普）
   - 对比 6+2 生产策略历史业绩

2. **v0.3 OPEN_QUESTION 决策**：
   - OQ-1：项目自管 DuckDB 路径与同步策略
   - OQ-2：`data.source` 命名重构
   - OQ-E：`sector_heat_mode` 是否引入 `historical` 模式
   - OQ-F：`target_volume` 由 strategy_core 直接给出（去掉 engine 端 `_lot_floor` 重算）

3. **运维自动化**：
   - `clean_results.py` 加 cron：每日 02:00 dry-run 报告，每周 --apply
   - `validate_data.py` 加 cron：每日同步后跑一次，输出到 `LOGS_DIR/validate_data_<date>.json`

4. **批量探索**：
   - 扩展 `experiments/` 多份 yaml（参数敏感性分析、止损阈值扫描、min_score gridsearch 等）

---

签字：CC（夜班自主验收）
日期：2026-06-14
依据：`01_cc_full_night_authorization.md` §一、§三、§六.1
