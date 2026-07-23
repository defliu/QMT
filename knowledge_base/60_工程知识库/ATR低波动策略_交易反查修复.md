---
tags: #已验证 #可转SPEC
---

# ATR低波动策略 — 交易反查4BUG修复记录

**日期**: 2026-07-23
**策略**: `atr_lowvol/strategy_atr.py`
**根因**: QMT `passorder()` 异步接口返回值误用 + 反查逻辑缺陷

---

## BUG 1 (致命): passorder 返回值当订单号用

**问题**: `C.passorder()` 是异步接口，正常返回 `0` 或 `None`，不是真实订单号。代码用 `str(order_id)` 去比对反查委托列表的 `m_strOrderID` → `"0" == "真实订单号"` → 永远不匹配 → 永远报"反查失败"。

**修复**: 重写为 `_lookup_order()` 函数，不依赖 passorder 返回值，按 `code + volume + direction(中文"买入"/"卖出")` 匹配。

## BUG 2 (致命): 反查无过滤条件

**问题**: 遍历所有委托不做任何过滤，可能匹配到不相关订单。

**修复**: `_lookup_order()` 做 AND 过滤：code 精确匹配 + volume ±10% 容差 + direction 中文匹配 + 排除已撤/已废/已拒状态(54/55/57)。remark 不硬卡，只作候选排序信号。

## BUG 3 (严重): 反查失败也直接删持仓

**问题**: 即使反查失败（可能只是QMT异步延迟100ms），仍然 `del _g_my_codes[code]`，如果订单实际没报上，持仓就丢了。

**修复**: 反查失败时登记到 `_g_pending_sells`，由 `_check_pending_orders()` 后续轮询确认，30秒超时放弃。[[sell-order-instant-lookup-false-fail]]

## BUG 4 (严重): 买入同样问题

**问题**: 买入也用了相同的 `oid == str(order_id)` 模式。

**修复**: 同上，改用 `_lookup_order()` + `_g_pending_buys` 兜底。

---

## 参考文档

- [[qmt-passorder-async-lookup]] — QMT passorder 异步特性
- [[sell-order-instant-lookup-false-fail]] — 600641 卖单成交反查失败根因
- [[qmt-order-lookup-remark-not-hardfilter]] — remark 不硬卡
- [[sell-order-lookup-fix]] — 反查链路修复历程
- [[sell-market-retry-blocked-by-lookup-fail]] — 市价重试被反查失败断链

## 代码位置

- `_lookup_order()`: `atr_lowvol/strategy_atr.py` 行 447
- `_check_pending_orders()`: `atr_lowvol/strategy_atr.py` 行 500
- `_execute_sells()`: 行 558（调用 _lookup_order）
- `_execute_buys()`: 行 649（调用 _lookup_order）
