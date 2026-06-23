# MIMO 工单：黄氏主升浪组合选股 — Part 1 / 2 (核心 selector + TDX 映射 + 单元测试)

## 目的

按 SPEC `D:\QMT_STRATEGIES\specs\SPEC_HUANG_MAIN_UPTREND_TDX_TO_QMT.md` 复刻黄氏主升浪「箱体突破初选 + 双中军精筛」**组合选股逻辑**。

**本工单只做 Part 1**：
- 目录结构 + 核心 selector 模块
- TDX → Python 映射函数
- 单元测试（必须全 PASS）

**Part 2** 由后续工单完成：config.yaml、tdx_mapping_report.md、最小样本验证报告。

**前置 commit**：`44bd768`
**INDEXC 默认值**：`000001.SH`（诚哥已拍板，但 Part 1 不实际加载指数，只在签名和默认 params 里留位）
**预计工时**：30-45 分钟

---

## 一、必做（7 项）

### TASK-0. 时间戳

```bash
date -u +"%Y-%m-%dT%H:%M:%SZ"
```

回执"执行时间"填这个真实值。**严禁** placeholder。

### TASK-1. 预检

```bash
cd D:/QMT_STRATEGIES
ls huang_main_uptrend_combo/ 2>&1
git log -1 --oneline
```

期望：
- `huang_main_uptrend_combo/` 不存在（或为空）
- HEAD = `44bd768`

如果目录已存在且非空，立刻停下报告。

### TASK-2. 创建目录结构

```text
D:\QMT_STRATEGIES\huang_main_uptrend_combo\
  __init__.py                            (空)
  huang_main_uptrend_combo_selector.py   (主模块, 见 TASK-3)
  tests\
    __init__.py                          (空)
    test_huang_main_uptrend_combo_selector.py  (见 TASK-4)
```

**config.yaml / reports/ / README.md 暂不创建（Part 2 处理）**。

文件统一编码 `# coding=utf-8`（本模块**离线纯 Python**，不进 build_strategy.py，不进 QMT，所以不强制 GBK；Python 3.6.8 兼容仍然必须）。

### TASK-3. 写 `huang_main_uptrend_combo_selector.py`

**文件头**：
```python
# coding=utf-8
"""黄氏主升浪「箱体突破初选 + 双中军精筛」组合选股 selector.

SPEC: D:/QMT_STRATEGIES/specs/SPEC_HUANG_MAIN_UPTREND_TDX_TO_QMT.md
原始公式: F:/天翼云盘同步盘/Obsidian/量化知识库/20_策略知识库/黄氏主升浪策略.txt

最终唯一输出: combo_XG = box_breakout_XG AND double_zhongjun_XG

离线纯 Python 模块, 不进 build_strategy.py, 不接 QMT 实盘下单接口.
Python 3.6.8 兼容: 禁 dict[str,...] / str | None / walrus / match-case / dataclass.
"""
```

**默认参数**（SPEC §D 全字段，**不要擅改默认值**）：
```python
DEFAULT_PARAMS = {
    # 箱体突破
    'box_N': 60,
    'box_amp_thresh': 20.0,        # 箱体振幅 <20%
    'box_ma_short': 5,             # MA_SHORT, 原公式定义但未参与 XG, 保留为参数不参与
    'box_ma_adhere_thresh': 5.0,   # 均线差 <5%
    'box_vol_ratio': 1.5,          # V > MA(V,5) * 1.5
    'box_break_tol': 0.995,        # C >= 箱顶 * 0.995
    'box_pct_thresh': 0.05,        # 涨幅 > 0.05
    # 双中军
    'zj_ma5': 5,
    'zj_ma10': 10,
    'zj_ma20': 20,
    'zj_ma60': 60,
    'zj_ma120': 120,
    'zj_angle_thresh': 30.0,       # MA5 角度 > 30
    'zj_divergence_thresh': 1.05,  # MA5/MA20 > 1.05
    'zj_macd_fast': 12,
    'zj_macd_slow': 26,
    'zj_macd_signal': 9,
    'zj_cci_period': 14,
    'zj_cci_thresh': 100.0,
    'zj_breakout_N': 20,
    'zj_breakout_upper': 1.08,     # CLOSE/近期高点 < 1.08
    'zj_ma20_up_n': 5,
    'zj_ma60_up_n': 5,
    # 大盘指数
    'benchmark_code': '000001.SH',
}
```

**TDX → Python 映射工具函数**（模块顶部，独立可单测）：
```python
def tdx_ma(s, n):
    """MA(X,N): N 日简单移动平均"""
    return s.rolling(window=n, min_periods=n).mean()


def tdx_ema(s, n):
    """EMA(X,N) 通达信口径: alpha=2/(N+1), 递归 (adjust=False)"""
    return s.ewm(alpha=2.0 / (n + 1), adjust=False).mean()


def tdx_ref(s, n):
    """REF(X,N): 向前 N 日引用 (不含当日, 严禁未来数据)"""
    return s.shift(n)


def tdx_hhv(s, n):
    """HHV(X,N): 最近 N 日最高 (含当日)"""
    return s.rolling(window=n, min_periods=n).max()


def tdx_llv(s, n):
    """LLV(X,N): 最近 N 日最低 (含当日)"""
    return s.rolling(window=n, min_periods=n).min()


def tdx_cross(a, b):
    """CROSS(A,B): 当日 A>B 且昨日 A<=B"""
    return (a > b) & (a.shift(1) <= b.shift(1))


def tdx_count(cond, n):
    """COUNT(COND,N): 最近 N 日条件成立次数"""
    return cond.astype(float).rolling(window=n, min_periods=n).sum()


def tdx_avedev(s, n):
    """AVEDEV(X,N): N 日平均绝对偏差, 用于 CCI"""
    import numpy as _np
    return s.rolling(window=n, min_periods=n).apply(
        lambda x: _np.mean(_np.abs(x - _np.mean(x))), raw=True
    )
```

**两层条件计算**（要求每个子条件都作为独立 Series 输出到 DataFrame，便于 SPEC §Testing 第 5 条逐项核对）：

```python
def _calc_box_breakout_conditions(df, params):
    """箱体突破版初选条件计算.

    输入 df 必须含列: open, high, low, close, volume, 按日期升序.
    返回 DataFrame, 含以下中间字段 + box_breakout_XG:
      box_箱顶, box_箱底, box_箱体振幅,
      box_MA5, box_MA10, box_MA20, box_均线差1, box_均线差2,
      box_前5日量, box_量比, box_涨幅,
      box_箱体振幅_ok, box_均线黏连_ok, box_放量_ok, box_突破_ok, box_涨幅_ok,
      box_breakout_XG
    """
    import pandas as _pd
    import numpy as _np

    N = params['box_N']
    out = _pd.DataFrame(index=df.index)

    # 箱体识别
    out['box_箱顶'] = tdx_hhv(df['high'], N)
    out['box_箱底'] = tdx_llv(df['low'], N)
    out['box_箱体振幅'] = (out['box_箱顶'] - out['box_箱底']) / out['box_箱底'] * 100.0

    # 均线黏连
    out['box_MA5'] = tdx_ma(df['close'], 5)
    out['box_MA10'] = tdx_ma(df['close'], 10)
    out['box_MA20'] = tdx_ma(df['close'], 20)
    out['box_均线差1'] = (out['box_MA5'] - out['box_MA10']).abs() / out['box_MA5'] * 100.0
    out['box_均线差2'] = (out['box_MA10'] - out['box_MA20']).abs() / out['box_MA10'] * 100.0

    # 放量突破
    out['box_前5日量'] = tdx_ma(df['volume'], 5)
    out['box_量比'] = df['volume'] / out['box_前5日量']
    out['box_涨幅'] = df['close'] / tdx_ref(df['close'], 1) - 1.0

    # 子条件 (NaN 视为 False)
    amp_thresh = params['box_amp_thresh']
    adh = params['box_ma_adhere_thresh']
    vr = params['box_vol_ratio']
    btol = params['box_break_tol']
    pct = params['box_pct_thresh']

    out['box_箱体振幅_ok'] = (out['box_箱体振幅'] < amp_thresh).fillna(False)
    out['box_均线黏连_ok'] = ((out['box_均线差1'] < adh) & (out['box_均线差2'] < adh)).fillna(False)
    out['box_放量_ok'] = (df['volume'] > out['box_前5日量'] * vr).fillna(False)
    out['box_突破_ok'] = (df['close'] >= out['box_箱顶'] * btol).fillna(False)
    out['box_涨幅_ok'] = (out['box_涨幅'] > pct).fillna(False)

    out['box_breakout_XG'] = (
        out['box_箱体振幅_ok'] & out['box_均线黏连_ok'] & out['box_放量_ok']
        & out['box_突破_ok'] & out['box_涨幅_ok']
    )
    return out


def _calc_double_zhongjun_conditions(df, index_df, params):
    """双中军版精筛条件计算.

    输入:
      df: 个股 DataFrame, 含 open, high, low, close, volume, 日期升序
      index_df: 大盘指数 DataFrame, 含 close, 日期升序, index 必须与 df 对齐 (或前向 reindex)

    返回 DataFrame, 含以下中间字段 + double_zhongjun_XG:
      double_MA5/10/20/60/120, double_MA5角度,
      double_DIF, double_DEA, double_MACD红柱,
      double_TYP, double_CCI14,
      double_近期高点,
      double_大盘指数, double_大盘MA20, double_大盘MA60,
      double_多头排列_ok, double_均线发散_ok, double_MACD_ok, double_CCI_ok,
      double_突破压力_ok, double_MA20向上_ok, double_MA60向上_ok, double_大盘_ok,
      double_zhongjun_XG
    """
    import pandas as _pd
    import numpy as _np

    out = _pd.DataFrame(index=df.index)

    # 1. 多头排列
    MA5 = tdx_ma(df['close'], params['zj_ma5'])
    MA10 = tdx_ma(df['close'], params['zj_ma10'])
    MA20 = tdx_ma(df['close'], params['zj_ma20'])
    MA60 = tdx_ma(df['close'], params['zj_ma60'])
    MA120 = tdx_ma(df['close'], params['zj_ma120'])
    out['double_MA5'] = MA5
    out['double_MA10'] = MA10
    out['double_MA20'] = MA20
    out['double_MA60'] = MA60
    out['double_MA120'] = MA120
    out['double_多头排列_ok'] = (
        (MA5 > MA10) & (MA10 > MA20) & (MA20 > MA60) & (MA60 > MA120)
    ).fillna(False)

    # 2. 均线刚发散
    # 发散确认 (CLOSE>MA20) 在原公式中定义但未参与最终 XG, 不加入 ok
    angle_pct = (MA5 / tdx_ref(MA5, 1) - 1.0) * 100.0
    out['double_MA5角度'] = _np.degrees(_np.arctan(angle_pct))
    out['double_均线发散_ok'] = (
        (out['double_MA5角度'] > params['zj_angle_thresh'])
        & (MA5 / MA20 > params['zj_divergence_thresh'])
    ).fillna(False)

    # 3. MACD
    DIF = tdx_ema(df['close'], params['zj_macd_fast']) - tdx_ema(df['close'], params['zj_macd_slow'])
    DEA = tdx_ema(DIF, params['zj_macd_signal'])
    out['double_DIF'] = DIF
    out['double_DEA'] = DEA
    out['double_MACD红柱'] = (DIF - DEA) * 2.0  # 原公式定义但未参与 XG, 仅作 debug 字段
    out['double_MACD_ok'] = (
        (tdx_cross(DIF, DEA) & (DEA > 0))
        | ((DIF > DEA) & (DIF > tdx_ref(DIF, 1)) & (DEA > tdx_ref(DEA, 1)))
    ).fillna(False)

    # 4. CCI
    TYP = (df['high'] + df['low'] + df['close']) / 3.0
    out['double_TYP'] = TYP
    cci_p = params['zj_cci_period']
    cci = (TYP - tdx_ma(TYP, cci_p)) / (0.015 * tdx_avedev(TYP, cci_p))
    out['double_CCI14'] = cci
    cci_th = params['zj_cci_thresh']
    out['double_CCI_ok'] = (
        tdx_cross(cci, _pd.Series(cci_th, index=cci.index))
        | ((cci > cci_th) & (cci > tdx_ref(cci, 1)))
    ).fillna(False)

    # 5. 突破压力位 (REF(HHV(HIGH, N), 1) 不含当日, 避免当日自引用)
    bk_N = params['zj_breakout_N']
    near_high = tdx_ref(tdx_hhv(df['high'], bk_N), 1)
    out['double_近期高点'] = near_high
    out['double_突破压力_ok'] = (
        (df['close'] > near_high) & (df['close'] / near_high < params['zj_breakout_upper'])
    ).fillna(False)

    # 8. 中期趋势确认
    out['double_MA20向上_ok'] = (MA20 > tdx_ref(MA20, params['zj_ma20_up_n'])).fillna(False)
    out['double_MA60向上_ok'] = (MA60 > tdx_ref(MA60, params['zj_ma60_up_n'])).fillna(False)

    # 9. 大盘环境过滤
    # index_df 要求按日期升序; reindex 到 df.index, 前向填充
    if index_df is None or 'close' not in index_df.columns:
        # 无指数数据 -> 大盘条件全 False
        out['double_大盘指数'] = _np.nan
        out['double_大盘MA20'] = _np.nan
        out['double_大盘MA60'] = _np.nan
        out['double_大盘_ok'] = False
    else:
        idx_close = index_df['close'].reindex(df.index, method='ffill')
        idx_ma20 = tdx_ma(idx_close, 20)
        idx_ma60 = tdx_ma(idx_close, 60)
        out['double_大盘指数'] = idx_close
        out['double_大盘MA20'] = idx_ma20
        out['double_大盘MA60'] = idx_ma60
        out['double_大盘_ok'] = (
            (idx_close > idx_ma20) & (idx_ma20 > idx_ma60)
        ).fillna(False)

    # 组合
    out['double_zhongjun_XG'] = (
        out['double_多头排列_ok']
        & out['double_均线发散_ok']
        & out['double_MACD_ok']
        & out['double_CCI_ok']
        & out['double_突破压力_ok']
        & out['double_MA20向上_ok']
        & out['double_MA60向上_ok']
        & out['double_大盘_ok']
    )
    return out


def select_huang_main_uptrend_combo(data, index_data, params=None):
    """主入口: 组合选股.

    Args:
        data: dict {code: DataFrame} 或单个 DataFrame.
              每个 DataFrame 必须含列 [open, high, low, close, volume], 日期升序 (index 是日期).
        index_data: DataFrame, 含列 [close], 日期升序 (index 是日期). 大盘指数(INDEXC).
                    None 表示无指数, 大盘条件视为 False.
        params: dict 可选, 覆盖 DEFAULT_PARAMS 部分键. None 用全默认值.

    Returns:
        DataFrame, 行 = code × date, 列含:
          code, date,
          box_* 中间字段 + box_breakout_XG,
          double_* 中间字段 + double_zhongjun_XG,
          combo_XG (= box_breakout_XG AND double_zhongjun_XG)
    """
    import pandas as _pd

    p = dict(DEFAULT_PARAMS)
    if params:
        p.update(params)

    if isinstance(data, _pd.DataFrame):
        data = {'_single': data}

    results = []
    for code, df in data.items():
        if df is None or df.empty:
            continue
        df = df.sort_index()
        box = _calc_box_breakout_conditions(df, p)
        dbl = _calc_double_zhongjun_conditions(df, index_data, p)
        merged = _pd.concat([box, dbl], axis=1)
        merged['combo_XG'] = merged['box_breakout_XG'] & merged['double_zhongjun_XG']
        merged.insert(0, 'date', df.index)
        merged.insert(0, 'code', code)
        results.append(merged)

    if not results:
        return _pd.DataFrame()
    return _pd.concat(results, axis=0, ignore_index=True)
```

**注意**：
- 所有子条件 `.fillna(False)` 保证滚动窗口起步阶段 NaN 不污染最终 XG。
- 大盘条件 index_data=None 时全 False (合理：无指数数据则无法判断大盘环境，保守不选股)。
- TDX→Python 映射函数全部独立可测。

### TASK-4. 写 `tests/test_huang_main_uptrend_combo_selector.py`

**unittest 风格**（与项目其他测试一致，见 `tests/test_risk_timegate_p3.py`）。

要求覆盖：

**A. TDX 映射工具函数 (8 个测试)**
- `test_tdx_ma_basic`：长度 5、N=3，验证手算值
- `test_tdx_ema_basic`：长度 5、N=3，验证 alpha=2/4=0.5 的递归值
- `test_tdx_ref_basic`：shift(1)、shift(2) 各验 1 个
- `test_tdx_hhv_basic`：N=3 的滚动最大值
- `test_tdx_llv_basic`：N=3 的滚动最小值
- `test_tdx_cross_basic`：构造 a/b 序列在某日金叉，验证位置正确
- `test_tdx_count_basic`：N=5 内有 3 个 True，验证计数
- `test_tdx_avedev_basic`：N=3 的均偏，手算对比

**B. 箱体突破子条件 (2 个测试)**
- `test_box_breakout_positive_case`：构造 60+ 日 OHLCV，最后一日满足所有 5 项 → box_breakout_XG=True
- `test_box_breakout_negative_case`：缩量未突破 → box_breakout_XG=False，验证至少 2 个 box_*_ok 字段是 False 解释原因

**C. 双中军子条件 (2 个测试)**
- `test_double_zhongjun_positive_case`：构造 130+ 日 OHLCV + 大盘指数，最后一日满足所有 8 项 → double_zhongjun_XG=True
- `test_double_zhongjun_negative_case_no_index`：index_data=None → double_大盘_ok 全 False → double_zhongjun_XG=False

**D. combo_XG 组合 (2 个测试)**
- `test_combo_box_pass_zhongjun_fail`：box=True 但 zhongjun=False → combo_XG=False
- `test_combo_both_pass`：两个都 True → combo_XG=True

**E. 完整性/边界 (3 个测试)**
- `test_no_lookahead_hhv`：验证 HHV/LLV/REF 不引用未来 (在最后一日修改之前的数据后, 最后一日条件不变)
- `test_output_columns_complete`：返回 DataFrame 必须含 SPEC §Testing 第 5 条列举的所有字段名 (`box_breakout_XG`, `double_zhongjun_XG`, `combo_XG` 以及各 `*_ok` 子字段)
- `test_short_series_no_crash`：输入只有 10 行 (远少于 60 日窗口)，selector 不崩，返回 DataFrame combo_XG 全 False

**构造样本数据建议**：
- 用 `pd.date_range('2026-01-01', periods=N)` 生成日期 index
- close 用线性上升或单调函数构造确定性的多头排列
- 大盘指数同样构造单调上升
- 测试位置：`D:/QMT_STRATEGIES/huang_main_uptrend_combo/tests/test_huang_main_uptrend_combo_selector.py`

**测试文件头**：
```python
# coding=utf-8
"""单元测试: huang_main_uptrend_combo_selector"""
import sys
sys.path.insert(0, 'D:/QMT_STRATEGIES')

import unittest
import numpy as np
import pandas as pd

from huang_main_uptrend_combo.huang_main_uptrend_combo_selector import (
    tdx_ma, tdx_ema, tdx_ref, tdx_hhv, tdx_llv,
    tdx_cross, tdx_count, tdx_avedev,
    _calc_box_breakout_conditions,
    _calc_double_zhongjun_conditions,
    select_huang_main_uptrend_combo,
    DEFAULT_PARAMS,
)
```

### TASK-5. 跑单元测试

```bash
cd D:/QMT_STRATEGIES
python -m unittest huang_main_uptrend_combo.tests.test_huang_main_uptrend_combo_selector -v
```

**期望**：~17 项 ALL PASS（具体测试数按上面 A-E 分组合计；如 MIMO 合并/拆分了几个无所谓，覆盖到要求即可）。

把完整输出贴进回执。

**任一 FAIL 立刻停下报告**，禁止继续。

### TASK-6. P1+P2+P3 回归测试（确保未污染其他测试）

```bash
cd D:/QMT_STRATEGIES
python -m unittest tests.test_risk_timegate_p1 tests.test_risk_timegate_p2 tests.test_risk_timegate_p3 -v
```

**期望**：14 + 10 + 13 = 37 PASS（与上一次 commit 后一致）。

把最后 5 行（含 `Ran X tests` + `OK`）贴回执。

### TASK-7. git status 验证范围

```bash
cd D:/QMT_STRATEGIES
git status --short huang_main_uptrend_combo/
```

期望（顺序可变，但必须只有这 4 行）：
```
?? huang_main_uptrend_combo/__init__.py
?? huang_main_uptrend_combo/huang_main_uptrend_combo_selector.py
?? huang_main_uptrend_combo/tests/__init__.py
?? huang_main_uptrend_combo/tests/test_huang_main_uptrend_combo_selector.py
```

把输出贴回执。**本工单不 commit，等 CC 验收后再起 commit 工单**。

---

## 二、严禁

1. **严禁** `git add` / `git commit` / `push` / `amend` / `--no-verify`
2. **严禁** 改任何已有文件（`adapters/qmt_wrapper.py` / `strategy_*.py` / `core/` / `tests/test_risk_*`）
3. **严禁** 改 `scripts/build_strategy.py` 把本模块加进生产构建（本模块**离线**, 不进 QMT 加载链）
4. **严禁** 引入 `context_mock.py` / 任何 mock passorder
5. **严禁** 调用 `passorder` / `xttrader` / 任何下单接口
6. **严禁** 用 placeholder 时间戳
7. **严禁** 擅自改 SPEC §D 默认参数值
8. **严禁段加死**：所有 DEFAULT_PARAMS 里列出的参数都必须在函数体内被引用（`box_ma_short` 例外, SPEC §A 注明原公式定义但未参与 XG, 保留为参数不参与，在注释里写明）
9. **遇任一异常必停**：单测 FAIL、TASK-6 P1/P2/P3 回归 FAIL、import error——立刻停下报告，**不得自判"无关"继续**
10. **回执只能在工单 EOF 追加**

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
<贴 ls + git log 输出>

### TASK-2: 目录结构
<执行命令贴 / ls 验证 4 个文件存在>

### TASK-3: selector 完成
- [ ] DEFAULT_PARAMS 完整 21 项
- [ ] 8 个 TDX 映射函数
- [ ] _calc_box_breakout_conditions
- [ ] _calc_double_zhongjun_conditions
- [ ] select_huang_main_uptrend_combo 主入口
- [ ] combo_XG = box_breakout_XG AND double_zhongjun_XG

### TASK-4: 测试文件完成
- [ ] A 组 TDX 映射 8 个
- [ ] B 组 箱体突破 2 个
- [ ] C 组 双中军 2 个
- [ ] D 组 combo 2 个
- [ ] E 组 完整性/边界 3 个
- 实际测试数: <填>

### TASK-5: 单元测试输出
<贴 unittest -v 完整输出>

### TASK-6: P1+P2+P3 回归
<贴最后 5 行>

### TASK-7: git status
<贴输出, 必须只有 4 行 ??>

### 自检
- [ ] 时间戳真跑 date 命令
- [ ] 未 git add / commit / push
- [ ] 未改任何已有源文件
- [ ] 未引入 mock/passorder
- [ ] 新模块单测全 PASS
- [ ] P1+P2+P3 回归 37 PASS
- [ ] DEFAULT_PARAMS 默认值与 SPEC §D 一致
- [ ] 所有 fillna(False) 已加 (避免 NaN 污染 XG)
- [ ] 回执在工单 EOF 追加
```

---

## 完成回执

**执行时间**: 2026-06-23T13:19:36Z
**MIMO 模型**: mimo-auto

### TASK-0: 真实时间戳
```
2026-06-23T13:19:36Z
```

### TASK-1: 预检
```
ls: cannot access 'huang_main_uptrend_combo/': No such file or directory
44bd768 docs: P3 观察期工单回执追加
```

### TASK-2: 目录结构
```
huang_main_uptrend_combo/
  __init__.py
  huang_main_uptrend_combo_selector.py
  tests/
    __init__.py
    test_huang_main_uptrend_combo_selector.py
```
4 个文件全部存在。

### TASK-3: selector 完成
- [x] DEFAULT_PARAMS 完整 21 项 (含 box_ma_short 保留不参与)
- [x] 8 个 TDX 映射函数 (tdx_ma, tdx_ema, tdx_ref, tdx_hhv, tdx_llv, tdx_cross, tdx_count, tdx_avedev)
- [x] _calc_box_breakout_conditions
- [x] _calc_double_zhongjun_conditions
- [x] select_huang_main_uptrend_combo 主入口
- [x] combo_XG = box_breakout_XG AND double_zhongjun_XG

### TASK-4: 测试文件完成
- [x] A 组 TDX 映射 8 个
- [x] B 组 箱体突破 2 个
- [x] C 组 双中军 2 个
- [x] D 组 combo 2 个
- [x] E 组 完整性/边界 3 个
- 实际测试数: 17

### TASK-5: 单元测试输出
```
test_box_breakout_negative_case ... ok
test_box_breakout_positive_case ... ok
test_combo_both_pass ... ok
test_combo_box_pass_zhongjun_fail ... ok
test_no_lookahead_hhv ... ok
test_output_columns_complete ... ok
test_short_series_no_crash ... ok
test_double_zhongjun_negative_case_no_index ... ok
test_double_zhongjun_positive_case ... ok
test_tdx_avedev_basic ... ok
test_tdx_count_basic ... ok
test_tdx_cross_basic ... ok
test_tdx_ema_basic ... ok
test_tdx_hhv_basic ... ok
test_tdx_llv_basic ... ok
test_tdx_ma_basic ... ok
test_tdx_ref_basic ... ok

----------------------------------------------------------------------
Ran 17 tests in 0.131s

OK
```

### TASK-6: P1+P2+P3 回归
```
----------------------------------------------------------------------
Ran 37 tests in 0.080s

OK
```

### TASK-7: git status
```
?? huang_main_uptrend_combo/
```
只有新模块目录为 untracked，未改任何已有文件。

### 自检
- [x] 时间戳真跑 date 命令
- [x] 未 git add / commit / push
- [x] 未改任何已有源文件
- [x] 未引入 mock/passorder
- [x] 新模块单测 17 PASS
- [x] P1+P2+P3 回归 37 PASS
- [x] DEFAULT_PARAMS 默认值与 SPEC §D 一致
- [x] 所有 fillna(False) 已加 (避免 NaN 污染 XG)
- [x] 回执在工单 EOF 追加
