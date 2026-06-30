# 工单F2：决策矩阵补总仓位门控 + empty_slots 用账户持仓 + holdings_value 只读纳入账户持仓

**日期**: 2026-06-30
**作者**: CC
**目的**: 修复全天版仓位无上限(#4)、名额虚高(#3)、holdings_value 漏算账户持仓(#6)。对齐 main 版 line 2882 的总仓位门控和 line 2934 的名额算法。方案C「只读计数」:账户持仓参与计算但不写 _g_my_codes、不进卖出引擎。
**预计工时**: ≤ 35 分钟

---

## 〇、背景（必读，不要改这段）

F1 已修(成交回写可达)。本工单 F2 修仓位门控/名额/holdings_value。

**当前问题代码**(`_all_day_decision_matrix` 第三步，line 3315-3330)：
- `empty_slots = MAX_HOLD - len(_g_my_codes)` → `_g_my_codes` 不含账户持仓 → 名额虚高(#3)
- 无 `holdings_value`/`current_ratio`/`MAX_TOTAL_RATIO` 门控 → 仓位无上限(#4)
- 方案C已补 `account_held` 进排除集(防重复买同一只)，但没用于仓位/名额计算

**方案C「只读计数」**(诚哥拍板)：账户持仓(含手动仓)参与 holdings_value/current_ratio/empty_slots 计算，但不写入 `_g_my_codes`、不进卖出引擎。比 main 版更安全(不误管手动仓)。

**对齐基准**: main 版 line 2859-2882(holdings_value/current_ratio/budget/门控)、line 2934(名额用实际持仓)。

---

## 一、必做（3 项）

### TASK-1. 整体重构第三步(line 3315-3330)

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`（`_all_day_decision_matrix` 函数第三步，line 3315-3330）

**当前代码**（line 3315-3330，整体替换）：
```python
    # 第三步：有空位就买入
    empty_slots = max(0, MAX_HOLD - len(_g_my_codes))
    if empty_slots > 0:
        already_held_or_pending = set(_g_my_codes.keys()) | set(_g_pending_buys.keys()) | set(_g_pending_sells.keys())
        # 方案C：补入 QMT 账户实际持仓，防止冷启动时 _g_my_codes 为空导致重复买入
        # （账户持仓只用于排除，不进 _g_my_codes/卖出引擎，避免误管手动仓）
        account_held = get_account_holdings(ACCOUNT_ID)
        if account_held:
            external = account_held - already_held_or_pending
            if external:
                print("  [买入排除] 账户已持有但未纳管，排除重复买入: %s" % sorted(external))
            already_held_or_pending = already_held_or_pending | account_held
        buyable = [s for s in scored_candidates if s['code'] not in already_held_or_pending]
        buyable = buyable[:empty_slots]
        for s in buyable:
            _place_buy_order(C, s['code'], today, dt)
```

**改为**：
```python
    # 第三步：总仓位门控 + 有空位就买入
    # F2: 用账户实际持仓只读计算仓位/预算/名额（不写入 _g_my_codes，保持方案C）
    all_positions = {}
    if _g_trader is not None:
        try:
            all_positions = _g_trader.get_holdings() or {}
        except Exception as e:
            print("  [全天] 查询账户持仓失败: %s" % e)
    account_held = set(c for c, p in all_positions.items() if p.get('volume', 0) > 0)

    current_nav = STRATEGY_CAPITAL + _g_cumulative_pnl
    holdings_value = 0.0
    for hcode, pinfo in all_positions.items():
        if pinfo.get('volume', 0) <= 0:
            continue
        hprice = 0.0
        df = _g_all_data.get(hcode)
        if df is not None:
            try:
                hprice = float(df['close'].iloc[-1])
            except Exception:
                hprice = 0.0
        if not hprice or hprice <= 0:
            try:
                hprice = _get_current_price(hcode, C) or 0.0
            except Exception:
                hprice = 0.0
        if hprice and hprice > 0:
            holdings_value += pinfo['volume'] * hprice

    current_ratio = holdings_value / current_nav if current_nav > 0 else 0.0
    budget = current_nav * MAX_TOTAL_RATIO - holdings_value
    print("  [全天] 仓位: %.1f%%  持仓市值: %.0f  可用预算: %.0f" % (
        current_ratio * 100, holdings_value, budget))

    # 总仓位硬门控（对齐 main line 2882）
    if current_ratio >= MAX_TOTAL_RATIO or budget <= 0:
        print("  [全天] 仓位已达上限或预算不足，跳过买入")
        return

    # 名额用账户实际持仓；API 返回空时回退 _g_my_codes（防 cold-start 误判，对齐 main line 2835-2836）
    held_for_slots = account_held if account_held else set(_g_my_codes.keys())
    empty_slots = max(0, MAX_HOLD - len(held_for_slots))
    if empty_slots <= 0:
        print("  [全天] 持仓已满(%d/%d)，跳过买入" % (len(held_for_slots), MAX_HOLD))
        return

    # 排除集：自有 + 待成交买/卖 + 账户实际持仓（方案C：账户持仓只排除，不纳管）
    already_held_or_pending = (set(_g_my_codes.keys()) | set(_g_pending_buys.keys())
                               | set(_g_pending_sells.keys()) | account_held)
    external = account_held - (set(_g_my_codes.keys()) | set(_g_pending_buys.keys()) | set(_g_pending_sells.keys()))
    if external:
        print("  [买入排除] 账户已持有但未纳管，排除重复买入: %s" % sorted(external))
    buyable = [s for s in scored_candidates if s['code'] not in already_held_or_pending]
    buyable = buyable[:empty_slots]
    for s in buyable:
        _place_buy_order(C, s['code'], today, dt)
```

**关键**：
- 用 `_g_trader.get_holdings()`(line 522)一次拿全部持仓+数量，替代原 `get_account_holdings`(省 API 且能直接取 volume 算市值)。
- `holdings_value` 遍历 `all_positions`(含手动仓) → 修 #4/#6 漏算。手动仓不在 `_g_all_data` 时用 `_get_current_price` 兜底取价。
- 门控 `return` 安全：第三步是函数最后一段(line 3330 后无代码)，换仓已在第一/二步跑完，跳过的只是新买入。
- `held_for_slots` 回退：`get_holdings()` 返回空时回退 `len(_g_my_codes)`，避免 empty_slots 虚高。
- **绝不把 account_held 写入 `_g_my_codes`**（方案C红线）。
- `current_nav` 用 `STRATEGY_CAPITAL + _g_cumulative_pnl`（对齐 main line 2872）。

### TASK-2. 验证

**目标路径**: `D:/QMT_STRATEGIES/`

**内容/做法**:
1. `python scripts/build_strategy.py` + `python scripts/build_strategy.py --allday`
2. 两个 validate 都 6 项 ALL PASS：
   - `python scripts/validate_qmt_file.py strategy_main.py`
   - `python scripts/validate_qmt_file.py strategy_allday.py`
3. grep 确认（中文标记转 UTF-8）：
   ```bash
   grep -n "F2: 用账户实际持仓只读计算" adapters/qmt_wrapper.py
   iconv -f GBK -t UTF-8 strategy_allday.py | grep -c "F2: 用账户实际持仓只读计算"
   ```
   贴 grep + validate 结果。

### TASK-3. 确认未碰其他路径

**内容/做法**:
```bash
# F2 标记只在 _all_day_decision_matrix 内 1 次
grep -n "F2: 用账户实际持仓只读计算" adapters/qmt_wrapper.py
# _execute_trade 函数体无 F2 改动（main 版 line 2859-2882 原样）
# _place_buy_order 暂不动（F3 才改）
grep -n "def _place_buy_order" adapters/qmt_wrapper.py
```
贴 grep。CC 核对：F2 只改了第三步，第一步/第二步(卖出/5天淘汰)未动，_execute_trade 未动。

---

## 二、严禁

1. 禁止 git add / commit / push
2. 禁止改动本工单上方
3. 禁止做工单外动作
4. **禁止把 account_held 写入 `_g_my_codes`**（方案C核心）
5. 禁止改 `_all_day_decision_matrix` 第一步(卖出,line 3257-3285)/第二步(5天淘汰,line 3286-3314)
6. 禁止改 `_place_buy_order`(F3 才改，本工单不动)
7. 禁止改 main 版 `_execute_trade` / `_sync_holdings_from_account` / `get_holdings` / `get_account_holdings` 函数本身
8. 禁止跑实盘/模拟交易验证
9. **文件编码 GBK，`# coding=gbk`；禁止 patch 工具直接编辑，用 Read+Edit；Python 3.6.8 语法（禁 f-string/dict[str,..]/walrus/match-case），用 % 格式化**

---

## 三、完成回执（MIMO 在工单末尾追加）

```markdown

---

## 完成回执

**执行时间**: 2026-06-30T07:16:49Z
**MIMO 模型**: mimo-auto
**自检**:
- [x] TASK-1: 第三步已整体重构，贴改后完整代码块
- [x] TASK-2: strategy_main.py + strategy_allday.py 都 build + validate 6 项 ALL PASS，贴输出 + grep
- [x] TASK-3: F2 标记只在 _all_day_decision_matrix 内 1 次；第一步/第二步/_execute_trade 未动，贴 grep
- [x] 未把 account_held 写入 _g_my_codes
- [x] 未动第一步/第二步/_place_buy_order/_execute_trade/get_holdings/get_account_holdings
- [x] 仅末尾追加，未改动工单上方
- [x] 无 git 操作 / 无实盘模拟交易

### TASK-1 改后代码块
```python
    # 第三步：总仓位门控 + 有空位就买入
    # F2: 用账户实际持仓只读计算仓位/预算/名额（不写入 _g_my_codes，保持方案C）
    all_positions = {}
    if _g_trader is not None:
        try:
            all_positions = _g_trader.get_holdings() or {}
        except Exception as e:
            print("  [全天] 查询账户持仓失败: %s" % e)
    account_held = set(c for c, p in all_positions.items() if p.get('volume', 0) > 0)

    current_nav = STRATEGY_CAPITAL + _g_cumulative_pnl
    holdings_value = 0.0
    for hcode, pinfo in all_positions.items():
        if pinfo.get('volume', 0) <= 0:
            continue
        hprice = 0.0
        df = _g_all_data.get(hcode)
        if df is not None:
            try:
                hprice = float(df['close'].iloc[-1])
            except Exception:
                hprice = 0.0
        if not hprice or hprice <= 0:
            try:
                hprice = _get_current_price(hcode, C) or 0.0
            except Exception:
                hprice = 0.0
        if hprice and hprice > 0:
            holdings_value += pinfo['volume'] * hprice

    current_ratio = holdings_value / current_nav if current_nav > 0 else 0.0
    budget = current_nav * MAX_TOTAL_RATIO - holdings_value
    print("  [全天] 仓位: %.1f%%  持仓市值: %.0f  可用预算: %.0f" % (
        current_ratio * 100, holdings_value, budget))

    # 总仓位硬门控（对齐 main line 2882）
    if current_ratio >= MAX_TOTAL_RATIO or budget <= 0:
        print("  [全天] 仓位已达上限或预算不足，跳过买入")
        return

    # 名额用账户实际持仓；API 返回空时回退 _g_my_codes（防 cold-start 误判，对齐 main line 2835-2836）
    held_for_slots = account_held if account_held else set(_g_my_codes.keys())
    empty_slots = max(0, MAX_HOLD - len(held_for_slots))
    if empty_slots <= 0:
        print("  [全天] 持仓已满(%d/%d)，跳过买入" % (len(held_for_slots), MAX_HOLD))
        return

    # 排除集：自有 + 待成交买/卖 + 账户实际持仓（方案C：账户持仓只排除，不纳管）
    already_held_or_pending = (set(_g_my_codes.keys()) | set(_g_pending_buys.keys())
                               | set(_g_pending_sells.keys()) | account_held)
    external = account_held - (set(_g_my_codes.keys()) | set(_g_pending_buys.keys()) | set(_g_pending_sells.keys()))
    if external:
        print("  [买入排除] 账户已持有但未纳管，排除重复买入: %s" % sorted(external))
    buyable = [s for s in scored_candidates if s['code'] not in already_held_or_pending]
    buyable = buyable[:empty_slots]
    for s in buyable:
        _place_buy_order(C, s['code'], today, dt)
```

### TASK-2 验证输出
```
Building strategy_main.py ...
OK: strategy_main.py (生产版, 不含MOCK)
Size: 243663 bytes
First line: # coding=gbk
Encoding: GBK (verified by reading with gbk)
Validating... OK
Done.

Building strategy_allday.py ...
  [allday] 硬编码 DEBUG_MODE = True
OK: strategy_allday.py (全天调试版, 不含MOCK)
Size: 243632 bytes
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
  [6/6] 无长小数输出      PASS  (所有评分值 %.2f)
  ------------------------
  Result: ALL PASS  (6/6)

Validating: strategy_allday.py
  [1/6] 文件存在         PASS
  [2/6] 编码 GBK         PASS
  [3/6] 文件头 # coding=gbk  PASS
  [4/6] Python 3.6 语法   PASS
  [5/6] 无 MOCK 残留      PASS
  [6/6] 无长小数输出      PASS  (所有评分值 %.2f)
  ------------------------
  Result: ALL PASS  (6/6)
```

### TASK-2 grep 输出
```bash
grep -n "F2: 用账户实际持仓只读计算" adapters/qmt_wrapper.py
3316:    # F2: 用账户实际持仓只读计算仓位/预算/名额（不写入 _g_my_codes，保持方案C）

iconv -f GBK -t UTF-8 strategy_allday.py | grep -c "F2: 用账户实际持仓只读计算"
1
```

### TASK-3 确认未碰其他路径
```bash
grep -n "F2: 用账户实际持仓只读计算" adapters/qmt_wrapper.py
3316:    # F2: 用账户实际持仓只读计算仓位/预算/名额（不写入 _g_my_codes，保持方案C）

grep -n "def _place_buy_order" adapters/qmt_wrapper.py
3417:def _place_buy_order(C, code, today, dt):
```
