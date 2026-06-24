# MIMO 工单：HUANG-505-V01 —— 505 版主升浪选股复刻 + 3 时点对比回测

## 背景

诚哥实操工作流不是回测工厂里那条"双中军"，而是**通达信里跑 505 版主升浪选股 → 导出股池 selected.txt → QMT 实盘读外部池打分排序**。

CC 已审过黄氏主升浪策略.txt（`F:/天翼云盘同步盘/Obsidian/量化知识库/20_策略知识库/黄氏主升浪策略.txt` 第 261-317 行 #505版块）拿到完整 TDX 公式正文。

诚哥要 3 个买入时点的对比回测：
1. **尾盘选股 + 尾盘买入**（T 日 14:55 选股 + T 日 close 撮合）
2. **盘后选股 + 次日开盘买入**（T 日收盘后选 + T+1 open 撮合，next_open 工厂模式）
3. **盘中选股 + 盘中买入**（T 日 10:00 选股 + T 日 open 撮合）

工作量 ~120 分钟。**MIMO 模型**：mimo-auto

---

## 一、TDX 505 版公式正文（CC 审定的 1:1 复刻基准）

来源：`knowledge_base/20_策略知识库/黄氏主升浪策略.txt` 第 261-317 行 #505版块

```
{参数}
N:=5; N1:=10; N2:=20; N3:=60;
启用过滤:=0;

{===== 双带计算 =====}（仅用于主图绘制，选股不依赖，本工单忽略）

{===== 均线与角度 =====}
MA5_:=MA(C,N);
MA10_:=MA(C,N1);
MA20_:=MA(C,N2);
MA60_:=MA(C,N3);
角度:=ATAN((MA5_/REF(MA5_,1)-1)*100)*180/3.1416;

{===== 5日乖离率 =====}
BIAS5:=(C-MA5_)/MA5_*100;

{===== 筹码与获利 =====}
筹码集中OK:=SCR.SCR < 15;        ← TDX 筹码集中度指标 (SCR.SCR L1 内置)
收盘获利OK:=WINNER(C)*100 > 90;   ← TDX 获利盘比例

{===== 买点1 =====}
买点1:= C>MA5_ AND MA5_>MA10_ AND MA10_>MA20_ AND MA20_>MA60_
        AND C>O AND L>=MA5_*0.98 AND 角度>=45
        AND 筹码集中OK AND 收盘获利OK;

{===== 无L2：资金条件恒过 =====}
资金OK:=1;

{===== 过滤条件 (启用过滤=0 时恒为 1) =====}
大盘股:=FINANCE(40)/100000000 > 250;
大盘OK:=INDEXC>MA(INDEXC,20) AND MA(INDEXC,20)>MA(INDEXC,60);
过滤条件:=IF(启用过滤=1, 大盘股 AND 筹码集中OK AND 大盘OK, 1);

{===== 综合买点 =====}
全满足买点:= 买点1 AND 资金OK AND 过滤条件;

{===== 乖离率分类 =====}
正常买点:=全满足买点 AND BIAS5<=10;
高乖离买点:=全满足买点 AND BIAS5>10;

{===== 唯一选股输出 =====}
XG:正常买点 OR 高乖离买点;        ← 等价 XG := 全满足买点 (BIAS5 任意)
```

## 二、CC 决策（不许 MIMO 自己改）

### 2.1 筹码条件降级（v1）

`SCR.SCR < 15` 和 `WINNER(C)*100 > 90` 是 TDX 筹码分布指标，需要 L2 / 模拟筹码分布算法（~200 行）。**v1 工单先砍掉这两个条件并显式标注**：

```python
# CC 工单 §2.1: 筹码 v1 降级
# 原 TDX: 筹码集中OK := SCR.SCR < 15 AND 收盘获利OK := WINNER(C)*100 > 90
# v1 强制为 True (= 不过滤). v2 若必要再补真实模拟.
chip_concentration_ok = True
chip_winner_ok = True
```

诚哥决策已确认: v1 先验骨架, 选不出再上 v2 模拟筹码。

### 2.2 启用过滤=0

按 TDX 原文 `启用过滤:=0`, 过滤条件恒为 1, **大盘股/大盘OK/筹码集中OK 均不参与最终 XG**。CC 严格按 TDX 原意。

### 2.3 BIAS5 不过滤

`XG = 正常买点 OR 高乖离买点 = 全满足买点 AND (BIAS5<=10 OR BIAS5>10) = 全满足买点`。
BIAS5 字段保留作 diagnostic, **不**作为 XG 过滤项。

### 2.4 综合后 v1 最终 XG（精确等价）

```
huang_505_XG := C > MA5
             AND MA5 > MA10 AND MA10 > MA20 AND MA20 > MA60
             AND C > O
             AND L >= MA5 * 0.98
             AND ATAN((MA5/REF(MA5,1)-1)*100)*180/π >= 45
```

只有 6 个子条件（多头排列 + 阳线 + 最低价站稳 MA5 98% + MA5 角度 >= 45°）。**比双中军(7 条件 + 大盘)宽松很多**, 预期选出票多。

---

## 三、必做（10 步）

### TASK-0. 时间戳

```bash
date -u +"%Y-%m-%dT%H:%M:%SZ"
```

### TASK-1. 预检

```bash
cd D:/QMT_STRATEGIES
git status --short huang_main_uptrend_combo/
git log -1 --oneline huang_main_uptrend_combo/huang_main_uptrend_combo_selector.py
git log -1 --oneline
```

期望:
- `huang_main_uptrend_combo/` 无 dirty (除 reports/__pycache__ 之外)
- selector 最近 commit: `b97a1dc` 或更新
- HEAD: `19e1863` ([MS-J] benchmark lead-in fix)

异常 → 停。

### TASK-2. 在 selector 里新增 505 版条件函数（**仅新增，不改动现有任何代码**）

定位 `D:/QMT_STRATEGIES/huang_main_uptrend_combo/huang_main_uptrend_combo_selector.py`，
在文件末尾（`select_huang_main_uptrend_combo` 函数**之前**，第 248 行附近 `_calc_double_zhongjun_conditions` 函数**之后**）追加：

```python
def _calc_huang_505_conditions(df, params):
    """黄氏 505 版主升浪选股条件 (v1: 已砍 SCR.SCR / WINNER 筹码条件).

    TDX 公式来源: knowledge_base/20_策略知识库/黄氏主升浪策略.txt #505版
    复刻范围: 买点1 主体 (均线多头 + C>O + L>=MA5*0.98 + 角度>=45)
    已降级:    SCR.SCR / WINNER (筹码集中 / 获利盘) -> 强制 True
    已忽略:    启用过滤=0 故过滤条件恒为 1 (大盘股/大盘OK 不参与)
    已合并:    BIAS5 仅作 diagnostic, 不参与 XG

    Args:
        df: DataFrame[open,high,low,close,volume,...], 升序
        params: dict, 沿用 DEFAULT_PARAMS + 505 专属字段

    Returns:
        DataFrame 索引同 df, 包含:
          huang505_MA5, huang505_MA10, huang505_MA20, huang505_MA60,
          huang505_角度, huang505_BIAS5,
          huang505_多头排列_ok, huang505_阳线_ok, huang505_站稳MA5_ok, huang505_角度_ok,
          huang505_chip_v1_降级标记 (固定 True),
          huang505_XG  (v1 最终选股信号)
    """
    out = _pd.DataFrame(index=df.index)

    # 1. 均线
    MA5 = tdx_ma(df['close'], params.get('h505_ma_n', 5))
    MA10 = tdx_ma(df['close'], params.get('h505_ma_n1', 10))
    MA20 = tdx_ma(df['close'], params.get('h505_ma_n2', 20))
    MA60 = tdx_ma(df['close'], params.get('h505_ma_n3', 60))
    out['huang505_MA5'] = MA5
    out['huang505_MA10'] = MA10
    out['huang505_MA20'] = MA20
    out['huang505_MA60'] = MA60

    # 2. 角度 (TDX 原式: ATAN((MA5/REF(MA5,1)-1)*100)*180/π)
    angle_pct = (MA5 / tdx_ref(MA5, 1) - 1.0) * 100.0
    angle_deg = _np.degrees(_np.arctan(angle_pct))
    out['huang505_角度'] = angle_deg

    # 3. BIAS5 (TDX 原式: (C-MA5)/MA5*100) - 仅 diagnostic
    out['huang505_BIAS5'] = (df['close'] - MA5) / MA5 * 100.0

    # 4. 子条件
    out['huang505_多头排列_ok'] = (
        (df['close'] > MA5) & (MA5 > MA10) & (MA10 > MA20) & (MA20 > MA60)
    ).fillna(False)
    out['huang505_阳线_ok'] = (df['close'] > df['open']).fillna(False)
    out['huang505_站稳MA5_ok'] = (df['low'] >= MA5 * 0.98).fillna(False)
    out['huang505_角度_ok'] = (angle_deg >= params.get('h505_angle_thresh', 45.0)).fillna(False)

    # v1: 筹码降级标记 (强制 True)
    out['huang505_chip_v1_降级标记'] = True

    # 5. 最终 XG (v1)
    out['huang505_XG'] = (
        out['huang505_多头排列_ok']
        & out['huang505_阳线_ok']
        & out['huang505_站稳MA5_ok']
        & out['huang505_角度_ok']
    )
    return out
```

**严禁**: 任何对 `_calc_box_breakout_conditions` / `_calc_double_zhongjun_conditions` / `select_huang_main_uptrend_combo` 的修改。**只追加新函数**。

### TASK-3. DEFAULT_PARAMS 追加 505 专属参数（**仅追加 4 行**）

定位 `DEFAULT_PARAMS` dict 末尾 (第 44 行附近, `'box_window_N': 120,` 那条之后)，**在闭合 `}` 之前**追加：

```python
    # 505 版主升浪选股参数 (v1)
    'h505_ma_n': 5, 'h505_ma_n1': 10, 'h505_ma_n2': 20, 'h505_ma_n3': 60,
    'h505_angle_thresh': 45.0,
```

**严禁**改任何现有 DEFAULT_PARAMS 字段。

### TASK-4. selector 主入口 `select_huang_main_uptrend_combo` 新增 505 列（**最小侵入**）

定位 `select_huang_main_uptrend_combo` 函数体中，第 280 行附近 `merged = _pd.concat([box, dbl], axis=1)` **之后**、`win_N = p['box_window_N']` **之前**，追加：

```python
        # 505 版条件 (与 zhongjun / box 独立, 不参与 combo_XG)
        h505 = _calc_huang_505_conditions(df, p)
        merged = _pd.concat([merged, h505], axis=1)
```

**严禁**改其他任何 selector 主函数代码。

### TASK-5. 建包结构: `huang_main_uptrend_combo/backtest/huang_505/`

```
huang_main_uptrend_combo/backtest/huang_505/
├─ __init__.py                              # 空
├─ run_backtest_huang_505.py                # 主 runner (拷贝改造自 run_backtest_huang_combo.py)
└─ tests/
    ├─ __init__.py                          # 空
    └─ test_huang_505_signal.py             # 信号触发单测
```

#### 5.1 `__init__.py` (两个都创建为空文件 `# coding=utf-8\n"""huang 505 backtest package."""\n`)

#### 5.2 `run_backtest_huang_505.py`

直接复制 `run_backtest_huang_combo.py` 全文，做 5 处定向改动:

**改动 1**: 文件 docstring 头部
```python
# coding=utf-8
"""黄氏 505 版主升浪 historical backtest — 3 时点对比.

撮合时点对比:
  - close:     T 日 14:55 选股 + T 日 close 撮合 (尾盘选 + 尾盘买)
  - next_open: T 日盘后选股 + T+1 open 撮合 (盘后选 + 次日开盘买, 与工厂 next_open 等价)
  - open:      T 日 10:00 选股 + T 日 open 撮合 (盘中选 + 盘中买)

注: 信号源 = huang505_XG (selector 新增列, 见 _calc_huang_505_conditions)
"""
```

**改动 2**: `parse_args` 默认值改: `--signal-source` 默认 `huang505_XG`, choices 加 `huang505_XG`

```python
    p.add_argument('--signal-source', default='huang505_XG',
                   choices=['combo_XG', 'double_zhongjun_XG', 'box_breakout_XG', 'huang505_XG'],
                   help='信号源字段; 默认 huang505_XG (505 版)')
    p.add_argument('--entry-timing', default='close',
                   choices=['close', 'open', 'next_open'],
                   help='engine=full 下生效; close=T日尾盘成交, open=T日盘中成交, next_open=T+1开盘成交')
```

**改动 3**: `_make_run_id` 加 huang505 短名映射:

```python
    src_short = (signal_source.replace('_XG', '')
                              .replace('double_', 'zj_')
                              .replace('huang', 'h'))
    return 'huang_%s_%s_%s' % (src_short, ts, h)
```

**改动 4**: `_run_full_engine_backtest` 内部 `zhongjun_by_date` 段加 huang505 分支:

```python
    zhongjun_by_date = {}
    if signal_source == 'huang505_XG' and 'huang505_XG' in result.columns:
        # 复用 zhongjun_by_date 字典结构, 即"今日触发选股的 code set"
        hits = result[result['huang505_XG'] == True]
    elif 'double_zhongjun_XG' in result.columns:
        hits = result[result['double_zhongjun_XG'] == True]
    else:
        hits = result.iloc[:0]
    for _, row in hits.iterrows():
        d = pd.Timestamp(row['date'])
        zhongjun_by_date.setdefault(d, set()).add(row['code'])
    print('[full] 预计算信号 %s: %d 天有触发' % (signal_source, len(zhongjun_by_date)))
```

(注: `signal_source` 已是 `_run_full_engine_backtest` 入参 第 8 个位置, 见原文件第 258 行签名)

**改动 5**: entry_timing='next_open' 撮合逻辑

定位 `_run_full_engine_backtest` 内部 entry_timing 判断处（grep `if entry_timing == 'open'` 或 `entry_timing == 'close'`），扩展为支持 3 种模式:

```python
# 撮合价取价规则:
#   close:     T 日 close (原行为)
#   open:      T 日 open (T 日盘中, 原行为)
#   next_open: T+1 日 open (T 日盘后, 与工厂 next_open 等价)
def _entry_price(df_sub, i, code_arrays, current_date, mode):
    """根据 mode 返回撮合价. df_sub 是已切到 current_date 的子集.
    mode='close': df_sub['close'].iloc[-1]
    mode='open':  df_sub['open'].iloc[-1]
    mode='next_open': 查 code_arrays 取 T+1 日 open, 若 T+1 无 bar 返回 None
    """
    if mode == 'close':
        return float(df_sub['close'].iloc[-1])
    if mode == 'open':
        return float(df_sub['open'].iloc[-1])
    if mode == 'next_open':
        code = df_sub.name if hasattr(df_sub, 'name') else None
        # 需要 caller 传 code 进来取 T+1; 这里简化为读 next bar from full df
        # 由 caller 函数体内自己实现 next-day lookup
        raise NotImplementedError('next_open 由调用方处理')
    raise ValueError('unknown entry_timing=' + str(mode))
```

**关键约束**: `next_open` 的实现要保证 **T+1 没 bar (停牌) 时跳过, 不能用 T 日数据回退**。
具体实现思路: 在选股循环里, 若 entry_timing='next_open', `current_date` 实际撮合价用 `code_arrays[code][1]` 里 `current_date` 索引位置 +1 的 open。若 +1 越界或不存在则跳过。

> **如果 next_open 实现复杂度 > 30 分钟**, 在文件顶部 docstring 写"next_open mode v1 已实现/未实现"明确告知, 不要硬怼。若未实现, TASK-7/8/9 只跑 close + open 两种, **不要静默装跑了**。

### TASK-6. 单测 `tests/test_huang_505_signal.py`

```python
# coding=utf-8
"""505 版信号触发的最小单测."""
import numpy as np
import pandas as pd
import pytest

from huang_main_uptrend_combo.huang_main_uptrend_combo_selector import (
    _calc_huang_505_conditions, DEFAULT_PARAMS, select_huang_main_uptrend_combo,
)


def _make_bullish_df(n=80, start=10.0, end=20.0):
    """构造单调上涨 + 阳线 + 站稳 MA5 的票."""
    dates = pd.date_range('2025-01-01', periods=n)
    close = np.linspace(start, end, n)
    open_ = close * 0.99  # 阳线: open < close
    high = close * 1.02
    low = close * 0.985   # 站稳 MA5: low >= MA5*0.98
    vol = np.full(n, 10000.0)
    df = pd.DataFrame({
        'open': open_, 'high': high, 'low': low, 'close': close,
        'volume': vol,
    }, index=dates)
    return df


def test_huang505_bullish_triggers_xg():
    """单调上涨 + 阳线 + 站稳 MA5 + 角度足够 → 最后一根必触发 XG."""
    df = _make_bullish_df()
    out = _calc_huang_505_conditions(df, DEFAULT_PARAMS)
    assert 'huang505_XG' in out.columns
    # MA60 要求 >= 60 根, 最后 20 根应至少有一根 XG=True
    assert bool(out['huang505_XG'].iloc[-1]) or out['huang505_XG'].iloc[-20:].any(), \
        'bullish 票 80 根日 K 内未触发任何 huang505_XG'


def test_huang505_flat_no_xg():
    """横盘票 → 所有条件不达, XG 全 False."""
    dates = pd.date_range('2025-01-01', periods=80)
    close = np.full(80, 10.0)
    df = pd.DataFrame({
        'open': close, 'high': close * 1.005, 'low': close * 0.995,
        'close': close, 'volume': np.full(80, 10000.0),
    }, index=dates)
    out = _calc_huang_505_conditions(df, DEFAULT_PARAMS)
    assert not out['huang505_XG'].any(), '横盘票不该触发 huang505_XG'


def test_huang505_chip_v1_degraded():
    """v1 筹码降级标记必须是 True."""
    df = _make_bullish_df()
    out = _calc_huang_505_conditions(df, DEFAULT_PARAMS)
    assert out['huang505_chip_v1_降级标记'].all()


def test_huang505_xg_in_selector_output():
    """selector 主入口也应输出 huang505_XG 列."""
    df = _make_bullish_df()
    bench = pd.DataFrame({'close': np.linspace(3000, 3300, 80)},
                         index=df.index)
    result = select_huang_main_uptrend_combo({'TEST.SZ': df}, bench)
    assert 'huang505_XG' in result.columns


def test_huang505_bias5_diagnostic_only():
    """BIAS5 是 diagnostic, 不影响 XG."""
    df = _make_bullish_df(end=30.0)  # 强势冲高, BIAS5 大
    out = _calc_huang_505_conditions(df, DEFAULT_PARAMS)
    # 即使 BIAS5 > 10, XG 也可能 True (只要其他条件满足)
    bias = out['huang505_BIAS5'].iloc[-1]
    assert bias > 0  # diagnostic 字段非空且正常
```

### TASK-7. 跑单测

```bash
cd D:/QMT_STRATEGIES
py -3.10 -m pytest huang_main_uptrend_combo/backtest/huang_505/tests/ -v
py -3.10 -m pytest huang_main_uptrend_combo/tests/ -v --tb=line
py -3.10 -m pytest backtest/tests/ --tb=line | tail -5
```

期望:
- 新 huang_505 单测全 PASS (5 个)
- 既有 `huang_main_uptrend_combo/tests/` 0 failed (回归)
- 工厂全量 281 passed (未受影响)

**FAIL → 停**。

### TASK-8. 3 时点回测（核心交付）

数据源: `huicexitong` (E:/huicexitong/runtime/sj/gpsj.duckdb)
股池: `D:/QMT_STRATEGIES/backtest/data/universe/huang_small_mid_20260403.csv`
窗口 (smoke): 2025-09-02 ~ 2025-12-31

```bash
cd D:/QMT_STRATEGIES
OUT=F:/backtest_workspace/huang_505_3timing

# 模式1: close (尾盘选 + 尾盘买)
py -3.10 -m huang_main_uptrend_combo.backtest.huang_505.run_backtest_huang_505 \
    --start 2025-09-02 --end 2025-12-31 \
    --universe D:/QMT_STRATEGIES/backtest/data/universe/huang_small_mid_20260403.csv \
    --benchmark 000001.SH \
    --out-root $OUT \
    --signal-source huang505_XG \
    --engine full \
    --entry-timing close \
    --max-positions 3 \
    --initial-cash 1000000 2>&1 | tee /tmp/h505_close.log

# 模式2: next_open (盘后选 + 次日开盘买, 与工厂对齐)
py -3.10 -m huang_main_uptrend_combo.backtest.huang_505.run_backtest_huang_505 \
    --start 2025-09-02 --end 2025-12-31 \
    --universe D:/QMT_STRATEGIES/backtest/data/universe/huang_small_mid_20260403.csv \
    --benchmark 000001.SH \
    --out-root $OUT \
    --signal-source huang505_XG \
    --engine full \
    --entry-timing next_open \
    --max-positions 3 \
    --initial-cash 1000000 2>&1 | tee /tmp/h505_nextopen.log

# 模式3: open (盘中选 + 盘中买)
py -3.10 -m huang_main_uptrend_combo.backtest.huang_505.run_backtest_huang_505 \
    --start 2025-09-02 --end 2025-12-31 \
    --universe D:/QMT_STRATEGIES/backtest/data/universe/huang_small_mid_20260403.csv \
    --benchmark 000001.SH \
    --out-root $OUT \
    --signal-source huang505_XG \
    --engine full \
    --entry-timing open \
    --max-positions 3 \
    --initial-cash 1000000 2>&1 | tee /tmp/h505_open.log
```

每个模式预期产物（与 `run_backtest_huang_combo.py` 一致）:
- `<out_root>/huang_h505_<ts>_<hash>/summary.json`
- `<out_root>/huang_h505_<ts>_<hash>/nav.csv`
- `<out_root>/huang_h505_<ts>_<hash>/trades.csv` 或 `trades.json`

### TASK-9. 对比报告 `huang_main_uptrend_combo/backtest/huang_505/reports/SMOKE_3TIMING_COMPARISON.md`

```markdown
# 黄氏 505 版主升浪 3 时点对比 — Smoke

**回测窗口**: 2025-09-02 ~ 2025-12-31 (81 交易日, is_short_sample=true)
**股池**: huang_small_mid_20260403.csv (中小盘<100亿)
**基线**: 000001.SH
**信号源**: huang505_XG (v1, 已砍 SCR/WINNER)
**T+1 合规**: 是

## 三时点结果对比

| 指标 | close (T尾盘) | next_open (T+1开盘) | open (T盘中) |
|---|---|---|---|
| 总收益 | <%> | <%> | <%> |
| 年化 | <%> | <%> | <%> |
| 最大回撤 | <%> | <%> | <%> |
| Sharpe | <值> | <值> | <值> |
| 总交易笔数 | <int> | <int> | <int> |
| 买入次数 | <int> | <int> | <int> |
| 卖出次数 | <int> | <int> | <int> |
| 胜率 | <%> | <%> | <%> |
| 平均持仓天数 | <值> | <值> | <值> |
| 信号触发天数 (huang505_XG=True 的日数) | <int> | <int> | <int> |
| 大盘相对收益 | <%> | <%> | <%> |

## 信号统计

- universe size: <int>
- 81 日内累计 huang505_XG 触发次数: <int> (跨 <int> 只股票, <int> 个交易日)
- 平均每日触发数: <值>

## 子条件命中率 (每日均值)

| 子条件 | 命中率 |
|---|---|
| 多头排列 (C>MA5>MA10>MA20>MA60) | <%> |
| 阳线 (C>O) | <%> |
| 站稳 MA5 (L>=MA5*0.98) | <%> |
| 角度>=45° | <%> |

**说明**: 若某子条件命中率 < 5%, 即"它最严", 是后续 v2 优化目标。

## 结论 (MIMO 写一句话)

<填: 例如 "next_open 与 open 净值差异 <X%, 与 close 模式比差 <Y%>, ... 与诚哥实操 QMT 模拟盘走势 <align/不 align>">
```

### TASK-10. 精确 add + commit

**所有产物 + 工单回执打成单 commit**:

```bash
cd D:/QMT_STRATEGIES
git add huang_main_uptrend_combo/huang_main_uptrend_combo_selector.py
git add huang_main_uptrend_combo/backtest/huang_505/__init__.py
git add huang_main_uptrend_combo/backtest/huang_505/run_backtest_huang_505.py
git add huang_main_uptrend_combo/backtest/huang_505/tests/__init__.py
git add huang_main_uptrend_combo/backtest/huang_505/tests/test_huang_505_signal.py
git add huang_main_uptrend_combo/backtest/huang_505/reports/SMOKE_3TIMING_COMPARISON.md
git add agent_hub/2026-06-23_huang_main_uptrend/Mimo_HUANG_505_V01.md

git diff --cached --name-only
```

期望恰好 7 行。staged ≠ 7 → 停。

```bash
git commit -m "$(cat <<'EOF'
feat(huang_combo): 黄氏 505 版主升浪选股 v1 + 3 时点对比回测

诚哥实操工作流: 通达信 505 公式 → selected.txt → QMT 实盘外部池打分。
本次离线 1:1 复刻 TDX 505 版选股 (黄氏主升浪策略.txt #505版段), 接入
独立脚本框架 (run_backtest_huang_combo.py 派生), 对比 3 个买入时点:

  close     T 日 14:55 选股 + T 日 close 撮合 (尾盘选 + 尾盘买)
  next_open T 日盘后选股 + T+1 open 撮合     (盘后选 + 次日开盘买)
  open      T 日 10:00 选股 + T 日 open 撮合 (盘中选 + 盘中买)

复刻范围 (v1):
- huang505_XG = 多头排列 AND 阳线 AND 站稳MA5*0.98 AND 角度>=45°
- 启用过滤=0, 大盘股/大盘OK/筹码集中OK 不参与 (TDX 原意)
- BIAS5 仅 diagnostic, 不参与 XG

v1 降级 (待 v2 补真实模拟):
- SCR.SCR < 15      → 强制 True
- WINNER(C)*100>90  → 强制 True
理由: TDX L1 筹码分布指标外部不可得, 先验骨架。

工程不动:
- 不动 backtest/ 工厂 (撮合时点是策略代码内部职责)
- 不动 _calc_double_zhongjun_conditions / select_huang_main_uptrend_combo
- 不动 run_backtest_huang_combo.py
- 仅向 selector 追加 _calc_huang_505_conditions + DEFAULT_PARAMS 4 个键

新增 (7 文件):
- selector.py:                      +85 行 (_calc_huang_505_conditions + DEFAULT 4 键)
- huang_505/__init__.py:            空包
- huang_505/run_backtest_huang_505: 派生于 run_backtest_huang_combo.py + 4 处定向改动
- huang_505/tests/__init__.py:      空包
- huang_505/tests/test_huang_505_signal.py: 5 个单测
- huang_505/reports/SMOKE_3TIMING_COMPARISON.md: 3 时点对比结果
- Mimo_HUANG_505_V01.md:            本工单 + 回执

测试 (5 PASS): bullish_triggers / flat_no_xg / chip_v1_degraded /
xg_in_selector_output / bias5_diagnostic_only
回归: huang_main_uptrend_combo/tests/ 0 failed, backtest/tests/ 281 passed.

3 时点回测 (2025-09-02 ~ 2025-12-31, smoke):
- close:     n_trades=<填>, total_return=<填>
- next_open: n_trades=<填>, total_return=<填>
- open:      n_trades=<填>, total_return=<填>

Refs:
- 黄氏主升浪策略.txt #505版 (knowledge_base/20_策略知识库)
- selected.txt 标识 "505选股" 确认实操版本
- [[backtest-factory-not-for-event-strategies]] 故走独立脚本
EOF
)"

git log -1 --stat HEAD
```

---

## 四、严禁

1. **严禁** `git add .` / `git add -A` / 目录批量 add
2. **严禁** push / amend / --no-verify
3. **严禁** 改 backtest/ 工厂任何文件
4. **严禁** 改 _calc_double_zhongjun_conditions / _calc_box_breakout_conditions / select_huang_main_uptrend_combo 现有任何代码 (只能追加)
5. **严禁** 改 run_backtest_huang_combo.py (派生到新文件, 原文件不动)
6. **严禁** 把 SCR / WINNER 强行用其他算法补上 (诚哥指令: v1 先砍)
7. **严禁** 跑实盘 / 模拟盘任何接口
8. **严禁** 拆 chore commit ([[mimo-receipt-commit-separation]])
9. **严禁** 用 placeholder 时间戳
10. **严禁** 任一时点回测 0 trades 静默通过 (必须在 commit message 和 SMOKE 报告里如实记录)
11. **严禁** TASK-5 改动 5 (next_open 实现) 复杂度 > 30 分钟硬怼 (停下汇报)

## 五、停手条件

- TASK-1 任一目标文件 dirty → 停
- TASK-2/3/4 定位字符串非唯一 / 匹配不到 → 停
- TASK-5 next_open 实现卡停 → 停下汇报 (不许装做实现了)
- TASK-7 任一测试 FAIL → 停
- TASK-8 任一时点回测退出码 ≠ 0 → 停
- TASK-9 任一时点 n_trades / total_return 数据未填进表格 → 停
- staged ≠ 7 → 停
- 累计耗时 > 150 分钟 → 停

遇异常**必停**贴回执 ([[mimo-must-stop-on-any-failure]])

---

## 六、完成回执

```markdown

---

## 完成回执

**执行时间**: <date -u 输出>
**MIMO 模型**: <实际名>

### TASK-0: 时间戳

### TASK-1: 预检

### TASK-2: selector _calc_huang_505_conditions
<贴 git diff hunk>

### TASK-3: DEFAULT_PARAMS 追加 4 键

### TASK-4: select_huang_main_uptrend_combo 接入 505 列

### TASK-5: huang_505/ 包结构
- LOC: <填>
- run_backtest_huang_505.py: <派生说明>
- next_open 实现状态: 已实现 / 未实现 (写实情, 不许糊弄)

### TASK-6: 单测
- LOC: <填>
- 用例数: 5

### TASK-7: 测试结果
- huang_505 单测: <P/F 数>
- huang_main_uptrend_combo 回归: <P/F 数>
- backtest/ 回归: <P/F 数>

### TASK-8: 3 时点 smoke 回测
- close:     <结果目录, 退出码>
- next_open: <结果目录, 退出码>  (若未实现, 写"未实现")
- open:      <结果目录, 退出码>

### TASK-9: 对比报告
<贴 SMOKE_3TIMING_COMPARISON.md 表格>

### TASK-10: commit
<贴 7 行 + git log -1 --stat>

### 自检
- [ ] 时间戳真跑 date -u
- [ ] selector 仅追加, 未动 zhongjun / box / select_huang 主入口
- [ ] run_backtest_huang_combo.py 未动
- [ ] backtest/ 工厂未动
- [ ] SCR/WINNER 未补真实实现 (诚哥指令)
- [ ] 5 个单测 PASS
- [ ] huang_main_uptrend_combo/tests/ 回归 0 failed
- [ ] backtest/tests/ 281 passed 不变
- [ ] 3 时点 (或 close+open 2 时点, 若 next_open 卡停) 回测退出码 0, n_trades 真实记录
- [ ] SMOKE 报告所有数字填实, 子条件命中率分析填了
- [ ] staged 恰好 7 个文件, 单 commit
- [ ] 回执模板所有占位符已填
- [ ] commit 成功
```
