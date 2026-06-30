# 工单F3：_place_buy_order 补均分 budget + 资金检查（对齐 main line 3015-3033）

**日期**: 2026-06-30
**作者**: CC
**目的**: 修复全天版 #5(不均分 budget、不查可用资金、累计超仓)。矩阵层算好 per_stock_amount 传入,_place_buy_order 瘦身。顺带修 _g_per_stock_amount 全天版恒=0。对齐 main 版 line 3015-3033。
**预计工时**: ≤ 35 分钟

---

## 〇、背景（必读，不要改这段）

F1(成交回写)、F2(仓位门控+名额+holdings_value)已修。本工单 F3 修单只金额。

**当前问题**:
- `_place_buy_order`(line 3417)自算 `holdings_value`(只遍历 `_g_my_codes`,不含账户持仓,虚高 budget)、`amount = min(_g_per_stock_amount or TARGET_RATIO, budget)` —— 不均分 budget、不查可用资金。
- `_g_per_stock_amount` 全天版恒=0(只有 main 版 line 3022/3033 赋值)→ 走 TARGET_RATIO 兜底。
- 矩阵层(F2 已加 budget 计算)已有正确 budget,但没算 per_stock_amount 传给 _place_buy_order。

**对齐基准**: main 版 line 3015-3033:`per_stock_amount = min(TARGET_RATIO, budget/len(buyable))` 均分 + `real_cash*0.80` 资金上限。

---

## 一、必做（3 项）

### TASK-1. 矩阵层算 per_stock_amount 并传入（落点A）

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`（`_all_day_decision_matrix` 第三步末尾，F2 改后的 `buyable = buyable[:empty_slots]` 之后、`for s in buyable:` 之前）

**当前代码**（F2 改后的第三步末尾）：
```python
    buyable = [s for s in scored_candidates if s['code'] not in already_held_or_pending]
    buyable = buyable[:empty_slots]
    for s in buyable:
        _place_buy_order(C, s['code'], today, dt)
```

**改为**：
```python
    buyable = [s for s in scored_candidates if s['code'] not in already_held_or_pending]
    buyable = buyable[:empty_slots]

    # F3: 按剩余只数均分 budget + 可用资金 80% 门控（对齐 main line 3015-3033）
    per_stock_amount_raw = current_nav * TARGET_RATIO
    if buyable and budget > 0:
        per_stock_amount_raw = min(per_stock_amount_raw, budget / len(buyable))
    per_stock_amount = int(per_stock_amount_raw / 100) * 100
    if per_stock_amount < 100:
        print("  [全天] 单只金额不足100股，跳过买入")
        return
    _g_per_stock_amount = per_stock_amount

    real_cash = _g_trader.get_available_cash() if _g_trader else 0.0
    total_buy_amount = per_stock_amount * len(buyable)
    if total_buy_amount > real_cash * 0.80 and len(buyable) > 0:
        adjusted = int(real_cash * 0.80 / len(buyable) / 100) * 100
        if adjusted < 100:
            print("  [全天] 可用资金不足，跳过买入")
            return
        per_stock_amount = adjusted
        _g_per_stock_amount = per_stock_amount

    for s in buyable:
        _place_buy_order(C, s['code'], today, dt, per_stock_amount)
```

**关键**：
- `current_nav` / `budget` 已在 F2 第三步算好,直接用。
- `TARGET_RATIO`(line 143)、`MAX_TOTAL_RATIO`(line 144)是全局常量。
- `_g_per_stock_amount` 赋值,让 `_try_buy_replacement`/`_check_pending_orders` 补买也用正确金额。
- `_g_trader.get_available_cash()`(line 538)。
- 调用改签名:`_place_buy_order(C, s['code'], today, dt, per_stock_amount)`。

### TASK-2. _place_buy_order 瘦身改签名（落点B）

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`（`_place_buy_order` 函数，line 3417-3471）

**当前代码**（line 3417-3459，关键部分）：
```python
def _place_buy_order(C, code, today, dt):
    """直接买入（全天版决策矩阵使用）"""
    global _g_trader, _g_pending_buys, _g_my_codes, _g_per_stock_amount, _g_cumulative_pnl, _g_all_data

    # 兜底：若账户已持有该股，拒绝买入（防重复建仓，与决策矩阵排除集双保险）
    try:
        pos = _g_trader.get_position(code)
        if pos and pos.get('volume', 0) > 0:
            print("    [买入拦截] %s 账户已持有 %d 股，跳过重复买入" % (code, pos.get('volume', 0)))
            return
    except Exception as e:
        print("    [买入拦截] %s 查询持仓异常: %s" % (code, e))

    price = _get_current_price(code, C)
    if not price or price <= 0:
        print("    [买入] %s 无法获取价格" % code)
        return

    if _is_limit_up(code, C):
        print("    [买入] %s 涨停，跳过" % code)
        return

    current_nav = STRATEGY_CAPITAL + _g_cumulative_pnl
    holdings_value = 0.0
    for hcode in list(_g_my_codes.keys()):
        df = _g_all_data.get(hcode)
        if df is not None:
            try:
                hprice = float(df['close'].iloc[-1])
                pos = _g_trader.get_position(hcode)
                if pos and pos.get('volume', 0) > 0:
                    holdings_value += pos['volume'] * hprice
            except Exception:
                pass
    budget = current_nav * MAX_TOTAL_RATIO - holdings_value
    if budget <= 0:
        print("    [买入] %s 预算不足 (budget=%.0f)，跳过" % (code, budget))
        return
    amount = min(_g_per_stock_amount if _g_per_stock_amount > 0 else current_nav * TARGET_RATIO, budget)
    volume = int(amount / price / 100) * 100
    if volume < 100:
        print("    [买入] %s 不足100股" % code)
        return

    order_id = _g_trader.buy(code, volume, remark='全天买入')
    # ... 后面 _g_pending_buys 写入不变
```

**改为**：
```python
def _place_buy_order(C, code, today, dt, per_stock_amount):
    """直接买入（全天版决策矩阵使用，per_stock_amount 由矩阵层均分算好传入）"""
    global _g_trader, _g_pending_buys, _g_my_codes, _g_cumulative_pnl

    # 兜底：若账户已持有该股，拒绝买入（防重复建仓，与决策矩阵排除集双保险）
    try:
        pos = _g_trader.get_position(code)
        if pos and pos.get('volume', 0) > 0:
            print("    [买入拦截] %s 账户已持有 %d 股，跳过重复买入" % (code, pos.get('volume', 0)))
            return
    except Exception as e:
        print("    [买入拦截] %s 查询持仓异常: %s" % (code, e))

    price = _get_current_price(code, C)
    if not price or price <= 0:
        print("    [买入] %s 无法获取价格" % code)
        return

    if _is_limit_up(code, C):
        print("    [买入] %s 涨停，跳过" % code)
        return

    # F3: per_stock_amount 由矩阵层均分 budget + 资金检查后传入，此处直接用
    volume = int(per_stock_amount / price / 100) * 100
    if volume < 100:
        print("    [买入] %s 金额%.0f不足100股" % (code, per_stock_amount))
        return

    order_id = _g_trader.buy(code, volume, remark='全天买入')
    # ... 后面 _g_pending_buys 写入不变（原 line 3462-3471 保持不动）
```

**关键**：
- 改签名加 `per_stock_amount` 参数。
- **删除** line 3439-3459 的自算 current_nav/holdings_value/budget/amount（与 F2 矩阵层重复，且 holdings_value 只遍历 _g_my_codes 虚高）。
- **保留** line 3421-3428 兜底拦截（方案C第二道）、line 3430 取价、line 3435 涨停跳过。
- `volume = int(per_stock_amount / price / 100) * 100`。
- **保留** line 3461-3471 的 `_g_trader.buy` + `_g_pending_buys[code]=...` 写入逻辑不动。
- global 行可去掉不再用的 `_g_per_stock_amount` / `_g_all_data`（如果函数体内不再引用）。注意确认去掉后没有其他地方引用,若拿不准就保留 global 声明不删（多余 global 无害）。

### TASK-3. 验证

**目标路径**: `D:/QMT_STRATEGIES/`

**内容/做法**:
1. `python scripts/build_strategy.py` + `python scripts/build_strategy.py --allday`
2. 两个 validate 都 6 项 ALL PASS。
3. grep 确认：
   ```bash
   grep -n "F3: 按剩余只数均分" adapters/qmt_wrapper.py
   grep -n "def _place_buy_order" adapters/qmt_wrapper.py
   # _place_buy_order 签名应含 per_stock_amount 参数
   grep -n "_place_buy_order(C, s\['code'\], today, dt, per_stock_amount)" adapters/qmt_wrapper.py
   ```
   贴 grep + validate。

### TASK-4. 确认 _place_buy_order 单一调用点已更新

**内容/做法**:
```bash
# _place_buy_order 所有调用点
grep -n "_place_buy_order" adapters/qmt_wrapper.py
```
确认调用点都传了 per_stock_amount（应只有 TASK-1 的那一处调用）。贴 grep。

---

## 二、严禁

1. 禁止 git add / commit / push
2. 禁止改动本工单上方
3. 禁止做工单外动作
4. 禁止改 F2 已改的第三步前半段（仓位门控/名额/holdings_value），只在末尾 buyable 之后加 per_stock_amount 计算
5. 禁止改 _place_buy_order 的兜底拦截（方案C第二道）、取价、涨停跳过、下单、_g_pending_buys 写入
6. 禁止改 main 版 _execute_trade / _check_pending_orders / _try_buy_replacement
7. 禁止跑实盘/模拟交易验证
8. **文件编码 GBK，`# coding=gbk`；禁止 patch 工具直接编辑，用 Read+Edit；Python 3.6.8 语法（禁 f-string/dict[str,..]/walrus/match-case），用 % 格式化**

---

## 三、完成回执（MIMO 在工单末尾追加）

```markdown

---

## 完成回执

**执行时间**: 2026-06-30T07:25:26Z
**MIMO 模型**: mimo-auto
**自检**:
- [x] TASK-1: 矩阵层已加 per_stock_amount 均分 + 资金80%门控，调用改签名传参，贴代码块
- [x] TASK-2: _place_buy_order 已瘦身改签名，删除自算 budget/amount，保留兜底/取价/涨停/下单，贴改后完整函数体
- [x] TASK-3: 两个 build + validate 6 项 ALL PASS + grep，贴输出
- [x] TASK-4: _place_buy_order 调用点都已传 per_stock_amount，贴 grep
- [x] 未动 F2 第三步前半段 / 兜底拦截 / 下单逻辑 / main 版
- [x] 仅末尾追加，未改动工单上方
- [x] 无 git 操作 / 无实盘模拟交易
```
