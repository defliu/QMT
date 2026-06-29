# QMT 科创板最低委托量 200 股

#已验证 #实盘观察

## 核心结论

**科创板(688/689)卖出最低委托量是 200 股,不是 100 股。** 分层卖出按比例算股数若得 100 股,科创板会被柜台拒单废掉。普通 A 股(沪/深主板、创业板)最低 100 股。

## 现场错误(2026-06-29 模拟盘 688396.SH)

```
[COUNTER] [120156][最高委托数量，最低委托数量合法性校验失败]
v_enable_amount_t=300.00,p_entrust_amount=100.00,p_high_amount=100000.00,p_low_amount=200.00,stock_type=e
```

含义:
- `p_entrust_amount=100` 策略委托 100 股
- `p_low_amount=200` 柜台最低 200 股
- `stock_type=e` 科创板
- 结果:废单(`stat:9 cancelvol:100`)

## 最低委托量规则表

| 市场/类型 | 代码特征 | 买入最低 | 卖出最低 | 备注 |
|---|---:|---:|---:|---|
| 沪深主板 | 600/601/603/605/000/001/002 | 100 | 100 | 100 股整数倍 |
| 创业板 | 300/301 | 100 | 100 | 100 股整数倍 |
| **科创板** | **688/689** | **200** | **200** | 持仓<200 剩余仓位可一次性卖;≥200 时单笔不能低于 200,但 300 股可整笔卖(不强行取整成 200) |
| 北交所 | 8/4 开头 | 100 | 100 | 本策略当前不重点覆盖 |

可转债/ETF 等单位不同(10 张/100 份),股票策略不要混入。

## 策略实现(adapters/qmt_wrapper.py)

三个辅助函数:

- `_is_star_market_stock(code)`:兼容 `688396.SH`/`SH688396`/`688396` 多种格式(QMT 回报里见过 `SH688396` 不带点)。
- `_min_sell_volume_for_board(code)`:科创板返回 200,其他 100。
- `_normalize_sell_volume_for_board(code, desired_vol, available_vol, is_clear=False)`:按市场规则修正卖出量。

科创板修正逻辑:

```python
if available_vol <= 0: return 0
if is_clear: return available_vol          # 清仓直接卖全部
if available_vol < 200: return available_vol  # 剩余仓位一次性卖
if desired_vol < 200: return min(200, available_vol)  # 补到 200
return min(desired_vol, available_vol)     # >=200 保持(300 不取整成 200)
```

## 接入的 4 条卖出路径

1. `_check_and_execute_sell()` 初始卖出:下单前 `get_position` 查 `can_use`,用辅助函数修正 `sell_vol`,`<=0` 跳过。
2. `_retry_pending_sell()` 撤单重试:`new_vol` 用辅助函数修正(避免重试继续发 100 股科创板废单)。
3. `_check_pre_market_hard_stop()` 集合竞价预埋:用 `_normalize(..., is_clear=True)` 替代 `shares < min` 硬过滤,允许不足 200 剩余仓位一次性卖。
4. `_check_limitdown_sells()` 跌停强卖/放行:判断从 `sell_vol >= min` 改为 `sell_vol > 0`,同上。

## 踩过的坑

1. **代码识别不全**:v4 只 `code.split('.')[0]`,不认 `SH688396`(QMT 回报常见无点格式)。v5 加 `_stock_code_digits` 剥前缀。
2. **规则自相矛盾**:v4 主规则说"`available<200` 一次性卖剩余",但预埋/跌停路径又用 `sell_vol >= _min_sell_volume_for_board(code)` 判断,把 100 股剩余仓位挡掉。v5 统一改成 `sell_vol > 0`。
3. **300 股被取整**:不能把科创板 300 股向下取整成 200,`desired>=200` 时保持原值。

## 相关链接

- [[QMT_passorder异步与反查订单号]]
- 代码:`adapters/qmt_wrapper.py:_is_star_market_stock` / `_normalize_sell_volume_for_board`
- 测试:`tests/test_sell_retry.py::TestNormalizeSellVolumeForBoard` / `TestIsStarMarketStock`
- 工单:`agent_hub/2026-06-29_qmt_sell_order_tracking/`(v4/v5)
