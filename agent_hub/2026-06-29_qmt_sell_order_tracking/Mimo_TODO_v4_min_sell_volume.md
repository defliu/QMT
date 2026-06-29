# MIMO_TODO_v4：修复科创板卖出最低委托量 200 股规则

**日期**: 2026-06-29
**作者**: CC
**目的**: 在订单反查修复基础上，补上科创板/特殊股票卖出最低委托量规则，避免 688396.SH 这类 100 股卖单被柜台以 `p_low_amount=200` 拒单。
**预计工时**: ≤ 60 分钟

---

## 一、背景

2026-06-29 QMT 日志中 688396.SH 卖出 100 股被柜台拒绝：

```text
[COUNTER] [120156][最高委托数量，最低委托数量合法性校验失败]
v_enable_amount_t=300.00,p_entrust_amount=100.00,p_high_amount=100000.00,p_low_amount=200.00,stock_type=e
```

含义：
- 688396.SH 是科创板；
- 可卖 300 股；
- 策略卖出 100 股；
- 柜台最低委托量 200 股；
- 结果废单。

本单只修股票卖出量合法性，不改订单反查逻辑。

---

## 二、必做（6 项）

### TASK-1. 初始 dirty 检查

执行：

```bash
git -C D:/QMT_STRATEGIES diff --stat -- adapters/qmt_wrapper.py tests/test_sell_retry.py tests/test_order_lookup.py strategy_main.py strategy_allday.py
git -C D:/QMT_STRATEGIES status --short -- adapters/qmt_wrapper.py tests/test_sell_retry.py tests/test_order_lookup.py strategy_main.py strategy_allday.py
```

回执记录摘要。注意：v1/v3 已有订单反查改动，不要误判为异常。

### TASK-2. 增加卖出最小委托量辅助函数

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`

**建议位置**: `Trader` 类之外、卖出逻辑附近，或 `_check_and_execute_sell()` 前。

**要求实现**:

新增类似函数，命名可自定，但语义必须清晰，例如：

```python
def _is_star_market_stock(code):
    # 688/689 开头，兼容 688396.SH / SH688396 / 688396


def _normalize_sell_volume_for_board(code, desired_vol, available_vol, is_clear=False):
    """按市场规则修正卖出数量。

    普通 A 股：最低 100 股；不足 100 的剩余零股只允许清仓/可用不足 100 时一次性卖。
    科创板：最低 200 股；可用 >=200 且 desired<200 时补到 200；可用 <200 时只允许一次性卖剩余。
    返回 int，不能卖则返回 0。
    """
```

规则要求：

1. 普通股票：
   - `available_vol <= 0` → 0；
   - `is_clear=True` → `available_vol`；
   - `desired_vol >= 100` → 不超过 available，按 100 股整数向下；
   - `desired_vol < 100` 且 `available_vol < 100` → `available_vol`（零股一次性卖）；
   - 否则 → 0。

2. 科创板 `688/689`：
   - `available_vol <= 0` → 0；
   - `is_clear=True` → `available_vol`；
   - `available_vol < 200` → `available_vol`（不足 200 的剩余仓位一次性卖）；
   - `desired_vol < 200` → `min(200, available_vol)`；
   - `desired_vol >= 200` → `min(desired_vol, available_vol)`；
   - 注意不要把 300 股强行取整成 200；科创板卖出 300 股应保留 300。

3. 所有返回值必须是 `int`，不能超过 `available_vol`。

### TASK-3. 接入初始卖出与重试卖出

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`

必须接入两个链路：

1. `_check_and_execute_sell()` 中，原本直接使用 `shares` 下单：
   - 下单前查 `pos = _g_trader.get_position(code)`；
   - `available = pos['can_use'] if pos else shares`；
   - 用辅助函数修正 `sell_vol`；
   - 如果 `sell_vol <= 0`，打印一次明确日志并跳过；
   - 后续 `_g_trader.sell()`、`_g_pending_sells['volume']`、日志和 `sells.append(... volume ...)` 都用 `sell_vol`，不要继续用旧 `shares`。

2. `_retry_pending_sell()` 中，原本：
   ```python
   new_vol = min(info['volume'], available)
   ```
   改为用辅助函数修正，`is_clear=info.get('is_clear', False)`。

日志建议：
- 若科创板 100 → 200，可打印 `[卖出数量修正] 688396.SH 100股 -> 200股 (科创板最低200)`。
- 如果跳过，打印 `[卖出跳过] xxx 数量不满足最低委托量 desired=... available=...`。

### TASK-4. 预埋/跌停链路检查

检查 `_check_pre_market_hard_stop()`、`_check_limitdown_sells()` 中卖出数量是否可能出现科创板 100 股。

要求：
- 如果这些路径直接使用全仓 `shares` / `available`，可以不改，但回执里说明。
- 如果发现会用 `remaining_vol` 算出 100 股卖科创板，也要接入辅助函数。

### TASK-5. 补测试

**目标路径**: 优先 `D:/QMT_STRATEGIES/tests/test_sell_retry.py`，也可新增专门文件。

至少覆盖：

1. `_normalize_sell_volume_for_board('688396.SH', 100, 300, False) == 200`。
2. `_normalize_sell_volume_for_board('688396.SH', 300, 300, False) == 300`。
3. `_normalize_sell_volume_for_board('688396.SH', 100, 100, False) == 100`（不足 200 剩余仓位一次性卖）。
4. 普通股票 `600641.SH`：`desired=100, available=600` 仍是 100。
5. `_check_and_execute_sell()` 场景：科创板 raw decision shares=100、position can_use=300 时，实际调用 `_g_trader.sell()` 的 volume 是 200。
6. `_retry_pending_sell()` 场景：科创板 info volume=100、can_use=300 时，实际重试 sell volume 是 200。

测试不依赖真实 QMT，用 fake trader / monkeypatch。

### TASK-6. 构建与验证

运行：

```bash
"C:/Users/Administrator/AppData/Local/Programs/Python/Python310/python.exe" -m pytest tests/test_sell_retry.py tests/test_order_lookup.py -q
"C:/Users/Administrator/AppData/Local/Programs/Python/Python310/python.exe" scripts/build_strategy.py
"C:/Users/Administrator/AppData/Local/Programs/Python/Python310/python.exe" scripts/build_strategy.py --allday
"C:/Users/Administrator/AppData/Local/Programs/Python/Python310/python.exe" scripts/validate_qmt_file.py strategy_main.py
```

要求：
- 新增/相关测试必须通过；
- 如果旧测试仍有已知 pre-existing 失败，必须逐项说明；
- build 生产版和全天版 OK；
- validate 6/6 PASS。

---

## 三、严禁

1. 禁止 git add / commit / push。
2. 禁止修改 release、QMT 日志、`D:/QMT_POOL/`、QMT 安装目录。
3. 禁止改订单反查 v1/v3 逻辑，除非测试必须微调且要说明。
4. 禁止改历史失败测试的业务预期。
5. 禁止直接手改 `strategy_main.py` / `strategy_allday.py`，只能 build 生成。
6. 禁止整文件行尾转换导致巨大 diff；`adapters/qmt_wrapper.py` 必须保持小 diff。
7. 遇异常必须停下写明，不得自判无关继续。

---

## 四、完成回执（MIMO 在工单末尾追加）

```markdown

---

## 完成回执

**执行时间**: <ISO 8601 真实时刻>
**MIMO 模型**: <实际名>
**初始 dirty 摘要**: <摘要>
**改动文件**:
- <file>: <摘要>
**关键逻辑**:
- <说明普通/科创板规则>
**验证命令与结果**:
- `<命令>` → PASS/FAIL，摘要
**自检**:
- [ ] 科创板 desired=100 available=300 修正为 200
- [ ] 科创板 desired=300 available=300 保持 300
- [ ] 普通股票 100 股卖出不受影响
- [ ] 初始卖出和重试卖出均接入修正
- [ ] qmt_wrapper.py 未出现整文件行尾巨大 diff
- [ ] build_strategy.py / --allday OK
- [ ] validate_qmt_file.py strategy_main.py 6/6 PASS
- [ ] 未 git add/commit/push
```
