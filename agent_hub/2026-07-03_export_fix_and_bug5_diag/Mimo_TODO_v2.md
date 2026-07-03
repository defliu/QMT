# 盘前预埋G3_ONLY + 版本号bump + commit本轮全部改动

**日期**: 2026-07-03
**作者**: CC
**目的**: 开盘前预埋硬止损(原P3观察期OFF→G3_ONLY)；bump版本号供诚哥部署确认；commit本轮导出修复+BUG5诊断+盘前预埋全部改动
**预计工时**: ≤ 25 分钟

---

## 背景（必读）

- 目标源文件：`D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`（GBK，`# coding=gbk`）。strategy_main.py 是构建产物。
- 本轮 v1 已改（**未 commit**）：导出修复（行3943 global 补 `_g_exported_today` / 行939+4062 1505→1500）+ BUG5 诊断（行544-571 `lookup_diag`）。
- 本轮 v2 新增：盘前预埋 OFF→G3_ONLY + 版本号 bump + commit 全部。
- ⚠️ **当前 git 有大量诚哥的 dirty（不能带进 commit）**：`core/signal_main_rise.py`、`core/scoring/dimension6plus2.py`、`strategy_dev.py`、`.claude/*`、`backtest/*` 等多个 M 文件。**commit 只 add 本轮 3 个目标**，严禁 `git add -A`。

---

## 一、必做（4 项）

### TASK-1. 开盘前预埋 OFF→G3_ONLY

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`
**内容/做法**: 行244当前为：
```
PREMARKET_HARD_STOP_MODE = 'OFF'  # 'OFF' / 'G3_ONLY' / 'G2_AND_G3'  P3 观察期: 验日K字段后切回 'G3_ONLY'
```
改为：
```
PREMARKET_HARD_STOP_MODE = 'G3_ONLY'  # 'OFF' / 'G3_ONLY' / 'G2_AND_G3'  0703结束P3观察期启用：集合竞价累计亏<=-5%或日跌<=-7%预埋G3
```
原因：诚哥拍板启用盘前预埋。G3_ONLY 保守（只 G3 级）。风险可控：`_get_premarket_ref_price` 用 close[-1]，09:25 若未更新集合竞价价则 daily_drop=0 不触发（漏预埋，不会错价预埋）；但 cum_pnl 用昨收算仍能触发昨天已大跌的票。

### TASK-2. bump 版本号

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`
**内容/做法**: 行158 `STRATEGY_VERSION = 'v2026.07.02-orphan-adopt2'` 改为 `STRATEGY_VERSION = 'v2026.07.03-export-fix-g3'`
原因：诚哥部署时看版本号确认新代码生效。

### TASK-3. rebuild + validate

**做法**:
1. `python scripts/build_strategy.py` 重新构建 strategy_main.py
2. `python scripts/validate_qmt_file.py strategy_main.py` 必须 6/6 ALL PASS（贴出 6 项）
3. grep strategy_main.py 确认 `PREMARKET_HARD_STOP_MODE = 'G3_ONLY'` 和 `v2026.07.03-export-fix-g3` 已同步进产物

### TASK-4. commit（只 add 本轮 3 个目标，严禁 git add -A）

**做法**:
1. `git add adapters/qmt_wrapper.py strategy_main.py agent_hub/2026-07-03_export_fix_and_bug5_diag/`
2. `git status` 确认 staged **只有**上述 3 个目标（+ 工单目录内 v1/v2 文件）；**诚哥的其他 dirty（core/signal_main_rise.py、core/scoring/dimension6plus2.py、strategy_dev.py、.claude/*、backtest/* 等）必须保持 unstaged**
3. `git commit -m "fix(qmt): 盘后导出1505→1500收盘帧触发+_handlebar_impl补global；BUG5反查失败加诊断日志(lookup_diag)；盘前预埋OFF→G3_ONLY；版本号export-fix-g3"`
4. `git log -1 --stat` 确认 commit 只含 3 个目标文件（贴出）
5. `git status --short` 确认诚哥的 dirty 仍在（未被动，贴出前 10 行）

**严禁 push**（项目无远程）。

---

## 二、严禁

1. 禁止 `git add -A` / `git add .` / `git add -u`（会带诚哥 dirty，踩过 YEN_FIX 坑）
2. 禁止 commit 诚哥的 dirty 文件（core/signal_main_rise.py、core/scoring/dimension6plus2.py、strategy_dev.py、.claude/*、backtest/* 等）
3. 禁止 push
4. 禁止改本轮 3 个目标（adapters/qmt_wrapper.py、strategy_main.py、本工单目录）以外的任何文件
5. 禁止手改 strategy_main.py（只通过 build_strategy.py 重建）
6. 禁止用 patch 工具编辑 GBK 文件（用 Edit）
7. 文件头保持 `# coding=gbk`，Python 3.6.8 语法兼容（禁 f-string / walrus / match-case / dict[str,..]）
8. 禁止改 `_check_pre_market_hard_stop` 函数体逻辑（只改行244的 MODE 常量）
9. 禁止改 v1 已落地的导出修复 + BUG5 诊断代码

---

## 三、完成回执（MIMO 在工单末尾追加）

```markdown

---

## 完成回执

**执行时间**: <用 `date -u +"%Y-%m-%dT%H:%M:%SZ"` 真实拿，禁止 placeholder>
**MIMO 模型**: <实际名>
**自检**:
- [ ] TASK-1 行244 `PREMARKET_HARD_STOP_MODE = 'G3_ONLY'`（grep 确认 + 注释已更新）
- [ ] TASK-2 行158 `STRATEGY_VERSION = 'v2026.07.03-export-fix-g3'`（grep 确认）
- [ ] TASK-3 build_strategy.py 重建成功 + validate 6/6 ALL PASS（贴 6 项）+ strategy_main.py grep 确认两处同步
- [ ] TASK-4.1 `git add` 只 add 3 个目标
- [ ] TASK-4.2 git status staged 只有 3 个目标（诚哥 dirty 全 unstaged）
- [ ] TASK-4.3 commit 成功（贴 `git log -1 --stat`）
- [ ] TASK-4.4 `git status --short` 确认诚哥 dirty 仍在（贴前 10 行）
- [ ] 未 push
- [ ] 未改 3 个目标以外文件
- [ ] v1 导出修复 + BUG5 诊断代码未被破坏（grep 确认 `lookup_diag` / `if now >= '1500'` 仍在）
- [ ] 仅末尾追加回执，未改动上方
```

---

## 完成回执

**执行时间**: 2026-07-03T08:50:41Z
**MIMO 模型**: mimo-auto
**自检**:
- [x] TASK-1 行244 `PREMARKET_HARD_STOP_MODE = 'G3_ONLY'`（grep 确认 + 注释已更新）
- [x] TASK-2 行158 `STRATEGY_VERSION = 'v2026.07.03-export-fix-g3'`（grep 确认）
- [x] TASK-3 build_strategy.py 重建成功 + validate 6/6 ALL PASS（贴 6 项）+ strategy_main.py grep 确认两处同步
- [x] TASK-4.1 `git add` 只 add 3 个目标
- [x] TASK-4.2 git status staged 只有 3 个目标（诚哥 dirty 全 unstaged）
- [x] TASK-4.3 commit 成功（贴 `git log -1 --stat`）
- [x] TASK-4.4 `git status --short` 确认诚哥 dirty 仍在（贴前 10 行）
- [x] 未 push
- [x] 未改 3 个目标以外文件
- [x] v1 导出修复 + BUG5 诊断代码未被破坏（grep 确认 `lookup_diag` / `if now >= '1500'` 仍在）
- [x] 仅末尾追加回执，未改动上方

**TASK-3 validate 6/6**:
1. [1/6] 文件存在 PASS
2. [2/6] 编码 GBK PASS
3. [3/6] 文件头 # coding=gbk PASS
4. [4/6] Python 3.6 语法 PASS
5. [5/6] 无 MOCK 残留 PASS
6. [6/6] 无长小数输出 PASS (所有评分值 %.2f)

**TASK-4.3 git log -1 --stat**:
```
commit b3077797ff995bef53683c4f4009e23f31340c6c
Author: Developer <developer@qmt-strategies.local>
Date:   Fri Jul 3 16:50:22 2026 +0800

    fix(qmt): 盘后导出1505→1500收盘帧触发+_handlebar_impl补global；BUG5反查失败加诊断日志(lookup_diag)；盘前预埋OFF→G3_ONLY；版本号export-fix-g3

 adapters/qmt_wrapper.py                            |  41 +++++-
 .../Mimo_TODO_v1.md                                | 141 +++++++++++++++++++++
 .../Mimo_TODO_v2.md                                |  96 ++++++++++++++
 strategy_main.py                                   |  43 +++++--
 4 files changed, 306 insertions(+), 15 deletions(-)
```

**TASK-4.4 git status --short (前10行)**:
```
 M .claude/CLAUDE.md
 M .claude/settings.json
 M .claude/settings.local.json
 M .vscode/settings.json
 M "D\357\200\272/QMT_POOL/safemode_logs/safemode_started.log"
 M "Project_01_\351\273\206\346\260\217\344\270\273\345\215\207\346\265\252\347\255\226\347\225\245/\351\241\271\347\233\257\346\200\350\247\210\344\270\216\344\270\213\344\270\200\346\255\245.md"
 D __pycache__/risk_only_strategy.cpython-310.pyc
 D __pycache__/strategy_main.cpython-310.pyc
 D __pycache__/strategy_main.cpython-311.pyc
```
