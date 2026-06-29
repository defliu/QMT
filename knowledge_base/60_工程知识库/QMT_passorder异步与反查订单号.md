# QMT passorder 异步与反查订单号

## 核心结论

`passorder()` 是 QMT 的**异步**下单接口，正常情况返回 `0` 或 `None`，**不是订单号**。要拿真实订单号，必须 `passorder` 调用后立刻反查 `get_trade_detail_data(account, account_type, 'order')`。

把 `passorder` 返回值当 `order_id` 用 → 0 流进跟踪字典 → truthy 检查把 0 判为"无效"清理 → 策略以为没挂单，券商端还挂着 → **孤儿限价委托**没人撤没人重挂。

## 反查匹配的过滤条件

反查 `get_trade_detail_data('order')` 拿到全部委托,倒序遍历(最新优先)。

**硬条件(必须 AND 满足,2026-06-29 修订)**:

1. **code**:`"%s.%s" % (m_strInstrumentID, m_strExchangeID) == stock_code`
2. **volume**:`m_nOrderVolume == expected_vol`
3. **status**:`m_nOrderStatus not in (54, 55, 57)`(排除已撤/已废/已拒)
4. **direction**:`m_strOptName` 含 `卖`/`买`;字段为空时**放宽不卡**
5. **time**:`m_strInsertTime` HHMMSS 整数 ≥ `t_before` HHMMSS - 1;解析失败/字段空时**放宽不卡**

**remark 不再是硬条件,改为优先级信号**(见下节"remark 硬过滤翻车")。

## QMT 委托对象（XtOrder）字段速查

| 字段 | 类型 | 实测可用 | 说明 |
|------|------|------|------|
| `m_nOrderID` | int | ✓ | 委托号 |
| `m_strInstrumentID` | str | ✓ | 股票代码（不含交易所后缀） |
| `m_strExchangeID` | str | ✓ | 交易所代码（SH/SZ） |
| `m_nOrderVolume` | int | ✓ | 委托数量 |
| `m_nVolumeTraded` | int | ✓ | 已成交数量 |
| `m_strRemark` | str | ✓ | 备注（策略名写这里用于反查） |
| `m_nOrderStatus` | int | ✓ | 状态码（54/55/57=已撤/已废/已拒） |
| `m_strOptName` | str | ✓ | 操作名（"买入"/"卖出"等中文字符串） |
| `m_strInsertTime` | str | ✓ | 委托时间 HHMMSS 格式（如 '143215'） |
| `m_dLimitPrice` | float | ✓ | 限价 |
| `m_nOffsetFlag` | int | ⚠️ | 开/平标志，**股票现货账户通常为 0=未指定**，期货才有意义 |
| `m_nDirection` | int | ⚠️ | 买卖方向，股票账户上是否可用未知 |
| `m_strOpType` | str | ⚠️ | 操作类型字符串，本项目未实测 |

**判方向优先级**：`m_strOptName`（中文字符串可靠） > 其他字段。**不要**用 `m_nOffsetFlag` / `m_nDirection` 作为主判断 —— 本项目代码没有这些字段的实测先例。

## 时间比较换算

`t_before` 是 `time.time()` epoch 浮点，`m_strInsertTime` 是 HHMMSS 字符串，**不能直接比较**。

```python
import time as _time
t_struct = _time.localtime(t_before)
t_before_hms = t_struct.tm_hour * 10000 + t_struct.tm_min * 100 + t_struct.tm_sec
t_threshold_hms = t_before_hms - 1  # 1 秒容差

ot_str = getattr(o, 'm_strInsertTime', '')
if ot_str:
    try:
        ot_hms = int(ot_str[-6:])  # 兼容 '143215'/'20260622143215'/'14:32:15'
    except Exception:
        ot_hms = None
    if ot_hms is not None and ot_hms < t_threshold_hms:
        continue
```

容差 1 秒：passorder 调用瞬间委托到券商，回报 `m_strInsertTime` 可能略小于调用时刻。

跨日 / 跨午盘极不可能在本策略发生，不处理。

## 边界放宽原则

字段缺失或解析失败时**放宽不卡**(跳过这一条规则,不一票否决)。否则任何 QMT 版本变动 / 字段格式变动都会让反查瞬间失效,全部委托被误判。

## remark 硬过滤翻车(2026-06-29 实盘踩坑)

旧版反查第 3 条是硬条件 `strategy_name in m_strRemark`,2026-06-29 模拟盘 600641.SH 翻车:

- 600641 限价卖单真实挂到 QMT(`stat:2 bizvol:0 cancelvol:0`),一直未成交未撤。
- 但 QMT 真实订单回报里这笔委托 `m_strRemark` 空/不含策略名,被硬 `continue` 过滤掉,反查返回 None。
- `_check_and_execute_sell()` 只在 `order_id is not None` 时登记 `_g_pending_sells`,反查失败 → 没登记 → 后续 `_check_pending_sells()` 无对象 → 撤单/重试/市价单分支全不触发。
- 表象:"限价单不成交也不撤单换市价"。根因不是缺机制,是反查失联断在最前。

**修复**:remark 改为多候选打分排序信号——收集所有满足硬条件的候选,按 `(remark_match, ot_hms)` 降序,remark 含策略名优先、同级时间越近越优先,取第一条返回 `m_nOrderID`。唯一候选即使 remark 空也返回。

```python
candidates = []
for o in reversed(orders):
    ...  # 硬条件过滤
    remark = getattr(o, 'm_strRemark', '')
    remark_match = 1 if self.strategy_name in remark else 0
    candidates.append((remark_match, ot_hms if ot_hms is not None else -1, o))
if not candidates:
    return None
candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
return getattr(candidates[0][2], 'm_nOrderID', None)
```

**同理买入也翻车过**:`Trader.buy()` 旧版直接返回 `_passorder()` 结果,`passorder` 返回 0 被当有效订单号。修复后 buy 也接入反查,反查失败返回 None。详见 [[QMT_passorder异步与反查订单号]] 本节。

**教训**:反查任何过滤条件都不能一票否决真实订单。remark 是"锦上添花"的优先级信号,不是"雪中送炭"的硬门槛。

## 配合的 truthy 修复

`_check_pending_sells` 里：

```python
# 错（0 被 truthy 误判为无效）
if not info.get('order_id'):
    ...

# 对（显式 None 检查）
if info.get('order_id') is None:
    ...
```

理由：哪怕反查保证返回真实订单号或 None，也要把 truthy 改成显式 None 检查 —— 防止未来某天订单号合法为 0（理论可能），形成双重保险。

## 相关链接

- [[QMT编码制度]]
- [[QMT科创板最低委托量]]
- [[QMT新设备部署清单]]
- 代码：`adapters/qmt_wrapper.py:_lookup_recent_order_id` / `Trader.sell` / `Trader.buy` / `_check_pending_sells`
- 历史修复 commit：`ab8f369` fix(sell): passorder 后反查真实 m_nOrderID + 方向/时间过滤
- 2026-06-29 remark 放宽工单链：`agent_hub/2026-06-29_qmt_sell_order_tracking/`(v1/v3)
- 流程教训：[[MIMO静默简化案例-2026-06-22]]
