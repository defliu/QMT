# 工单E：全天版重复买入修复 — 买入排除集补入 QMT 账户实际持仓（方案C）

**日期**: 2026-06-30
**作者**: CC
**目的**: 修复全天版(DEBUG_MODE)从空持仓文件冷启动时，不知道 QMT 账户已持有该股，导致重复买入（今日 13:41:57 重复买入 688396 共 300 股）。方案C：把 QMT 账户实际持仓并入买入排除集，只防重复买入，不纳入卖出引擎管理（不破坏"不纳手动仓"设计）。
**预计工时**: ≤ 30 分钟

---

## 〇、背景与根因（必读，不要改这段）

诚哥授权修复。今日实盘已造成 688396 重复买入 300 股。

**根因**：
- 全天版用独立持仓文件 `allday_holdings.txt`（DEBUG_MODE 路径覆盖，line ~171），冷启动时该文件不存在 → `_g_my_codes = {}`（空）。
- init 的 `_sync_holdings_from_account`（line ~663）**只做减法不做加法**（line ~701 注释明说"不自动加入，避免误纳手动仓"）。
- 全天版决策矩阵 `_run_allday_decision`（line ~3253）第三步买入排除集（line ~3311）：
  ```python
  already_held_or_pending = set(_g_my_codes.keys()) | set(_g_pending_buys.keys()) | set(_g_pending_sells.keys())
  ```
  只含 `_g_my_codes`（空）+ 挂单，**不含 QMT 账户实际持仓** → 688396 不被排除 → 重复买入。

**对比**：尾盘版 `_execute_trade`（line ~2838-2842）有"加入账户中发现的票"逻辑，但全天版决策矩阵没有。本工单只补全天版。

**方案C 设计**（诚哥拍板）：
- 不把账户持仓塞进 `_g_my_codes`（避免被卖出引擎管理/误卖手动仓）。
- 用独立的"账户实际持仓 set"并入买入排除集，纯防重复买入。
- 加诊断日志，让诚哥能看到"账户有但策略未纳管的票"。

---

## 一、必做（3 项）

### TASK-1. 全天版决策矩阵第三步：排除集补入 QMT 账户持仓

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`（`_run_allday_decision` 函数第三步，line ~3308-3315）

**当前代码**：
```python
    # 第三步：有空位就买入
    empty_slots = max(0, MAX_HOLD - len(_g_my_codes))
    if empty_slots > 0:
        already_held_or_pending = set(_g_my_codes.keys()) | set(_g_pending_buys.keys()) | set(_g_pending_sells.keys())
        buyable = [s for s in scored_candidates if s['code'] not in already_held_or_pending]
        buyable = buyable[:empty_slots]
        for s in buyable:
            _place_buy_order(C, s['code'], today, dt)
```

**改为**：
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

**关键**：
- 用现有的 `get_account_holdings(ACCOUNT_ID)`（line ~683，返回 `m_nVolume>0` 的 code set），不要新写查询函数。
- `account_held` 只并入排除集，**绝不写入 `_g_my_codes`**。
- 诊断日志 ` [买入排除] 账户已持有但未纳管...` 让诚哥能看到被排除的票。

### TASK-2. `_place_buy_order` 加一道重复买入兜底

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`（`_place_buy_order` 函数，line ~3361 开头）

**内容/做法**:

在 `_place_buy_order` 函数体开头（`price = _get_current_price(code, C)` 之前）加一道兜底：
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
    # ... 原逻辑不动
```

**关键**：
- 这是第二道保险（决策矩阵排除集是第一道）。即使排除集逻辑出问题，下单前最后一刻还能拦住。
- `get_position` 读 QMT 缓存，可能有延迟，但"已持有"这种状态缓存通常准确（不会无中生有），作为兜底够用。
- 不要改 `_place_buy_order` 后面的预算/数量/下单逻辑。

### TASK-3. 验证

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`

**内容/做法**:

1. `python scripts/build_strategy.py`（生成 strategy_main.py）
2. `python scripts/build_strategy.py --allday`（生成 strategy_allday.py，诚哥要部署全天版）
3. 两个文件都跑 validate：
   - `python scripts/validate_qmt_file.py strategy_main.py`
   - `python scripts/validate_qmt_file.py strategy_allday.py`
   - 必须 6 项 ALL PASS。
4. grep 确认改动落点：
   ```bash
   grep -n "买入排除.*账户已持有但未纳管" adapters/qmt_wrapper.py
   grep -n "买入拦截.*账户已持有" adapters/qmt_wrapper.py
   ```
   两条都应有输出。贴 grep + validate 结果。

---

## 二、严禁

1. 禁止 git add / commit / push（本工单不授权 git）
2. 禁止改动本工单上方
3. 禁止做工单外动作
4. **禁止把 account_held 写入 `_g_my_codes`**（方案C核心：只排除不纳管，见 TASK-1 关键）
5. 禁止改 `_sync_holdings_from_account` 的"不加手动仓"逻辑（那是另一条线，本工单不动）
6. 禁止改尾盘版 `_execute_trade` 的持仓同步逻辑（尾盘版已有"加入账户发现"逻辑，不需要改）
7. 禁止改 `_place_buy_order` 的预算/数量/下单逻辑（只加开头兜底）
8. 禁止改 `get_account_holdings` 函数本身
9. 禁止跑实盘 / 模拟盘交易验证（只做 build + validate + grep）
10. **文件编码 GBK，`# coding=gbk` 文件头保持；禁止用 patch 工具直接编辑，用 Read+Edit；Python 3.6.8 语法（禁 f-string / dict[str,..] / walrus / match-case）**

---

## 三、完成回执（MIMO 在工单末尾追加）

```markdown

---

## 完成回执

**执行时间**: <用 `date -u +"%Y-%m-%dT%H:%M:%SZ"` 真实拿，禁止 placeholder>
**MIMO 模型**: <实际模型名>
**自检**:
- [ ] TASK-1: _run_allday_decision 第三步排除集已补入 get_account_holdings，未写入 _g_my_codes，贴改后代码块
- [ ] TASK-2: _place_buy_order 开头已加重复买入兜底，贴改后代码块
- [ ] TASK-3: strategy_main.py + strategy_allday.py 都 build + validate 6 项 ALL PASS，贴输出
- [ ] grep 两条标记都有输出
- [ ] 未把 account_held 写入 _g_my_codes
- [ ] 未改 _sync_holdings_from_account / _execute_trade / get_account_holdings
- [ ] 仅末尾追加，未改动工单上方
- [ ] 无 git 操作 / 无实盘模拟交易
```

---

## 完成回执

**执行时间**: 2026-06-30T05:58:56Z
**MIMO 模型**: mimo-auto
**自检**:
- [x] TASK-1: _run_allday_decision 第三步排除集已补入 get_account_holdings，未写入 _g_my_codes
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
- [x] TASK-2: _place_buy_order 开头已加重复买入兜底
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
  ```
- [x] TASK-3: strategy_main.py + strategy_allday.py 都 build + validate 6 项 ALL PASS
  ```
  strategy_main.py:
    [1/6] 文件存在         PASS
    [2/6] 编码 GBK         PASS
    [3/6] 文件头 # coding=gbk  PASS
    [4/6] Python 3.6 语法   PASS
    [5/6] 无 MOCK 残留      PASS
    [6/6] 无长小数输出      PASS
    Result: ALL PASS  (6/6)

  strategy_allday.py:
    [1/6] 文件存在         PASS
    [2/6] 编码 GBK         PASS
    [3/6] 文件头 # coding=gbk  PASS
    [4/6] Python 3.6 语法   PASS
    [5/6] 无 MOCK 残留      PASS
    [6/6] 无长小数输出      PASS
    Result: ALL PASS  (6/6)
  ```
- [x] grep 两条标记都有输出
  ```
  adapters/qmt_wrapper.py:3318: print("  [买入排除] 账户已持有但未纳管，排除重复买入: %s" % sorted(external))
  adapters/qmt_wrapper.py:3377: print("    [买入拦截] %s 账户已持有 %d 股，跳过重复买入" % (code, pos.get('volume', 0)))
  ```
- [x] 未把 account_held 写入 _g_my_codes
- [x] 未改 _sync_holdings_from_account / _execute_trade / get_account_holdings
- [x] 仅末尾追加，未改动工单上方
- [x] 无 git 操作 / 无实盘模拟交易
