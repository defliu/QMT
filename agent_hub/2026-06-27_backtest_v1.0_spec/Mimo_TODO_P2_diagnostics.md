# MIMO 工单 — V1.0 Phase 2:diagnostics 聚合通用化 + 测试解耦

**状态**: 草稿(待诚哥确认 V1.0 SPEC 后发出)
**日期**: 2026-06-27
**作者**: CC
**对应 SPEC**: `specs/SPEC_BACKTEST_FACTORY_V1.0_REFACTOR.md` §7
**对应 freeze**: `agent_hub/2026-06-23_backtest_generalization/06_interface_freeze_v10.md`
**预计工时**: ≤ 2 小时

---

## 背景

V1.0 Phase 2 是最痛债务。daily_engine 的 diagnostics 聚合仍硬编码 ima_uptrend_v31,新策略自定义 namespace 不进 summary。本工单清掉硬编码 + 死代码 + 测试解耦。

**前置**:Phase 1(06 freeze)已由诚哥签字,L2 重冻结承认 trigger_counts/filter_counts 下沉到 strategy_specific。

---

## 一、必做

### TASK-1. 清死代码
**目标路径**: `backtest/engine/daily_engine.py`
**内容/做法**:
- 删 L146-167 死代码 `_avg_filter_counts` / `_sum_trigger_counts`(定义了从未调用,grep 确认)
- 删 L359-360 `daily_filter_counts` / `daily_trigger_counts` 列表声明(填了不消费)
- 删 L460-463 ima 旁路(`_ima = ss_today.get("ima_uptrend_v31", {})` + 两个 append 到死代码列表)
- 保留 L458-459 通用通路 `daily_strategy_specific.append(ss_today)`

### TASK-2. 去 trigger_counts 特例
**目标路径**: `backtest/engine/daily_engine.py` L226-229
**内容/做法**:
- `_aggregate_strategy_specific` 内 `if sub_key == "trigger_counts"` 特例删除
- 统一规则:所有 `dict[str,number]` 子键 → `{key}_avg_per_day`;其他类型 → `{key}_present`
- 按 06 freeze §4 / SPEC 附录 A 实现
- **不认任何特定 namespace 名字**

### TASK-3. 新增测试 spy 机制
**目标路径**: `backtest/strategies/__init__.py`
**内容/做法**:
- 新增 `register_test_spy(name, fn)` + 上下文管理器 `strategy_spy(name)`
- `with strategy_spy("production/ima_uptrend_v31"): ...` 临时替换 registry fn,退出 try/finally 还原
- 不污染生产 registry

### TASK-4. 测试解耦
**目标路径**: `backtest/tests/`
**内容/做法**:
- `test_daily_engine.py` L259 `{"ima_uptrend_v31"}` → 从 `strategy_name` 配置动态取,断言"含当前配置策略 namespace"
- L262-263 filter_counts/trigger_counts 断言 → 改为断言"任一注册策略 namespace 下有这两键",不绑死名字
- L298-320 三处 `_REGISTRY[name]=spy` → 改用 `strategy_spy()` 上下文管理器
- `test_pit_manifest.py` L155-174/L198-217 同上
- `test_strategy_decision_schema_v04.py` L33-34/L42/L56/L66/L73 同上
- **`test_decision_logic.py` 保留硬编码**(6+2 专属单测,reference strategy 私有测试,非通用化测试)

### TASK-5. 新增通用化测试
**目标路径**: `backtest/tests/test_diagnostics_aggregate_arbitrary_namespace.py`(新建)
**内容/做法**:
- 注册临时 spy 策略,返回自定义 namespace 如 `{"my_test_strat": {"custom_counts": {"a":1,"b":2}}}`
- 断言 summary 里 `strategy_specific.my_test_strat.custom_counts_avg_per_day` 存在
- 证明任意 namespace 自动进 summary

### TASK-6. 一致性验收(P2 core100)
**内容/做法**:
- 迁移前:当前 master 跑 `p2_core100.yaml` → 产物存 `F:/backtest_workspace/v04_baseline/p2_core100/`
- 本工单改后:跑 `p2_core100.yaml` → 存 `v10_p2_diagnostics/p2_core100/`
- `python backtest/scripts/_compare_sha256.py v04_baseline/p2_core100 v10_p2_diagnostics/p2_core100`
- trades/equity/positions 业务列 sha256 **bit-identical**(剥除 run_id)
- summary.json `performance` 四指标(total_return/annualized_return/sharpe/max_drawdown)容差 0
- `diagnostics_aggregate` **允许结构差异**(L2 重冻结批准),验收单独标注"允许差异项"
- **不通过 → 停,不 commit,写回执报错**

---

## 二、严禁

1. 禁止改 `evaluate_day` 8 参签名 / StrategyDecision 6 顶层键(L1 红线)
2. 禁止改 6+2 业务逻辑(`decision.py`/`scoring_adapter.py`/`risk_adapter.py` 只读不碰)
3. 禁止改 L2 其他产物 schema(trades/equity/positions/summary 顶层 23 字段)
4. 禁止影响冻结期/模拟盘/实盘策略
5. 禁止 `git add .`,逐文件 add
6. 禁止 push
7. 禁止 `test_decision_logic.py`(6+2 私有测试)
8. 一致性 diff 不通过禁止 commit

---

## 三、完成回执(MIMO 追加)

```markdown

---

## 完成回执

**执行时间**: <ISO 8601, date -u>
**MIMO 模型**: <实际名>
**自检**:
- [ ] TASK-1 死代码清理(grep 确认 _avg_filter_counts/_sum_trigger_counts 无残留)
- [ ] TASK-2 trigger_counts 特例删除,统一 avg_per_day 规则
- [ ] TASK-3 strategy_spy 上下文管理器实现
- [ ] TASK-4 测试解耦(test_decision_logic.py 未碰)
- [ ] TASK-5 新增 test_diagnostics_aggregate_arbitrary_namespace.py
- [ ] TASK-6 P2 core100 一致性 diff 通过(trades/equity/positions bit-identical,performance 容差0)
- [ ] 全量 pytest PASS(238+)
- [ ] 未改 evaluate_day 8参/6键/6+2业务/L2其他schema
- [ ] 未 push
**一致性报告**: <_compare_sha256.py 输出摘要>
**一句话结论**: <diagnostics 聚合已通用化,新策略 namespace 自动进 summary;P2 core100 一致性通过>
```
