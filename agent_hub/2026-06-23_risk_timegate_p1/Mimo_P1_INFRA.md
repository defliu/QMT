# MIMO 工单：P1 基础设施层 — triggered_sublayer + 时段函数

## 来源

SPEC: `D:\QMT_STRATEGIES\specs\SPEC_20260623_RISK_TIMEGATE_P1_INFRA.md`
设计稿: `knowledge_base\30_策略卡片\风控分时段触发架构_v0.2.md`

## 必做（3 项）

### TASK-1: core/risk_manager.py — SellDecision 字段 + trailing 标记

**1a. `SellDecision.__init__` 加 `triggered_sublayer=None` 参数**（`core/risk_manager.py:72-76`）

改前：
```python
def __init__(self, action=Action.HOLD, code='', sell_pct=0.0, reason='',
             triggered_layer='', triggered_signals=None):
```

改后：
```python
def __init__(self, action=Action.HOLD, code='', sell_pct=0.0, reason='',
             triggered_layer='', triggered_signals=None, triggered_sublayer=None):
```

加一行：
```python
self.triggered_sublayer = triggered_sublayer
```

**1b. `SellDecision.clear()` 加 `sublayer=None` 转发参数**（`core/risk_manager.py:92-93`）

改前：
```python
@staticmethod
def clear(code, reason, layer, signals=None):
    return SellDecision(Action.CLEAR, code, 1.0, reason, layer, signals or [])
```

改后：
```python
@staticmethod
def clear(code, reason, layer, signals=None, sublayer=None):
    return SellDecision(Action.CLEAR, code, 1.0, reason, layer, signals or [], triggered_sublayer=sublayer)
```

**1c. `_check_clear_level` 内 trailing 条件打 sublayer**（约 line 562-570）

在 `if signals:` 内部，`return SellDecision.clear(...)` 之前加 sublayer 判断逻辑：

```python
# signals 已存在（包括可能已 append "移动止盈"）
trailing_sublayer = None
if len(signals) == 1 and signals[0] == "移动止盈":
    trailing_sublayer = 'trailing'
# 改 return 行传 sublayer
```

`return SellDecision.clear(...)` 改传 `sublayer=trailing_sublayer`。

### TASK-2: adapters/qmt_wrapper.py — 辅助函数 + 全局变量

**2a. `_g_strategy_start_ts` 全局变量**（约 line 138）

在 `_g_candidate_queue = []` 之后加一行：
```python
_g_strategy_start_ts = None   # 策略启动时间戳（cooling-off 用）
```

**2b. `init()` 内赋值**（约 line 2875-2910）

- 把 `_g_strategy_start_ts` 加到 `init()` 函数开头的 `global` 声明行
- 在 `_g_init_done = True` 之前（约 line 2910 之前）加：
  ```python
  _g_strategy_start_ts = time.time()
  ```

**2c. 新增 `_get_allowed_sell_layers(now)` 函数**（放在 `_check_and_execute_sell` 之前，约 line 1725-1728）

```python
def _get_allowed_sell_layers(now):
    """根据当前时点决定本轮允许哪些 sell decision triggered_layer 通过。
    
    返回 dict:
        {'layers': set[str],           # 允许的 layer 白名单
         'exclude_sublayers': set[str]} # 排除的 sublayer 黑名单
    layers 为空集表示本时段不允许任何卖出。
    """
    if now < '0925':
        return {'layers': set(), 'exclude_sublayers': set()}
    if now < '0930':
        return {'layers': set(), 'exclude_sublayers': set()}
    if now < '0935':
        return {'layers': {'底线层'}, 'exclude_sublayers': set()}
    if now < '0940':
        return {'layers': {'底线层', '清仓层'}, 'exclude_sublayers': {'trailing'}}
    if now < '1440':
        return {'layers': {'底线层', '清仓层', '预警层', '确认层', 'warning_add'},
                'exclude_sublayers': set()}
    if now < '1458':
        return {'layers': {'底线层', '清仓层', '预警层', '确认层', 'warning_add'},
                'exclude_sublayers': set()}
    return {'layers': set(), 'exclude_sublayers': set()}
```

**2d. 新增 `_is_in_cooling_off()` 函数**（放在 `_get_allowed_sell_layers` 旁边）

```python
def _is_in_cooling_off():
    """策略启动后 60 秒内屏蔽所有交易。
    P1 只声明不调用，P2 接通 handlebar。
    """
    if _g_strategy_start_ts is None:
        return False
    return (time.time() - _g_strategy_start_ts) < 60
```

### TASK-3: 新增单测文件 `tests/test_risk_timegate_p1.py`

编码 `# coding=gbk`。文件写 `tests/test_risk_timegate_p1.py`，内容如下：

```python
# coding=gbk
"""P1 基础设施：SellDecision.triggered_sublayer + 时段辅助函数"""
import unittest
import time
try:
    from core.risk_manager import SellDecision
except ImportError:
    import sys
    sys.path.insert(0, 'D:/QMT_STRATEGIES')
    from core.risk_manager import SellDecision
from adapters import qmt_wrapper


class TestSellDecisionSublayer(unittest.TestCase):

    def test_clear_no_sublayer_default(self):
        d = SellDecision.clear('000001', '硬止损', '底线层', ['累计亏损'])
        self.assertIsNone(d.triggered_sublayer)

    def test_clear_with_trailing_sublayer(self):
        d = SellDecision.clear('000001', '移动止盈', '清仓层', ['移动止盈'], sublayer='trailing')
        self.assertEqual(d.triggered_sublayer, 'trailing')

    def test_hold_no_sublayer(self):
        d = SellDecision.hold()
        self.assertIsNone(d.triggered_sublayer)

    def test_reduce_no_sublayer(self):
        d = SellDecision.reduce('000001', 0.3, '预警信号', '预警层', ['B1'])
        self.assertIsNone(d.triggered_sublayer)


class TestGetAllowedLayers(unittest.TestCase):

    def test_pre_open(self):
        r = qmt_wrapper._get_allowed_sell_layers('0900')
        self.assertEqual(r['layers'], set())

    def test_open_impact(self):
        r = qmt_wrapper._get_allowed_sell_layers('0930')
        self.assertEqual(r['layers'], {'底线层'})

    def test_early_buffer(self):
        r = qmt_wrapper._get_allowed_sell_layers('0937')
        self.assertIn('清仓层', r['layers'])
        self.assertIn('trailing', r['exclude_sublayers'])

    def test_mid_session(self):
        r = qmt_wrapper._get_allowed_sell_layers('0945')
        for layer in ('底线层', '清仓层', '预警层', '确认层', 'warning_add'):
            self.assertIn(layer, r['layers'])
        self.assertEqual(r['exclude_sublayers'], set())

    def test_tail_session(self):
        r = qmt_wrapper._get_allowed_sell_layers('1445')
        for layer in ('底线层', '清仓层', '预警层', '确认层', 'warning_add'):
            self.assertIn(layer, r['layers'])

    def test_close_cancel(self):
        r = qmt_wrapper._get_allowed_sell_layers('1458')
        self.assertEqual(r['layers'], set())

    def test_exclude_sublayers_structure(self):
        """所有时段返回值都包含 layers 和 exclude_sublayers 两个 key"""
        for t in ('0800', '0925', '0930', '0937', '0945', '1200', '1445', '1458', '1600'):
            r = qmt_wrapper._get_allowed_sell_layers(t)
            self.assertIn('layers', r)
            self.assertIn('exclude_sublayers', r)


class TestCoolingOff(unittest.TestCase):

    def test_cooling_off_active(self):
        """mock 启动时间在 30 秒前 → cooling-off 应返回 True"""
        saved = qmt_wrapper._g_strategy_start_ts
        qmt_wrapper._g_strategy_start_ts = time.time() - 30
        try:
            self.assertTrue(qmt_wrapper._is_in_cooling_off())
        finally:
            qmt_wrapper._g_strategy_start_ts = saved

    def test_cooling_off_expired(self):
        """mock 启动时间在 120 秒前 → cooling-off 应返回 False"""
        saved = qmt_wrapper._g_strategy_start_ts
        qmt_wrapper._g_strategy_start_ts = time.time() - 120
        try:
            self.assertFalse(qmt_wrapper._is_in_cooling_off())
        finally:
            qmt_wrapper._g_strategy_start_ts = saved

    def test_cooling_off_none(self):
        """_g_strategy_start_ts 为 None → 安全返回 False"""
        saved = qmt_wrapper._g_strategy_start_ts
        qmt_wrapper._g_strategy_start_ts = None
        try:
            self.assertFalse(qmt_wrapper._is_in_cooling_off())
        finally:
            qmt_wrapper._g_strategy_start_ts = saved


if __name__ == '__main__':
    unittest.main()
```

---

## 完成回执

**执行时间**: 2026-06-23T00:00:00Z
**MIMO 模型**: mimo-auto

### 预检：git diff --stat
（两个文件均无输出，working tree 干净）

### git diff --stat（改后）
 adapters/qmt_wrapper.py | 41 +++++++++++++++++++++++++++++++++++++++++
 core/risk_manager.py    | 12 ++++++++----
 2 files changed, 49 insertions(+), 4 deletions(-)

### 单测结果
 tests/test_risk_timegate_p1.py::TestSellDecisionSublayer::test_clear_no_sublayer_default PASSED [  7%]
 tests/test_risk_timegate_p1.py::TestSellDecisionSublayer::test_clear_with_trailing_sublayer PASSED [ 14%]
 tests/test_risk_timegate_p1.py::TestSellDecisionSublayer::test_hold_no_sublayer PASSED [ 21%]
 tests/test_risk_timegate_p1.py::TestSellDecisionSublayer::test_reduce_no_sublayer PASSED [ 28%]
 tests/test_risk_timegate_p1.py::TestGetAllowedLayers::test_close_cancel PASSED [ 35%]
 tests/test_risk_timegate_p1.py::TestGetAllowedLayers::test_early_buffer PASSED [ 42%]
 tests/test_risk_timegate_p1.py::TestGetAllowedLayers::test_exclude_sublayers_structure PASSED [ 50%]
 tests/test_risk_timegate_p1.py::TestGetAllowedLayers::test_mid_session PASSED [ 57%]
 tests/test_risk_timegate_p1.py::TestGetAllowedLayers::test_open_impact PASSED [ 64%]
 tests/test_risk_timegate_p1.py::TestGetAllowedLayers::test_pre_open PASSED [ 71%]
 tests/test_risk_timegate_p1.py::TestGetAllowedLayers::test_tail_session PASSED [ 78%]
 tests/test_risk_timegate_p1.py::TestCoolingOff::test_cooling_off_active PASSED [ 85%]
 tests/test_risk_timegate_p1.py::TestCoolingOff::test_cooling_off_expired PASSED [ 92%]
 tests/test_risk_timegate_p1.py::TestCoolingOff::test_cooling_off_none PASSED [100%]
 
 ============================= 14 passed in 0.20s =============================

### 手动验证 exclude_sublayers
 {'trailing'}

### 自检
- [x] risk_manager 改行数 ≤12（只有字段 + clear 签名 + _check_clear_level 逻辑）
- [x] wrapper 改行数 ≤55（全局变量 + init 赋值 + 2 个函数）
- [x] 单测文件编码 GBK
- [x] 单测 ALL PASS
- [x] 未 push / amend / --no-verify
- [x] 未接通主循环

## 严禁

1. **git add 之前先 `git diff <target_file>` 校验**目标文件的 dirty 范围。见 §预检。
2. **禁止 git add . / git add -A**
3. **禁止 push、amend、--no-verify、--force**
4. **禁止 P1 范围内接通主循环调用**（`_get_allowed_sell_layers` 和 `_is_in_cooling_off` 只声明不调用）

## 预检（Edit 之前跑）

```bash
cd D:/QMT_STRATEGIES
git diff core/risk_manager.py --stat
git diff adapters/qmt_wrapper.py --stat
```
两个 stat 都应接近 0，说明目标文件在 P1 之前是干净的。
把 stat 原文贴进回执。

## 改后验证

```bash
cd D:/QMT_STRATEGIES
git diff --stat core/risk_manager.py adapters/qmt_wrapper.py
# 期望：risk_manager ~10 行 / wrapper ~50 行

python -m pytest tests/test_risk_timegate_p1.py -v
# 期望：ALL PASS

python -c "from adapters import qmt_wrapper; r = qmt_wrapper._get_allowed_sell_layers('0937'); print(r['exclude_sublayers'])"
# 输出: {'trailing'}
```

## 完成回执

```markdown
---

## 完成回执

**执行时间**: <date -u +"%Y-%m-%dT%H:%M:%SZ">
**MIMO 模型**: <实际名>

### 预检：git diff --stat
<贴 stat 原文>

### git diff --stat（改后）
<贴 stat 原文>

### 单测结果
<贴 pytest -v 原文>

### 手动验证 exclude_sublayers
<贴输出原文>

### 自检
- [ ] risk_manager 改行数 ≤12（只有字段 + clear 签名 + _check_clear_level 逻辑）
- [ ] wrapper 改行数 ≤55（全局变量 + init 赋值 + 2 个函数）
- [ ] 单测文件编码 GBK
- [ ] 单测 ALL PASS
- [ ] 未 push / amend / --no-verify
- [ ] 未接通主循环
```