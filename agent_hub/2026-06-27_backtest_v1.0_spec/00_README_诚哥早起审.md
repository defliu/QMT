# V1.0 重构 SPEC 起草 — 交付总览(诚哥早起审)

**日期**: 2026-06-27 通宵
**作者**: CC
**状态**: SPEC + freeze + 工单草稿已落盘,**待诚哥确认后派 MIMO**

---

## 诚哥,先看这里

昨晚你让我通宵搞定 T-001(回测工厂通用化)。**Round 4 拍板白纸黑字写着"SPEC 完成并经诚哥确认前不得启动工程改造"**,所以我没派 MIMO 改代码,只做了 CC 本职:**起 SPEC + freeze + 工单草稿**。

你审完 SPEC 确认后,我立刻派 MIMO 干 Phase 2-4。

---

## 今晚交付物(5 个文件)

| # | 文件 | 是啥 | 状态 |
|---|---|---|---|
| 1 | `specs/SPEC_BACKTEST_FACTORY_V1.0_REFACTOR.md` | 正式重构 SPEC(18章+3附录) | ✅ 起草完 |
| 2 | `agent_hub/2026-06-23_backtest_generalization/06_interface_freeze_v10.md` | V1.0 freeze(L2重冻结+L3扩展+附录C对照表) | ✅ 起草完 |
| 3 | `agent_hub/2026-06-27_backtest_v1.0_spec/Mimo_TODO_P2_diagnostics.md` | Phase 2 工单(diagnostics通用化,最痛) | ✅ 草稿 |
| 4 | `agent_hub/2026-06-27_backtest_v1.0_spec/Mimo_TODO_P3_yaml_registry.md` | Phase 3 工单(yaml迁移+registry自动扫描) | ✅ 草稿 |
| 5 | `agent_hub/2026-06-27_backtest_v1.0_spec/Mimo_TODO_P4_astock_event_batch.md` | Phase 4 工单(astock+event_study+batch+尾债,可后置) | ✅ 草稿 |

---

## 关键认知(摸底发现)

1. **Round 4 拍板已存在**(2026-06-23,7 项核心决策全定了),不是没拍板
2. **v0.4 Phase 1 已落地大部分通用化**:registry 已存在(3 策略已注册)、6+2 已物理迁出、trading_model 配置化已做、diagnostics namespace 化已做
3. **V1.0 不是从零设计,是收口 10 项遗留债务**:
   - D1 diagnostics 聚合硬编码(MS-G 遗留,最痛)
   - D2 yaml `strategy:`→`strategy_params:` 迁移(16 config)
   - D3 registry 启动 import 手写 → 自动扫描
   - D4 测试 spy 与策略名强耦合
   - D5 astock parquet reader 缺失
   - D6 event_study stub
   - D7 batch 串行无续跑
   - D8 L2 freeze 被 v0.4 静默打破,需补登
   - D9 huang_zhongjun_combo 未文档化
   - D10 paths.py 占位符不一致

---

## 需要你拍板的 4 个决策点(SPEC §0 已列)

1. **L2 顶层 trigger_counts_total/filter_counts 下沉到 strategy_specific** 是否接受?
   - 推荐:接受(v0.4 已既成事实,06 freeze 只是补登,非新破坏)
2. **event_study stub 是否引入 paradigm registry 第二级**?
   - 推荐:不引入,只留函数签名 stub(更简单,YAGNI)
3. **Phase 4 是否纳入 V1.0 还是拆 V1.1**?
   - 建议:4a/4e 纳入(轻量),4b stub 纳入,4c/4d 可拆 V1.1
4. **registry 自动扫描(pkgutil)vs 保留手写 import**?
   - 推荐:自动扫描(onboarding 痛点),手写 import 作备选

---

## 派单顺序(SPEC §18)

```
你确认 SPEC + 06 freeze → CC 打 git tag freeze-v1.0-L2/L3
  → 派 MIMO Phase 2(diagnostics,最痛,优先) → CC 验收(P2 core100 一致性 diff)
  → 派 MIMO Phase 3(yaml 迁移,可与 P2 并行不同文件) → CC 验收
  → 派 MIMO Phase 4(可后置,按需) → CC 验收
```

Phase 2 改 engine+tests,Phase 3 改 scripts+yaml+registry,文件不重叠,可并行派两个 MIMO。

---

## RS 三问(已代答,SPEC §15)

基于研究方向代答:
- Q1 Python 类/函数为主(yaml 只做参数)
- Q2 组合回测为主 + 事件研究其次(因子 IC 后置)
- Q3 旧 yaml 一次性迁移可接受,但需 P2 core100 一致性 diff 验收

若你的实际诉求与代答偏差大,告诉我,SPEC 会校准。

---

## 未做(明示)

- 未动 `backtest/` 任何代码(Round 4 红线)
- 未派 MIMO 改代码(等 SPEC 确认)
- 未 commit(等你审完一起)
- 未跑 Phase 2-4(等派单)

---

*早起审完 SPEC 告诉我"确认"或哪里要改,我立刻打 tag + 派 MIMO。*
