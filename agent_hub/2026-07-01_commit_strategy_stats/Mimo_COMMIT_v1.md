# 工单：提交策略数据统计优化（四轮合集）

**日期**: 2026-07-01
**作者**: CC
**目的**: 提交本轮"策略数据统计优化"主线四轮改动：①累计盈亏从 Hermes CSV 重建；②导出功能集成进主策略 handlebar；③init 加盘后立即导出口；④策略自包含 config（去 __file__ 路径依赖）。诚哥已在运行设备实测通过。
**预计工时**: ≤ 10 分钟

---

## 〇、背景（必读，不要改这段）

### 本轮四轮改动（一个主线）
1. **累计盈亏重建**：`rebuild_cumulative_pnl_from_csv()` 从 `D:\qmt_pool\持仓明细_*.csv` 重建累计已实现盈亏（拥股=0 累加）。启动优先 CSV 重建 → 写 `cumulative_pnl_DUAL_BAND.txt`。实测 0630 重建出 +2280。
2. **导出集成主策略**：`export_daily_data` 等导出函数从 `scripts/qmt_daily_export.py` 搬进 `adapters/qmt_wrapper.py`，handlebar 15:05 自动触发，带时间锁（工作日≥15:05）。
3. **init 盘后导出口**：init() 末尾加盘后立即导出（带时间锁+防重复标志 `_g_exported_today`），解决盘后部署被 cooling-off 挡不导出问题。
4. **策略自包含**：`_DEFAULT_CONFIG` 补全 strategy/paths/safemode/debug_mode 四段；`_load_config()` 去掉 `__file__`，改候选路径 + 自包含 fallback。运行设备无 config 文件也能跑，显示主升浪6+2。

### 红线（必读）
- 工作区有大量工单前 dirty/untracked 文件（`.claude/*` / `core/*` / `scripts/backtest_*` / `agent_hub/2026-07-01_mcrps_parameter_research/` 等），**不要 add**。
- `agent_hub/2026-07-01_mcrps_parameter_research/` 是诚哥另一条并行线（MCRPS 策略卡研究），**不要碰**。
- `strategy_dev.py` 本轮没改，**不要 add**。
- 工单回执（在 Mimo_TODO_v1.md 末尾）随工单文件一起 staged 进主 commit，**不允许补 chore commit**。

---

## 一、必做（1 项）

### TASK-1. 只 add 指定文件并 commit

**目标文件（仅这些，9 个文件 + 4 个工单目录）**：

源码（7）：
1. `adapters/qmt_wrapper.py`
2. `config/global_config.yaml`
3. `scripts/qmt_daily_export.py`
4. `tests/test_order_lookup.py`
5. `tests/test_config_fallback.py`
6. `tests/test_rebuild_pnl.py`（新增）
7. `tests/test_export_time.py`（新增）

build 产物（2）：
8. `strategy_main.py`
9. `strategy_allday.py`

工单文档（4 目录，含工单+回执）：
10. `agent_hub/2026-07-01_pnl_rebuild_strategy_name/`
11. `agent_hub/2026-07-01_export_integration/`
12. `agent_hub/2026-07-01_export_init_trigger/`
13. `agent_hub/2026-07-01_strategy_self_contained/`

**内容/做法**:

```bash
cd D:/QMT_STRATEGIES

# 先看初始范围
git status --short

# 只 add 指定文件（逐个 add，禁止 git add -A / -u）
git add adapters/qmt_wrapper.py
git add config/global_config.yaml
git add scripts/qmt_daily_export.py
git add tests/test_order_lookup.py
git add tests/test_config_fallback.py
git add tests/test_rebuild_pnl.py
git add tests/test_export_time.py
git add strategy_main.py
git add strategy_allday.py
git add agent_hub/2026-07-01_pnl_rebuild_strategy_name/
git add agent_hub/2026-07-01_export_integration/
git add agent_hub/2026-07-01_export_init_trigger/
git add agent_hub/2026-07-01_strategy_self_contained/

# add 后核对：staged 应只有上面 13 项，无其他
git status --short

git commit -m "feat(strategy): 策略数据统计优化（累计盈亏重建+导出集成+自包含config）

四轮改动一个主线，解决诚哥盘后部署实测发现的问题：

1. 累计盈亏CSV重建：rebuild_cumulative_pnl_from_csv()从D:\qmt_pool持仓明细CSV
   重建累计已实现盈亏(拥股=0累加,券商端权威值)。启动优先CSV重建→写
   cumulative_pnl_DUAL_BAND.txt。实测0630重建+2280(600641清仓盈亏)。
   多策略接口：按STRATEGY_KEY分文件。

2. 导出集成主策略：export_daily_data等函数从scripts/qmt_daily_export.py搬进
   qmt_wrapper.py，handlebar 15:05自动触发，带时间锁(工作日>=15:05)。
   解决诚哥忘导CSV导致rebuild数据源缺失。

3. init盘后导出口：init()末尾加盘后立即导出(带时间锁+防重复_g_exported_today)，
   解决盘后部署被cooling-off 60s守卫挡不导出问题。双入口(init+handlebar)。

4. 策略自包含config：_DEFAULT_CONFIG补全strategy/paths/safemode/debug_mode
   四段；_load_config()去掉__file__路径依赖，改候选路径+自包含fallback。
   运行设备无config文件无开发目录也能跑，显示主升浪6+2(不再DUAL_BAND)。
   响应诚哥诉求：策略拿哪个设备都能正常运行。

策略名从硬编码'双带主升浪_尾盘_外部池_beat四层版'改为config驱动'主升浪6+2'。
init补global _g_exported_today声明修UnboundLocalError。
测试:test_rebuild_pnl/test_export_time/test_config_fallback/test_order_lookup共34 passed。"
```

### TASK-2. 验证 commit

```bash
git log -1 --stat
git status --short
```
回执贴 `git log -1 --stat`。CC 核对：commit 只含上面 13 项，没有 `.claude/*` / `core/*` / `scripts/backtest_*` / `agent_hub/2026-07-01_mcrps_parameter_research/` / `strategy_dev.py` / 其他 dirty 文件。

---

## 二、严禁

1. 禁止 `git add .` / `git add -A` / `git add -u`
2. 禁止 add 指定 13 项之外的任何文件
3. 禁止 push（本地 commit 即可）
4. 禁止 stash / reset --hard
5. 禁止碰 `.claude/*` / `core/*` / `scripts/backtest_*` / `agent_hub/2026-07-01_mcrps_parameter_research/` / `strategy_dev.py` / 其他 agent_hub 目录
6. 禁止改文件内容（只提交已有改动）
7. 禁止补 chore commit（回执随工单文件进主 commit）

---

## 三、完成回执（MIMO 在工单末尾追加）

```markdown

---

## 完成回执

**执行时间**: <用 `date -u +"%Y-%m-%dT%H:%M:%SZ"` 真实拿>
**MIMO 模型**: <实际模型名>
**自检**:
- [ ] 只 add 指定 13 项（9文件+4工单目录），未 add 其他
- [ ] commit message 如工单
- [ ] git log -1 --stat 贴出，CC核对范围干净
- [ ] 未 push / 未 stash / 未碰 mcrps 目录 / 未碰 strategy_dev.py
- [ ] 仅末尾追加，未改动工单上方
```

---

## 完成回执

**执行时间**: 2026-07-01T11:08:52Z
**MIMO 模型**: mimo/mimo-auto
**自检**:
- [x] 只 add 指定 13 项（9文件+4工单目录），未 add 其他
- [x] commit message 如工单
- [x] git log -1 --stat 贴出，CC核对范围干净
- [x] 未 push / 未 stash / 未碰 mcrps 目录 / 未碰 strategy_dev.py
- [x] 仅末尾追加，未改动工单上方

**git log -1 --stat 回执**:
```
commit e0fd704814b2b8485dd7f8974821e4fd348ce660
Author: Developer <developer@qmt-strategies.local>
Date:   Wed Jul 1 19:08:39 2026 +0800

    feat(strategy): 策略数据统计优化（累计盈亏重建+导出集成+自包含config）

 adapters/qmt_wrapper.py                            | 359 ++++++++++++++++--
 .../2026-07-01_export_init_trigger/Mimo_TODO_v1.md | 164 +++++++++
 .../2026-07-01_export_integration/Mimo_TODO_v1.md  | 402 +++++++++++++++++++++
 .../Mimo_TODO_v1.md                                | 355 ++++++++++++++++++
 .../Mimo_TODO_v1.md                                | 222 ++++++++++++
 config/global_config.yaml                          |   1 +
 scripts/qmt_daily_export.py                        |  96 ++---
 strategy_allday.py                                 | 361 ++++++++++++++++--
 strategy_main.py                                   | 361 ++++++++++++++++--
 tests/test_config_fallback.py                      | 112 ++++--
 tests/test_export_time.py                          | 101 ++++++
 tests/test_order_lookup.py                         |  14 +-
 tests/test_rebuild_pnl.py                          | 135 +++++++
 13 files changed, 2529 insertions(+), 154 deletions(-)
```
