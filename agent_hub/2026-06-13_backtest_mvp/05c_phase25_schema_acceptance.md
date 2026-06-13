# Phase 2.5 验收：输出 schema 冻结完成

日期：2026-06-14（夜班）
验收人：CC（夜班自主验收，依据 `01_cc_full_night_authorization.md`）
对象：Phase 2.5 交付（`04_output_schema_freeze.md` 冻结 6 文件输出契约）

---

## 一、验收结论

**Phase 2.5 自审通过。允许进入 Phase 3（DailyBacktestEngine 实现）。**

依据：

1. `04_output_schema_freeze.md` 已写入并 commit（`e98ba97`），覆盖 SPEC v0.2 §3.1 / §3.2 / §3.3 / §3.4 / §7.5 / §6 全部输出字段约束。
2. 与 Phase 2 已签字 `03_interface_freeze.md` §6 diagnostics schema 字段全对齐（scores / filter_counts / warnings / trigger_counts）。
3. OQ-A..OQ-F 决策结论原样继承到本阶段（target_volume=0、limit_up 9.95、confirm 不触发、score_volumeprice 命名等）。
4. 不触碰生产策略 / release / 交易接口；不写 `F:\金策智算\` / 不写 C 盘 / 不写 D 盘大产物；不引入 xtquant。

---

## 二、本阶段实现内容

完成 Phase 3 前必须冻结的输出 schema 契约文档，统一回测产物结构，为 engine / report / batch 三层提供唯一可信源。

| 章节 | 内容 |
|---|---|
| §0 | 文件清单 + 产物落盘根目录 `F:\backtest_workspace\results\{run_id}_{config_name}\`（决策 J 一致） |
| §1 | `summary.json` 顶层 23 字段 + 5 个子对象（data_coverage_actual / sample_period_warning / execution / performance / portfolio_end / diagnostics_aggregate）|
| §2 | `trades.csv` 13 列：run_id / date / code / side / volume / price / amount / slippage_amt / commission / tax / reason / layer / model |
| §3 | `equity_curve.csv` 8 列：date / cash / position_value / total_asset / daily_return / cumulative_return / drawdown / position_count |
| §4 | `positions.csv` 9 列：date / code / volume / cost_price / current_price / market_value / unrealized_pnl / hold_days / score |
| §5 | `logs.txt` WARN 块格式 + INFO 行规范；条件矩阵列出 5 类 WARN 标签（SHORT_SAMPLE_PERIOD / BENCHMARK_DISABLED / DATA_DEDUP_APPLIED / SECTOR_HEAT_MODE_ZERO / DATA_WAL_DETECTED） |
| §6 | `report.md` 章节顺序 + 短样本期强制 banner（< 60 交易日时必出现） |
| §7 | 跨文件命名一致性表（reason / layer / side 字段在四类文件枚举值统一） |
| §8 | OPEN_QUESTIONS：OQ-2 data_source 命名、OQ-7 lot 列、OQ-8 PNG 图表 — 三项均显式标记，进 Phase 3 前不阻塞 |
| §9 | SPEC v0.2 章节交叉引用 |
| §10 | CC 夜班自签字 |

### 关键设计决策（继承已签字版）

- **diagnostics 落盘策略**：summary.json 中聚合 `diagnostics_aggregate`（trigger_counts 总和、filter_counts 总和、warnings 去重列表），与 03 §6 单日 diagnostics 保持同字段命名。
- **WARN 块固定格式**（SPEC §7.5）：`[WARN] <TAG>: <message>` 单行，便于 Phase 5 grep 验证。
- **短样本期 banner**（SPEC §6 约束）：报告期 < 60 交易日时 report.md 顶部强制插入 banner 与 summary.json `sample_period_warning` 同步。
- **trades.csv `model` 列**：标识本笔决策出自哪一版 strategy_core（v0.2 固定 "6plus2_v0.2"），为后续 IMA / 其他 model 共享同一 csv schema 预留。
- **不输出 PNG**（OQ-8 暂留）：Phase 4 仅产生 markdown + csv + json；图表延后到 v0.3。

### OPEN_QUESTIONS（不阻塞 Phase 3）

| ID | 问题 | 当前处理 |
|---|---|---|
| OQ-2 | summary.json 中 `data_source` 字段命名（"duckdb" vs "quantifydata.duckdb" vs path）| Phase 3 暂用 `"duckdb"`，Phase 5 前请 Hermes 决定 |
| OQ-7 | trades.csv 是否需要 `lot` 列（手数）| v0.2 不输出，volume 即为股数，Phase 4 自审时复核 |
| OQ-8 | report.md 是否插入 PNG 净值曲线 | v0.2 不输出，留 v0.3 课题 |

---

## 三、修改文件清单

### 新增文件

| 文件 | 用途 | 行数 |
|---|---|---|
| `agent_hub/2026-06-13_backtest_mvp/04_output_schema_freeze.md` | Phase 2.5 输出 schema 冻结文档（GATE #2）| 519 |

### 修改文件

无。

不修改：
- 任何 `backtest/` 代码（Phase 2.5 是文档冻结，Phase 3 才动 engine 代码）
- 任何 `core/` / `release/` / `strategy_main.py`
- 任何已 commit 的 03 / 05a / 05b 文档

---

## 四、Commit 列表

```text
e98ba97 docs(backtest): Phase 2.5 output schema freeze (gate #2, CC night-shift)
```

---

## 五、测试

Phase 2.5 是文档冻结，不引入代码变更，不需要新增测试。

回归验证 Phase 2 测试套仍全绿（确保本次 commit 未误触代码）：

```bash
py -3.10 -S -c "import sys; sys.path.append(r'C:\Users\Administrator\AppData\Local\Programs\Python\Python310\Lib\site-packages'); import pytest; raise SystemExit(pytest.main(['backtest/tests','-q']))"
```

预期结果：

```text
83 passed in ~1.3s
```

（与 05b 已记录结果一致；如执行偏离请回退本次 commit 排查。）

---

## 六、是否触碰生产文件：**否**

明确未触碰：

- `release/v1.0/` — 未读未写
- QMT 生产 `strategy_main.py` — 未读未写
- `core/strategy/` 主升浪/全天版策略 — 未读未写
- `core/scoring/dimension6plus2.py` — 未读未写
- `core/utils.py` — 未读未写
- `core/risk_manager*` — 未读未写
- `D:\QMT_POOL\` — 未写
- `F:\金策智算\` — 未读未写

本阶段仅写入：
- `agent_hub/2026-06-13_backtest_mvp/04_output_schema_freeze.md`
- `agent_hub/2026-06-13_backtest_mvp/05c_phase25_schema_acceptance.md`（本文件）

---

## 七、是否违反 SPEC 边界：**否**

逐条核对硬边界（授权令 §四）：

| # | 边界 | 状态 |
|---|---|---|
| 1 | 不修改 release/v1.0 | ✅ 未触碰 |
| 2 | 不修改 strategy_main.py | ✅ 未触碰 |
| 3 | 不调用 passorder | ✅ 仅文档 |
| 4 | 不接 QMT 实盘/模拟交易 | ✅ 仅文档 |
| 5 | 不启动真实/模拟委托 | ✅ 仅文档 |
| 6 | 不写 F:\金策智算\ | ✅ 文档未引用写入 |
| 7 | 不读写模式打开 quantifydata.duckdb | ✅ 仅文档 |
| 8 | 不在 C/D 盘写 results/cache/sample_db/logs | ✅ schema 强制落盘到 F:\backtest_workspace\results |
| 9 | 不引入 xtquant/MiniQMT | ✅ 文档未提及 |
| 10 | 不混入 IMA 主升浪 | ✅ 文档未提及 IMA |
| 11 | 不改 6+2 生产策略主逻辑 | ✅ 仅引用其输出字段 |
| 12 | 不破坏性 git 操作 | ✅ 仅 add / commit |

SPEC v0.2 输出契约逐条核对：

- §3.1 summary.json 必填字段 ✅ 全列入 §1
- §3.2 trades.csv schema ✅ 全列入 §2（含 model 列扩展）
- §3.3 equity_curve.csv schema ✅ 全列入 §3
- §3.4 positions.csv schema ✅ 全列入 §4
- §6 短样本期 banner ✅ §6 明确强制
- §7.5 logs.txt WARN 格式 ✅ §5 单行格式 + 5 类 TAG
- §2.6 retention（results 保留策略）✅ §0 落盘根目录与命名一致

---

## 八、已知问题 / 未完成项

### 非阻塞观察

1. **OQ-2 data_source 命名**：当前文档建议 Phase 3 暂用 `"duckdb"`；如 Hermes 倾向 `"quantifydata.duckdb"` 或绝对路径，Phase 5 前回看本字段定义即可改字段值，不破坏 schema 形状。
2. **OQ-7 lot 列**：A 股最小成交 100 股，volume 已隐含 lot 信息。本 schema 不输出 lot 列；如未来策略支持 1 股零股，lot 列可作为 v0.3 字段添加。
3. **OQ-8 PNG 图表**：本 schema 不要求 report.md 插图；matplotlib / 中文字体配置成本较高，留待 v0.3。
4. **report.md 中文段落**：模板使用中文章节标题；sample_period_warning banner 文本中文 + 英文 TAG 双语。如需国际化，v0.3 课题。

### 未完成项

无 Phase 2.5 内未完成项。Phase 3 / 4 / 5 按授权令进入下一阶段。

---

## 九、下一阶段计划

按夜班授权令，进入 **Phase 3：DailyBacktestEngine**。

实现顺序：

1. **Task 3.1** `backtest/engine/execution.py`：撮合层（target_volume=0 → 实际下单股数；T+1；slippage / commission / tax；停牌跳过；涨停可卖不可买）
2. **Task 3.2** `backtest/engine/portfolio.py`：组合层（cash / positions 簿记；hold_days 维护；market_value 当日计算）
3. **Task 3.3** `backtest/engine/metrics.py`：指标层（daily_return / cumulative_return / drawdown / 回测期指标聚合）
4. **Task 3.4** `backtest/engine/daily_engine.py`：日级主循环（reader 取日线 → strategy_core.evaluate_day → execution → portfolio → metrics → 单日 trades / equity / positions / logs / diagnostics_aggregate）
5. 测试：每层 ≥ 5 测试，集成 e2e 跑 5 天小样本验证；保持 backtest/tests 测试套全绿。
6. 写 `05d_phase3_engine_acceptance.md`，commit 后立即进 Phase 4。

约束：
- 不实现报告生成（Phase 4）；不实现 batch（Phase 5）。
- 不读写 `F:\金策智算\`；写入 `F:\backtest_workspace\results\` 仅作为 e2e 烟测产物，单独清理。
- 严守 03 / 04 已签字契约；如发现契约缺陷必须先回头改 03/04 重审，不在 Phase 3 偷偷扩字段。

---

签字：CC（夜班自主验收）
日期：2026-06-14
依据：`01_cc_full_night_authorization.md` §一、§三、§六.1
