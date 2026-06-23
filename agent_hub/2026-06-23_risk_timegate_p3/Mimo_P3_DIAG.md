# MIMO 工单：P3 观察期 — 09:25 日 K 字段诊断 + 临时切 OFF

## 目的

P3 已合入 master（`394a0b9`），但 `_get_premarket_ref_price` 假设"09:25 集合竞价撮合后 QMT 日 K `close[-1]` 反映撮合价"未经过实盘验证。本工单加诊断 log 收集明早 09:25 真实数据，并临时把 `PREMARKET_HARD_STOP_MODE` 切到 `'OFF'`（只观察不下单），等数据回来后再决定是否切回 `'G3_ONLY'`。

**前置 commit**: `394a0b9`
**预计工时**: 20-30 分钟

---

## 一、必做（6 步）

### TASK-0. 时间戳

```bash
date -u +"%Y-%m-%dT%H:%M:%SZ"
```

回执"执行时间"填这个真实值。**严禁** placeholder。

### TASK-1. 预检

```bash
cd D:/QMT_STRATEGIES
git status --short adapters/qmt_wrapper.py strategy_main.py
git log -1 --oneline
```

期望：
- `adapters/qmt_wrapper.py` 干净（HEAD = `394a0b9`，无 ` M`）
- `strategy_main.py` 状态可有可无（构建产物会重生成，dirty 也无所谓，但本工单只 commit 这两个 + 单测 + 工单）

**如果 `adapters/qmt_wrapper.py` 已 dirty**，立刻停下报告。

把输出贴进回执。

### TASK-2. Edit `adapters/qmt_wrapper.py`（3 处改动）

#### 2a. 切默认开关到 OFF（line 144 精确匹配）

定位（精确字符串，only 1 处）：
```python
PREMARKET_HARD_STOP_MODE = 'G3_ONLY'  # 'OFF' / 'G3_ONLY' / 'G2_AND_G3'
```

替换为：
```python
PREMARKET_HARD_STOP_MODE = 'OFF'  # 'OFF' / 'G3_ONLY' / 'G2_AND_G3'  P3 观察期: 验日K字段后切回 'G3_ONLY'
```

#### 2b. 新增诊断函数（插在 `_get_premarket_ref_price` 函数之后、`_check_pre_market_hard_stop` 之前）

定位（精确匹配 `_get_premarket_ref_price` 函数末尾，**only 1 处**）：
```python
    if ref_price <= 0 or prev_close <= 0:
        return None, None
    return ref_price, prev_close


def _check_pre_market_hard_stop(C, today, now):
```

替换为：
```python
    if ref_price <= 0 or prev_close <= 0:
        return None, None
    return ref_price, prev_close


def _log_premarket_diagnostic(C, today, now):
    """P3 观察期: 把 09:25 日K close[-1]/close[-2] 与 tick lastPrice/preClose 写到
    D:\\QMT_POOL\\premarket_diag_YYYYMMDD.csv 用于验证 close[-1] 是否反映撮合价。
    每天只写一次（由 _g_premarket_check_done 守护，调用方负责）。
    异常不抛，只打印。
    """
    if C is None or not _g_my_codes:
        return
    try:
        codes = list(_g_my_codes.keys())
        md = {}
        try:
            md = C.get_market_data_ex(['close'], codes, period='1d', count=2) or {}
        except Exception as e:
            print("    [P3诊断] get_market_data_ex 异常: %s" % e)
        tick = {}
        try:
            tick = C.get_full_tick(codes) or {}
        except Exception as e:
            print("    [P3诊断] get_full_tick 异常: %s" % e)

        path = 'D:/QMT_POOL/premarket_diag_%s.csv' % today
        write_header = not os.path.exists(path)
        try:
            f = open(path, 'a')
            try:
                if write_header:
                    f.write('timestamp,today,now,code,md_close_minus_1,md_close_minus_2,tick_lastPrice,tick_preClose,tick_open,tick_high,tick_low\n')
                ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                for code in codes:
                    md_c1 = ''
                    md_c2 = ''
                    df = md.get(code) if md else None
                    if df is not None and len(df) >= 2:
                        try:
                            md_c1 = '%.4f' % float(df['close'].iloc[-1])
                            md_c2 = '%.4f' % float(df['close'].iloc[-2])
                        except Exception:
                            pass
                    t = tick.get(code, {}) if tick else {}
                    last_p = t.get('lastPrice', '')
                    pre_c = t.get('preClose', '')
                    op = t.get('open', '')
                    hi = t.get('high', '')
                    lo = t.get('low', '')
                    f.write('%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n'
                            % (ts, today, now, code, md_c1, md_c2, last_p, pre_c, op, hi, lo))
            finally:
                f.close()
            print("    [P3诊断] 已写 %s (%d 只)" % (path, len(codes)))
        except Exception as e:
            print("    [P3诊断] 写文件异常: %s" % e)
    except Exception as e:
        print("    [P3诊断] 整体异常: %s" % e)


def _check_pre_market_hard_stop(C, today, now):
```

#### 2c. 在 `_check_pre_market_hard_stop` 入口（防重入门之后、OFF 检查之前）调用诊断

定位（精确匹配）：
```python
    global _g_premarket_check_done, _g_premarket_orders

    if _g_premarket_check_done:
        return
    if PREMARKET_HARD_STOP_MODE == 'OFF':
        _g_premarket_check_done = True
        print("  [%s] 集合竞价预埋: 模式 OFF, 跳过" % STRATEGY_NAME)
        return
```

替换为：
```python
    global _g_premarket_check_done, _g_premarket_orders

    if _g_premarket_check_done:
        return

    # P3 观察期: 不论模式都先写诊断 CSV (每日一次，由 _g_premarket_check_done 守护)
    _log_premarket_diagnostic(C, today, now)

    if PREMARKET_HARD_STOP_MODE == 'OFF':
        _g_premarket_check_done = True
        print("  [%s] 集合竞价预埋: 模式 OFF, 跳过 (诊断已写)" % STRATEGY_NAME)
        return
```

### TASK-3. 新增 1 个单测到 `tests/test_risk_timegate_p3.py`（追加到现有文件末尾，`if __name__` 之前）

定位（精确匹配文件末尾区域）：
```python
        with contextlib.redirect_stdout(io.StringIO()):
            qmt_wrapper._check_pre_market_hard_stop(C, '20260624', '0925')
        self.assertEqual(qmt_wrapper._g_trader.sell_limit_price.call_count, 2)


if __name__ == '__main__':
    unittest.main()
```

替换为：
```python
        with contextlib.redirect_stdout(io.StringIO()):
            qmt_wrapper._check_pre_market_hard_stop(C, '20260624', '0925')
        self.assertEqual(qmt_wrapper._g_trader.sell_limit_price.call_count, 2)


class TestPremarketDiagnostic(unittest.TestCase):
    """P3 观察期诊断 CSV 测试"""

    def setUp(self):
        import tempfile, os
        self._tmpdir = tempfile.mkdtemp(prefix='p3diag_')
        self._saved_my_codes = dict(qmt_wrapper._g_my_codes)
        qmt_wrapper._g_my_codes = {'000001.SZ': 10.0, '600000.SH': 5.0}

    def tearDown(self):
        import shutil
        qmt_wrapper._g_my_codes = self._saved_my_codes
        try:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
        except Exception:
            pass

    def test_diag_writes_csv_with_both_fields(self):
        """验证诊断函数同时记录 md close[-1]/[-2] 和 tick lastPrice/preClose"""
        import os
        C = MagicMock()
        # md: 000001 close=[10.0, 8.5], 600000 close=[5.0, 4.8]
        def _get_md(fields, codes, period='1d', count=2):
            return {
                '000001.SZ': pd.DataFrame({'close': [10.0, 8.5]}),
                '600000.SH': pd.DataFrame({'close': [5.0, 4.8]}),
            }
        C.get_market_data_ex.side_effect = _get_md
        # tick
        C.get_full_tick.return_value = {
            '000001.SZ': {'lastPrice': 8.6, 'preClose': 10.0, 'open': 9.0, 'high': 9.1, 'low': 8.4},
            '600000.SH': {'lastPrice': 4.85, 'preClose': 5.0, 'open': 4.9, 'high': 4.95, 'low': 4.78},
        }

        # 把 D:/QMT_POOL 重定向到 tmpdir（patch os.path.exists + open）
        diag_path = os.path.join(self._tmpdir, 'premarket_diag_20260624.csv')
        with patch.object(qmt_wrapper, 'os') as mock_os:
            # 让 path 拼接走真路径
            mock_os.path.exists.side_effect = lambda p: os.path.exists(diag_path) if 'premarket_diag' in p else os.path.exists(p)
            with patch('builtins.open', wraps=open) as mock_open:
                def _redirect_open(path, *args, **kwargs):
                    if isinstance(path, str) and 'premarket_diag' in path:
                        return open(diag_path, *args, **kwargs)
                    return open(path, *args, **kwargs)
                mock_open.side_effect = _redirect_open
                with contextlib.redirect_stdout(io.StringIO()):
                    qmt_wrapper._log_premarket_diagnostic(C, '20260624', '0925')

        self.assertTrue(os.path.exists(diag_path), '诊断 CSV 应已写入')
        with open(diag_path, 'r') as f:
            content = f.read()
        # 表头
        self.assertIn('md_close_minus_1', content)
        self.assertIn('tick_lastPrice', content)
        # 两个 code 都写了
        self.assertIn('000001.SZ', content)
        self.assertIn('600000.SH', content)
        # md 字段值
        self.assertIn('8.5000', content)  # close[-1]
        self.assertIn('10.0000', content)  # close[-2]
        # tick 字段值
        self.assertIn('8.6', content)
        self.assertIn('4.85', content)

    def test_diag_handles_missing_data(self):
        """C 取不到数据时不抛异常"""
        import os
        C = MagicMock()
        C.get_market_data_ex.side_effect = Exception('mock fail')
        C.get_full_tick.side_effect = Exception('mock fail')
        diag_path = os.path.join(self._tmpdir, 'premarket_diag_20260624.csv')
        with patch('builtins.open', wraps=open) as mock_open:
            def _redirect_open(path, *args, **kwargs):
                if isinstance(path, str) and 'premarket_diag' in path:
                    return open(diag_path, *args, **kwargs)
                return open(path, *args, **kwargs)
            mock_open.side_effect = _redirect_open
            with contextlib.redirect_stdout(io.StringIO()):
                # 不应抛异常
                qmt_wrapper._log_premarket_diagnostic(C, '20260624', '0925')


if __name__ == '__main__':
    unittest.main()
```

### TASK-4. 验证 4 步

```bash
cd D:/QMT_STRATEGIES

# 4a. P3 单测（含新增 2 个诊断单测）
python -m unittest tests.test_risk_timegate_p3 -v
# 期望: 11 + 2 = 13 PASS

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

每步输出贴回执，**任一失败立刻停下报告**。

### TASK-5. 精确 add + commit（4 文件）

```bash
cd D:/QMT_STRATEGIES
git add adapters/qmt_wrapper.py
git add strategy_main.py
git add tests/test_risk_timegate_p3.py
git add agent_hub/2026-06-23_risk_timegate_p3/Mimo_P3_DIAG.md

git diff --cached --name-only
```

**期望输出（4 行，多一行少一行都不行）**：
```
adapters/qmt_wrapper.py
agent_hub/2026-06-23_risk_timegate_p3/Mimo_P3_DIAG.md
strategy_main.py
tests/test_risk_timegate_p3.py
```

**严禁** `git add .` / `git add -A` / 整目录 add。staged 不止 4 个立刻停下报告。

```bash
git commit -m "$(cat <<'EOF'
feat(risk): P3 观察期 - 09:25 日K字段诊断 + 临时切 OFF

新增（行为变更）:
- _log_premarket_diagnostic: 每日 09:25 第一次进 _check_pre_market_hard_stop
  时同时记录 get_market_data_ex 1d close[-1]/[-2] 和 get_full_tick
  lastPrice/preClose/open/high/low 到 D:/QMT_POOL/premarket_diag_YYYYMMDD.csv
- PREMARKET_HARD_STOP_MODE 默认临时切 'OFF'（观察期，验日K字段后切回 'G3_ONLY'）
- 诊断写文件无副作用，异常吞掉只打印

13 P3 单测 + 14 P1 + 10 P2 回归全 PASS。validate_qmt_file 6 项 PASS。
不动 Layer 1 / Layer 2 / SAFEMODE / DEBUG_MODE / TEST_MODE / core/risk_manager。
EOF
)"

git log -1 --stat HEAD
```

把 `git log -1 --stat HEAD` 完整输出贴进回执。

## 二、严禁

1. **严禁** `git add .` / `git add -A` / 任何整目录 add
2. **严禁** push / amend / --no-verify / --force
3. **严禁**改 `core/risk_manager.py` / Layer 1 / Layer 2 / SAFEMODE / DEBUG_MODE / TEST_MODE / 任何 P1/P2 已落地代码
4. **严禁**用 placeholder 时间戳（必须真跑 `date -u`）
5. **严禁** TASK-2 定位字符串非唯一或匹配不到时强行改——立刻停下报告
6. **严禁段加死**——所有新增变量/参数必须在函数体内被引用
7. **遇任一异常必停**：TASK-4 任一步 FAIL、staged 范围异常、commit 报错——立刻停下报告，**不得自判"无关"继续**
8. **回执只能在工单 EOF 追加**（最末尾）

## 三、完成回执（在工单 EOF 追加）

```markdown

---

## 完成回执

**执行时间**: <真实 date -u 输出>
**MIMO 模型**: <实际名>

### TASK-0: 真实时间戳
<贴 date 输出>

### TASK-1: 预检
<贴 git status + git log -1 输出>

### TASK-2: 3 处 Edit
- [ ] 2a PREMARKET_HARD_STOP_MODE 切 OFF
- [ ] 2b _log_premarket_diagnostic 函数插入
- [ ] 2c _check_pre_market_hard_stop 入口调用

### TASK-3: 单测追加
- [ ] TestPremarketDiagnostic 类追加
- [ ] 2 个新单测函数

### TASK-4: 验证输出
**4a P3 单测 (13)**:
<贴 unittest -v 完整输出>

**4b P1+P2 回归 (24)**:
<贴 unittest -v 完整输出>

**4c build_strategy**:
<贴最后 5-10 行输出>

**4d validate_qmt_file**:
<贴完整输出（6 项 PASS）>

### TASK-5: git diff --cached + commit
<贴 git diff --cached --name-only + git log -1 --stat HEAD>

### 自检
- [ ] 时间戳真跑 date 命令
- [ ] staged 只有 4 个文件
- [ ] commit 成功，未 push / amend / --no-verify
- [ ] P3 单测 13 PASS
- [ ] P1+P2 回归 24 PASS
- [ ] validate 6 项 PASS
- [ ] PREMARKET_HARD_STOP_MODE 默认值 = 'OFF'
- [ ] 回执在工单 EOF 追加（未插中间）
- [ ] 未改 core/risk_manager.py / Layer 1 / Layer 2 等无关代码
```
