# 工单H：补 fixup commit — 工单G 回执 hash 字段更新

**日期**: 2026-06-30
**作者**: CC
**目的**: 工单G commit 后,MIMO amend 了回执的 hash 字段(82c082666 → 3c36743)和两个自检勾选,但没补提交,导致 `Mimo_TODO_G_commit_v1.md` 工作区 dirty。补一个 docs commit 把这个文档改动提了。
**预计工时**: ≤ 5 分钟

---

## 〇、背景（必读，不要改这段）

工单G 已 commit(hash 3c36743,9 文件)。但 G md 回执的 hash 字段在 commit 后被 amend 改了一行 + 两个自检勾选 [x],这部分改动没进 commit。本工单只提这一个 md 文件的这一处文档改动。

CC 已确认 diff 干净:只有 hash 字段 + 两个自检勾选,无其他改动。

---

## 一、必做（2 项）

### TASK-1. add 并 commit G md

**目标文件（仅 1 个）**: `agent_hub/2026-06-30_holdings_sync_and_market_time/Mimo_TODO_G_commit_v1.md`

**内容/做法**:

```bash
cd D:/QMT_STRATEGIES

# 1. 确认 diff 只有 hash 字段 + 自检勾选
git diff agent_hub/2026-06-30_holdings_sync_and_market_time/Mimo_TODO_G_commit_v1.md

# 2. 只 add 这一个文件
git add agent_hub/2026-06-30_holdings_sync_and_market_time/Mimo_TODO_G_commit_v1.md

# 3. 确认 staged 只有这一个文件
git status --short

# 4. commit
git commit -m "docs: 工单G回执hash字段更新为最终commit 3c36743"
```

**关键**：
- 只 add 这 1 个 md 文件,不要碰其他。
- commit message 用 `docs:` 前缀(纯文档改动)。

### TASK-2. 验证

**内容/做法**:

```bash
git log -1 --stat
git status --short
```

贴 `git log -1 --stat` 输出。CC 核对:commit 里只有 `Mimo_TODO_G_commit_v1.md` 1 个文件;G md 不再 dirty;工单前 dirty 文件(.claude/* / core/*)仍未暂存。

---

## 二、严禁

1. 禁止 `git add .` / `-A` / `-u`
2. 禁止 add 该 md 之外的任何文件
3. 禁止 push
4. 禁止改动代码文件(qmt_wrapper.py / strategy_main.py / strategy_allday.py)
5. 禁止改动 G md 工单上方内容(只提交已有的 hash 字段 + 自检勾选改动)
6. 禁止 `git stash` / `git reset --hard`
7. 禁止触碰 .claude/* / core/* / scripts/* / 其他 agent_hub 目录

---

## 三、完成回执（MIMO 在工单末尾追加）

```markdown

---

## 完成回执

**执行时间**: <用 `date -u +"%Y-%m-%dT%H:%M:%SZ"` 真实拿>
**MIMO 模型**: <实际模型名>
**commit hash**: <git log -1 实际 hash>
**自检**:
- [ ] 只 add 了 Mimo_TODO_G_commit_v1.md 1 个文件
- [ ] git log -1 --stat 显示 commit 内只有这 1 个文件
- [ ] git status --short 显示 G md 不再 dirty，工单前 dirty 文件仍未暂存
- [ ] 未 push
- [ ] 未改动代码文件
- [ ] 仅末尾追加，未改动工单上方
```

---

## 完成回执

**执行时间**: 2026-06-30T11:05:23Z
**MIMO 模型**: mimo-auto
**commit hash**: 230aa06dc71ebbae60f6cf50bd2667f092d8f856
**自检**:
- [x] 只 add 了 Mimo_TODO_G_commit_v1.md 1 个文件
- [x] git log -1 --stat 显示 commit 内只有这 1 个文件
- [x] git status --short 显示 G md 不再 dirty，工单前 dirty 文件仍未暂存
- [x] 未 push
- [x] 未改动代码文件
- [x] 仅末尾追加，未改动工单上方
