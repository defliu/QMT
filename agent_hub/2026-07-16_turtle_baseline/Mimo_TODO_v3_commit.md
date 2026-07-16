# 海龟基线回测 v3 - commit 工单

**日期**: 2026-07-16
**作者**: CC
**目的**: v2 验收通过（仓位公式改标准海龟 avg_risk_pct=0.893%≈1%、beat_bench=100%、抽查补数值、4文件齐全），成果落地 commit。本工单**授权 git commit**。
**预计工时**: ≤ 5 分钟

---

## 一、必做

### TASK-1. commit 脚本 + 工单（授权 git）

**commit 范围**（只 add 这两项，**不 add backtest_results/**）：
```
git add scripts/backtest_turtle_baseline.py agent_hub/2026-07-16_turtle_baseline/
```

**commit message**（用 heredoc，单 commit）：
```
feat(turtle): 海龟策略A股基线回测v1.0(沪深300/2022-2025)

独立研究脚本(不进QMT build)。数据源astock parquet前复权(SPEC写mootdx实测默认不复权弃用)。
诚哥拍板修SPEC仓位公式笔误(原公式2*atr/price*100使单笔风险=100*price与atr无关),
改标准海龟shares=单笔风险/(2*ATR)单笔风险固定1%。

结果(298只,5623笔):年化0.5%/胜率34%/盈亏比2.41/正收益55.3%/100%跑赢沪深300(基准-19.96%)/
最大回撤24%。结论:原版海龟在A股保本微赚,收益弱不值得做。
产物在backtest_results/turtle_baseline/(不进git,可重建)。
```

### TASK-2. 验证 commit + working tree

- `git log --oneline -1` 确认新 commit 落地，hash 对得上
- `git status --short` 确认 working tree 状态：backtest_results/turtle_baseline/ 仍 untracked（**不要** add 它），其余无残留
- **不要 push**（诚哥 cc-no-deploy：CC 到 commit 为止；push 诚哥自己来或单独授权）

---

## 二、严禁

1. 禁止 `git add backtest_results/`（产物不进 git，项目惯例）
2. 禁止 push（不授权）
3. 禁止改动任何代码文件（本工单只 git 操作，v2 脚本已验收通过不动）
4. 禁止 commit 工单外的文件（会话前 dirty 的 M 文件一概不碰）

---

## 三、完成回执

```markdown

---

## 完成回执

**执行时间**: <date -u 真实时刻>
**MIMO 模型**: <实际名>
**自检**:
- [ ] TASK-1 已 git add scripts/backtest_turtle_baseline.py + agent_hub/2026-07-16_turtle_baseline/ 并 commit（贴 commit hash）
- [ ] TASK-2 git log -1 确认落地；git status 干净（backtest_results 仍 untracked，无其他残留）
- [ ] 未 push
- [ ] 未改动任何代码文件
- [ ] 未碰会话前 dirty 文件
```
