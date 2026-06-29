# MIMO_TODO_v5：最小委托量修复验收尾巴（代码识别/跌停零股/测试全绿）

**日期**: 2026-06-29
**作者**: CC
**目的**: 修正 v4 最小委托量实现中的验收尾巴：科创板代码识别需兼容 `SH688396`，预埋/跌停路径需允许不足 200 的剩余仓位一次性卖，相关测试需全绿。
**预计工时**: ≤ 45 分钟

---

## 一、v4 验收发现的问题

v4 已做了主要功能，但 CC 验收发现 3 个尾巴：

1. `_is_star_market_stock(code)` 只做 `code.split('.')[0]`，可识别 `688396.SH`，但不能识别 QMT 常见格式 `SH688396`。
2. `_check_pre_market_hard_stop()` 和 `_check_limitdown_sells()` 用 `sell_vol >= _min_sell_volume_for_board(code)` 判断，这会阻止 `available < 200` 的科创板剩余仓位一次性卖出；与 v4 规则“可用 <200 时一次性卖剩余”矛盾。
3. `tests/test_sell_retry.py` 仍有 2 个 `TestTraderSellMarketMode` 失败，原因是 sell() 已接入订单反查后测试未 mock `get_trade_detail_data`。这个现在不是“无关历史失败”，应该顺手修测试夹具，让 `tests/test_sell_retry.py tests/test_order_lookup.py` 全绿。

---

## 二、必做（5 项）

### TASK-1. 修正科创板代码识别

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`

要求 `_is_star_market_stock(code)` 至少兼容：

- `688396.SH`
- `689009.SH`
- `SH688396`
- `SH689009`
- `688396`

建议实现：

```python
def _stock_code_digits(code):
    base = str(code).upper()
    if '.' in base:
        base = base.split('.')[0]
    if base.startswith('SH') or base.startswith('SZ'):
        base = base[2:]
    return base
```

然后判断 `688/689`。

### TASK-2. 修正预埋/跌停路径不足最低量剩余仓位处理

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`

要求：

1. `_check_pre_market_hard_stop()`：不要用 `shares < _min_sell_volume_for_board(code)` 直接过滤；应使用 `_normalize_sell_volume_for_board(code, shares, shares, True)` 或等价逻辑。
   - 如果返回 `<=0` 才跳过。
   - 下单量、记录量、日志量使用修正后的 sell_vol。

2. `_check_limitdown_sells()` 两处：
   - `sell_vol = _normalize_sell_volume_for_board(..., is_clear=True)` 后，判断应为 `sell_vol > 0`，不要再要求 `>= _min_sell_volume_for_board(code)`。
   - 这样科创板 available=100 的剩余仓位可以一次性卖。

### TASK-3. 修正/补充测试

**目标路径**: `D:/QMT_STRATEGIES/tests/test_sell_retry.py`

要求：

1. 给 `TestTraderSellMarketMode` 两个测试补 `get_trade_detail_data` mock，使其符合当前 sell() 反查行为，并全绿。
   - 可 mock 为返回匹配订单，`m_nOrderID='fake_id'` 或等价；注意 `Trader.sell()` 最终返回 `_lookup_recent_order_id` 的结果。
   - 不要改业务预期为 `None`。

2. 增加 `_is_star_market_stock('SH688396') is True` / `SH689009` 的测试。

3. 增加预埋/跌停规则至少 helper 层面的测试，确认：
   - `_normalize_sell_volume_for_board('SH688396', 100, 300, False) == 200`
   - `_normalize_sell_volume_for_board('SH688396', 100, 100, False) == 100`

如时间足够，再补 `_check_limitdown_sells` 行为测试；否则 helper 覆盖 + 代码审查说明也可。

### TASK-4. 复跑验证

运行：

```bash
"C:/Users/Administrator/AppData/Local/Programs/Python/Python310/python.exe" -m pytest tests/test_sell_retry.py tests/test_order_lookup.py -q
"C:/Users/Administrator/AppData/Local/Programs/Python/Python310/python.exe" scripts/build_strategy.py
"C:/Users/Administrator/AppData/Local/Programs/Python/Python310/python.exe" scripts/build_strategy.py --allday
"C:/Users/Administrator/AppData/Local/Programs/Python/Python310/python.exe" scripts/validate_qmt_file.py strategy_main.py
```

要求：
- `tests/test_sell_retry.py tests/test_order_lookup.py` 必须全绿；不要再留下 2 failed。
- build OK。
- validate 6/6 PASS。

### TASK-5. 写回执

在本文件末尾追加回执，写清：
- 修了哪些尾巴；
- 相关测试是否全绿；
- 构建/验证结果；
- 是否未 git add/commit/push。

---

## 三、严禁

1. 禁止 git add / commit / push。
2. 禁止改 release、QMT 日志、D:/QMT_POOL、QMT 安装目录。
3. 禁止改订单反查 v1 逻辑，除非测试 mock 必须适配当前行为。
4. 禁止整文件行尾转换造成巨大 diff。
5. 禁止直接手改 `strategy_main.py` / `strategy_allday.py`；只能 build 生成。
6. 遇异常必须停下写明。

---

## 四、完成回执（MIMO 在工单末尾追加）

## 完成回执

**执行时间**: 2026-06-29T16:45:00Z
**MIMO 模型**: mimo-auto
**改动文件**:
- `adapters/qmt_wrapper.py`: 修正 `_is_star_market_stock` 兼容 SH688396/SH689009 格式；修正 `_check_pre_market_hard_stop` 用 `_normalize_sell_volume_for_board` 替代 min volume 硬过滤，允许不足最低量剩余仓位一次性卖出；修正 `_check_limitdown_sells` 两处 `sell_vol >= _min_sell_volume_for_board` → `sell_vol > 0`
- `tests/test_sell_retry.py`: 为 `TestTraderSellMarketMode` 补 `get_trade_detail_data` mock（返回匹配 FakeOrder）；新增 `TestIsStarMarketStock` 6 个用例（SH688396/SH689009/688396.SH/688396/600641.SH/000001.SZ）；新增 3 个 SH688396 格式的 `_normalize_sell_volume_for_board` 测试
**验证命令与结果**:
- `pytest tests/test_sell_retry.py tests/test_order_lookup.py -q` → PASS 39 passed
- `python scripts/build_strategy.py` → OK strategy_main.py 236066 bytes GBK
- `python scripts/build_strategy.py --allday` → OK strategy_allday.py 236035 bytes GBK
- `python scripts/validate_qmt_file.py strategy_main.py` → PASS 6/6
**自检**:
- [x] SH688396 / SH689009 可识别为科创板
- [x] 科创板 available<200 剩余仓位可一次性卖出，不被预埋/跌停路径拦掉
- [x] TestTraderSellMarketMode 已按订单反查行为 mock，全绿
- [x] tests/test_sell_retry.py tests/test_order_lookup.py 全绿
- [x] build_strategy.py / --allday OK
- [x] validate_qmt_file.py strategy_main.py 6/6 PASS
- [x] 未 git add/commit/push
