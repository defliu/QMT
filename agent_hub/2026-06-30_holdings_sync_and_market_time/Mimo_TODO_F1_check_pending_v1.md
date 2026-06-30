# 工单F1：让 _check_pending_orders 在全天版(DEBUG_MODE)可达 — 成交回写 _g_my_codes

**日期**: 2026-06-30
**作者**: CC
**目的**: 修复全天版最严重病根——`_check_pending_orders` 在 DEBUG_MODE 下不可达,导致买单成交后 `_g_my_codes` 不更新(买的票永不卖出、名额虚高、仓位无上限)。这是 F 系列的地基工单。
**预计工时**: ≤ 20 分钟

---

## 〇、背景与根因（必读，不要改这段）

诚哥授权深度对齐 main 版。排查发现:handlebar 在 DEBUG_MODE 下三条路径(line 3645 启动 / 3654 操作点 / 3658 非操作点)都在 line 3661 `_check_pending_orders(C)` 之前 return,所以全天版买单成交后永远不会写回 `_g_my_codes`(line 2731/2745)。

连锁反应:卖出引擎 evaluate(today, _g_my_codes,...) 评估空集 → 买的票永不卖出(止损止盈失效);empty_slots 恒=MAX_HOLD;holdings_value 恒=0 → budget 虚高。

本工单(F1)只修根因:让 `_check_pending_orders` 在全天版可达。后续 F2/F3 修仓位门控/均分。

**对齐基准**: main 版走 line 3661 原调用点,本工单不碰 main 版。

---

## 一、必做（3 项）

### TASK-1. 在 _execute_full_cycle 开头插入成交确认调用

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`（`_execute_full_cycle` 函数，line 3197）

**当前代码**（line 3197-3206）：
```python
def _execute_full_cycle(C, today, dt):
    """全流程：加载数据→评分池候选+持仓→决策执行"""
    global _g_data_loaded, _g_all_data, _g_my_codes, _g_scorer, _g_sell_engine

    if not _g_data_loaded:
        _load_data(C, dt)
        _g_data_loaded = True

    # 1. 加载池、评分池候选
    candidates = _load_pool()
```

**改为**（在 `_g_data_loaded = True` 之后、`# 1. 加载池` 之前插入）：
```python
def _execute_full_cycle(C, today, dt):
    """全流程：加载数据→评分池候选+持仓→决策执行"""
    global _g_data_loaded, _g_all_data, _g_my_codes, _g_scorer, _g_sell_engine

    if not _g_data_loaded:
        _load_data(C, dt)
        _g_data_loaded = True

    # F1: 操作点开场先确认上一操作点的买单成交，回写 _g_my_codes
    # （DEBUG_MODE 下 handlebar 不可达 line 3661，导致成交不写回、卖出引擎评估空集）
    if _g_pending_buys:
        _check_pending_orders(C)
        if _g_retry_queue:
            _try_retry_queue(C)

    # 1. 加载池、评分池候选
    candidates = _load_pool()
```

**关键**：
- 插入位置精确:`_g_data_loaded = True`(line 3203)之后、`# 1. 加载池`(line 3205)之前。
- 首帧 `_g_pending_buys` 为空(init line 3506 已清空)→ no-op,零风险。
- 用现有的 `_check_pending_orders(C)`(line 2703)和 `_try_retry_queue(C)`(line 2648),不要新写。
- **不要动 handlebar 的 line 3645-3667**,不要动 main 版 line 3661 调用点。

### TASK-2. 验证

**目标路径**: `D:/QMT_STRATEGIES/`

**内容/做法**:

1. `python scripts/build_strategy.py`（生成 strategy_main.py）
2. `python scripts/build_strategy.py --allday`（生成 strategy_allday.py）
3. 两个文件都 validate：
   - `python scripts/validate_qmt_file.py strategy_main.py`
   - `python scripts/validate_qmt_file.py strategy_allday.py`
   - 必须 6 项 ALL PASS。
4. grep 确认改动落点（中文标记在 GBK 文件，需转 UTF-8）：
   ```bash
   # 源文件直接 grep
   grep -n "F1: 操作点开场先确认" adapters/qmt_wrapper.py
   # build 产物转码后 grep
   iconv -f GBK -t UTF-8 strategy_allday.py | grep -c "F1: 操作点开场先确认"
   iconv -f GBK -t UTF-8 strategy_main.py | grep -c "F1: 操作点开场先确认"
   ```
   源文件应返回 1 行；allday 版应返回 1（含修复）；main 版应返回 0（main 版不该有这个标记，因为 F1 只改全天版路径，但 build 会合入源文件——所以 main 版也会含这段代码。**重要**:F1 插入在 `_execute_full_cycle` 内,该函数 main 版也存在但不被调用(DEBUG_MODE=False 走 _execute_trade)。所以 main 版 build 产物里会有这段代码但不执行,这是正常的,grep main 版返回 1 也 OK)。

   贴 grep + validate 结果。

### TASK-3. 确认未碰 main 版路径

**内容/做法**:

grep 确认 main 版的核心路径未被改动：
```bash
# _execute_trade 函数体不应有 F1 标记
grep -n "F1: 操作点开场" adapters/qmt_wrapper.py
# 应只在 _execute_full_cycle 内出现 1 次，不在 _execute_trade 内
# handlebar 的 line 3661 调用点仍在
grep -n "_check_pending_orders(C)" adapters/qmt_wrapper.py
# 应有多处调用点（line 3662 原调用 + F1 新增调用）
```

贴 grep 结果。CC 要核对:_execute_trade 函数体(line 2807-3075)内没有 F1 改动。

---

## 二、严禁

1. 禁止 git add / commit / push（本工单不授权 git）
2. 禁止改动本工单上方
3. 禁止做工单外动作
4. 禁止动 handlebar 的 line 3645-3667（DEBUG_MODE 分支和原 _check_pending_orders 调用点）
5. 禁止动 main 版 `_execute_trade`(line 2807-3075)
6. 禁止动 `_check_pending_orders` / `_try_retry_queue` 函数本体
7. 禁止动 `_sync_holdings_from_account`
8. 禁止跑实盘 / 模拟盘交易验证（只做 build + validate + grep）
9. **文件编码 GBK，`# coding=gbk` 文件头保持；禁止用 patch 工具直接编辑，用 Read+Edit；Python 3.6.8 语法（禁 f-string / dict[str,..] / walrus / match-case），用 % 格式化**

---

## 三、完成回执（MIMO 在工单末尾追加）

```markdown

---

## 完成回执

**执行时间**: <用 `date -u +"%Y-%m-%dT%H:%M:%SZ"` 真实拿，禁止 placeholder>
**MIMO 模型**: <实际模型名>
**自检**:
- [ ] TASK-1: _execute_full_cycle 开头已插入 F1 成交确认调用，贴改后代码块（含插入位置上下文）
- [ ] TASK-2: strategy_main.py + strategy_allday.py 都 build + validate 6 项 ALL PASS，贴输出
- [ ] TASK-2: grep 标记结果（源文件 1 行 / allday 含修复 / main 版说明）
- [ ] TASK-3: _execute_trade 函数体内无 F1 改动；handlebar line 3661 原调用点仍在；贴 grep
- [ ] 未动 handlebar / _execute_trade / _check_pending_orders 本体 / _sync_holdings_from_account
- [ ] 仅末尾追加，未改动工单上方
- [ ] 无 git 操作 / 无实盘模拟交易
```

---

## 完成回执

**执行时间**: 2026-06-30T07:12:19Z
**MIMO 模型**: mimo-auto
**自检**:
- [x] TASK-1: _execute_full_cycle 开头已插入 F1 成交确认调用，贴改后代码块（含插入位置上下文）
- [x] TASK-2: strategy_main.py + strategy_allday.py 都 build + validate 6 项 ALL PASS，贴输出
- [x] TASK-2: grep 标记结果（源文件 1 行 / allday 含修复 / main 版说明）
- [x] TASK-3: _execute_trade 函数体内无 F1 改动；handlebar line 3661 原调用点仍在；贴 grep
- [x] 未动 handlebar / _execute_trade / _check_pending_orders 本体 / _sync_holdings_from_account
- [x] 仅末尾追加，未改动工单上方
- [x] 无 git 操作 / 无实盘模拟交易

### TASK-1 改后代码（line 3197-3218）

```python
def _execute_full_cycle(C, today, dt):
    """全流程：加载数据→评分池候选+持仓→决策执行"""
    global _g_data_loaded, _g_all_data, _g_my_codes, _g_scorer, _g_sell_engine

    if not _g_data_loaded:
        _load_data(C, dt)
        _g_data_loaded = True

    # F1: 操作点开场先确认上一操作点的买单成交，回写 _g_my_codes
    # （DEBUG_MODE 下 handlebar 不可达 line 3661，导致成交不写回、卖出引擎评估空集）
    if _g_pending_buys:
        _check_pending_orders(C)
        if _g_retry_queue:
            _try_retry_queue(C)

    # 1. 加载池、评分池候选
    candidates = _load_pool()
    if not candidates:
        print("  [全天] 外部池无候选")
        return

    # 2. 过滤池候选（信号+ST+数据检查）
```

### TASK-2 build + validate 输出

```
Building strategy_main.py ...
OK: strategy_main.py (生产版, 不含MOCK)
Size: 242051 bytes
First line: # coding=gbk
Encoding: GBK (verified by reading with gbk)
Validating... OK
Done.

Validating: strategy_main.py
  [1/6] 文件存在         PASS
  [2/6] 编码 GBK         PASS
  [3/6] 文件头 # coding=gbk  PASS
  [4/6] Python 3.6 语法   PASS
  [5/6] 无 MOCK 残留      PASS
  [6/6] 无长小数输出      PASS
  ------------------------
  Result: ALL PASS  (6/6)

Building strategy_allday.py ...
  [allday] 硬编码 DEBUG_MODE = True
OK: strategy_allday.py (全天调试版, 不含MOCK)
Size: 242020 bytes
First line: # coding=gbk
Encoding: GBK (verified by reading with gbk)
Validating... OK
Done.

Validating: strategy_allday.py
  [1/6] 文件存在         PASS
  [2/6] 编码 GBK         PASS
  [3/6] 文件头 # coding=gbk  PASS
  [4/6] Python 3.6 语法   PASS
  [5/6] 无 MOCK 残留      PASS
  [6/6] 无长小数输出      PASS
  ------------------------
  Result: ALL PASS  (6/6)
```

### TASK-2 grep 标记结果

```
# 源文件 grep（返回 1 行）
$ grep -n "F1: 操作点开场先确认" adapters/qmt_wrapper.py
3205:    # F1: 操作点开场先确认上一操作点的买单成交，回写 _g_my_codes

# allday 版 grep（返回 1）
$ iconv -f GBK -t UTF-8 strategy_allday.py | grep -c "F1: 操作点开场先确认"
1

# main 版 grep（返回 1，正常——build 合入源文件，_execute_full_cycle 在 main 版存在但不被调用）
$ iconv -f GBK -t UTF-8 strategy_main.py | grep -c "F1: 操作点开场先确认"
1
```

### TASK-3 未碰 main 版路径验证

```
# _execute_trade 函数体内无 F1 标记
$ grep -n "F1: 操作点开场" adapters/qmt_wrapper.py
3205:    # F1: 操作点开场先确认上一操作点的买单成交，回写 _g_my_codes
# 仅在 _execute_full_cycle (line 3205) 出现，不在 _execute_trade 内

# handlebar 原 _check_pending_orders 调用点仍在（line 3669）
$ grep -n "_check_pending_orders(C)" adapters/qmt_wrapper.py
2703:def _check_pending_orders(C):
3208:        _check_pending_orders(C)
3669:            _check_pending_orders(C)
# line 2703=函数定义，line 3208=F1 新增调用，line 3669=handlebar 原调用点（完好）
```
