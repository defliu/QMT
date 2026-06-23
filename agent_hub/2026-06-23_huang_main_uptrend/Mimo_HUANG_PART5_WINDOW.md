# MIMO 工单：黄氏 combo Part 5 — selector 加滑动窗口串联 + Part 4 补丁 + 重跑回测

## 目的

Part 4 揭示 `combo_XG = box_breakout_XG AND double_zhongjun_XG` 同日 AND 在数学上互斥（箱体黏连 ↔ 多头排列发散互斥），3 年 0 信号。

按诚哥拍板：
1. **selector 加新字段** `combo_XG_window20`：滑动窗口串联（当日 zhongjun=True AND 近 20 日内任一日 box_breakout=True）
2. **保留原 `combo_XG` 字段不动**（Part 1/2 单测和报告依赖它，向后兼容）
3. **Part 4 改动一起 commit**：huice_loader 改读 huicexitong 板块指数 + 中小盘股池 + 单测
4. **重跑 3 年回测**，看 combo_XG_window20 效果

**前置 commit**: `16c15d5`
**预计工时**: 45-60 分钟

---

## 一、必做（10 步）

### TASK-0. 时间戳

```bash
date -u +"%Y-%m-%dT%H:%M:%SZ"
```

### TASK-1. 预检

```bash
cd D:/QMT_STRATEGIES
git status --short huang_main_uptrend_combo/ adapters/ strategy_main.py backtest/data/universe/
git log -1 --oneline
ls huang_main_uptrend_combo/backtest/
```

期望：HEAD = `16c15d5`，Part 4 的工作区改动还在（loader 改了、build_universe 已加、单测加了），但**还没 commit**。

把输出贴回执。**如果 Part 4 那 4 个改动文件不全（loader/build_universe/test_huice_loader/huang_small_mid_<date>.csv 任一缺失），停下报告**。

### TASK-2. 修改 `huang_main_uptrend_combo/huang_main_uptrend_combo_selector.py` — 加 combo_XG_window20

**不删/不改任何已有代码**，只在 `select_huang_main_uptrend_combo` 函数里追加 1 行 + 在 DEFAULT_PARAMS 加 1 个键。

#### 2a. 在 DEFAULT_PARAMS 末尾（'benchmark_code' 之后）追加

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
    # 组合串联窗口 (v1.2: SPEC §C 同日 AND 互斥, 改滑动窗口)
    'combo_window_N': 20,
}
```

#### 2b. 在 `select_huang_main_uptrend_combo` 主入口的 combo_XG 计算之后追加 combo_XG_window20

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
        merged['combo_XG'] = merged['box_breakout_XG'] & merged['double_zhongjun_XG']
        # v1.2 滑动窗口串联: 当日 zhongjun=True 且近 N 日内任一日 box_breakout=True
        # 解决 SPEC v1.1 同日 AND 互斥问题 (箱体黏连 vs 多头排列发散互斥)
        win_N = p['combo_window_N']
        box_in_window = merged['box_breakout_XG'].rolling(window=win_N, min_periods=1).max().astype(bool)
        merged['combo_XG_window20'] = merged['double_zhongjun_XG'] & box_in_window
        merged.insert(0, 'date', df.index)
        merged.insert(0, 'code', code)
        results.append(merged)
```

**注意**：字段名固定 `combo_XG_window20`（不要写成 `_window_N` 之类的动态名），即使 N 参数化也保持字段名固定。这样向下游脚本接口稳定。

### TASK-3. 加单测 `huang_main_uptrend_combo/tests/test_huang_main_uptrend_combo_selector.py`

在 `TestComboXG` 类之后、`TestCompletenessEdgeCases` 之前，新增 1 个类：

```python


class TestComboWindowXG(unittest.TestCase):
    """v1.2 滑动窗口串联 combo_XG_window20"""

    def test_window_signal_box_then_zhongjun(self):
        """构造: 第 30 日 box True, 第 40 日 zhongjun True
        预期: 第 40 日 combo_XG_window20=True (窗口内有 box)
        """
        import pandas as pd
        import numpy as np
        # 直接用 DataFrame 模拟两个 XG, 不跑 selector (单元粒度)
        n = 100
        dates = pd.date_range('2026-01-01', periods=n)
        box_xg = pd.Series([False] * n, index=dates)
        zj_xg = pd.Series([False] * n, index=dates)
        box_xg.iloc[30] = True
        zj_xg.iloc[40] = True

        # 滑动窗口 20
        win_N = 20
        box_in_window = box_xg.rolling(window=win_N, min_periods=1).max().astype(bool)
        combo = zj_xg & box_in_window

        # 第 40 日 (距 box 10 天, 在 20 日窗口内) 应触发
        self.assertTrue(combo.iloc[40])
        # 第 30 日单独 box, 无 zj -> False
        self.assertFalse(combo.iloc[30])

    def test_window_signal_box_too_old(self):
        """box 在第 10 日, zhongjun 在第 40 日, 距离 30 天超出 20 日窗口 -> False"""
        import pandas as pd
        n = 100
        dates = pd.date_range('2026-01-01', periods=n)
        box_xg = pd.Series([False] * n, index=dates)
        zj_xg = pd.Series([False] * n, index=dates)
        box_xg.iloc[10] = True
        zj_xg.iloc[40] = True

        box_in_window = box_xg.rolling(window=20, min_periods=1).max().astype(bool)
        combo = zj_xg & box_in_window
        self.assertFalse(combo.iloc[40])

    def test_window_via_select_main_entry(self):
        """通过 select_huang_main_uptrend_combo 主入口验证: 返回 DataFrame 含 combo_XG_window20 字段"""
        import pandas as pd
        import numpy as np
        from huang_main_uptrend_combo.huang_main_uptrend_combo_selector import (
            select_huang_main_uptrend_combo,
        )
        # 用最小数据 (60+ 日) 跑通主入口, 只验字段存在
        n = 100
        dates = pd.date_range('2026-01-01', periods=n)
        df = pd.DataFrame({
            'open': [10.0 + i * 0.01 for i in range(n)],
            'high': [10.1 + i * 0.01 for i in range(n)],
            'low': [9.9 + i * 0.01 for i in range(n)],
            'close': [10.0 + i * 0.01 for i in range(n)],
            'volume': [1000.0] * n,
        }, index=dates)
        index_df = pd.DataFrame({'close': [3000.0 + i for i in range(n)]}, index=dates)
        result = select_huang_main_uptrend_combo({'TEST': df}, index_df)
        self.assertIn('combo_XG_window20', result.columns)
        # 短数据下 combo_XG_window20 应全 False (无信号)
        self.assertEqual(int(result['combo_XG_window20'].sum()), 0)
```

跑全部 selector 单测：

```bash
cd D:/QMT_STRATEGIES
py -3.10 -m unittest huang_main_uptrend_combo.tests.test_huang_main_uptrend_combo_selector -v
```

期望：21 PASS（原 18 + 新 3）。**任一 FAIL 停**。把输出贴回执。

### TASK-4. 修改 `huang_main_uptrend_combo/backtest/run_backtest_huang_combo.py` — 同时算 combo_XG 和 combo_XG_window20

定位（精确字符串，only 1 处）：

```python
    # 5. 信号统计
    sig = result[result['combo_XG'] == True].copy()
    print('[step] combo_XG=True signals:', len(sig), '... (across', sig['code'].nunique(), 'stocks,',
          sig['date'].nunique(), 'trading days)')
```

替换为：

```python
    # 5. 信号统计 (v1.2: 既看原 combo_XG 也看 combo_XG_window20)
    n_combo_orig = int(result['combo_XG'].sum())
    n_combo_win = int(result['combo_XG_window20'].sum())
    print('[step] combo_XG (同日 AND) signals:', n_combo_orig)
    print('[step] combo_XG_window20 (滑动窗口) signals:', n_combo_win)
    # 以 combo_XG_window20 作为主信号源跑后续评估
    sig = result[result['combo_XG_window20'] == True].copy()
    print('[step] using combo_XG_window20 for evaluation:', len(sig),
          '(across', sig['code'].nunique() if len(sig) else 0, 'stocks,',
          sig['date'].nunique() if len(sig) else 0, 'trading days)')
```

定位（精确字符串）—— summary.json 也加新字段：

```python
    summary = {
        'run_id': run_id,
        'start': args.start,
        'end': args.end,
        'universe_path': args.universe,
        'universe_size': len(codes),
        'codes_with_data': len(ohlcv),
        'benchmark': args.benchmark,
        'benchmark_rows': len(bench),
        'total_trading_days': len(bench),
        'signal_rows': int(len(sig)),
        'signal_unique_stocks': int(sig['code'].nunique()),
        'signal_unique_days': int(sig['date'].nunique()),
        'empty_days': len(empty_days),
        'empty_days_pct': 100.0 * len(empty_days) / max(1, len(bench)),
        'stats': stats,
        'bench_compare': bench_compare,
        'created': datetime.now().isoformat(),
    }
```

替换为：

```python
    summary = {
        'run_id': run_id,
        'start': args.start,
        'end': args.end,
        'universe_path': args.universe,
        'universe_size': len(codes),
        'codes_with_data': len(ohlcv),
        'benchmark': args.benchmark,
        'benchmark_rows': len(bench),
        'total_trading_days': len(bench),
        'combo_XG_orig_signals': n_combo_orig,
        'combo_XG_window20_signals': n_combo_win,
        'signal_source': 'combo_XG_window20',
        'signal_rows': int(len(sig)),
        'signal_unique_stocks': int(sig['code'].nunique()) if len(sig) else 0,
        'signal_unique_days': int(sig['date'].nunique()) if len(sig) else 0,
        'empty_days': len(empty_days),
        'empty_days_pct': 100.0 * len(empty_days) / max(1, len(bench)),
        'stats': stats,
        'bench_compare': bench_compare,
        'created': datetime.now().isoformat(),
    }
```

### TASK-5. 跑 backtest 单测确认改动没破

```bash
cd D:/QMT_STRATEGIES
py -3.10 -m unittest huang_main_uptrend_combo.backtest.tests.test_huice_loader huang_main_uptrend_combo.backtest.tests.test_run_backtest_minimum -v
```

期望：6 PASS（与 Part 4 同）。**FAIL 停**。贴输出。

### TASK-6. 跑真实 3 年回测（中小盘 + 大盘 huicexitong + combo_XG_window20）

```bash
cd D:/QMT_STRATEGIES
py -3.10 -m huang_main_uptrend_combo.backtest.run_backtest_huang_combo \
  --start 2023-06-01 --end 2026-04-03 \
  --universe D:/QMT_STRATEGIES/backtest/data/universe/huang_small_mid_20260403.csv \
  --benchmark 000001.SH \
  --hold-periods 5,10,20
```

**期望**：
- `combo_XG (同日 AND) signals: 0`（确认原公式仍然 0，验证根因）
- `combo_XG_window20 (滑动窗口) signals: > 0`（新逻辑应有信号）
- 评估有有效样本（stats 表非空）

**如果 combo_XG_window20 仍然 0 信号**，停下报告（说明窗口逻辑或参数还有问题）。
**如果跑超 15 分钟未完成**，停下报告。

把完整 stdout 贴回执（含 stats、bench_compare、empty days 完整数字）。

### TASK-7. 重写报告 `huang_main_uptrend_combo/backtest/reports/backtest_report_3y.md`

整段覆盖前版。结构：

```markdown
# 黄氏主升浪 combo selector 3 年历史回测报告 (Part 5 / v1.2 滑动窗口版)

执行日期: <填本工单 date 真实值>
SPEC: D:/QMT_STRATEGIES/specs/SPEC_HUANG_MAIN_UPTREND_TDX_TO_QMT.md (v1.1 公式)
脚本: huang_main_uptrend_combo/backtest/run_backtest_huang_combo.py

## 演进记录

| Part | 问题 | 修复 |
|---|---|---|
| Part 3 (commit 16c15d5) | core_100 0 信号 | -- |
| Part 4 (未 commit) | 大盘指数缺 1.5 年 + 股池不匹配 | 换 huicexitong 板块指数 + 中小盘股池 (3633 只) |
| Part 4 重跑 | 大盘已修+股池已换, 仍 0 信号 | 根因: combo_XG 同日 AND 数学互斥 (箱体黏连 vs 多头排列发散) |
| **Part 5 (本次)** | 改 selector 加滑动窗口字段 combo_XG_window20 | 当日 zhongjun=True AND 近 20 日内任一日 box_breakout=True |

selector v1.1 原字段 `combo_XG` (同日 AND) **保留不删** (向后兼容).
新字段 `combo_XG_window20` 作为本回测的主信号源.

---

## 一、回测参数
... (同 Part 4 模板, 字段都填真实数字)

## 二、信号统计

| 指标 | 数值 |
|---|---:|
| combo_XG (同日 AND) | <填 n_combo_orig> |
| **combo_XG_window20 (滑动窗口 N=20)** | <填 n_combo_win> |
| ... |

## 三、持有期收益

<贴 stats.csv>

## 四、与大盘对比

<贴 bench_compare.csv>

## 五、结论

- 5/10/20 日胜率对比大盘
- 空仓比例
- 最大回撤
- 是否值得继续 / 后续建议
```

报告内容必须**真实回填脚本输出**，禁止 placeholder。

### TASK-8. 精确 add + commit（10 文件）

**注意**：Part 4 未 commit 的 4 文件 + Part 5 新增/修改的 6 文件 = 10 文件。

```bash
cd D:/QMT_STRATEGIES
# Part 4 未 commit 的 4 文件
git add huang_main_uptrend_combo/backtest/huice_loader.py
git add huang_main_uptrend_combo/backtest/build_universe_small_mid.py
git add huang_main_uptrend_combo/backtest/tests/test_huice_loader.py
git add backtest/data/universe/huang_small_mid_20260403.csv

# Part 5 新增/修改
git add huang_main_uptrend_combo/huang_main_uptrend_combo_selector.py
git add huang_main_uptrend_combo/tests/test_huang_main_uptrend_combo_selector.py
git add huang_main_uptrend_combo/backtest/run_backtest_huang_combo.py
git add huang_main_uptrend_combo/backtest/reports/backtest_report_3y.md

# Part 4 + Part 5 工单
git add agent_hub/2026-06-23_huang_main_uptrend/Mimo_HUANG_PART4_FIX.md
git add agent_hub/2026-06-23_huang_main_uptrend/Mimo_HUANG_PART5_WINDOW.md

git diff --cached --name-only
```

**期望输出 10 行**（多一行少一行都不行）：
```
agent_hub/2026-06-23_huang_main_uptrend/Mimo_HUANG_PART4_FIX.md
agent_hub/2026-06-23_huang_main_uptrend/Mimo_HUANG_PART5_WINDOW.md
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
feat(huang_combo): Part 4+5 - 大盘源修复 + selector 加滑动窗口 combo_XG_window20

Part 3 (16c15d5) core_100 0 信号; Part 4 换数据/股池仍 0 信号;
根因: selector v1.1 combo_XG = box AND zhongjun 同日互斥
(箱体要求黏连, zhongjun 要求多头排列发散, 数学上不可能同时 True).

Part 4 修复 (数据基础):
- huice_loader.py: load_benchmark_index 改读 huicexitong basic_data."板块指数"
  (000001.SH 覆盖 2004 起; 原 benchmark_index.duckdb 只覆盖 2025-01 起)
- build_universe_small_mid.py: 中小盘股池构造 (流通市值 <100亿 3633 只)
- test_huice_loader.py: +1 单测验证 3 年大盘数据可读

Part 5 selector v1.2 (诚哥拍板):
- DEFAULT_PARAMS 加 combo_window_N=20
- select_huang_main_uptrend_combo 加 combo_XG_window20 字段:
  当日 double_zhongjun_XG=True AND 近 20 日内任一日 box_breakout_XG=True
- 原 combo_XG (同日 AND) 保留, 向后兼容 Part 1/2 单测
- TestComboWindowXG: 3 个新单测

3 年回测重跑 (huang_small_mid + huicexitong 大盘 + combo_XG_window20):
- combo_XG 同日 AND: 0 信号 (验证根因)
- combo_XG_window20: <填 n_combo_win> 信号
- 详见 backtest/reports/backtest_report_3y.md

不动 adapters/qmt_wrapper.py / strategy_*.py / core/ / backtest/engine/*.
EOF
)"

git log -1 --stat HEAD
```

把 commit 完整输出贴回执。

### TASK-9. 最终核查

```bash
cd D:/QMT_STRATEGIES
git status --short huang_main_uptrend_combo/ backtest/data/universe/huang_small_mid_*.csv
ls F:/backtest_workspace/ | grep huang_combo | tail -3
```

期望：`git status` 无源文件 dirty，F:/ 下有新回测产物目录。

---

## 二、严禁

1. **严禁** `git add .` / `git add -A` / 整目录 add
2. **严禁** push / amend / --no-verify / --force
3. **严禁** 改 SPEC 文件 `D:/QMT_STRATEGIES/specs/SPEC_HUANG_MAIN_UPTREND_TDX_TO_QMT.md`（SPEC v1.2 是否更新由诚哥后续决定）
4. **严禁** 删除原 `combo_XG` 字段或改其计算逻辑（向后兼容）
5. **严禁** 修改 `_calc_box_breakout_conditions` / `_calc_double_zhongjun_conditions` / 8 个 tdx_* 工具函数（已 commit 锁定）
6. **严禁** 改 `adapters/qmt_wrapper.py` / `strategy_*.py` / `core/` / `backtest/engine/*` / `huicexitong_reader.py`
7. **严禁** 改 `selector.py` 已有 DEFAULT_PARAMS 24 项的值（只能在末尾追加 combo_window_N）
8. **严禁** 写文件到 D:/ 盘除了既定的 6 个源文件路径
9. **严禁** 引入 mock / passorder / xttrader / xtquant
10. **严禁** 用 placeholder 时间戳 / placeholder 数字（报告必须真实回填）
11. **严禁裸中文 SQL 字面量**
12. **严禁段加死**: combo_window_N 必须被 selector 函数体引用
13. **遇任一异常必停**:
    - TASK-1 Part 4 文件缺失 → 停
    - TASK-2 定位字符串非唯一或匹配不到 → 停
    - TASK-3 单测 FAIL → 停
    - TASK-5 backtest 单测 FAIL → 停
    - TASK-6 combo_XG_window20 仍 0 信号 → **必停**（说明窗口逻辑或参数还有问题）
    - TASK-6 超 15 分钟未完成 → 停
    - staged 不是 10 个 → 停
    - **不得自判"无关"继续**
14. **回执只能在工单 EOF 追加**

---

## 三、完成回执（在工单 EOF 追加）

```markdown

---

## 完成回执

**执行时间**: <真实 date -u 输出>
**MIMO 模型**: <实际名>

### TASK-0: 真实时间戳
### TASK-1: 预检
### TASK-2: selector 加 combo_XG_window20
- [ ] DEFAULT_PARAMS 加 combo_window_N=20
- [ ] select_main_entry 加滑动窗口逻辑
- [ ] 原 combo_XG 字段未动

### TASK-3: selector 单测 (21 PASS)
<贴完整>

### TASK-4: run_backtest 加双信号统计

### TASK-5: backtest 单测 (6 PASS)
<贴最后 5 行>

### TASK-6: 3 年回测 stdout
<贴完整, 含 combo_XG / combo_XG_window20 双信号 / stats / bench_compare>

### TASK-7: backtest_report_3y.md
<贴完整报告>

### TASK-8: git diff --cached + commit
<贴 10 行 + git log -1 --stat HEAD>

### TASK-9: 最终核查
<贴>

### 自检
- [ ] 时间戳真跑 date 命令
- [ ] selector 原 combo_XG 未动, 只追加 combo_XG_window20
- [ ] DEFAULT_PARAMS 仅末尾追加 combo_window_N
- [ ] selector 单测 21 PASS (原 18 + 新 3)
- [ ] backtest 单测 6 PASS
- [ ] 3 年回测 combo_XG_window20 > 0 信号
- [ ] 报告含真实数字
- [ ] staged 只有 10 个文件
- [ ] commit 成功
- [ ] 未改 SPEC / adapters / strategy_*.py / engine
- [ ] 回执在工单 EOF 追加
```
