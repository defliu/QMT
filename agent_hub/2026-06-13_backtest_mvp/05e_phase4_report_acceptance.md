# Phase 4 验收：标准报告输出 + e2e 烟测完成

日期：2026-06-14（夜班）
验收人：CC（夜班自主验收，依据 `01_cc_full_night_authorization.md`）
对象：Phase 4 交付（`backtest/engine/report.py` + `scripts/run_backtest.py` + `configs/baseline.yaml` + 13 测试）

---

## 一、验收结论

**Phase 4 自审通过。允许进入 Phase 5（batch + retention）。**

依据：

1. 6 文件 schema 与 04_output_schema_freeze.md §1-§7 全字段对齐。
2. e2e 测试用 sample_db（30 天，触发 INSUFFICIENT_HISTORY / SHORT_SAMPLE_PERIOD 路径）跑完整链路：6 文件全部产出、summary.json 可解析、WARN 块顺序正确、report.md 含样本期 banner。
3. 边界守护测试 `test_e2e_writes_only_under_results_dir` 用 mtime 快照对比验证：引擎 + report 写盘只写 `RESULTS_DIR`，不动 D: 任何源文件。
4. 全 backtest 套件 134 / 134 PASS（Phase 1A 30 + Phase 2 53 + Phase 3 38 + Phase 4 13），无回归。
5. 不触碰生产策略 / release / 交易接口；不写 `F:\金策智算\` / 不写 D 盘 / 不写 C 盘；不引入 xtquant。

---

## 二、本阶段实现内容

| Task | 内容 | Commit |
|---|---|---|
| 4.1 | `engine/report.py`：6 文件写入器 + 1 总线 `write_all()`。WARN 块固定顺序：SHORT_SAMPLE_PERIOD → BENCHMARK_DISABLED → DATA_DEDUP_APPLIED → SECTOR_HEAT_MODE_ZERO → [条件] DATA_WAL_DETECTED。 | `887f720` |
| 4.2 | `scripts/run_backtest.py`：CLI（`--config <yaml>`），加载 yaml → universe csv → reader → daily_engine.run_backtest → report.write_all。 | `e8754f0` |
| 4.3 | `configs/baseline.yaml`：v0.2 默认配置。universe = `strategy_pool_base.csv`；2025-09-02..2025-09-26；6+2 策略；sector_heat_mode=zero；benchmark_code=null。 | `e8754f0` |
| 4.4 | `tests/test_e2e_pipeline.py`：2 个 e2e 测试（6 文件产出 + D 盘只读守护）。 | `e8754f0` |

### 关键设计决策

- **`results_dir` 总在 `F:\backtest_workspace\results\<run_id>_<config>\`**：决策 J 强约束。`paths.RESULTS_DIR` 是唯一可信源；测试通过 monkeypatch `paths.RESULTS_DIR` 隔离到 tmp，不污染真实 results dir。
- **`write_all()` 单点入口**：Phase 5 batch runner 直接调它，省去重复装配。
- **WARN 块条件矩阵**（04 §5.3）：测试逐条覆盖（SHORT_SAMPLE_PERIOD 必出、BENCHMARK_DISABLED 必出、DATA_DEDUP_APPLIED 仅 dedup_count>0 出、SECTOR_HEAT_MODE_ZERO 必出、DATA_WAL_DETECTED 仅 wal 命中出）。
- **CSV 编码**：UTF-8 with BOM（Excel 兼容）；`logs.txt` / `report.md` UTF-8 无 BOM。
- **summary.json `default=str`**：兜底序列化 `datetime` 等非 JSON 原生类型；正常数据全部为基础类型，default 路径不会触发，但保留作为防御。
- **e2e 短样本可接受**：sample_db 仅 30 天，所有 universe 都因 < 60 bar 命中 INSUFFICIENT_HISTORY；引擎应产生「0 trade、equity 持平」的合法结果。这恰好验证了空交易路径 + 全 WARN 块出现路径。

### 不在 Phase 4 范围内

- batch runner（Phase 5）
- `clean_results.py` 完整版（Phase 5；当前是 Phase 1A 已交付的 import 隔离骨架）
- `validate_data.py`（Phase 5）
- 真实样本期 12 个月跑（Hermes 后续二次验收）

---

## 三、修改文件清单

### 新增文件

| 文件 | 用途 | 行数（约） |
|---|---|---|
| `backtest/engine/report.py` | 6 文件写入器 + WARN 块装配 | 280 |
| `backtest/scripts/run_backtest.py` | CLI runner | 100 |
| `backtest/configs/baseline.yaml` | v0.2 默认配置 | 35 |
| `backtest/tests/test_report.py` | 11 测试 | 230 |
| `backtest/tests/test_e2e_pipeline.py` | 2 e2e 测试 | 130 |

### 修改文件

无。

不修改：
- `backtest/engine/daily_engine.py`（Phase 3 已交付，本阶段仅消费）
- `backtest/engine/execution.py` / `portfolio.py` / `metrics.py`（同上）
- `backtest/strategy_core/`（Phase 2 冻结）
- `backtest/data_tools/`（Phase 1A 已交付）
- 任何 `core/` / `release/` / `strategy_main.py`

---

## 四、Commit 列表

```text
887f720 feat(engine): report writers (Task 4.1 -- 6 output files per 04 §1-§7)
e8754f0 feat(backtest): CLI runner + baseline.yaml + e2e tests (Task 4.2-4.4)
```

---

## 五、测试

### 测试命令

```bash
py -3.10 -S -c "import sys; sys.path.append(r'C:\Users\Administrator\AppData\Local\Programs\Python\Python310\Lib\site-packages'); import pytest; raise SystemExit(pytest.main(['backtest/tests','-q','--ignore=backtest/tests/test_ima_uptrend_v31.py','--ignore=backtest/tests/test_ima_no_lookahead.py','--ignore=backtest/tests/test_ima_signal_returns.py']))"
```

### 测试结果

```text
134 passed in 2.78s
```

按文件分布（仅列 Phase 4 新增）：

| 测试文件 | 通过数 | 覆盖契约 |
|---|---|---|
| **test_report.py** | **11** | **04 §1-§6 字段 / 列序 / WARN 块顺序与条件 / banner 触发** |
| **test_e2e_pipeline.py** | **2** | **e2e 6 文件 + D 盘只读守护** |
| 累计（含前 3 阶段） | **134** | |

### 关键测试场景覆盖

- **6 文件全产出**：`test_write_all_produces_six_files` + e2e。
- **WARN 块固定顺序**：`test_write_logs_txt_warn_block_order`（顺序断言用 index() 比较）。
- **WARN 条件性**：`test_write_logs_txt_omits_wal_when_not_detected` + `test_write_logs_txt_omits_dedup_when_zero`。
- **banner 触发**：`test_write_report_md_has_sample_period_banner` + 反向 `test_write_report_md_omits_banner_when_not_short`。
- **summary.json 可解析**：`test_write_summary_json_round_trip`。
- **trades.csv 列序与 04 §2 完全一致**：`test_write_trades_csv_columns_and_order` 断言列名列表 == 13 列预期值。
- **equity_curve / positions 列序**：同上。
- **e2e summary 字段完整**：`test_e2e_full_pipeline_produces_six_files` 断言 schema_version / sample_period_warning / sector_heat_mode / data_dedup_applied 等。
- **e2e D 盘 mtime 守护**：遍历 `paths.BACKTEST_ROOT` 下所有非 `__pycache__` 文件，对比前后 mtime 不变。
- **logs.txt 内容**：e2e 检查包含 [WARN] SHORT_SAMPLE_PERIOD / BENCHMARK_DISABLED / SECTOR_HEAT_MODE_ZERO 三条必出 WARN。

---

## 六、是否触碰生产文件：**否**

明确未触碰：

- `release/v1.0/` — 未读未写
- QMT 生产 `strategy_main.py` — 未读未写
- `core/strategy/` 主升浪/全天版策略 — 未读未写
- `core/scoring/dimension6plus2.py` — 未读未写（仅 Phase 2 已存在 import 链）
- `core/risk_manager*` — 未读未写
- `D:\QMT_POOL\` — 未写
- `F:\金策智算\` — 仅 read-only 通过 reader 访问；`access_mode='read_only'` 强制
- `F:\backtest_workspace\results\` — 测试中 monkeypatch 到 tmp_path；CLI 真实运行才写入此目录

本阶段写入：

- `backtest/engine/report.py`、`backtest/scripts/run_backtest.py`、`backtest/configs/baseline.yaml`
- `backtest/tests/test_report.py`、`backtest/tests/test_e2e_pipeline.py`
- `agent_hub/2026-06-13_backtest_mvp/05e_phase4_report_acceptance.md`（本文件）

---

## 七、是否违反 SPEC 边界：**否**

逐条核对硬边界（授权令 §四）：

| # | 边界 | 状态 |
|---|---|---|
| 1 | 不修改 release/v1.0 | ✅ 未触碰 |
| 2 | 不修改 strategy_main.py | ✅ 未触碰 |
| 3 | 不调用 passorder | ✅ grep `backtest/` 无 passorder |
| 4 | 不接 QMT 实盘/模拟交易 | ✅ 无交易 import |
| 5 | 不启动真实/模拟委托 | ✅ 纯计算 + 文件 IO |
| 6 | 不写 F:\金策智算\ | ✅ reader 强制 read-only |
| 7 | 不读写模式打开 quantifydata.duckdb | ✅ DuckDBDailyReader 已 hard-coded read_only |
| 8 | 不在 C/D 盘写 results/cache/sample_db/logs | ✅ report 仅写 paths.RESULTS_DIR (F 盘)；e2e 测试 mtime 守护 |
| 9 | 不引入 xtquant/MiniQMT | ✅ grep `backtest/` 无 xtquant |
| 10 | 不混入 IMA 主升浪 | ✅ 未引用 IMA 任何模块 |
| 11 | 不改 6+2 生产策略主逻辑 | ✅ scorer 仅 Phase 2 已有依赖，本阶段未改 |
| 12 | 不破坏性 git 操作 | ✅ 仅 add / commit |

04 输出 schema 契约逐条核对：

- §1.1 summary.json 23 顶层字段 + 子对象 ✅（写 + 测试 round-trip）
- §1.2 data_coverage_actual ✅
- §1.3 sample_period_warning ✅
- §1.4 performance 13 字段 ✅
- §1.5 diagnostics_aggregate ✅
- §2 trades.csv 13 列（顺序固定）✅
- §3 equity_curve.csv 8 列 ✅
- §4 positions.csv 9 列 ✅
- §5.1 WARN 块顺序 ✅
- §5.3 WARN 触发条件矩阵 ✅
- §6 report.md 强制 banner（短样本期）✅

---

## 八、已知问题 / 未完成项

### 非阻塞观察

1. **真实 12 个月样本期未跑**：DuckDB 数据停在 2026-02-27（金策智算未同步）；Hermes 二次验收时如需全量数据回测，请先按 MEMORY.md `jince-zhisuan-duckdb-sync.md` 触发同步。当前 e2e 用 30 天 sample_db 验证管线正确性，业绩数字本身无策略意义。
2. **`data_path` 在 summary.json 中是反斜杠 Windows 路径**：写盘时已转 `/`，但 reader.db_path 原样保留；下游 RS 解析需统一处理（建议 Hermes 阶段确认是否需要在 report.py 写盘前 normalize）。
3. **report.md 部分中文段落 emoji 缺失**：04 §6 模板使用 `> ⚠️` emoji；CLAUDE.md 全局规则禁止 emoji，本阶段以 `> WARNING` 文本替代。如 Hermes 偏好恢复 emoji，单独切换。
4. **CLI 不输出 progress bar**：长样本期跑 1+ 分钟时无进度反馈。Phase 5 batch runner 阶段可考虑加 tqdm；v0.2 不要求。

### 未完成项

无 Phase 4 内未完成项。Phase 5 按授权令进入下一阶段。

---

## 九、下一阶段计划

按夜班授权令，进入 **Phase 5：batch runner + retention + tests**。

实现顺序：

1. **Task 5.1** `backtest/configs/experiments/baseline_grid.yaml`：批量实验声明（参数网格）。
2. **Task 5.2** `backtest/scripts/run_batch.py`：批量 runner。读 yaml 声明 → 展开成多个临时 yaml → 顺序调用 `run_backtest.py` 主流程 → 汇总 `F:\backtest_workspace\batch_summary\<batch_id>.csv`。
3. **Task 5.3** `backtest/scripts/clean_results.py`：retention 完整版（删除 `results/` 中早于 N 天的子目录，归档到 `results_archive/`）。仍保持 import 隔离（不进 reader/engine 主线）。
4. **Task 5.4** `backtest/scripts/validate_data.py`：DuckDB 数据校验（覆盖率 / 去重 / WAL / coverage 报告输出到 `F:\backtest_workspace\logs\`）。
5. 测试：每脚本 ≥ 3 测试；全 backtest 套件全绿。
6. 写 `05f_phase5_batch_tests_acceptance.md`，commit 后归零。

约束：
- 不引入新数据源、新策略层、新交易接口。
- batch_summary 写 F 盘；不在 C/D 盘留产物。
- 不破坏 03 / 04 / 05* 已签字契约。

---

签字：CC（夜班自主验收）
日期：2026-06-14
依据：`01_cc_full_night_authorization.md` §一、§三、§六.1
