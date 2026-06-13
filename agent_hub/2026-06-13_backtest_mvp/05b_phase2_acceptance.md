# Phase 2 验收：strategy_core 实现完成

日期：2026-06-14（夜班）
验收人：CC（夜班自主验收，依据 `01_cc_full_night_authorization.md`）
对象：Phase 2 交付（`backtest/strategy_core/` 实现 + 测试）

---

## 一、验收结论

**Phase 2 自审通过。允许进入 Phase 2.5（输出 schema 冻结）。**

依据：

1. 03_interface_freeze.md 已 Hermes 签字（OQ-A..OQ-F 决策齐全）。
2. Task 2.1 / 2.2 / 2.3 / 2.4 全部按签字 schema 实现，53 个新增测试全部通过。
3. 全 backtest 套件 83 / 83 PASS（Phase 1A 30 + Phase 2 53），无回归。
4. 不触碰生产策略 / release / 交易接口；不写 `F:\金策智算\` / 不写 C 盘 / 不写 D 盘大产物；不引入 xtquant。

---

## 二、本阶段实现内容

| Task | 内容 | Commit |
|---|---|---|
| 2.1 | `interface.py` evaluate_day 8 参数签名 + `make_empty_decision()` 工厂 + `enums.py`（7 sell reasons + 8 blocked + LAYER/PRIORITY 常量） | `c14b265` |
| 2.2 | `scoring_adapter.py` `score_universe()`：包装 `core.scoring.dimension6plus2.ScoreCalculator6Plus2`；reader vol→volume 字段映射；zero 模式强制 `score_sector=0` 并重算 total；缺数据保护 | `8a8f2e4` |
| 2.3 | `risk_adapter.py` `evaluate_position_triggers/pick_top_reason/priority_of`；`decision.py` `make_decision()`：sell/buy/replace/blocked 完整流程，diagnostics（scores/filter_counts/trigger_counts/warnings）逐字段填充 | `d609193` |
| 2.4 | `interface.py` evaluate_day 真实整合：score_universe → make_decision → warnings 合并；docstring 更新 | `226b3ca` |

### 关键设计决策（按 03 签字版）

- **OQ-A**：`SELL_REASON_EARLY_STOP`（3 天 -5%）和 `SELL_REASON_EARLY_KICK`（5 天 < 3%）作为两条独立规则并存。
- **OQ-B**：评分字段命名 `score_volumeprice`，与 6+2 scorer 内部输出字段对齐。
- **OQ-C**：`SELL_REASON_CONFIRM` 仅保留枚举值，v0.2 不实现触发器。
- **OQ-D**：`BLOCKED_LIMIT_UP` 单一阈值 9.95（不分板）。
- **OQ-E**：strategy_core 不计算 PE/PB；valuation 维度按 scorer 默认中性分。
- **OQ-F**：`target_volume = 0`，由 engine 在 Phase 3 撮合层折算。

### 优先级映射（03 §7）

| reason | priority | layer |
|---|---|---|
| stop_loss / early_stop | 1 | bottom_line |
| early_kick / replace / confirm | 2 | confirm |
| score_drop / warning | 3 | warning |

`pick_top_reason()` 取 priority 最小者作为 sell_decision；其它触发理由计入 `diagnostics.trigger_counts`。

### blocked 过滤链短路顺序（decision.py）

`insufficient_history → suspended → already_held → limit_up → max_daily_pct → max_bias5 → min_core → min_score`

每个 universe code 命中第一条即记录到 `blocked_candidates`，`filter_counts` 自增。

---

## 三、修改文件清单

### 新增文件

| 文件 | 用途 | 行数（约） |
|---|---|---|
| `backtest/strategy_core/__init__.py` | 包入口 | 8 |
| `backtest/strategy_core/enums.py` | sell/blocked/layer/priority 常量 | 50 |
| `backtest/strategy_core/interface.py` | `evaluate_day` + `make_empty_decision` | 90 |
| `backtest/strategy_core/scoring_adapter.py` | `score_universe()` 包装层 | 100 |
| `backtest/strategy_core/decision.py` | `make_decision()` 决策层 | 250 |
| `backtest/strategy_core/risk_adapter.py` | `evaluate_position_triggers()` 单仓风险评估 | 80 |
| `backtest/tests/test_strategy_core_interface.py` | 4 测试 | 70 |
| `backtest/tests/test_score_universe.py` | 11 测试 | 130 |
| `backtest/tests/test_decision_logic.py` | 26 测试 | 280 |
| `backtest/tests/test_evaluate_day_integration.py` | 12 测试 | 170 |

### 修改文件

无（除 Task 2.4 在 Task 2.1 已交付的 interface.py 上替换 evaluate_day 函数体）。

不修改 paths.py / duckdb_reader.py / universe.py / hashing.py / clean_results.py / 任何 Phase 1A 已交付文件。

---

## 四、Commit 列表

```text
c14b265 feat(strategy_core): interface skeleton + enums (post gate #1)
8a8f2e4 feat(strategy_core): score_universe wrapper over 6+2 scorer (SPEC §3.4)
d609193 feat(strategy_core): decision layer with priority/replace/blocked filters
226b3ca feat(strategy_core): integrate evaluate_day end-to-end
```

---

## 五、测试

### 测试命令

```bash
# 标准
py -3.10 -m pytest backtest/tests -v

# Hermes 环境绕过 .pth 编码（已知本机问题，与项目无关）
py -3.10 -S -c "import sys; sys.path.append(r'C:\Users\Administrator\AppData\Local\Programs\Python\Python310\Lib\site-packages'); import pytest; raise SystemExit(pytest.main(['backtest/tests','-v']))"
```

### 测试结果

```text
83 passed in 1.32s
```

按文件分布：

| 测试文件 | 通过数 | 覆盖契约 |
|---|---|---|
| test_paths.py | 4 | 决策 J 路径 + v0.3 OPEN_QUESTION |
| test_init_workspace.py | 2 | F 盘工作区初始化 |
| test_duckdb_reader_readonly.py | 2 | DuckDB read-only 强制 |
| test_duckdb_reader_dedup.py | 1 | 双时间戳 dedup |
| test_duckdb_reader_coverage.py | 3 | 全表/universe coverage / 越界拒绝 |
| test_duckdb_reader_calendar.py | 2 | 交易日历 |
| test_concurrent_sync_wal.py | 2 | .wal 并发同步检测 |
| test_data_hash.py | 3 | data_hash 9 字段公式（决策 F） |
| test_universe_schema.py | 6 | universe CSV schema |
| test_paths_disk_partition.py | 4 | D/F/C 边界 + 金策智算只读 |
| test_clean_results_isolation.py | 1 | 硬约束 #6 import 链 |
| **test_strategy_core_interface.py** | **4** | **Task 2.1 接口骨架** |
| **test_score_universe.py** | **11** | **Task 2.2 6+2 包装** |
| **test_decision_logic.py** | **26** | **Task 2.3 决策层全规则** |
| **test_evaluate_day_integration.py** | **12** | **Task 2.4 端到端** |
| **合计** | **83** | |

### 关键测试场景覆盖

- **纯函数语义**（03 §1 约束 1）：`test_evaluate_day_is_deterministic` + `test_evaluate_day_no_input_mutation`
- **OQ-A early_stop / early_kick 并存**：`test_early_stop_triggers_at_3_days` + `test_early_kick_triggers_at_5_days`
- **OQ-C confirm 不触发**：`test_confirm_not_triggered_in_v02`
- **OQ-D 9.95 阈值**：`test_blocked_limit_up`
- **OQ-F target_volume=0**：`test_sell_decision_target_volume_zero` + `test_buy_top_candidates_when_slots_open`
- **优先级排序**：`test_priority_stop_loss_above_score_drop` + `test_sell_priority_ordering`
- **换仓 score_gap≥15**：`test_replace_when_score_gap_15` + `test_no_replace_when_gap_below_threshold`
- **diagnostics.scores 全覆盖**（03 §6 约束 5）：`test_diagnostics_scores_includes_all_scored`
- **sector_heat 非 zero 拒绝**（03 §4 约束 2）：`test_sector_heat_mode_static_raises`
- **None 入参防御**：`test_evaluate_day_handles_none_universe/positions/aux_data`

---

## 六、是否触碰生产文件：**否**

明确未触碰：

- `release/v1.0/` — 未读未写
- QMT 生产 `strategy_main.py` — 未读未写
- `core/strategy/` 主升浪/全天版策略 — 未读未写
- `core/scoring/dimension6plus2.py` — **只读 import**，未修改一行
- `core/utils.py` — **只读 import**（calc_bias / ma / safe_last），未修改
- `core/risk_manager*` — 未 import，本 Phase 用独立 `risk_adapter.py`，按 03 约束「不改 core/risk_manager」
- `D:\QMT_POOL\` — 未写
- `F:\金策智算\` — 未读未写（`ScoreCalculator6Plus2(sector_heat_path=None)` 显式禁用文件读取）

---

## 七、是否违反 SPEC 边界：**否**

逐条核对硬边界（授权令 §四）：

| # | 边界 | 状态 |
|---|---|---|
| 1 | 不修改 release/v1.0 | ✅ 未触碰 |
| 2 | 不修改 strategy_main.py | ✅ 未触碰 |
| 3 | 不调用 passorder | ✅ 全 backtest/ 包 grep 无 passorder |
| 4 | 不接 QMT 实盘/模拟交易 | ✅ 无交易 import |
| 5 | 不启动真实/模拟委托 | ✅ 纯计算，无网络 |
| 6 | 不写 F:\金策智算\ | ✅ reader read-only；scoring_adapter sector_heat_path=None |
| 7 | 不读写模式打开 quantifydata.duckdb | ✅ access_mode='read_only' 强制 |
| 8 | 不在 C/D 盘写 results/cache/sample_db/logs | ✅ 全在 F:\backtest_workspace\ |
| 9 | 不引入 xtquant/MiniQMT | ✅ grep 全 backtest/ 无 xtquant/MiniQMT |
| 10 | 不混入 IMA 主升浪 | ✅ 未实现 IMA 任何代码 |
| 11 | 不改 6+2 生产策略主逻辑 | ✅ scorer 仅作为依赖 import |
| 12 | 不破坏性 git 操作 | ✅ 仅 add / commit |

03 接口冻结契约逐条核对：

- §1 evaluate_day 8 参数顺序 / 名字 / 类型 ✅
- §1 约束 1 纯函数 / 无 IO / 无随机 ✅（确定性测试通过）
- §1 约束 2 无 xtquant / passorder / ContextInfo ✅
- §1 约束 3 3.6-safe 子集 ✅（无 dict[str,...] / 联合 / walrus / match-case / dataclass）
- §6 6 顶层 key 全在 ✅
- §6 diagnostics 4 子键全在 ✅
- §6 约束 5 scores 含所有 scored code ✅
- §7 sell reason 7 枚举（含 EARLY_KICK，删 BOTTOM_LINE reason）✅
- §8 blocked 8 枚举（含 INSUFFICIENT_HISTORY）✅
- target_volume = 0（OQ-F）✅
- limit_up 9.95（OQ-D）✅
- confirm 不触发（OQ-C）✅

---

## 八、已知问题 / 未完成项

### 非阻塞观察

1. **buy_candidates `target_cash` 资金分配粒度**：当前实现按 `total_asset / max_positions` 等权分配；如未来需要「剩余可用现金 / 待买只数」精细分配（避免持仓未清空时新买仓位过大），将在 Phase 3 engine 层调整（不破坏 strategy_core 接口）。
2. **replace 算法每日至多触发一次**：当前 decision.py 在最弱持仓与最强候选之间比较，每日最多换一只。如需多重 replace，可在不破坏接口前提下在 Phase 3 engine 层增强；或留作 v0.3 课题。
3. **`BLOCKED_INSUFFICIENT_HISTORY` 语义略宽**：兼覆「< 60 行」与「无 score record」两种情况。语义合理（都是数据不足），但 Phase 4 报告时建议在 logs 里区分子原因。
4. **本机 Python 3.10 `.pth` GBK 编码问题**：`py -3.10` 直接启动在某些环境失败，已有 `py -3.10 -S` 绕过，**与项目代码无关**，已在 qmt-pitfalls skill 记录。

### 未完成项

无 Phase 2 内未完成项。Phase 2.5 / 3 / 4 / 5 按授权令进入下一阶段。

---

## 九、下一阶段计划

按夜班授权令，进入 **Phase 2.5：输出 schema 冻结**：

1. 写 `04_output_schema_freeze.md`：列 6 文件全字段（summary.json / trades.csv / equity_curve.csv / positions.csv / logs.txt / report.md）
2. 字段来源对齐 SPEC v0.2 §3.x + 03 §6 diagnostics 字段
3. CC 自审签字（夜班授权下不等 Hermes）
4. 写 `05c_phase25_schema_acceptance.md`
5. 立刻进入 Phase 3：execution / portfolio / metrics / daily_engine

---

签字：CC（夜班自主验收）
日期：2026-06-14
依据：`01_cc_full_night_authorization.md` §一、§三、§六.1
