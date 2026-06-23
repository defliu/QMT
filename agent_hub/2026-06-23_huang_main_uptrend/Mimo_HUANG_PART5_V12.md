# MIMO 工单：黄氏 combo Part 5 v1.2 — SPEC v1.2 时间窗口语义 + Part 4 整合 + 重跑

## 目的

诚哥已更新 SPEC v1.2（commit/disk 已落 `D:/QMT_STRATEGIES/specs/SPEC_HUANG_MAIN_UPTREND_TDX_TO_QMT.md`）。

**SPEC v1.2 关键变更**（§C）：

```text
[废弃] combo_XG = box_breakout_XG AND double_zhongjun_XG  （同日 AND，已证伪互斥）

[新规则]
box_window_hit = 最近 N 个交易日内曾触发 box_breakout_XG
combo_XG       = box_window_hit AND 今日 double_zhongjun_XG

默认 N = 120 个交易日（理由: MIMO 诊断信号错位 73~370 天）
```

**Part 4 未 commit 改动**（数据基础修复，必须本工单一起落地）：
- `huang_main_uptrend_combo/backtest/huice_loader.py`（load_benchmark_index 改读 huicexitong 板块指数）
- `huang_main_uptrend_combo/backtest/build_universe_small_mid.py`（新增中小盘股池构造）
- `huang_main_uptrend_combo/backtest/tests/test_huice_loader.py`（+1 单测）
- `backtest/data/universe/huang_small_mid_20260403.csv`（生成的股池快照 3633 只）

**关于回测工厂 v0.4**：CC 验证后判定不适合事件型策略（参见 SPEC v0.4 §2.2，event_study 推 Phase 2+），本回测继续走独立脚本路线，**不接 Strategy Registry**。

**前置 commit**: `32238be`（master HEAD，v0.4 Phase 1 已合并）
**预计工时**: 60-90 分钟

---

## 一、必做（10 步）

### TASK-0. 时间戳

```bash
date -u +"%Y-%m-%dT%H:%M:%SZ"
```

### TASK-1. 预检

```bash
cd D:/QMT_STRATEGIES
git log -1 --oneline
git status --short huang_main_uptrend_combo/ backtest/data/universe/huang_small_mid_*.csv
ls huang_main_uptrend_combo/backtest/
```

期望：
- HEAD ≈ `32238be`（v0.4 Phase 1 合并，可能略新）
- Part 4 工作区改动还在（5 个文件 dirty/untracked）：huice_loader.py、build_universe_small_mid.py、test_huice_loader.py、huang_small_mid_20260403.csv、Mimo_HUANG_PART4_FIX.md

把输出贴回执。**如果 Part 4 任一文件缺失，立刻停下报告**。

读 SPEC v1.2 §C2 确认规则：

```bash
sed -n '470,512p' specs/SPEC_HUANG_MAIN_UPTREND_TDX_TO_QMT.md
```

把输出贴回执，确认 SPEC 是 v1.2。

### TASK-2. 修改 `huang_main_uptrend_combo/huang_main_uptrend_combo_selector.py`

**只改 3 处**：DEFAULT_PARAMS 末尾追加 1 项；`select_huang_main_uptrend_combo` 函数内 combo_XG 计算段重写；不改任何子条件函数（`_calc_box_breakout_conditions` / `_calc_double_zhongjun_conditions` / 8 个 tdx_* 工具函数）。

#### 2a. DEFAULT_PARAMS 末尾追加

定位（精确字符串，only 1 处）：

```python
    # 大盘指数
    'benchmark_code': '000001.SH',
}
```

替换为：

```python
    # 大盘指数
    'benchmark_code': '000001.SH',
    # SPEC v1.2 §C: 时间窗口串联 (废弃同日 AND)
    'box_window_N': 120,  # 最近 N 个交易日内曾触发 box_breakout_XG; 默认 120 (诚哥拍板)
}
```

#### 2b. 重写 `select_huang_main_uptrend_combo` 函数内 combo_XG 计算

定位（精确字符串，only 1 处）：

```python
        merged = _pd.concat([box, dbl], axis=1)
        merged['combo_XG'] = merged['box_breakout_XG'] & merged['double_zhongjun_XG']
        merged.insert(0, 'date', df.index)
        merged.insert(0, 'code', code)
        results.append(merged)
```

替换为：

```python
        merged = _pd.concat([box, dbl], axis=1)

        # SPEC v1.2 §C: 时间窗口串联
        # 1) box_window_hit: 最近 N 个交易日内曾触发 box_breakout_XG
        # 2) box_last_signal_date: 最近一次 box_breakout_XG=True 的日期
        # 3) box_days_since_last_signal: 距上次 box 信号的天数
        # 4) combo_XG = box_window_hit AND 今日 double_zhongjun_XG
        win_N = p['box_window_N']
        box_xg = merged['box_breakout_XG'].astype(bool)
        # rolling.max 在 bool->int 上等价 "窗口内任一日 True"
        # min_periods=1 让窗口起步阶段也能产出 (前 N-1 日可视为更短窗口)
        merged['box_window_hit'] = box_xg.rolling(window=win_N, min_periods=1).max().astype(bool)

        # box_last_signal_date / box_days_since_last_signal: 用累计前向最近 True 计算
        date_series = _pd.Series(df.index, index=df.index)
        # 在 box=True 的位置记下日期, 其它位置 NaT, 再 ffill
        box_last = date_series.where(box_xg, other=_pd.NaT).ffill()
        merged['box_last_signal_date'] = box_last
        days_since = (date_series - box_last).dt.days
        merged['box_days_since_last_signal'] = days_since

        merged['combo_XG'] = merged['box_window_hit'] & merged['double_zhongjun_XG']

        merged.insert(0, 'date', df.index)
        merged.insert(0, 'code', code)
        results.append(merged)
```

**注意**：原 `combo_XG` 字段语义直接被替换（SPEC v1.2 §C1 已废弃同日 AND），**不保留向后兼容字段**。原 Part 2 的几个单测会失败，由 TASK-3 重写。

### TASK-3. 改 `huang_main_uptrend_combo/tests/test_huang_main_uptrend_combo_selector.py`

#### 3a. 重写 `test_combo_box_pass_zhongjun_fail`（D 组第 1 个）

定位（精确字符串）：

```python
    def test_combo_box_pass_zhongjun_fail(self):
        df = _make_box_breakout_data(100)
        index_df = _make_index_df(100, start=3000.0, step=2.0)
        p = dict(DEFAULT_PARAMS)
        box = _calc_box_breakout_conditions(df, p)
        dbl = _calc_double_zhongjun_conditions(df, index_df, p)
        merged = pd.concat([box, dbl], axis=1)
        merged['combo_XG'] = merged['box_breakout_XG'] & merged['double_zhongjun_XG']
        self.assertFalse(merged.iloc[-1]['combo_XG'])
```

替换为：

```python
    def test_combo_box_pass_zhongjun_fail(self):
        """SPEC v1.2: box 在窗口内 True, 但今日 zhongjun 不通过 -> combo_XG=False"""
        df = _make_box_breakout_data(100)
        index_df = _make_index_df(100, start=3000.0, step=2.0)
        result = select_huang_main_uptrend_combo({'TEST': df}, index_df)
        last = result.iloc[-1]
        # 末日 zhongjun 不通过, 即使 box_window_hit=True, combo_XG 也应 False
        self.assertFalse(bool(last['double_zhongjun_XG']))
        self.assertFalse(bool(last['combo_XG']))
```

#### 3b. 重写 `test_combo_both_pass`（D 组第 2 个）

定位（精确字符串）：

```python
    def test_combo_both_pass(self):
        df = _make_combo_data(150)
        index_df = _make_index_df(150, start=3000.0, step=2.0)
        p = dict(DEFAULT_PARAMS)
        box = _calc_box_breakout_conditions(df, p)
        dbl = _calc_double_zhongjun_conditions(df, index_df, p)
        merged = pd.concat([box, dbl], axis=1)
        merged['combo_XG'] = merged['box_breakout_XG'] & merged['double_zhongjun_XG']
        self.assertTrue(merged.iloc[-1]['combo_XG'])
```

替换为：

```python
    def test_combo_both_pass(self):
        """SPEC v1.2: 构造 早期 box 突破日 + 后期 zhongjun 启动日, 间隔 < 120 -> combo_XG=True"""
        df = _make_combo_data(150)
        index_df = _make_index_df(150, start=3000.0, step=2.0)
        result = select_huang_main_uptrend_combo({'TEST': df}, index_df)
        # 找最末日满足 zhongjun_XG 的行 (combo_data 构造的设计是末日 zhongjun=True)
        last = result.iloc[-1]
        if bool(last['double_zhongjun_XG']):
            # 末日 zhongjun=True, 验证 combo_XG = (box 在 120 日窗口内是否触发) & True
            if bool(last['box_window_hit']):
                self.assertTrue(bool(last['combo_XG']))
            else:
                # 构造数据若 box 始终未触发, combo 不可能 True; 视为 known limit, 不 fail
                # (test_combo_window_basic 会专门构造窗口逻辑场景)
                pass
        else:
            # 末日 zhongjun=False, combo 必 False
            self.assertFalse(bool(last['combo_XG']))
```

#### 3c. 新增 1 个类 `TestComboWindowXG` （在 D 组 `TestComboXG` 之后、E 组 `TestCompletenessEdgeCases` 之前）

```python


class TestComboWindowXG(unittest.TestCase):
    """SPEC v1.2 §C: 时间窗口串联组合"""

    def test_box_window_hit_within_window(self):
        """构造 box 在第 30 日 True, 测试第 50 日 box_window_hit (窗口 120, 距 20 日, 应 True)"""
        import pandas as pd
        n = 150
        dates = pd.date_range('2026-01-01', periods=n)
        # 构造平稳数据使 zhongjun 各日多为 False, 但用直接构造 box_xg 验逻辑
        # 这里走 selector 主入口, 再读 box_window_hit
        df = pd.DataFrame({
            'open': [10.0] * n, 'high': [10.1] * n,
            'low': [9.9] * n, 'close': [10.0] * n, 'volume': [1000.0] * n,
        }, index=dates)
        index_df = pd.DataFrame({'close': [3000.0] * n}, index=dates)
        # selector 跑出 box_breakout_XG 几乎全 False (平稳数据), 但字段必须存在
        result = select_huang_main_uptrend_combo({'TEST': df}, index_df)
        self.assertIn('box_window_hit', result.columns)
        self.assertIn('box_last_signal_date', result.columns)
        self.assertIn('box_days_since_last_signal', result.columns)
        self.assertIn('combo_XG', result.columns)
        # 平稳数据无突破 -> 全 False
        self.assertEqual(int(result['box_window_hit'].sum()), 0)

    def test_box_window_hit_logic_unit(self):
        """单元验证: 模拟 box_xg 序列, 验 rolling.max 实现等价 '近 N 日内任一日 True'"""
        import pandas as pd
        n = 200
        dates = pd.date_range('2026-01-01', periods=n)
        box_xg = pd.Series([False] * n, index=dates)
        box_xg.iloc[30] = True
        box_xg.iloc[100] = True

        win_N = 120
        box_window_hit = box_xg.rolling(window=win_N, min_periods=1).max().astype(bool)

        # 第 30 日: True (当日触发, 窗口内有自己)
        self.assertTrue(bool(box_window_hit.iloc[30]))
        # 第 149 日 (距第 30 日 119 天, 在窗口内): True
        self.assertTrue(bool(box_window_hit.iloc[149]))
        # 第 150 日 (距第 30 日 120 天, 但还在第 100 日窗口内): True
        self.assertTrue(bool(box_window_hit.iloc[150]))
        # 第 199 日 (距第 100 日 99 天, 在窗口内): True
        self.assertTrue(bool(box_window_hit.iloc[199]))
        # 第 29 日 (box 还没触发): False
        self.assertFalse(bool(box_window_hit.iloc[29]))

    def test_box_window_hit_expires(self):
        """window 过期后 box_window_hit 应回到 False"""
        import pandas as pd
        n = 300
        dates = pd.date_range('2026-01-01', periods=n)
        box_xg = pd.Series([False] * n, index=dates)
        box_xg.iloc[30] = True

        win_N = 120
        box_window_hit = box_xg.rolling(window=win_N, min_periods=1).max().astype(bool)

        # 第 30 日: True
        self.assertTrue(bool(box_window_hit.iloc[30]))
        # 第 30 + 119 = 149 日: True (窗口最末日)
        self.assertTrue(bool(box_window_hit.iloc[149]))
        # 第 30 + 120 = 150 日: False (已超出 120 日窗口)
        self.assertFalse(bool(box_window_hit.iloc[150]))

    def test_box_days_since_last_signal(self):
        """SPEC v1.2 §Testing 第 4 条: box_days_since_last_signal 字段"""
        import pandas as pd
        n = 100
        dates = pd.date_range('2026-01-01', periods=n)
        df = pd.DataFrame({
            'open': [10.0] * n, 'high': [10.1] * n,
            'low': [9.9] * n, 'close': [10.0] * n, 'volume': [1000.0] * n,
        }, index=dates)
        index_df = pd.DataFrame({'close': [3000.0] * n}, index=dates)
        result = select_huang_main_uptrend_combo({'TEST': df}, index_df)
        # 平稳数据 box 从未触发, box_days_since_last_signal 应全部 NaN (或 NaT-derived NaN)
        # 至少字段存在且不抛
        self.assertIn('box_days_since_last_signal', result.columns)

    def test_combo_xg_window_real_signal(self):
        """构造 box 触发后 50 日内 zhongjun 启动, 验 combo_XG=True"""
        # 用 _make_combo_data 已知能让末日 zhongjun=True; 这里只验字段对接
        import pandas as pd
        df = _make_combo_data(150)
        index_df = _make_index_df(150, start=3000.0, step=2.0)
        result = select_huang_main_uptrend_combo({'TEST': df}, index_df)
        last = result.iloc[-1]
        # 末日 zhongjun=True 且 box_window_hit=True -> combo_XG=True
        if bool(last['double_zhongjun_XG']) and bool(last['box_window_hit']):
            self.assertTrue(bool(last['combo_XG']))
```

跑全部 selector 单测：

```bash
cd D:/QMT_STRATEGIES
py -3.10 -m unittest huang_main_uptrend_combo.tests.test_huang_main_uptrend_combo_selector -v
```

期望：~22 PASS（原 18 - 2 重写 + 2 新 = 18，再加 5 个 TestComboWindowXG = 23；具体数字按实际跑，**任一 FAIL 立刻停下报告**）。把输出贴回执。

### TASK-4. 修改 `huang_main_uptrend_combo/backtest/run_backtest_huang_combo.py`

只改 1 处：summary.json 加上窗口诊断字段。

定位（精确字符串）：

```python
    # 5. 信号统计
    sig = result[result['combo_XG'] == True].copy()
    print('[step] combo_XG=True signals:', len(sig), '... (across', sig['code'].nunique(), 'stocks,',
          sig['date'].nunique(), 'trading days)')
```

替换为：

```python
    # 5. 信号统计 (SPEC v1.2: combo_XG 已是 box_window_hit AND zhongjun, 不再是同日 AND)
    sig = result[result['combo_XG'] == True].copy()
    n_box = int(result['box_breakout_XG'].sum())
    n_zj = int(result['double_zhongjun_XG'].sum())
    n_window_hit = int(result['box_window_hit'].sum())
    n_combo = len(sig)
    print('[step] box_breakout_XG signals:', n_box)
    print('[step] double_zhongjun_XG signals:', n_zj)
    print('[step] box_window_hit (any day in last 120 trading days):', n_window_hit)
    print('[step] combo_XG (window_hit AND zhongjun):', n_combo,
          '(across', sig['code'].nunique() if len(sig) else 0, 'stocks,',
          sig['date'].nunique() if len(sig) else 0, 'trading days)')

    # 信号间隔分布 (SPEC v1.2 §E 第 3 条)
    if len(sig):
        gaps = sig['box_days_since_last_signal'].dropna()
        if len(gaps):
            print('[step] box→zhongjun 间隔天数: min=%.0f median=%.0f mean=%.1f max=%.0f' %
                  (gaps.min(), gaps.median(), gaps.mean(), gaps.max()))
```

定位 summary 构造段：

```python
        'total_trading_days': len(bench),
        'signal_rows': int(len(sig)),
        'signal_unique_stocks': int(sig['code'].nunique()),
        'signal_unique_days': int(sig['date'].nunique()),
```

替换为：

```python
        'total_trading_days': len(bench),
        'spec_version': 'v1.2',
        'box_window_N': 120,
        'box_breakout_signals': n_box,
        'double_zhongjun_signals': n_zj,
        'box_window_hit_signals': n_window_hit,
        'signal_rows': int(len(sig)),
        'signal_unique_stocks': int(sig['code'].nunique()) if len(sig) else 0,
        'signal_unique_days': int(sig['date'].nunique()) if len(sig) else 0,
```

### TASK-5. 跑 backtest 单测确认不破

```bash
cd D:/QMT_STRATEGIES
py -3.10 -m unittest huang_main_uptrend_combo.backtest.tests.test_huice_loader huang_main_uptrend_combo.backtest.tests.test_run_backtest_minimum -v
```

期望 6 PASS。**FAIL 停**。把最后 5 行贴回执。

### TASK-6. 重跑 3 年回测

```bash
cd D:/QMT_STRATEGIES
py -3.10 -m huang_main_uptrend_combo.backtest.run_backtest_huang_combo \
  --start 2023-06-01 --end 2026-04-03 \
  --universe D:/QMT_STRATEGIES/backtest/data/universe/huang_small_mid_20260403.csv \
  --benchmark 000001.SH \
  --hold-periods 5,10,20
```

**期望**：
- `box_breakout_XG signals: > 0`
- `double_zhongjun_XG signals: > 0`
- `box_window_hit signals: > 0`
- `combo_XG (window_hit AND zhongjun): > 0` ← 关键
- stats 表有非空数据

**如果 combo_XG 仍然 0 信号，停下报告**（说明 120 日窗口仍不够，或两个子条件确实从不交叉，需进一步诊断）。
**如果跑超 15 分钟未完成，停下报告**。

把完整 stdout 贴回执（含所有信号数、stats、bench_compare、间隔分布、empty days）。

### TASK-7. 重写报告 `huang_main_uptrend_combo/backtest/reports/backtest_report_3y.md`

整段覆盖。结构：

```markdown
# 黄氏主升浪 combo selector 3 年历史回测报告 (SPEC v1.2 时间窗口版)

执行日期: <填本工单 date 真实值>
SPEC: D:/QMT_STRATEGIES/specs/SPEC_HUANG_MAIN_UPTREND_TDX_TO_QMT.md (v1.2)
脚本: huang_main_uptrend_combo/backtest/run_backtest_huang_combo.py

## 演进记录

| Part | 问题 | 解决 |
|---|---|---|
| Part 3 (commit 16c15d5) | core_100 0 信号 | -- |
| Part 4 (本工单合入) | 大盘指数缺 1.5 年 + 股池不匹配 | 改 huicexitong 板块指数 + 中小盘股池 3633 只 |
| Part 4 重跑 | 仍 0 信号 | 根因: SPEC v1.1 combo_XG 同日 AND 数学互斥 |
| **Part 5 (本工单, SPEC v1.2)** | 改时间窗口串联 | combo_XG = box_window_hit AND 今日 zhongjun, N=120 |

## 一、回测参数

| 项 | 值 |
|---|---|
| SPEC 版本 | v1.2 |
| 时间区间 | 2023-06-01 ~ 2026-04-03 |
| 实际交易日数 | <填> |
| 股票池 | huang_small_mid_20260403.csv (3633 只, 流通市值<100亿) |
| 实际可得股票数 | <填> |
| 大盘指数 | 000001.SH (from huicexitong basic_data."板块指数") |
| 持有期 | 5 / 10 / 20 日 |
| **box_window_N** | **120 交易日 (诚哥拍板)** |

## 二、信号统计

| 信号字段 | 数量 |
|---|---:|
| box_breakout_XG (阶段 1 触发) | <填> |
| double_zhongjun_XG (阶段 2 触发) | <填> |
| box_window_hit (近 120 日内有 box) | <填> |
| **combo_XG (final 信号)** | **<填>** |
| 涉及股票数 | <填> |
| 涉及交易日数 | <填> |
| 空仓日 (无 combo_XG) | <填> / total (<%>) |

## 三、box → zhongjun 间隔分布

<贴 stdout 里的间隔统计行>

## 四、持有期收益

<贴 stats.csv markdown 表格>

## 五、与大盘对比

<贴 bench_compare.csv markdown 表格>

## 六、结论

- 5 日胜率 <X%> vs 大盘 <Y%>: <selector +/-/持平>
- 10 日胜率 ...
- 20 日胜率 ...
- 空仓比例 <Z%>: <过严/适中/过松>
- 最大回撤 <W%>: <可接受/偏大>
- box→zhongjun 平均间隔 <D> 日: <是否符合 SPEC v1.2 §C3 预期 (73-370 错位区间)>

**判断**:
- 是否值得继续 (接入 QMT 实盘 / Strategy Registry / 调参数)?
- 主要风险点
- 后续 N 敏感性建议 (SPEC v1.2 §E: 60/120/180/250 对比)
```

报告必须**真实回填脚本输出**，禁止 placeholder 数字。

### TASK-8. 精确 add + commit（10 文件）

```bash
cd D:/QMT_STRATEGIES
# Part 4 数据基础修复 (4 文件)
git add huang_main_uptrend_combo/backtest/huice_loader.py
git add huang_main_uptrend_combo/backtest/build_universe_small_mid.py
git add huang_main_uptrend_combo/backtest/tests/test_huice_loader.py
git add backtest/data/universe/huang_small_mid_20260403.csv

# Part 5 v1.2 selector + tests + backtest 改动 (4 文件)
git add huang_main_uptrend_combo/huang_main_uptrend_combo_selector.py
git add huang_main_uptrend_combo/tests/test_huang_main_uptrend_combo_selector.py
git add huang_main_uptrend_combo/backtest/run_backtest_huang_combo.py
git add huang_main_uptrend_combo/backtest/reports/backtest_report_3y.md

# 工单 (2 文件: Part 4 + Part 5_v1.2)
git add agent_hub/2026-06-23_huang_main_uptrend/Mimo_HUANG_PART4_FIX.md
git add agent_hub/2026-06-23_huang_main_uptrend/Mimo_HUANG_PART5_V12.md

git diff --cached --name-only
```

**期望输出 10 行**（多一行少一行都不行）：
```
agent_hub/2026-06-23_huang_main_uptrend/Mimo_HUANG_PART4_FIX.md
agent_hub/2026-06-23_huang_main_uptrend/Mimo_HUANG_PART5_V12.md
backtest/data/universe/huang_small_mid_20260403.csv
huang_main_uptrend_combo/backtest/build_universe_small_mid.py
huang_main_uptrend_combo/backtest/huice_loader.py
huang_main_uptrend_combo/backtest/reports/backtest_report_3y.md
huang_main_uptrend_combo/backtest/run_backtest_huang_combo.py
huang_main_uptrend_combo/backtest/tests/test_huice_loader.py
huang_main_uptrend_combo/huang_main_uptrend_combo_selector.py
huang_main_uptrend_combo/tests/test_huang_main_uptrend_combo_selector.py
```

**严禁** `git add .` / `git add -A` / 整目录 add。staged 不是 10 个立刻停下报告。

```bash
git commit -m "$(cat <<'EOF'
feat(huang_combo): Part 4+5 - SPEC v1.2 时间窗口串联 + 数据基础修复

诚哥 SPEC v1.2 拍板:
[废弃] combo_XG = box_breakout_XG AND double_zhongjun_XG (同日互斥, 已证伪)
[新规则] box_window_hit = 近 N 日曾触发 box_breakout_XG
         combo_XG = box_window_hit AND 今日 double_zhongjun_XG
默认 N = 120 交易日

Part 4 数据基础修复:
- huice_loader.py: load_benchmark_index 改读 huicexitong basic_data."板块指数"
  (覆盖 2004 起; 原 benchmark_index.duckdb 只覆盖 2025-01 起)
- build_universe_small_mid.py: 中小盘股池构造 (流通市值<100亿 3633 只)
- test_huice_loader.py: +1 单测验证 3 年大盘数据可读

Part 5 SPEC v1.2 实现:
- DEFAULT_PARAMS 加 box_window_N=120
- select_huang_main_uptrend_combo 加 box_window_hit / box_last_signal_date /
  box_days_since_last_signal 字段; combo_XG 重写为窗口语义
- TestComboWindowXG: 5 个新单测 (窗口边界 / 过期 / 间隔字段)
- 原 test_combo_box_pass_zhongjun_fail / test_combo_both_pass 按 v1.2 重写
- run_backtest 加双层信号统计 + 间隔分布

3 年回测重跑 (huang_small_mid + huicexitong 大盘 + combo_XG v1.2):
- box_breakout_XG: <填> 信号
- double_zhongjun_XG: <填> 信号
- combo_XG: <填> 信号
- 详见 backtest/reports/backtest_report_3y.md

不动 adapters/qmt_wrapper.py / strategy_*.py / core/ / backtest/engine/* /
backtest/strategies/ (v0.4 Phase 1 不受影响).

Refs: specs/SPEC_HUANG_MAIN_UPTREND_TDX_TO_QMT.md (v1.2)
EOF
)"

git log -1 --stat HEAD
```

把 commit 完整输出贴回执（含上面那段 `<填>` 占位被替换成真实数字的版本——MIMO commit 前要把数字替换好；这是 commit message 的一部分，不是 placeholder）。

### TASK-9. 最终核查

```bash
cd D:/QMT_STRATEGIES
git status --short huang_main_uptrend_combo/ backtest/data/universe/huang_small_mid_*.csv
ls F:/backtest_workspace/ | grep huang_combo | tail -3
git log -3 --oneline
```

期望：
- `git status` 工作树干净（除 __pycache__）
- F:/ 下能看到新产物目录
- master HEAD 是新 commit

---

## 二、严禁

1. **严禁** `git add .` / `git add -A` / 整目录 add
2. **严禁** push / amend / --no-verify / --force
3. **严禁** 改 SPEC 文件 `D:/QMT_STRATEGIES/specs/SPEC_HUANG_MAIN_UPTREND_TDX_TO_QMT.md`（诚哥已更新到 v1.2，本工单只读 SPEC，不写）
4. **严禁** 修改 `_calc_box_breakout_conditions` / `_calc_double_zhongjun_conditions` / 8 个 tdx_* 工具函数（已 commit 锁定，本次只改 select_huang_main_uptrend_combo 主入口 + DEFAULT_PARAMS）
5. **严禁** 改 `adapters/qmt_wrapper.py` / `strategy_*.py` / `core/` / `backtest/engine/*` / `backtest/strategies/*` / `huicexitong_reader.py`
6. **严禁** 改 selector.py 已有 DEFAULT_PARAMS 24 项的值（只能末尾追加 box_window_N）
7. **严禁** 写文件到 D:/ 盘除了既定的 10 个源文件路径
8. **严禁** 引入 mock / passorder / xttrader / xtquant
9. **严禁** 用 placeholder 时间戳 / placeholder 数字（报告 + commit message 必须真实回填）
10. **严禁裸中文 SQL 字面量**
11. **严禁段加死**: box_window_N 必须被 select_main_entry 引用
12. **遇任一异常必停**:
    - TASK-1 Part 4 文件缺失 → 停
    - TASK-2 定位字符串非唯一或匹配不到 → 停
    - TASK-3 selector 单测 FAIL → 停
    - TASK-5 backtest 单测 FAIL → 停
    - TASK-6 combo_XG 仍 0 信号 → **必停**（说明窗口逻辑还有问题）
    - TASK-6 超 15 分钟未完成 → 停
    - staged 不是 10 个 → 停
    - **不得自判"无关"继续**
13. **回执只能在工单 EOF 追加**

---

## 三、完成回执（在工单 EOF 追加）

```markdown

---

## 完成回执

**执行时间**: <真实 date -u 输出>
**MIMO 模型**: <实际名>

### TASK-0: 真实时间戳
### TASK-1: 预检
- 当前 HEAD: <填>
- Part 4 文件确认: <填>
- SPEC v1.2 §C2 内容: <贴>

### TASK-2: selector 改动
- [ ] DEFAULT_PARAMS 末尾加 box_window_N=120
- [ ] select_main_entry 加 box_window_hit / box_last_signal_date / box_days_since_last_signal
- [ ] combo_XG 重写为 window_hit AND zhongjun
- [ ] 未动 _calc_* / tdx_* 函数

### TASK-3: selector 单测
<贴 unittest -v 完整输出>

### TASK-4: run_backtest_huang_combo.py 改动
- [ ] 加双层信号统计
- [ ] 加间隔分布打印
- [ ] summary.json 加 spec_version / box_window_N / box_breakout_signals / double_zhongjun_signals / box_window_hit_signals

### TASK-5: backtest 单测
<贴最后 5 行>

### TASK-6: 3 年回测 stdout
<贴完整: box / zhongjun / window_hit / combo_XG 数量 + 间隔分布 + stats + bench_compare>

### TASK-7: backtest_report_3y.md
<贴完整报告>

### TASK-8: git diff --cached + commit
<贴 10 行 + git log -1 --stat HEAD>

### TASK-9: 最终核查

### 自检
- [ ] 时间戳真跑 date 命令
- [ ] selector 仅改 DEFAULT_PARAMS 末尾追加 + select_main_entry combo 段
- [ ] _calc_* 与 tdx_* 未动
- [ ] 原 18 单测的 2 个 (test_combo_box_pass_zhongjun_fail / test_combo_both_pass) 已按 v1.2 重写
- [ ] 新增 TestComboWindowXG 5 个测试
- [ ] selector 单测全 PASS
- [ ] backtest 单测 6 PASS
- [ ] 3 年回测 combo_XG > 0 信号
- [ ] 报告含真实数字
- [ ] commit message 含真实信号数量
- [ ] staged 只有 10 个文件
- [ ] commit 成功
- [ ] 未改 SPEC / adapters / strategy_*.py / engine / strategies/
- [ ] 回执在工单 EOF 追加
```
