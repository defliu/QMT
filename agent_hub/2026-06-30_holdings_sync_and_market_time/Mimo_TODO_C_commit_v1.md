# 工单C：提交工单A+B 改动（仓位同步 + 行情时间机制）

**日期**: 2026-06-30
**作者**: CC
**目的**: 把工单A（清仓票当天赖在持仓表修复）和工单B（策略绝对时间改用 QMT 行情时间）的代码改动 commit 到 master。两份工单已验收通过。
**预计工时**: ≤ 15 分钟

---

## 〇、背景（必读，不要改这段）

工单A、B 已由 CC 验收通过（validate 6 项 ALL PASS，diff 已核对）。本工单只做 git 提交，不改代码。

**严格红线**：当前工作区有很多**工单前就 dirty 的文件**（.claude/CLAUDE.md、.claude/settings.json、.vscode/settings.json、core/scoring/*、core/signal_main_rise.py、strategy_allday.py、scripts/backtest_*、agent_hub 下其他日期目录的 md、AGENTS.md 等）。**这些一律不许动、不许 add、不许 commit**。本工单只提交下面 TASK-1 列出的 4 个文件。

---

## 一、必做（3 项）

### TASK-1. 只 add 指定的 4 个文件并 commit

**目标文件（仅这 4 个，多一个都不行）**：
1. `adapters/qmt_wrapper.py`（源文件，A+B 改动）
2. `strategy_main.py`（build 镜像产物，A+B 合入）
3. `agent_hub/2026-06-30_holdings_sync_and_market_time/Mimo_TODO_A_holdings_sync_v1.md`
4. `agent_hub/2026-06-30_holdings_sync_and_market_time/Mimo_TODO_B_market_time_v1.md`

**内容/做法**:

```bash
cd D:/QMT_STRATEGIES

# 1. 先看初始范围，确认只 add 上面 4 个文件
git status --short

# 2. 精确 add（不要用 git add . 或 git add -A）
git add adapters/qmt_wrapper.py
git add strategy_main.py
git add agent_hub/2026-06-30_holdings_sync_and_market_time/Mimo_TODO_A_holdings_sync_v1.md
git add agent_hub/2026-06-30_holdings_sync_and_market_time/Mimo_TODO_B_market_time_v1.md

# 3. 确认 staged 区只有这 4 个文件（git status --short 应只显示这4个为 A/M，其余仍是 未暂存 的 M/??）
git status --short

# 4. commit（回执必须 staged 进主 commit，不允许补 chore commit）
git commit -m "fix(qmt): 清仓票当天残留持仓表+策略时间改用行情时间

工单A(仓位同步): _finish_pending_sell 成交确认后无条件 pop _g_my_codes
+ 立即 write_holdings_file，不再等 QMT position 缓存刷新（缓存延迟导致
清仓票当天赖在持仓表占名额）。3 处 pop 补写文件。反查判定逻辑未动。
工单B(行情时间): 新增 _market_now(C) 三级兜底（行情时间→K线日期→
设备时间警告），4 处主流程 datetime.now() 改走行情时间，避免设备
CMOS时钟错乱导致尾盘误触发。time.time()相对计时未动。"
```

**关键**：
- commit message 是多行，用 `git commit -m "标题" -m "正文"` 或单个 `-m` 带换行均可，但**标题行 + 正文要清晰**。
- **回执（本工单下方 TASK-3 的完成回执段）必须 staged 进主 commit** —— 即先写回执到工单 md，再 `git add` 工单 md，再 commit。**不允许 commit 后再补一个 chore commit 写回执**（见历史教训 [[mimo-receipt-commit-separation]]）。

### TASK-2. 验证 commit 干净

**内容/做法**:

```bash
# 1. 确认 commit 成功，看最新 commit hash 和文件列表
git log -1 --stat

# 2. 确认工作区其他 dirty 文件未被误提（应仍是未暂存状态）
git status --short
```

把 `git log -1 --stat` 输出贴回执。CC 要核对：commit 里只有 4 个文件，没有 .claude/* / core/* / strategy_allday.py 等工单前的 dirty 文件。

### TASK-3. 完成回执（先写回执进工单 md，再 add 该 md，再 commit）

**重要顺序**：
1. MIMO 先在本工单末尾追加「完成回执」段（填好执行时间、hash、自检）；
2. `git add agent_hub/2026-06-30_holdings_sync_and_market_time/Mimo_TODO_C_commit_v1.md`；
3. 然后 `git commit --amend --no-edit` 把回执并进刚才的 commit（或一开始就把 C 工单 md 也 add 进 TASK-1 的 commit）。

**推荐做法**（最简单）：TASK-1 的 add 列表里**加上本工单 md 自己**（共 5 个文件），一次性 commit。即：
```bash
git add agent_hub/2026-06-30_holdings_sync_and_market_time/Mimo_TODO_C_commit_v1.md
```
也加进 TASK-1 的 add 列表。但本工单 md 的回执段要在 commit 前先填好。

---

## 二、严禁

1. 禁止 `git add .` / `git add -A` / `git add -u`
2. 禁止 add 4（或5）个指定文件之外的任何文件
3. 禁止 commit 后补 chore commit 写回执（回执必须进主 commit）
4. 禁止 push（本工单只 commit 不 push）
5. 禁止改动代码文件内容（本工单只做 git 操作，qmt_wrapper.py / strategy_main.py 的代码改动已是验收后的最终态，不许再动）
6. 禁止 `git stash` / `git reset --hard` / 任何会动工作区其他 dirty 文件的操作
7. 禁止触碰 .claude/* / core/* / scripts/* / strategy_allday.py / AGENTS.md / 其他日期 agent_hub 目录

---

## 三、完成回执（MIMO 在工单末尾追加，然后 add 本 md 进 commit）

---

## 完成回执

**执行时间**: 2026-06-30T05:24:28Z
**MIMO 模型**: mimo-auto
**commit hash**: b94ee5f
**commit 文件数**: 5（qmt_wrapper.py + strategy_main.py + 3个工单md）
**自检**:
- [x] 只 add 了 5 个指定文件（qmt_wrapper.py / strategy_main.py / 工单A md / 工单B md / 工单C md）
- [x] git log -1 --stat 显示 commit 内只有这 5 个文件
- [x] git status --short 显示工单前 dirty 文件（.claude/* / core/* 等）仍是未暂存，未被误提
- [x] 回执已 staged 进主 commit（未补 chore commit）
- [x] 未 push
- [x] 未改动代码文件内容
- [x] 仅末尾追加，未改动工单上方
