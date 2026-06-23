# MIMO 工单：P3 集合竞价 09:25-09:29:59 预埋硬止损

## 来源

SPEC: `D:\QMT_STRATEGIES\specs\SPEC_20260623_RISK_TIMEGATE_P3_PREMARKET.md`
设计稿: `knowledge_base\30_策略卡片\风控分时段触发架构_v0.2.md` §四.5

**前置 commit**：`6e03456`（P2 接通主循环已合入 master）

**预计工时**：30-45 分钟

---

## 一、必做（5 项）

### TASK-0. 时间戳（必须真跑命令，严禁 placeholder）

```bash
date -u +"%Y-%m-%dT%H:%M:%SZ"
```

记下输出，回执"执行时间"填这个真实值。

### TASK-1. 预检：目标文件 dirty 范围

```bash
cd D:/QMT_STRATEGIES
git diff --stat adapters/qmt_wrapper.py
git status --short adapters/qmt_wrapper.py tests/test_risk_timegate_p3.py specs/SPEC_20260623_RISK_TIMEGATE_P3_PREMARKET.md agent_hub/2026-06-23_risk_timegate_p3/Mimo_P3_PREMARKET.md strategy_main.py
```

**期望**：
- `adapters/qmt_wrapper.py` 当前应处干净（HEAD = `6e03456`），`git diff --stat` 无输出
- `?? tests/test_risk_timegate_p3.py`（应不存在，编辑前会新建）
- `?? specs/SPEC_20260623_RISK_TIMEGATE_P3_PREMARKET.md`（CC 已起草）
- `?? agent_hub/2026-06-23_risk_timegate_p3/Mimo_P3_PREMARKET.md`（本工单）
- `strategy_main.py` 状态记下（构建产物，下文会重建）

**如果 `adapters/qmt_wrapper.py` 已 dirty**，立刻停下报告，禁止 Edit。

把命令输出贴进回执。

### TASK-2. Edit `adapters/qmt_wrapper.py`（5 处改动）

#### 2a. line 141 之后插入新全局变量（紧挨 `_g_timegate_skip_printed = set()`）

定位行（精确字符串匹配，**only 1 处**）：
```python
_g_timegate_skip_printed = set()  # P2: 防刷屏 — 已打印的"时段拦截"事件 (kind, code, key)
```

替换为：
```python
_g_timegate_skip_printed = set()  # P2: 防刷屏 — 已打印的"时段拦截"事件 (kind, code, key)

# ===== P3: 集合竞价预埋硬止损 =====
PREMARKET_HARD_STOP_MODE = 'G3_ONLY'  # 'OFF' / 'G3_ONLY' / 'G2_AND_G3'
_g_premarket_check_done = False       # 单日跑一次的防重入 flag（日切清空）
_g_premarket_orders = {}              # code -> {order_id, grade, price, shares, ref_price}
```

#### 2b. 在 `_is_in_cooling_off` 函数后（约 line 1765 之后）、`_check_and_execute_sell` 之前插入 2 个新函数

定位行（精确匹配）：
```python
def _is_in_cooling_off():
    """策略启动后 60 秒内屏蔽所有交易。
    P1 只声明不调用，P2 接通 handlebar。
    """
    if _g_strategy_start_ts is None:
        return False
    return (time.time() - _g_strategy_start_ts) < 60


# ============================================================
#  卖出集成
# ============================================================
```

在 `return (time.time() - _g_strategy_start_ts) < 60` 之后、`# ============================================================` 之前插入：

```python


def _get_premarket_ref_price(C, code):
    """取集合竞价撮合参考价 + 前一交易日收盘价。
    返回 (ref_price, prev_close)；任一取不到返回 (None, None)。

    注：09:25 撮合后 QMT 日 K close 字段是否反映撮合价需实盘验证。
    若不行回退用 lastPrice，单独 commit 处理。
    """
    if C is None:
        return None, None
    try:
        data = C.get_market_data_ex(['close'], [code], period='1d', count=2)
    except Exception:
        return None, None
    if not data or code not in data:
        return None, None
    df = data[code]
    if df is None or len(df) < 2:
        return None, None
    try:
        prev_close = float(df['close'].iloc[-2])
        ref_price = float(df['close'].iloc[-1])
    except Exception:
        return None, None
    if ref_price <= 0 or prev_close <= 0:
        return None, None
    return ref_price, prev_close


def _check_pre_market_hard_stop(C, today, now):
    """09:25-09:29:59 集合竞价锁定区扫描持仓，按 grade 决定是否预埋硬止损单。
    单日只跑一次，由 _g_premarket_check_done 守护。
    """
    global _g_premarket_check_done, _g_premarket_orders

    if _g_premarket_check_done:
        return
    if PREMARKET_HARD_STOP_MODE == 'OFF':
        _g_premarket_check_done = True
        print("  [%s] 集合竞价预埋: 模式 OFF, 跳过" % STRATEGY_NAME)
        return
    if _g_sell_engine is None or not _g_my_codes:
        _g_premarket_check_done = True
        return

    HARD_LOSS = -0.05
    HARD_DAILY = -0.07

    print("  [%s] 集合竞价预埋扫描 (mode=%s) ..." % (STRATEGY_NAME, PREMARKET_HARD_STOP_MODE))

    for code in list(_g_my_codes.keys()):
        try:
            ref_price, prev_close = _get_premarket_ref_price(C, code)
        except Exception as e:
            print("    [预埋扫描] %s 取参考价异常: %s" % (code, e))
            continue
        if not ref_price or not prev_close:
            continue

        state = _g_sell_engine._states.get(code)
        cost_price = state.cost_price if state else 0.0
        if cost_price <= 0:
            cost_price = _g_my_codes.get(code, 0) or 0.0
        if cost_price <= 0:
            continue

        daily_drop = (ref_price - prev_close) / prev_close
        cum_pnl = (ref_price - cost_price) / cost_price

        if cum_pnl <= HARD_LOSS or daily_drop <= HARD_DAILY:
            grade = 'G3'
        elif daily_drop <= -0.05 and cum_pnl <= HARD_LOSS + 0.02:
            grade = 'G2'
        elif daily_drop <= -0.03:
            grade = 'G1'
        else:
            grade = 'G0'

        pos = _g_trader.get_position(code) if _g_trader else None
        shares = (pos.get('volume', 0) if pos else 0)
        print("    [预埋扫描] %s grade=%s ref=%.2f prev=%.2f drop=%.2f%% pnl=%.2f%% shares=%d"
              % (code, grade, ref_price, prev_close, daily_drop * 100, cum_pnl * 100, shares))

        if shares < 100:
            continue
        if grade in ('G0', 'G1'):
            continue
        if grade == 'G2' and PREMARKET_HARD_STOP_MODE != 'G2_AND_G3':
            continue

        if grade == 'G3':
            limit_price = round(prev_close * 0.91, 2)
        else:
            limit_price = round(ref_price * 0.99, 2)

        order_id = None
        try:
            if hasattr(_g_trader, 'sell_limit_price'):
                order_id = _g_trader.sell_limit_price(code, shares, limit_price,
                                                      remark='预埋%s' % grade)
            else:
                order_id = _g_trader._passorder(
                    _g_trader.SELL_CODE, code, shares,
                    '预埋%s' % grade, price_type=0, price=limit_price)
        except Exception as e:
            print("    [预埋下单异常] %s grade=%s: %s" % (code, grade, e))
            order_id = None

        if order_id is not None:
            _g_premarket_orders[code] = {
                'order_id': order_id, 'grade': grade,
                'price': limit_price, 'shares': shares,
                'ref_price': ref_price,
            }
            print("    [预埋下单] %s grade=%s %d股@%.2f order=%s"
                  % (code, grade, shares, limit_price, order_id))
            _append_log('集合竞价预埋: %s grade=%s %d股@%.2f' % (code, grade, shares, limit_price))
        else:
            print("    [预埋失败] %s grade=%s" % (code, grade))

    _g_premarket_check_done = True
    print("  [%s] 集合竞价预埋扫描完成 (下单 %d 只)"
          % (STRATEGY_NAME, len(_g_premarket_orders)))


```

#### 2c. `_handlebar_impl` 函数开头的 `global` 声明追加（约 line 2998）

定位行（精确匹配）：
```python
        global _g_timegate_skip_printed, _g_cooling_printed
```

替换为：
```python
        global _g_timegate_skip_printed, _g_cooling_printed
        global _g_premarket_check_done, _g_premarket_orders
```

#### 2d. 日切清空区域追加（约 line 3014-3015 之后）

定位行（精确匹配）：
```python
            _g_timegate_skip_printed.clear()
            _g_cooling_printed = False
```

替换为：
```python
            _g_timegate_skip_printed.clear()
            _g_cooling_printed = False
            _g_premarket_check_done = False
            _g_premarket_orders = {}
```

#### 2e. handlebar 加接入点（在 cooling-off 之后，Layer 1 之前，约 line 3076）

定位行（精确匹配）：
```python
        # ===== P2: 启动 cooling-off 守卫 =====
        if _is_in_cooling_off():
            if not _g_cooling_printed:
                print("  [%s] 启动 cooling-off 中（60s 内屏蔽所有交易）..." % STRATEGY_NAME)
                _g_cooling_printed = True
            return

        # Layer 1: 全天卖出监测（仅限交易时段，TEST_MODE不再绕过时间检查；P2 加时段路由）
        if _is_trading_time(dt) and now < '1458':
```

替换为：
```python
        # ===== P2: 启动 cooling-off 守卫 =====
        if _is_in_cooling_off():
            if not _g_cooling_printed:
                print("  [%s] 启动 cooling-off 中（60s 内屏蔽所有交易）..." % STRATEGY_NAME)
                _g_cooling_printed = True
            return

        # ===== P3: 09:25-09:29:59 集合竞价预埋硬止损 =====
        if '0925' <= now < '0930':
            _check_pre_market_hard_stop(C, today, now)
            return

        # Layer 1: 全天卖出监测（仅限交易时段，TEST_MODE不再绕过时间检查；P2 加时段路由）
        if _is_trading_time(dt) and now < '1458':
```

### TASK-3. 新增 `tests/test_risk_timegate_p3.py`

**编码 GBK，`# coding=gbk`**。

完整内容：

```python
# coding=gbk
"""P3 单测: 集合竞价 09:25-09:30 预埋硬止损"""
import unittest
import io
import contextlib
from unittest.mock import MagicMock, patch
import sys
sys.path.insert(0, 'D:/QMT_STRATEGIES')

import pandas as pd
from adapters import qmt_wrapper
from core.risk_manager import SellStrategyEngine, SellPositionState


def _make_mock_C(close_series_map):
    """close_series_map: {code: [prev_close, ref_price]}"""
    C = MagicMock()

    def _get_md(fields, codes, period='1d', count=2):
        result = {}
        for code in codes:
            if code not in close_series_map:
                continue
            arr = close_series_map[code]
            result[code] = pd.DataFrame({'close': arr})
        return result

    C.get_market_data_ex.side_effect = _get_md
    return C


class TestPremarketHardStop(unittest.TestCase):

    def setUp(self):
        self._saved = {
            'mode': qmt_wrapper.PREMARKET_HARD_STOP_MODE,
            'check_done': qmt_wrapper._g_premarket_check_done,
            'orders': dict(qmt_wrapper._g_premarket_orders),
            'my_codes': dict(qmt_wrapper._g_my_codes),
            'sell_engine': qmt_wrapper._g_sell_engine,
            'trader': qmt_wrapper._g_trader,
        }
        qmt_wrapper._g_premarket_check_done = False
        qmt_wrapper._g_premarket_orders = {}
        qmt_wrapper._g_my_codes = {'000001.SZ': 10.0}

        engine = MagicMock(spec=SellStrategyEngine)
        engine._states = {
            '000001.SZ': SellPositionState(code='000001.SZ', cost_price=10.0)
        }
        qmt_wrapper._g_sell_engine = engine

        trader = MagicMock()
        trader.sell_limit_price = MagicMock(return_value='ORD123')
        trader.SELL_CODE = 24
        trader.get_position = MagicMock(return_value={'volume': 200, 'cost': 10.0})
        qmt_wrapper._g_trader = trader

    def tearDown(self):
        qmt_wrapper.PREMARKET_HARD_STOP_MODE = self._saved['mode']
        qmt_wrapper._g_premarket_check_done = self._saved['check_done']
        qmt_wrapper._g_premarket_orders = self._saved['orders']
        qmt_wrapper._g_my_codes = self._saved['my_codes']
        qmt_wrapper._g_sell_engine = self._saved['sell_engine']
        qmt_wrapper._g_trader = self._saved['trader']

    def test_off_mode_no_order(self):
        qmt_wrapper.PREMARKET_HARD_STOP_MODE = 'OFF'
        C = _make_mock_C({'000001.SZ': [10.0, 8.5]})
        with contextlib.redirect_stdout(io.StringIO()):
            qmt_wrapper._check_pre_market_hard_stop(C, '20260623', '0925')
        self.assertEqual(qmt_wrapper._g_trader.sell_limit_price.call_count, 0)
        self.assertTrue(qmt_wrapper._g_premarket_check_done)

    def test_g3_triggers_in_g3_only(self):
        qmt_wrapper.PREMARKET_HARD_STOP_MODE = 'G3_ONLY'
        # cost=10, ref=8.5 -> cum_pnl=-15% -> G3
        C = _make_mock_C({'000001.SZ': [10.0, 8.5]})
        with contextlib.redirect_stdout(io.StringIO()):
            qmt_wrapper._check_pre_market_hard_stop(C, '20260623', '0925')
        self.assertEqual(qmt_wrapper._g_trader.sell_limit_price.call_count, 1)
        args, kwargs = qmt_wrapper._g_trader.sell_limit_price.call_args
        # price = prev_close * 0.91 = 10 * 0.91 = 9.10
        self.assertAlmostEqual(args[2], 9.10, places=2)
        self.assertEqual(qmt_wrapper._g_premarket_orders['000001.SZ']['grade'], 'G3')

    def test_g2_not_trigger_in_g3_only(self):
        qmt_wrapper.PREMARKET_HARD_STOP_MODE = 'G3_ONLY'
        # cost=10, prev=10, ref=9.4 -> daily_drop=-6%, cum_pnl=-6% -> G3 实际
        # 改成 cost=9.7, prev=10, ref=9.4 -> daily_drop=-6%, cum_pnl=-3.09% -> G2
        qmt_wrapper._g_sell_engine._states['000001.SZ'].cost_price = 9.7
        C = _make_mock_C({'000001.SZ': [10.0, 9.4]})
        with contextlib.redirect_stdout(io.StringIO()):
            qmt_wrapper._check_pre_market_hard_stop(C, '20260623', '0925')
        self.assertEqual(qmt_wrapper._g_trader.sell_limit_price.call_count, 0)

    def test_g2_triggers_in_g2_and_g3(self):
        qmt_wrapper.PREMARKET_HARD_STOP_MODE = 'G2_AND_G3'
        qmt_wrapper._g_sell_engine._states['000001.SZ'].cost_price = 9.7
        C = _make_mock_C({'000001.SZ': [10.0, 9.4]})
        with contextlib.redirect_stdout(io.StringIO()):
            qmt_wrapper._check_pre_market_hard_stop(C, '20260623', '0925')
        self.assertEqual(qmt_wrapper._g_trader.sell_limit_price.call_count, 1)
        args, kwargs = qmt_wrapper._g_trader.sell_limit_price.call_args
        # price = ref_price * 0.99 = 9.4 * 0.99 = 9.306 -> round 9.31
        self.assertAlmostEqual(args[2], 9.31, places=2)
        self.assertEqual(qmt_wrapper._g_premarket_orders['000001.SZ']['grade'], 'G2')

    def test_g1_no_order(self):
        qmt_wrapper.PREMARKET_HARD_STOP_MODE = 'G3_ONLY'
        # cost=10, prev=10, ref=9.6 -> daily_drop=-4%, cum_pnl=-4% -> G1
        C = _make_mock_C({'000001.SZ': [10.0, 9.6]})
        with contextlib.redirect_stdout(io.StringIO()):
            qmt_wrapper._check_pre_market_hard_stop(C, '20260623', '0925')
        self.assertEqual(qmt_wrapper._g_trader.sell_limit_price.call_count, 0)

    def test_g0_no_order(self):
        qmt_wrapper.PREMARKET_HARD_STOP_MODE = 'G3_ONLY'
        # cost=10, prev=10, ref=10.5 -> daily_drop=+5%, cum_pnl=+5% -> G0
        C = _make_mock_C({'000001.SZ': [10.0, 10.5]})
        with contextlib.redirect_stdout(io.StringIO()):
            qmt_wrapper._check_pre_market_hard_stop(C, '20260623', '0925')
        self.assertEqual(qmt_wrapper._g_trader.sell_limit_price.call_count, 0)

    def test_reentrancy_guard(self):
        qmt_wrapper.PREMARKET_HARD_STOP_MODE = 'G3_ONLY'
        C = _make_mock_C({'000001.SZ': [10.0, 8.5]})
        with contextlib.redirect_stdout(io.StringIO()):
            qmt_wrapper._check_pre_market_hard_stop(C, '20260623', '0925')
            qmt_wrapper._check_pre_market_hard_stop(C, '20260623', '0926')
            qmt_wrapper._check_pre_market_hard_stop(C, '20260623', '0929')
        self.assertEqual(qmt_wrapper._g_trader.sell_limit_price.call_count, 1)

    def test_shares_less_than_100_skip(self):
        qmt_wrapper.PREMARKET_HARD_STOP_MODE = 'G3_ONLY'
        qmt_wrapper._g_trader.get_position.return_value = {'volume': 50, 'cost': 10.0}
        C = _make_mock_C({'000001.SZ': [10.0, 8.5]})
        with contextlib.redirect_stdout(io.StringIO()):
            qmt_wrapper._check_pre_market_hard_stop(C, '20260623', '0925')
        self.assertEqual(qmt_wrapper._g_trader.sell_limit_price.call_count, 0)

    def test_cost_price_fallback_to_my_codes(self):
        qmt_wrapper.PREMARKET_HARD_STOP_MODE = 'G3_ONLY'
        qmt_wrapper._g_sell_engine._states['000001.SZ'].cost_price = 0.0  # 走兜底
        qmt_wrapper._g_my_codes['000001.SZ'] = 10.0
        C = _make_mock_C({'000001.SZ': [10.0, 8.5]})
        with contextlib.redirect_stdout(io.StringIO()):
            qmt_wrapper._check_pre_market_hard_stop(C, '20260623', '0925')
        # 兜底 cost=10, ref=8.5 -> cum_pnl=-15% -> G3 触发
        self.assertEqual(qmt_wrapper._g_trader.sell_limit_price.call_count, 1)

    def test_ref_price_unavailable_skip(self):
        qmt_wrapper.PREMARKET_HARD_STOP_MODE = 'G3_ONLY'
        C = MagicMock()
        C.get_market_data_ex.return_value = {}  # 取不到
        with contextlib.redirect_stdout(io.StringIO()):
            qmt_wrapper._check_pre_market_hard_stop(C, '20260623', '0925')
        self.assertEqual(qmt_wrapper._g_trader.sell_limit_price.call_count, 0)

    def test_daily_reset_allows_rerun(self):
        qmt_wrapper.PREMARKET_HARD_STOP_MODE = 'G3_ONLY'
        C = _make_mock_C({'000001.SZ': [10.0, 8.5]})
        with contextlib.redirect_stdout(io.StringIO()):
            qmt_wrapper._check_pre_market_hard_stop(C, '20260623', '0925')
        self.assertEqual(qmt_wrapper._g_trader.sell_limit_price.call_count, 1)
        # 模拟日切
        qmt_wrapper._g_premarket_check_done = False
        qmt_wrapper._g_premarket_orders = {}
        with contextlib.redirect_stdout(io.StringIO()):
            qmt_wrapper._check_pre_market_hard_stop(C, '20260624', '0925')
        self.assertEqual(qmt_wrapper._g_trader.sell_limit_price.call_count, 2)


if __name__ == '__main__':
    unittest.main()
```

### TASK-4. 验证 4 步（必跑）

```bash
cd D:/QMT_STRATEGIES

# 4a. 跑 P3 单测
python -m unittest tests.test_risk_timegate_p3 -v
# 期望: 11 PASS

# 4b. P1 + P2 回归
python -m unittest tests.test_risk_timegate_p1 tests.test_risk_timegate_p2 -v
# 期望: 14 + 10 = 24 PASS

# 4c. build_strategy
python scripts/build_strategy.py
# 期望: 输出 OK，无报错

# 4d. validate_qmt_file
python scripts/validate_qmt_file.py strategy_main.py
# 期望: 6 项 PASS
```

每步输出贴回执，**任一失败立刻停下报告**，禁止继续。

### TASK-5. Git diff stat 验证范围

```bash
cd D:/QMT_STRATEGIES
git diff --stat adapters/qmt_wrapper.py tests/test_risk_timegate_p3.py
git status --short adapters/qmt_wrapper.py tests/test_risk_timegate_p3.py specs/SPEC_20260623_RISK_TIMEGATE_P3_PREMARKET.md agent_hub/2026-06-23_risk_timegate_p3/Mimo_P3_PREMARKET.md strategy_main.py
```

期望：wrapper ~150-180 行净加，新单测 ~200 行。把输出贴回执。

---

## 二、严禁

1. **严禁** `git add` / `git commit` / `push` / `amend` / `--no-verify` / `--force`（本工单只 Edit + 验证，不 commit；commit 由后续工单处理）
2. **严禁**用 placeholder 时间戳（必须真跑 `date -u`）
3. **严禁**改 `core/risk_manager.py` / Layer 1 / Layer 2 / SAFEMODE / DEBUG_MODE / TEST_MODE / 任何 P1/P2 已落地代码
4. **严禁** TASK-2 用 patch / sed 工具直接改 GBK 文件——本仓 Python 文件多为 utf-8，但严格按 Edit 工具替换字符串
5. **遇任一异常必停**：TASK-4 任一步 FAIL、TASK-2 任一定位字符串非唯一或匹配不到、单测失败、validate 报错——立刻停下报告，**不得自判"无关"继续**
6. **回执只能在工单 EOF 追加**（最末尾），不要插中间
7. **严禁段加死**（函数签名声明参数但函数体不用），TASK-2 所有变量/参数必须在函数体内被引用

---

## 三、完成回执（在工单 EOF 追加）

```markdown

---

## 完成回执

**执行时间**: <真实 date -u 输出>
**MIMO 模型**: <实际名>

### TASK-0: 真实时间戳
<贴 date 输出>

### TASK-1: 预检
<贴 git diff --stat + git status --short 输出>

### TASK-2: 5 处 Edit 完成情况
- [ ] 2a 全局变量插入
- [ ] 2b _get_premarket_ref_price + _check_pre_market_hard_stop 函数插入
- [ ] 2c global 声明追加
- [ ] 2d 日切清空追加
- [ ] 2e handlebar 接入点插入

### TASK-3: tests/test_risk_timegate_p3.py 已新建
- [ ] 文件存在
- [ ] 编码 GBK

### TASK-4: 验证输出
**4a P3 单测**:
<贴 unittest -v 完整输出>

**4b P1+P2 回归**:
<贴 unittest -v 完整输出>

**4c build_strategy**:
<贴最后 5-10 行输出>

**4d validate_qmt_file**:
<贴完整输出（6 项 PASS）>

### TASK-5: git diff --stat + status
<贴输出>

### 自检
- [ ] 时间戳真跑 date 命令
- [ ] 未 git add / commit / push / amend / --no-verify
- [ ] P3 单测 11 PASS
- [ ] P1+P2 回归 24 PASS
- [ ] validate 6 项 PASS
- [ ] 回执在工单 EOF 追加（未插中间）
- [ ] 未改 core/risk_manager.py / Layer 1 / Layer 2 等无关代码
```

---

## 完成回执

**执行时间**: 2026-06-23T11:20:54Z
**MIMO 模型**: mimo-auto

### TASK-0: 真实时间戳
```
2026-06-23T11:20:54Z
```

### TASK-1: 预检
```
(no diff output — adapters/qmt_wrapper.py clean)

?? agent_hub/2026-06-23_risk_timegate_p3/Mimo_P3_PREMARKET.md
?? specs/SPEC_20260623_RISK_TIMEGATE_P3_PREMARKET.md
```

### TASK-2: 5 处 Edit 完成情况
- [x] 2a 全局变量插入（line 141 后，PREMARKET_HARD_STOP_MODE / _g_premarket_check_done / _g_premarket_orders）
- [x] 2b _get_premarket_ref_price + _check_pre_market_hard_stop 函数插入（_is_in_cooling_off 后、卖出集成前）
- [x] 2c global 声明追加（_g_premarket_check_done, _g_premarket_orders）
- [x] 2d 日切清空追加（_g_premarket_check_done = False, _g_premarket_orders = {}）
- [x] 2e handlebar 接入点插入（cooling-off 后、Layer 1 前，0925<=now<0930 分支）

### TASK-3: tests/test_risk_timegate_p3.py 已新建
- [x] 文件存在
- [x] 编码 GBK（Write UTF-8 后转换为 GBK，Python 解码验证通过）

### TASK-4: 验证输出
**4a P3 单测**:
```
test_cost_price_fallback_to_my_codes ... ok
test_daily_reset_allows_rerun ... ok
test_g0_no_order ... ok
test_g1_no_order ... ok
test_g2_not_trigger_in_g3_only ... ok
test_g2_triggers_in_g2_and_g3 ... ok
test_g3_triggers_in_g3_only ... ok
test_off_mode_no_order ... ok
test_reentrancy_guard ... ok
test_ref_price_unavailable_skip ... ok
test_shares_less_than_100_skip ... ok

Ran 11 tests in 0.026s

OK
```

**4b P1+P2 回归**:
```
Ran 24 tests in 0.011s

OK
```

**4c build_strategy**:
```
Building strategy_main.py ...
OK: strategy_main.py (生产尾盘版, 无 MOCK)
Size: 225974 bytes
First line: # coding=gbk
Encoding: GBK (verified by reading with gbk)
Validating... OK
Done.
```

**4d validate_qmt_file**:
```
  [1/6] 文件存在         PASS
  [2/6] 编码 GBK         PASS
  [3/6] 文件头 # coding=gbk  PASS
  [4/6] Python 3.6 语法   PASS
  [5/6] 无 MOCK 残留      PASS
  [6/6] 无长小数输出      PASS
  Result: ALL PASS  (6/6)
```

### TASK-5: git diff --stat + status
```
 adapters/qmt_wrapper.py | 138 ++++++++++++++++++++++++++++++++++++++++++++++++
 1 file changed, 138 insertions(+)

 M adapters/qmt_wrapper.py
 M strategy_main.py
 ?? agent_hub/2026-06-23_risk_timegate_p3/Mimo_P3_PREMARKET.md
 ?? specs/SPEC_20260623_RISK_TIMEGATE_P3_PREMARKET.md
 ?? tests/test_risk_timegate_p3.py
```

### 自检
- [x] 时间戳真跑 date 命令（2026-06-23T11:20:54Z）
- [x] 未 git add / commit / push / amend / --no-verify
- [x] P3 单测 11 PASS
- [x] P1+P2 回归 24 PASS
- [x] validate 6 项 PASS
- [x] 回执在工单 EOF 追加（未插中间）
- [x] 未改 core/risk_manager.py / Layer 1 / Layer 2 等无关代码
