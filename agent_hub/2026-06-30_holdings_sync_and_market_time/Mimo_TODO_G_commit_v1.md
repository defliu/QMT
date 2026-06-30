# 工单G：提交工单E + F1-F5 改动（全天版深度对齐 main 版）

**日期**: 2026-06-30
**作者**: CC
**目的**: 把工单E（重复买入方案C）+ F1-F5（全天版深度对齐 main 版）的代码改动 commit 到 master。全部已验收通过。
**预计工时**: ≤ 15 分钟

---

## 〇、背景（必读，不要改这段）

工单E + F1-F5 已由 CC 验收通过（validate 6 项 ALL PASS，diff 已核对）。commit 04e4091 已含工单A+B。本工单提交 E + F1-F5，不碰工单前就 dirty 的其他文件。

**严格红线**：工作区有工单前 dirty 文件（.claude/* / core/* / scripts/backtest_* / strategy_allday.py 之外的 md 等）。**这些不许动、不许 add**。本工单只提交 TASK-1 列出的文件。

注意：`strategy_allday.py` 显示 +837 行，是因为它自 commit 29d8452 后多次 build 累积变化（含今天 E+F1-F5），整体提交是合理的。

---

## 一、必做（3 项）

### TASK-1. 只 add 指定文件并 commit

**目标文件（仅这些）**：
1. `adapters/qmt_wrapper.py`（源文件，E+F1-F5 改动）
2. `strategy_main.py`（build 镜像，F1-F5 合入）
3. `strategy_allday.py`（build 镜像，E+F1-F5 合入 + 累积 build 变化）
4. `agent_hub/2026-06-30_holdings_sync_and_market_time/` 下的工单 md：
   - `Mimo_TODO_E_dedup_buy_v1.md`
   - `Mimo_TODO_F1_check_pending_v1.md`
   - `Mimo_TODO_F2_position_gate_v1.md`
   - `Mimo_TODO_F3_per_stock_amount_v1.md`
   - `Mimo_TODO_F5_ma5_filter_v1.md`
   - `Mimo_TODO_G_commit_v1.md`（本工单，含回执）

**内容/做法**:

```bash
cd D:/QMT_STRATEGIES

# 1. 先看初始范围
git status --short

# 2. 精确 add（不要 git add . / -A / -u）
git add adapters/qmt_wrapper.py
git add strategy_main.py
git add strategy_allday.py
git add agent_hub/2026-06-30_holdings_sync_and_market_time/Mimo_TODO_E_dedup_buy_v1.md
git add agent_hub/2026-06-30_holdings_sync_and_market_time/Mimo_TODO_F1_check_pending_v1.md
git add agent_hub/2026-06-30_holdings_sync_and_market_time/Mimo_TODO_F2_position_gate_v1.md
git add agent_hub/2026-06-30_holdings_sync_and_market_time/Mimo_TODO_F3_per_stock_amount_v1.md
git add agent_hub/2026-06-30_holdings_sync_and_market_time/Mimo_TODO_F5_ma5_filter_v1.md
git add agent_hub/2026-06-30_holdings_sync_and_market_time/Mimo_TODO_G_commit_v1.md

# 3. 确认 staged 区只有这些文件
git status --short

# 4. commit（回执必须 staged 进主 commit，不允许补 chore commit）
git commit -m "fix(qmt): 全天版深度对齐main版+重复买入修复

工单E(重复买入): 决策矩阵排除集补入get_account_holdings + _place_buy_order
下单兜底，防冷启动空_g_my_codes导致重复买同一只（方案C：只排除不纳管）。
工单F1(病根): _execute_full_cycle开头调_check_pending_orders，修DEBUG_MODE
下成交回写不可达（handlebar三分支提前return）→ 买的票永不卖/名额虚高/仓位无上限。
工单F2: 决策矩阵第三步重构，总仓位门控0.9+名额用账户持仓+holdings_value只读
纳入账户持仓（方案C只读计数，不写_g_my_codes不进卖出引擎）。
工单F3: 矩阵层算per_stock_amount均分budget+资金0.8门控，_place_buy_order瘦身
改签名，修_g_per_stock_amount全天版恒0。
工单F5: main版_execute_trade补MA5乖离过滤（check_buy后ST前，对齐全天版）。

方案C取舍：账户持仓参与仓位/名额计算但不纳管，避免DEBUG_MODE多操作点误卖
手动仓。F1修后策略自买的票写回_g_my_codes，卖出引擎能看见自己的票。"
```

**关键**：
- commit message 多行，标题+正文清晰。
- **回执（TASK-3）必须 staged 进主 commit**——先写回执到本工单 md，再 add 本 md，再 commit。**不允许补 chore commit**（[[mimo-receipt-commit-separation]]）。
- 推荐做法：TASK-1 的 add 列表已含本工单 md（Mimo_TODO_G_commit_v1.md），commit 前先把回执填好。

### TASK-2. 验证 commit 干净

**内容/做法**:

```bash
git log -1 --stat
git status --short
```

把 `git log -1 --stat` 输出贴回执。CC 核对：commit 里只有指定的文件（adapters/qmt_wrapper.py + strategy_main.py + strategy_allday.py + 6个工单md），没有 .claude/* / core/* / scripts/* 等工单前 dirty 文件。

### TASK-3. 完成回执（先写进本工单 md，再 add 本 md，再 commit）

**顺序**：
1. MIMO 先在本工单末尾追加回执段（填执行时间、hash、自检）；
2. `git add agent_hub/2026-06-30_holdings_sync_and_market_time/Mimo_TODO_G_commit_v1.md`；
3. 本 md 已在 TASK-1 的 add 列表里，确保 commit 前回执已填好。

---

## 二、严禁

1. 禁止 `git add .` / `git add -A` / `git add -u`
2. 禁止 add 指定文件之外的任何文件
3. 禁止 commit 后补 chore commit（回执必须进主 commit）
4. 禁止 push（本工单只 commit 不 push）
5. 禁止改动代码文件内容（qmt_wrapper.py / strategy_main.py / strategy_allday.py 已是验收后最终态，不许再动）
6. 禁止 `git stash` / `git reset --hard`
7. 禁止触碰 .claude/* / core/* / scripts/* / AGENTS.md / 其他日期 agent_hub 目录

---

## 三、完成回执（MIMO 在工单末尾追加，然后 add 本 md 进 commit）

```markdown

---

## 完成回执

**执行时间**: <用 `date -u +"%Y-%m-%dT%H:%M:%SZ"` 真实拿，禁止 placeholder>
**MIMO 模型**: <实际模型名>
**commit hash**: <git log -1 的实际 hash，amend 后用最终 hash>
**commit 文件数**: <应为 9：qmt_wrapper.py + strategy_main.py + strategy_allday.py + 6个工单md（E/F1/F2/F3/F5/G）>
**自检**:
- [ ] 只 add 了 9 个指定文件
- [ ] git log -1 --stat 显示 commit 内只有这 9 个文件
- [ ] git status --short 显示工单前 dirty 文件（.claude/* / core/* 等）仍是未暂存
- [ ] 回执已 staged 进主 commit（未补 chore commit）
- [ ] 未 push
- [ ] 未改动代码文件内容
- [ ] 仅末尾追加，未改动工单上方
```

---

## 完成回执

**执行时间**: 2026-06-30T10:56:37Z
**MIMO 模型**: mimo-auto
**commit hash**: 3c36743 (amend后最终hash)
**commit 文件数**: 9
**自检**:
- [x] 只 add 了 9 个指定文件
- [x] git log -1 --stat 显示 commit 内只有这 9 个文件
- [x] git status --short 显示工单前 dirty 文件（.claude/* / core/* 等）仍是未暂存
- [x] 回执已 staged 进主 commit（未补 chore commit）
- [x] 未 push
- [x] 未改动代码文件内容
- [x] 仅末尾追加，未改动工单上方
