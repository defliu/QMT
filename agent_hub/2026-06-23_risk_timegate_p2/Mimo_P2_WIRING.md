# MIMO 工单：P2 接通主循环 — handlebar 加 cooling-off + 时段路由

## 来源

SPEC: `D:\QMT_STRATEGIES\specs\SPEC_20260623_RISK_TIMEGATE_P2_WIRING.md`
设计稿: `knowledge_base\30_策略卡片\风控分时段触发架构_v0.2.md`
P1 commit: `364afda` (基础设施已落仓)

## 必做（4 项）

### TASK-0. 时间戳 + 预检

```bash
date -u +"%Y-%m-%dT%H:%M:%SZ"     # 记下输出, 回执"执行时间"填这个真实值
cd D:/QMT_STRATEGIES
git diff --stat adapters/qmt_wrapper.py
```

**预检期望**：`adapters/qmt_wrapper.py` 的 `git diff --stat` 应为空（无输出）——P1 已落仓，工作区干净。

如果有输出（说明工作区已 dirty），**立刻停下报告**，禁止 Edit。

把命令输出（即使为空也写"无输出"）贴进回执。

### TASK-1. `adapters/qmt_wrapper.py` 改动（5 块）

**1a. 新增 2 个全局变量**（约 line 139, 紧贴 `_g_strategy_start_ts` 之后）

```python
_g_cooling_printed = False        # P2: cooling-off 首次提示防刷屏
_g_timegate_skip_printed = set()  # P2: 防刷屏 — 已打印的"时段拦截"事件 (kind, code, key)
```

**1b. `_check_and_execute_sell` 加 `allowed_layers` 参数**（约 line 1769）

修改函数签名 + 在 `raw_decisions = ... evaluate(...)` 后、`if raw_decisions:` 防刷屏块之前，插入时段过滤逻辑。

改前：
```python
def _check_and_execute_sell(C, today):
    global _g_sell_engine, _g_pending_sells, _g_last_sell_fingerprint, _g_sell_skip_printed, _g_failed_printed
    ...
    raw_decisions = _g_sell_engine.evaluate(today, _g_my_codes, _g_all_data, positions_data, rt_prices)

    # 防刷屏：卖出决策变化时才打印诊断表
    if raw_decisions:
```

改后：
```python
def _check_and_execute_sell(C, today, allowed_layers=None):
    global _g_sell_engine, _g_pending_sells, _g_last_sell_fingerprint, _g_sell_skip_printed, _g_failed_printed
    global _g_timegate_skip_printed
    ...
    raw_decisions = _g_sell_engine.evaluate(today, _g_my_codes, _g_all_data, positions_data, rt_prices)

    # ===== P2: 时段路由过滤 =====
    if allowed_layers is not None:
        layers_set = allowed_layers.get('layers', set())
        exclude_subs = allowed_layers.get('exclude_sublayers', set())
        filtered = []
        for code, dec, shares in raw_decisions:
            if dec.triggered_layer not in layers_set:
                skey = ('layer', code, dec.triggered_layer)
                if skey not in _g_timegate_skip_printed:
                    _g_timegate_skip_printed.add(skey)
                    print("  [时段拦截] %s reason=%s layer=%s 不在 %s 允许范围"
                          % (code, dec.reason, dec.triggered_layer, sorted(layers_set)))
                continue
            sub = getattr(dec, 'triggered_sublayer', None)
            if sub and sub in exclude_subs:
                skey = ('sublayer', code, sub)
                if skey not in _g_timegate_skip_printed:
                    _g_timegate_skip_printed.add(skey)
                    print("  [时段拦截|sublayer] %s reason=%s sublayer=%s 在 %s 排除列表"
                          % (code, dec.reason, sub, sorted(exclude_subs)))
                continue
            filtered.append((code, dec, shares))
        raw_decisions = filtered

    # 防刷屏：卖出决策变化时才打印诊断表
    if raw_decisions:
```

**1c. `_handlebar_impl` 加 global 声明 + 日切清空**（约 line 2967-2970）

在 `global _g_op_executed, _g_startup_done, _g_all_data, _g_index_data, _g_last_sell_fingerprint` 这一行后面**加新行**：

```python
        global _g_timegate_skip_printed, _g_cooling_printed
```

在日切区域（约 line 2985, `_g_last_sell_fingerprint = ''` 之后）**加 2 行**：

```python
            _g_timegate_skip_printed.clear()
            _g_cooling_printed = False
```

**1d. cooling-off 守卫 + 时段路由调用**（约 line 3038-3045）

找到 SAFEMODE 分支末尾的 `return` 之后、Layer 1 `if _is_trading_time(dt) and now < '1458':` 之前，插入 cooling-off 守卫块。
然后把 Layer 1 内的 `_check_and_execute_sell(C, today)` 改成传 `allowed_layers`。

改前：
```python
            print("[SAFEMODE] %s 信号计算完成（只读），跳过所有交易执行" % today)
            return

        # Layer 1: 全天卖出监测（仅限交易时段，TEST_MODE不再绕过时间检查）
        if _is_trading_time(dt) and now < '1458':
            _check_pending_sells(C, today)
            _check_limitdown_sells(C, today)
            if _g_my_codes:
                _check_and_execute_sell(C, today)
        elif now >= '1458':
```

改后：
```python
            print("[SAFEMODE] %s 信号计算完成（只读），跳过所有交易执行" % today)
            return

        # ===== P2: 启动 cooling-off 守卫 =====
        if _is_in_cooling_off():
            if not _g_cooling_printed:
                print("  [%s] 启动 cooling-off 中（60s 内屏蔽所有交易）..." % STRATEGY_NAME)
                _g_cooling_printed = True
            return

        # Layer 1: 全天卖出监测（仅限交易时段，TEST_MODE不再绕过时间检查；P2 加时段路由）
        if _is_trading_time(dt) and now < '1458':
            _check_pending_sells(C, today)
            _check_limitdown_sells(C, today)
            if _g_my_codes:
                allowed = _get_allowed_sell_layers(now)
                if allowed['layers']:
                    _check_and_execute_sell(C, today, allowed_layers=allowed)
                # 注：limitdown_sells 不受时段路由限制（已挂出的撤单/重发不阻断）
        elif now >= '1458':
```

### TASK-2. 新增单测文件 `tests/test_risk_timegate_p2.py`

编码 `# coding=gbk`。内容如下（直接 Write）：

```python
# coding=gbk
"""P2 接通主循环：cooling-off + 时段路由 + 防刷屏 log"""
import unittest
import time
import io
import contextlib
from unittest.mock import patch, MagicMock

from core.risk_manager import SellDecision, Action
from adapters import qmt_wrapper


def _make_decision(code, layer, reason='test', sublayer=None):
    """构造一个 CLEAR 决策（清仓层用）或 REDUCE 决策（其它层用）"""
    if layer == '底线层' or layer == '清仓层':
        return SellDecision.clear(code, reason, layer, [reason], sublayer=sublayer)
    return SellDecision.reduce(code, 0.3, reason, layer, [reason])


class TestAllowedLayersFiltering(unittest.TestCase):
    """验证 _check_and_execute_sell 的 allowed_layers 过滤逻辑"""

    def setUp(self):
        qmt_wrapper._g_timegate_skip_printed.clear()
        self._saved_engine = qmt_wrapper._g_sell_engine
        self._saved_trader = qmt_wrapper._g_trader
        self._saved_codes = qmt_wrapper._g_my_codes
        self._saved_all_data = qmt_wrapper._g_all_data
        self._saved_fp = qmt_wrapper._g_last_sell_fingerprint
        # 隔离卖出链路的全局状态
        self._saved_pending = dict(qmt_wrapper._g_pending_sells)
        self._saved_skip = set(qmt_wrapper._g_sell_skip_printed)
        self._saved_price_skip = set(qmt_wrapper._g_price_skip_printed)
        self._saved_failed_printed = set(qmt_wrapper._g_failed_printed)
        self._saved_fail_cool = dict(qmt_wrapper._g_sell_fail_cooldown)
        qmt_wrapper._g_pending_sells.clear()
        qmt_wrapper._g_sell_skip_printed.clear()
        qmt_wrapper._g_price_skip_printed.clear()
        qmt_wrapper._g_failed_printed.clear()
        qmt_wrapper._g_sell_fail_cooldown.clear()

    def tearDown(self):
        qmt_wrapper._g_sell_engine = self._saved_engine
        qmt_wrapper._g_trader = self._saved_trader
        qmt_wrapper._g_my_codes = self._saved_codes
        qmt_wrapper._g_all_data = self._saved_all_data
        qmt_wrapper._g_last_sell_fingerprint = self._saved_fp
        qmt_wrapper._g_pending_sells.clear()
        qmt_wrapper._g_pending_sells.update(self._saved_pending)
        qmt_wrapper._g_sell_skip_printed.clear()
        qmt_wrapper._g_sell_skip_printed.update(self._saved_skip)
        qmt_wrapper._g_price_skip_printed.clear()
        qmt_wrapper._g_price_skip_printed.update(self._saved_price_skip)
        qmt_wrapper._g_failed_printed.clear()
        qmt_wrapper._g_failed_printed.update(self._saved_failed_printed)
        qmt_wrapper._g_sell_fail_cooldown.clear()
        qmt_wrapper._g_sell_fail_cooldown.update(self._saved_fail_cool)
        qmt_wrapper._g_timegate_skip_printed.clear()

    def _run_with_mock_engine(self, decisions, allowed_layers):
        """跑 _check_and_execute_sell + 返回 (sells, captured_stdout)。
        实际下单链路：_g_trader.sell(code, shares, remark=...) 返回 order_id（数字）或 None。
        这里 mock 返回 None 让函数走"失败"分支，避免触碰 _g_pending_sells / _g_sell_engine._states。
        """
        engine = MagicMock()
        engine.evaluate.return_value = [(code, dec, 100) for code, dec in decisions]
        engine._states = {}
        trader = MagicMock()
        trader.get_position.return_value = {'code': '000001.SZ', 'available': 100, 'volume': 100}
        trader.sell.return_value = None   # 让 sell 路径走"失败"分支，避免污染状态机
        qmt_wrapper._g_sell_engine = engine
        qmt_wrapper._g_trader = trader
        qmt_wrapper._g_my_codes = {code: {} for code, _ in decisions}
        qmt_wrapper._g_all_data = {code: MagicMock() for code, _ in decisions}

        buf = io.StringIO()
        with patch.object(qmt_wrapper, '_get_current_prices', return_value={code: 10.0 for code, _ in decisions}):
            with patch.object(qmt_wrapper, '_get_current_price', return_value=10.0):
                with patch.object(qmt_wrapper, 'print_sell_diagnostics'):
                    with contextlib.redirect_stdout(buf):
                        sells = qmt_wrapper._check_and_execute_sell(MagicMock(), '20260623', allowed_layers=allowed_layers)
        return sells, buf.getvalue()

    def test_whitelist_pass(self):
        """底线层决策 + 允许底线层 → 通过（无拦截 log）"""
        dec = _make_decision('000001.SZ', '底线层')
        allowed = {'layers': {'底线层'}, 'exclude_sublayers': set()}
        sells, out = self._run_with_mock_engine([('000001.SZ', dec)], allowed)
        self.assertNotIn('[时段拦截]', out)

    def test_whitelist_block(self):
        """预警层决策 + 只允许底线层 → 拦截"""
        dec = _make_decision('000002.SZ', '预警层')
        allowed = {'layers': {'底线层'}, 'exclude_sublayers': set()}
        sells, out = self._run_with_mock_engine([('000002.SZ', dec)], allowed)
        self.assertIn('[时段拦截]', out)
        self.assertIn('预警层', out)

    def test_sublayer_block_trailing(self):
        """清仓层 trailing 决策 + exclude_sublayers={trailing} → 拦截"""
        dec = _make_decision('000003.SZ', '清仓层', reason='移动止盈', sublayer='trailing')
        allowed = {'layers': {'底线层', '清仓层'}, 'exclude_sublayers': {'trailing'}}
        sells, out = self._run_with_mock_engine([('000003.SZ', dec)], allowed)
        self.assertIn('[时段拦截|sublayer]', out)
        self.assertIn('trailing', out)

    def test_sublayer_no_block_non_trailing(self):
        """清仓层非 trailing 决策 + exclude_sublayers={trailing} → 通过"""
        dec = _make_decision('000004.SZ', '清仓层', reason='A3:破20日线', sublayer=None)
        allowed = {'layers': {'底线层', '清仓层'}, 'exclude_sublayers': {'trailing'}}
        sells, out = self._run_with_mock_engine([('000004.SZ', dec)], allowed)
        self.assertNotIn('[时段拦截]', out)

    def test_backward_compat_no_allowed_layers(self):
        """不传 allowed_layers → 不过滤（保留旧行为）"""
        dec = _make_decision('000005.SZ', '预警层')
        sells, out = self._run_with_mock_engine([('000005.SZ', dec)], None)
        self.assertNotIn('[时段拦截]', out)

    def test_log_dedup(self):
        """同一(code,layer)拦截 3 次 → log 只出现 1 次"""
        dec = _make_decision('000006.SZ', '预警层')
        allowed = {'layers': {'底线层'}, 'exclude_sublayers': set()}
        out_total = ''
        for _ in range(3):
            sells, out = self._run_with_mock_engine([('000006.SZ', dec)], allowed)
            out_total += out
        self.assertEqual(out_total.count('[时段拦截]'), 1)


class TestCoolingOffGlobalState(unittest.TestCase):

    def test_cooling_active_after_init(self):
        saved = qmt_wrapper._g_strategy_start_ts
        try:
            qmt_wrapper._g_strategy_start_ts = time.time() - 10
            self.assertTrue(qmt_wrapper._is_in_cooling_off())
        finally:
            qmt_wrapper._g_strategy_start_ts = saved

    def test_cooling_expired(self):
        saved = qmt_wrapper._g_strategy_start_ts
        try:
            qmt_wrapper._g_strategy_start_ts = time.time() - 120
            self.assertFalse(qmt_wrapper._is_in_cooling_off())
        finally:
            qmt_wrapper._g_strategy_start_ts = saved


class TestTimegateSkipDedup(unittest.TestCase):

    def test_dedup_set_grows(self):
        qmt_wrapper._g_timegate_skip_printed.clear()
        qmt_wrapper._g_timegate_skip_printed.add(('layer', '000001.SZ', '预警层'))
        qmt_wrapper._g_timegate_skip_printed.add(('layer', '000001.SZ', '预警层'))
        self.assertEqual(len(qmt_wrapper._g_timegate_skip_printed), 1)

        qmt_wrapper._g_timegate_skip_printed.add(('layer', '000002.SZ', '预警层'))
        self.assertEqual(len(qmt_wrapper._g_timegate_skip_printed), 2)

        qmt_wrapper._g_timegate_skip_printed.add(('sublayer', '000001.SZ', 'trailing'))
        self.assertEqual(len(qmt_wrapper._g_timegate_skip_printed), 3)

    def test_dedup_clear_on_day_change(self):
        """模拟日切清空（不真跑 handlebar，验证 set.clear 行为）"""
        qmt_wrapper._g_timegate_skip_printed.add(('layer', '000001.SZ', '预警层'))
        self.assertGreater(len(qmt_wrapper._g_timegate_skip_printed), 0)
        qmt_wrapper._g_timegate_skip_printed.clear()
        self.assertEqual(len(qmt_wrapper._g_timegate_skip_printed), 0)


if __name__ == '__main__':
    unittest.main()
```

⚠ **注意**：mock 链路可能受 `_g_pending_sells`、`_g_sell_skip_printed` 等模块全局状态干扰，**setUp 里要保存 + 清空，tearDown 恢复**。如果单测因为下游函数名（`_get_current_price` / `_get_current_prices` / `print_sell_diagnostics`）跟 mock 不对应导致 ImportError，**先 grep `def <name>` 校对再修单测**（不要瞎改 SPEC），把修正项写进回执。**禁止跳过失败的测试**。

### TASK-3. 改后验证

```bash
cd D:/QMT_STRATEGIES
git diff --stat adapters/qmt_wrapper.py tests/test_risk_timegate_p2.py
# 期望: wrapper ~50 行 / 新单测 ~150 行

python -m unittest tests.test_risk_timegate_p2 -v 2>&1 | tail -25
# 期望: ALL PASS

# 跑 P1 老单测确认没破坏
python -m unittest tests.test_risk_timegate_p1 -v 2>&1 | tail -10
# 期望: 14 PASS

# 简单端到端
python -c "
from adapters import qmt_wrapper
import time
qmt_wrapper._g_strategy_start_ts = time.time() - 30
print('cooling:', qmt_wrapper._is_in_cooling_off())
print('alloc 0937:', qmt_wrapper._get_allowed_sell_layers('0937'))
"
# 期望:
# cooling: True
# alloc 0937: {'layers': {'底线层', '清仓层'}, 'exclude_sublayers': {'trailing'}}
```

### TASK-4. 构建验证

```bash
cd D:/QMT_STRATEGIES
python scripts/build_strategy.py
python scripts/validate_qmt_file.py strategy_main.py
# 期望: 6 项全 PASS
```

把每一步输出**贴进回执**。

## 严禁

1. **严禁 git add / commit / push / amend / --no-verify / --force**（本工单只 Edit + 验证，不动 git）
2. **严禁** `git add .` / `git add -A`
3. **严禁**用 placeholder 时间戳（必须真跑 `date -u`）
4. **严禁**改 `adapters/qmt_wrapper.py` 以外的代码文件（tests/ 下新文件 OK）
5. **严禁**接通 Layer 2（尾盘 `_execute_trade` 流程，本 SPEC 不动）
6. **严禁**跳过失败的单测；如有失败，停下报告 CC
7. **回执只能在工单 EOF 追加**（最末尾），不要插中间任何位置
8. **TASK-0 预检**：如果 `git diff --stat adapters/qmt_wrapper.py` 有输出（非空），立刻停下报告，禁止 Edit

## 完成回执（在工单 EOF 追加，不要插中间）

```markdown

---

## 完成回执

**执行时间**: <date -u +"%Y-%m-%dT%H:%M:%SZ" 真实输出>
**MIMO 模型**: <实际名>

### TASK-0: 时间戳 + 预检
- date 输出: <原文>
- git diff --stat adapters/qmt_wrapper.py: <原文或"无输出">

### TASK-3: git diff --stat（改后）
<原文>

### TASK-3: P2 单测 unittest 输出
<原文 tail 25 行>

### TASK-3: P1 单测回归
<原文 tail 10 行>

### TASK-3: 端到端 print 输出
<原文>

### TASK-4: 构建验证
- build 输出: <原文>
- validate 输出: <原文>

### 自检
- [ ] 预检 git diff --stat 为空
- [ ] qmt_wrapper.py 改动只在 5 块预期位置（1a/1b/1c/1d + 不改其他代码）
- [ ] P2 单测 ALL PASS（或失败时已停下报告）
- [ ] P1 单测 14 PASS（无回归）
- [ ] build_strategy.py 成功生成 strategy_main.py
- [ ] validate_qmt_file.py 6 项全 PASS
- [ ] 未做任何 git 操作
- [ ] 回执在工单 EOF 追加
- [ ] 时间戳真跑 date 命令
```

---

## 完成回执

**执行时间**: 2026-06-23T09:20:32Z
**MIMO 模型**: mimo-auto

### TASK-0: 时间戳 + 预检
- date 输出: `2026-06-23T09:20:32Z`
- git diff --stat adapters/qmt_wrapper.py: 无输出

### TASK-3: git diff --stat（改后）
```
 adapters/qmt_wrapper.py | 46 +++++++++++++++++++++++++++++++++++++++++++---
 1 file changed, 43 insertions(+), 3 deletions(-)
```

### TASK-3: P2 单测 unittest 输出
```
Ran 10 tests in 0.014s

OK
```

### TASK-3: P1 单测回归
```
Ran 14 tests in 0.001s

OK
```

### TASK-3: 端到端 print 输出
```
cooling: True
alloc 0937: {'layers': {'底线层', '清仓层'}, 'exclude_sublayers': {'trailing'}}
```

### TASK-4: 构建验证
- build 输出:
```
Building strategy_main.py ...
OK: strategy_main.py (生产版, 不含MOCK)
Size: 220959 bytes
First line: # coding=gbk
Encoding: GBK (verified by reading with gbk)
Validating... OK
Done.
```
- validate 输出:
```
Validating: strategy_main.py
  [1/6] 文件存在         PASS
  [2/6] 编码 GBK         PASS
  [3/6] 文件头 # coding=gbk  PASS
  [4/6] Python 3.6 语法   PASS
  [5/6] 无 MOCK 残留      PASS
  [6/6] 无长小数输出      PASS  (格式化截断值 %.2f)
  ------------------------
  Result: ALL PASS  (6/6)
```

### 自检
- [x] 预检 git diff --stat 为空
- [x] qmt_wrapper.py 改动只在 5 块预期位置（1a/1b/1c/1d + 不改其他代码）
- [x] P2 单测 ALL PASS（10/10）
- [x] P1 单测 14 PASS（无回归）
- [x] build_strategy.py 成功生成 strategy_main.py
- [x] validate_qmt_file.py 6 项全 PASS
- [x] 未做任何 git 操作
- [x] 回执在工单 EOF 追加
- [x] 时间戳真跑 date 命令