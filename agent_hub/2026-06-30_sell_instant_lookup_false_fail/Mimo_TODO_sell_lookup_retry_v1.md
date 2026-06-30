# 工单：sell_order 即时反查撞 QMT 异步延迟误判失败 — 改短轮询

**日期**: 2026-06-30
**作者**: CC
**目的**: 修复"卖出委托 passorder 已报交易所、但策略即时反查 order_id 撞上 QMT 异步分配 ~100ms 延迟，被判失败 return None，导致不登记 _g_pending_sells → 单子实际成交策略不知道"的 bug。今日 0630 实盘 600641 已因此被清仓（10:00:58/@37.25 + 10:09:28/@37.31 共 600 股真成交），但策略日志全程报"卖出反查失败/换仓失败"。
**预计工时**: ≤ 30 分钟

---

## 〇、背景与根因（必读，不要改这段）

诚哥授权修复，非冻结期违规。今日 0630 实盘 600641 异常卖出已坐实（QMT 运行日志 `\\192.168.31.131\国金qmt交易端模拟\userdata\log\XtClient_20260630.log` trade push 原文为证）。

**根因代码**（`D:/QMT_STRATEGIES/adapters/qmt_wrapper.py` line 389-421 `sell` 方法）：

```python
t_before = time.time()
# ... self._passorder(...) 下单 ...

order_id = self._lookup_recent_order_id(stock_code, vol, 'sell', t_before)
if order_id is None:
    print("  [卖出反查失败] %s %d股 委托可能未到达交易所，按失败处理" % (stock_code, vol))
    return None
return order_id
```

**问题链**（QMT 主日志 trade push 时序为证）：
1. `01:06:40.548` passorder 下单（卖5价 37.31，300 股）
2. `01:06:40.549` QMT `[order log]` 记录
3. `01:06:40.653` QMT `processOrderIDResp` 才分配 order_id（ref 1082139285）
4. **`sell` 方法的即时反查 `_lookup_recent_order_id` 落在 40.548~40.653 这 ~100ms 窗口内 → 订单簿里还没有这笔 → 查不到 → return None → 打"卖出反查失败"**
5. 上游换仓路径（line 2986-3004）`if oid is not None` 不成立 → **不登记 `_g_pending_sells`** → 打"换仓失败"
6. 单子实际报上去了，挂卖五价，50 分钟后股价涨上来撮合成交（biztime 100058 / 100928）
7. 策略内存里这笔从没存在过 → sell_state 不更新 → 12:24 重启靠 `_sync_holdings_from_account` 才发现 600641 没了

**为什么今天 04e4091 工单A的兜底够不着**：工单A改的 `_check_pending_sells`（line 2328-2382）三分支兜底（found_order is None 时按 actual_vol 归零确认成交）前提是**已登记 `_g_pending_sells`**。600641 这笔在 `sell` 方法就 return None 没登记，`_check_pending_sells` 那套兜底根本没机会运行。本工单修的就是"登记前"的这一步。

**关联**：这是 commit b0e0fca"卖出反查失联"的未竟部分——b0e0fca 改了 remark 不硬卡（`_lookup_recent_order_id` v3），但没改"即时反查拿不到 order_id 就判失败"这个根。详见 memory `[[sell-order-instant-lookup-false-fail]]`。

---

## 一、必做（3 项）

### TASK-1. 改 `sell` 方法：即时反查失败时短轮询重试

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`（`sell` 方法，line 389-421）

**当前代码**（line 417-421）：
```python
        order_id = self._lookup_recent_order_id(stock_code, vol, 'sell', t_before)
        if order_id is None:
            print("  [卖出反查失败] %s %d股 委托可能未到达交易所，按失败处理" % (stock_code, vol))
            return None
        return order_id
```

**改为**（passorder 已发出，order_id 异步分配有延迟，短轮询等它落地）：
```python
        # passorder 已发出，QMT 异步分配 order_id 有 ~100ms 延迟；
        # 即时反查一次可能撞在分配窗口内查不到，短轮询几次再判失败
        # （0630 600641 bug：即时反查撞 100ms 窗口判失败→不登记_g_pending_sells→单子真成交策略不知道）
        order_id = None
        for _attempt in range(SELL_LOOKUP_RETRIES):
            order_id = self._lookup_recent_order_id(stock_code, vol, 'sell', t_before)
            if order_id is not None:
                break
            time.sleep(SELL_LOOKUP_INTERVAL)
        if order_id is None:
            print("  [卖出反查失败] %s %d股 委托可能未到达交易所，按失败处理" % (stock_code, vol))
            return None
        return order_id
```

**关键**：
- `time` 模块在文件顶部已 import（line 405 已用 `time.time()`），不要重复 import。
- `SELL_LOOKUP_RETRIES` 和 `SELL_LOOKUP_INTERVAL` 是新常量，在 TASK-2 定义。
- 轮询失败后**仍 return None 并打原有的"卖出反查失败"日志**——保持上游 4 处 `if oid is not None` 行为不变，不改上游。
- 轮询期间单子已报交易所，**不撤单**（passorder 已发出，撤单是另一条路径，本工单不碰）。
- `use_market=True`（市价单）路径同样适用——市价单也存在 order_id 异步分配，统一走轮询。

### TASK-2. 定义轮询参数常量

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`

**内容/做法**:

在文件顶部常量区（`_g_failed_printed` 附近，line ~238 之后，或其他 SELL 相关常量旁）新增：

```python
# 卖出委托 passorder 后反查 order_id 的短轮询参数
# QMT 异步分配 order_id 有 ~100ms 延迟，撞窗口内会查不到，轮询几次等它落地
SELL_LOOKUP_RETRIES = 4       # 反查次数（含首次）
SELL_LOOKUP_INTERVAL = 0.2    # 每次间隔秒（4次×0.2s=最多等 0.8s，覆盖 100ms 延迟有余）
```

**关键**：数值不要改大——`sell` 在主卖出循环和换仓路径调用，单次阻塞太久会拖慢决策周期。0.8s 上限可接受（QMT order_id 分配实测 ~100ms，正常情况首次或第二次就能拿到，轮询几乎不触发）。

### TASK-3. 验证（不跑实盘/模拟）

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
   # 源文件
   grep -n "SELL_LOOKUP_RETRIES\|短轮询\|撞 100ms 窗口" adapters/qmt_wrapper.py
   # build 产物转码后 grep
   iconv -f GBK -t UTF-8 strategy_main.py | grep -c "SELL_LOOKUP_RETRIES"
   iconv -f GBK -t UTF-8 strategy_allday.py | grep -c "SELL_LOOKUP_RETRIES"
   ```
   源文件应返回常量定义 + 轮询代码共 ≥2 行；main 版和 allday 版都应返回 ≥1（build 合入源文件，两个产物都该含这段代码）。
5. grep 确认上游 4 处 `if ... is not None` / `if oid` 判断**未被改动**（本工单不动上游）：
   ```bash
   grep -n "if order_id is not None\|if oid is not None\|if oid:" adapters/qmt_wrapper.py
   # 应仍是原有 4 处（line ~2266/2987/3422 + 重试 2560），无新增无删改
   ```
   贴 grep 结果。

---

## 二、严禁

1. 禁止 git add / commit / push（本工单不授权 git）
2. 禁止改动本工单上方
3. 禁止做工单外动作
4. **禁止改动 `buy` 方法**（line 370-388）——buy 有同源隐患（即时反查 100ms 窗口），但本轮只授权卖单，buy 留待后续工单。F1 工单刚改过 buy 下游（`_check_pending_orders` 可达性），动 buy 要另开工单避免冲突。
5. 禁止改动 `_lookup_recent_order_id` 函数本体（line 432-504）——它是 b0e0fca 领域，本工单只改它的**调用方式**（轮询），不改它内部。
6. 禁止改动上游 4 处 `if oid is not None` / `if oid:` 判断（line 2266/2560/2987/3422）——本工单只改 `sell` 方法返回 order_id 的可靠性，上游契约不变。
7. 禁止改动 `_check_pending_sells` / `_finish_pending_sell` / `_confirm_engine_clear`（04e4091 工单A领域）。
8. 禁止改动 `_passorder` / `passorder` 调用本身。
9. 禁止跑实盘 / 模拟盘交易验证（只做 build + validate + grep）。
10. **文件编码 GBK，`# coding=gbk` 文件头保持；禁止用 patch 工具直接编辑，用 Read+Edit；Python 3.6.8 语法（禁 f-string / dict[str,..] / walrus / match-case），用 % 格式化。**

---

## 三、完成回执（MIMO 在工单末尾追加）

---

## 完成回执

**执行时间**: 2026-06-30T13:33:36Z
**MIMO 模型**: mimo-auto
**自检**:
- [x] TASK-1: sell 方法 line 422-434 已改为短轮询，改后完整 sell 方法体：
```python
        # passorder 已发出，QMT 异步分配 order_id 有 ~100ms 延迟；
        # 即时反查一次可能撞在分配窗口内查不到，短轮询几次再判失败
        # （0630 600641 bug：即时反查撞 100ms 窗口判失败→不登记_g_pending_sells→单子真成交策略不知道）
        order_id = None
        for _attempt in range(SELL_LOOKUP_RETRIES):
            order_id = self._lookup_recent_order_id(stock_code, vol, 'sell', t_before)
            if order_id is not None:
                break
            time.sleep(SELL_LOOKUP_INTERVAL)
        if order_id is None:
            print("  [卖出反查失败] %s %d股 委托可能未到达交易所，按失败处理" % (stock_code, vol))
            return None
        return order_id
```
- [x] TASK-2: SELL_LOOKUP_RETRIES / SELL_LOOKUP_INTERVAL 常量已定义（line 241-244）：
```
# 卖出委托 passorder 后反查 order_id 的短轮询参数
# QMT 异步分配 order_id 有 ~100ms 延迟，撞窗口内会查不到，轮询几次等它落地
SELL_LOOKUP_RETRIES = 4       # 反查次数（含首次）
SELL_LOOKUP_INTERVAL = 0.2    # 每次间隔秒（4次x0.2s=最多等 0.8s，覆盖 100ms 延迟有余）
```
- [x] TASK-3: strategy_main.py + strategy_allday.py 都 build + validate 6 项 ALL PASS：
  - strategy_main.py: ALL PASS (6/6)
  - strategy_allday.py: ALL PASS (6/6)
- [x] TASK-3: grep 落点结果：
  - 源文件 5 行含 SELL_LOOKUP_RETRIES/短轮询/撞 100ms 窗口（≥2 行）
  - strategy_main.py: 2 次匹配 SELL_LOOKUP_RETRIES
  - strategy_allday.py: 2 次匹配 SELL_LOOKUP_RETRIES
- [x] TASK-3: grep 上游 if-oid 判断未被改动（4 处原始位置均在，行号因新增常量顺移 +13）：
  - line 2279: `if order_id is not None:`（原 ~2266）
  - line 2573: `if order_id is not None:`（原 ~2560，重试）
  - line 3000: `if oid is not None:`（原 ~2987）
  - line 3435: `if oid:`（原 ~3422）
- [x] 未动 buy 方法 / _lookup_recent_order_id 本体 / _check_pending_sells / _finish_pending_sell / _passorder
- [x] 仅末尾追加，未改动工单上方
- [x] 无 git 操作 / 无实盘模拟交易
