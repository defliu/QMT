# MIMO 工单：黄氏主升浪 combo selector 历史回测（A 方案 / huicexitong / 3 年）

## 目的

把 `huang_main_uptrend_combo` 当作纯选股器跑 3 年历史回测，看 selector 选股质量。

**模式**：A 方案纯选股回测（每日选 → 次日开盘买 → 持有 5/10/20 日各算一份卖 → 收益统计）。
**数据源**：huicexitong (`E:/huicexitong/runtime/sj/gpsj.duckdb` → `daily_data."行情数据"`)，按 huicexitong_reader 约定走独立 reader（**不走 daily_engine**）。
**前置 commit**：`c94e7f3`
**预计工时**：60-90 分钟

---

## 一、必做（8 步）

### TASK-0. 时间戳

```bash
date -u +"%Y-%m-%dT%H:%M:%SZ"
```

### TASK-1. 预检 + 数据探测

```bash
cd D:/QMT_STRATEGIES
git log -1 --oneline
ls huang_main_uptrend_combo/
```

期望：HEAD = `c94e7f3`。

接着用 py -3.10 探测数据可用性（**先验证再写代码**）：

```bash
py -3.10 << 'PYEOF' 2>&1
import duckdb, sys
sys.path.insert(0, 'D:/QMT_STRATEGIES')
from backtest.data_tools._huicexitong_names import T_DAILY, C_CODE, C_DATE
from backtest.paths import UNIVERSE_DIR
import pandas as pd

uni = pd.read_csv(UNIVERSE_DIR + '/core_100.csv')
codes = uni['code'].tolist()
print('core_100:', len(codes), 'codes')

con = duckdb.connect('E:/huicexitong/runtime/sj/gpsj.duckdb', read_only=True)
q = '''
SELECT "%s" AS code, COUNT(*) n, MIN("%s") mn, MAX("%s") mx
FROM daily_data."%s"
WHERE "%s" = ANY(?)
  AND "%s" BETWEEN '2023-06-01' AND '2026-04-03'
GROUP BY "%s"
''' % (C_CODE, C_DATE, C_DATE, T_DAILY, C_CODE, C_DATE, C_CODE)
df = con.execute(q, [codes]).fetchdf()
print('matched codes:', len(df), '/', len(codes))
print('avg rows per code:', df['n'].mean())
print('missing codes:', sorted(set(codes) - set(df['code'].tolist()))[:20])
PYEOF
```

把输出贴回执。**如果 matched/total < 80%（即超过 20 只 core_100 缺失），停下报告（数据不够）**。

### TASK-2. 写历史回测脚本 `huang_main_uptrend_combo/backtest/run_backtest_huang_combo.py`

**目录结构**（在已 commit 的 huang_main_uptrend_combo/ 下新建）：
```
huang_main_uptrend_combo/
  backtest/                          (新增子目录)
    __init__.py                      (空)
    huice_loader.py                  (huicexitong OHLCV 加载器, TASK-3)
    run_backtest_huang_combo.py      (主回测脚本, 本 TASK)
    tests/
      __init__.py                    (空)
      test_huice_loader.py           (TASK-5)
      test_run_backtest_minimum.py   (TASK-5)
```

**编码 utf-8**。**注意**：项目里有中文字段名取自 `_huicexitong_names.py`，遵守它的"ASCII + \\u escape" 约定（见 huicexitong_reader.py 头注释），**不要在脚本里写裸中文 SQL 字面量**——所有中文表名/列名都通过 `from backtest.data_tools._huicexitong_names import ...` 拿。

**run_backtest_huang_combo.py 主体**（结构）：

```python
# coding=utf-8
"""黄氏 combo selector 历史回测（A 方案：纯选股 + 持有期收益）.

数据源: huicexitong daily_data."行情数据" (1990-12 ~ 2026-04)
股池: backtest/data/universe/core_100.csv ∩ huicexitong 数据可得
区间: 2023-06-01 ~ 2026-04-03
持有期: 5 / 10 / 20 日
评估: 每日通过 combo 数、N 日胜率、平均收益、最大回撤、空仓天数、大盘对比

边界:
- 不走 backtest/engine/daily_engine.py (主源仅 17 个月)
- huicexitong 走独立 reader (huicexitong_reader.py 边界契约一致)
- 输出落 F:/backtest_workspace/huang_combo_backtest_<run_id>/ (不写 D:/)
- 不下单 / 不接 QMT
"""
import argparse, os, sys, json, hashlib
from datetime import datetime

sys.path.insert(0, 'D:/QMT_STRATEGIES')

import numpy as np
import pandas as pd

from huang_main_uptrend_combo.huang_main_uptrend_combo_selector import (
    select_huang_main_uptrend_combo, DEFAULT_PARAMS,
)
from huang_main_uptrend_combo.backtest.huice_loader import (
    load_ohlcv_from_huicexitong, load_benchmark_index,
)


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--start', default='2023-06-01')
    p.add_argument('--end', default='2026-04-03')
    p.add_argument('--universe', default='D:/QMT_STRATEGIES/backtest/data/universe/core_100.csv')
    p.add_argument('--benchmark', default='000001.SH')
    p.add_argument('--out-root', default='F:/backtest_workspace')
    p.add_argument('--hold-periods', default='5,10,20')
    return p.parse_args()


def _make_run_id(start, end, n_codes, n_trade_days):
    h = hashlib.md5(('%s|%s|%d|%d' % (start, end, n_codes, n_trade_days)).encode()).hexdigest()[:8]
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    return 'huang_combo_%s_%s' % (ts, h)


def run_backtest(args):
    # 1. 读股池
    uni_df = pd.read_csv(args.universe)
    codes = uni_df['code'].tolist()
    print('[step] 股池 core_100:', len(codes), '只')

    # 2. 读 OHLCV
    print('[step] 加载 OHLCV from huicexitong ...')
    ohlcv = load_ohlcv_from_huicexitong(codes, args.start, args.end)
    print('       实际可得:', len(ohlcv), '只')
    if len(ohlcv) < int(len(codes) * 0.5):
        raise RuntimeError('可得股票数 < 股池一半, 中止')

    # 3. 读大盘
    print('[step] 加载 benchmark', args.benchmark, '...')
    bench = load_benchmark_index(args.benchmark, args.start, args.end)
    print('       benchmark 行数:', len(bench))

    # 4. 跑 selector
    print('[step] 跑 selector ...')
    result = select_huang_main_uptrend_combo(ohlcv, bench)
    print('       signal rows:', len(result))

    # 5. 信号统计
    sig = result[result['combo_XG'] == True].copy()
    print('[step] combo_XG=True 信号:', len(sig), '条 (跨', sig['code'].nunique(), '只股票,',
          sig['date'].nunique(), '个交易日)')

    # 6. 评估持有期收益
    hold_periods = [int(x) for x in args.hold_periods.split(',')]
    eval_rows = []
    for code, sub_sig in sig.groupby('code'):
        if code not in ohlcv:
            continue
        df = ohlcv[code]
        for _, row in sub_sig.iterrows():
            sig_date = row['date']
            # 取信号日后第一个交易日作为开盘买入
            future = df.loc[df.index > sig_date]
            if len(future) < 1:
                continue
            buy_date = future.index[0]
            buy_price = future.iloc[0]['open']
            if not (buy_price > 0):
                continue
            for n in hold_periods:
                if len(future) <= n:
                    continue
                sell_date = future.index[n]
                sell_price = future.iloc[n]['close']
                if not (sell_price > 0):
                    continue
                ret = sell_price / buy_price - 1.0
                eval_rows.append({
                    'code': code,
                    'signal_date': sig_date,
                    'buy_date': buy_date,
                    'hold_n': n,
                    'sell_date': sell_date,
                    'buy_price': buy_price,
                    'sell_price': sell_price,
                    'return': ret,
                })

    eval_df = pd.DataFrame(eval_rows)
    print('[step] 评估样本数:', len(eval_df))

    # 7. 统计
    stats = []
    for n in hold_periods:
        sub = eval_df[eval_df['hold_n'] == n]
        if len(sub) == 0:
            stats.append({'hold_n': n, 'n': 0})
            continue
        rets = sub['return']
        # 最大回撤 (累计收益曲线视角): 把所有交易按 signal_date 排序后等权累计
        sub_sorted = sub.sort_values('signal_date')
        cum = (1 + sub_sorted['return']).cumprod()
        peak = cum.cummax()
        drawdown = (cum - peak) / peak
        stats.append({
            'hold_n': n,
            'n_signals': len(rets),
            'win_rate': float((rets > 0).mean()),
            'avg_return': float(rets.mean()),
            'median_return': float(rets.median()),
            'std_return': float(rets.std()),
            'max_return': float(rets.max()),
            'min_return': float(rets.min()),
            'max_drawdown': float(drawdown.min()),
            'sharpe_like': float(rets.mean() / rets.std() * np.sqrt(252.0 / n)) if rets.std() > 0 else 0.0,
        })

    stats_df = pd.DataFrame(stats)
    print('[step] 统计:')
    print(stats_df.to_string(index=False))

    # 8. 大盘对比 (信号日 vs 大盘 N 日后)
    bench_compare = []
    bench['close_norm'] = bench['close']
    for n in hold_periods:
        bench_rets = []
        for sig_date in sig['date'].unique():
            future = bench.loc[bench.index > sig_date]
            if len(future) <= n:
                continue
            bp = future.iloc[0]['close']
            sp = future.iloc[n]['close']
            if bp > 0 and sp > 0:
                bench_rets.append(sp / bp - 1.0)
        if bench_rets:
            bench_compare.append({
                'hold_n': n,
                'bench_n': len(bench_rets),
                'bench_avg_return': float(np.mean(bench_rets)),
                'bench_win_rate': float(np.mean([r > 0 for r in bench_rets])),
            })

    bench_df = pd.DataFrame(bench_compare)
    print('[step] 大盘对比:')
    print(bench_df.to_string(index=False))

    # 9. 空仓日 (没有任何信号的交易日)
    all_trading_days = set(bench.index)
    signal_days = set(sig['date'].unique())
    empty_days = all_trading_days - signal_days
    print('[step] 空仓日:', len(empty_days), '/', len(all_trading_days),
          '(%.1f%%)' % (100.0 * len(empty_days) / max(1, len(all_trading_days))))

    # 10. 出文件 (写 F:/, 不写 D:/)
    run_id = _make_run_id(args.start, args.end, len(codes), len(bench))
    out_dir = os.path.join(args.out_root, run_id)
    os.makedirs(out_dir, exist_ok=True)

    sig.to_csv(os.path.join(out_dir, 'signals.csv'), index=False, encoding='utf-8')
    eval_df.to_csv(os.path.join(out_dir, 'eval_trades.csv'), index=False, encoding='utf-8')
    stats_df.to_csv(os.path.join(out_dir, 'stats.csv'), index=False, encoding='utf-8')
    bench_df.to_csv(os.path.join(out_dir, 'bench_compare.csv'), index=False, encoding='utf-8')

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
    with open(os.path.join(out_dir, 'summary.json'), 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print('[done] 输出到:', out_dir)
    return summary


if __name__ == '__main__':
    args = parse_args()
    run_backtest(args)
```

### TASK-3. 写 `huang_main_uptrend_combo/backtest/huice_loader.py`

**编码 utf-8**。所有中文标识符通过 `_huicexitong_names.py` 拿，**禁止裸中文 SQL 字面量**。

```python
# coding=utf-8
"""huicexitong OHLCV 加载器 (黄氏 combo 回测用).

边界（与 huicexitong_reader.py 一致）:
- read_only; 不写 gpsj.duckdb
- 独立模块, 不被 backtest/engine/daily_engine 引用
- 中文表名/列名走 _huicexitong_names.py (ASCII + \\u escape), 禁裸中文字面量
- selector 要求列名: open, high, low, close, volume (映射到中文字段)
"""
import duckdb
import pandas as pd

from backtest.data_tools._huicexitong_names import (
    T_DAILY, C_CODE, C_DATE,
)

HUICE_DB = 'E:/huicexitong/runtime/sj/gpsj.duckdb'
BENCH_DB = 'F:/backtest_workspace/data/duckdb/benchmark_index.duckdb'

# huicexitong 字段名 (含中文, 通过 \u escape 写; 这些在 _huicexitong_names.py 里没有)
# 这里只能在本模块内显式声明; 用 \u escape 避免裸中文
# 开盘价 / 收盘价 / 最高价 / 最低价 / 成交量(股)
_C_OPEN  = '开盘价'        # 开盘价
_C_HIGH  = '最高价'        # 最高价
_C_LOW   = '最低价'        # 最低价
_C_CLOSE = '收盘价'        # 收盘价
_C_VOL   = '成交量(股)'  # 成交量(股)


def load_ohlcv_from_huicexitong(codes, start_date, end_date, db_path=HUICE_DB):
    """读 OHLCV, 返回 dict {code: DataFrame(index=date, columns=[open/high/low/close/volume])}.

    Args:
        codes: list of '600000.SH' etc.
        start_date, end_date: 'YYYY-MM-DD'
    """
    con = duckdb.connect(db_path, read_only=True)
    try:
        q = (
            'SELECT "%s" AS code, "%s" AS date, '
            '"%s" AS open, "%s" AS high, "%s" AS low, "%s" AS close, "%s" AS volume '
            'FROM daily_data."%s" '
            'WHERE "%s" = ANY(?) AND "%s" BETWEEN ? AND ? '
            'ORDER BY "%s", "%s"'
        ) % (
            C_CODE, C_DATE,
            _C_OPEN, _C_HIGH, _C_LOW, _C_CLOSE, _C_VOL,
            T_DAILY,
            C_CODE, C_DATE,
            C_CODE, C_DATE,
        )
        df = con.execute(q, [codes, start_date, end_date]).fetchdf()
    finally:
        con.close()

    result = {}
    for code, sub in df.groupby('code'):
        sub = sub.drop(columns=['code']).copy()
        sub['date'] = pd.to_datetime(sub['date'])
        sub = sub.set_index('date').sort_index()
        # 过滤掉任一价格 <=0 或 NaN 的行
        sub = sub.dropna(subset=['open', 'high', 'low', 'close'])
        sub = sub[(sub['open'] > 0) & (sub['high'] > 0) & (sub['low'] > 0) & (sub['close'] > 0)]
        if len(sub) > 0:
            result[code] = sub
    return result


def load_benchmark_index(code, start_date, end_date, db_path=BENCH_DB):
    """读大盘指数, 返回 DataFrame(index=date, columns=[close]).
    走 benchmark_index.duckdb (BenchmarkIndexReader 同一文件, 但本模块直接 sql 取 close).
    """
    con = duckdb.connect(db_path, read_only=True)
    try:
        # benchmark schema 见 sync_xtquant_index_to_duckdb.py: trade_date / code / close
        rows = con.execute(
            'SELECT trade_date, close FROM index_daily '
            'WHERE code = ? AND trade_date BETWEEN ? AND ? '
            'ORDER BY trade_date',
            [code, start_date, end_date]
        ).fetchall()
    finally:
        con.close()
    if not rows:
        raise ValueError('benchmark %s 无数据 (%s ~ %s)' % (code, start_date, end_date))
    df = pd.DataFrame(rows, columns=['date', 'close'])
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()
    return df
```

**TASK-3 收尾验证**（在 MIMO 写完后跑）：

```bash
py -3.10 -c "
import sys; sys.path.insert(0, 'D:/QMT_STRATEGIES')
from huang_main_uptrend_combo.backtest.huice_loader import load_ohlcv_from_huicexitong, load_benchmark_index
d = load_ohlcv_from_huicexitong(['000001.SZ', '600000.SH'], '2025-01-01', '2025-03-31')
print('OHLCV loaded:', list(d.keys()), 'rows:', {k: len(v) for k,v in d.items()})
print(d['000001.SZ'].head())
b = load_benchmark_index('000001.SH', '2025-01-01', '2025-03-31')
print('benchmark rows:', len(b))
print(b.head())
"
```

期望：3 段输出无报错，OHLCV 列含 open/high/low/close/volume，benchmark 列含 close。把输出贴回执。

### TASK-4. 写 2 个单测

**`tests/test_huice_loader.py`**（unittest 风格）：

- `test_load_ohlcv_small_window`：取 3 只股票 1 个月数据，验证返回结构（dict / DataFrame / 列名 / 行数 > 0）
- `test_load_ohlcv_filters_bad_prices`：取 1 只股票，但起止区间含 ST 或停牌段；验证 dropna + price>0 过滤
- `test_load_benchmark_returns_close_only`：000001.SH 1 个月，验证列只有 close、date 是 DatetimeIndex
- `test_no_lookahead_ordering`：返回 DataFrame index 必须严格升序（无回退）

**`tests/test_run_backtest_minimum.py`**（最小冒烟）：

- `test_run_backtest_smoke`：调 main `run_backtest()` 用 2 只股票 + 3 个月窗口；验证：
  - 不抛异常
  - 输出目录创建
  - summary.json 包含 `run_id, signal_rows, stats, bench_compare` 字段
  - stats 列表至少含 3 个 hold_n（5/10/20）
  - **不要断言具体数字**（这是冒烟测试，不是结果验证）

写完后跑：

```bash
cd D:/QMT_STRATEGIES
py -3.10 -m unittest huang_main_uptrend_combo.backtest.tests.test_huice_loader huang_main_uptrend_combo.backtest.tests.test_run_backtest_minimum -v
```

期望全 PASS。把输出贴回执。

### TASK-5. 跑真实 3 年回测

```bash
cd D:/QMT_STRATEGIES
py -3.10 -m huang_main_uptrend_combo.backtest.run_backtest_huang_combo \
  --start 2023-06-01 --end 2026-04-03 \
  --universe D:/QMT_STRATEGIES/backtest/data/universe/core_100.csv \
  --benchmark 000001.SH \
  --hold-periods 5,10,20
```

**期望**：完整跑完无报错，最后输出 `[done] 输出到: F:/backtest_workspace/huang_combo_<...>/`。

把完整 stdout 贴回执（不要截断 stats 和 bench_compare 表格）。

**注意**：如果跑超过 15 分钟没结束，**停下报告**（说明数据量评估错了），不要无限等。

### TASK-6. 写回测报告 `huang_main_uptrend_combo/backtest/reports/backtest_report_3y.md`

**编码 utf-8**，建目录 `huang_main_uptrend_combo/backtest/reports/`。

报告结构：

```markdown
# 黄氏主升浪 combo selector 3 年历史回测报告

执行日期: <填本工单 date 真实值>
SPEC: D:/QMT_STRATEGIES/specs/SPEC_HUANG_MAIN_UPTREND_TDX_TO_QMT.md
脚本: huang_main_uptrend_combo/backtest/run_backtest_huang_combo.py

---

## 一、回测参数

| 项 | 值 |
|---|---|
| 时间区间 | 2023-06-01 ~ 2026-04-03 |
| 实际交易日数 | <填 summary.total_trading_days> |
| 股票池 | core_100 (<填 universe_size>) |
| 实际可得股票数 | <填 codes_with_data> |
| 大盘指数 | 000001.SH |
| 持有期 | 5 / 10 / 20 日 |
| 数据源 | huicexitong daily_data."行情数据" |

## 二、信号统计

| 指标 | 数值 |
|---|---:|
| 总信号数 | <填 signal_rows> |
| 涉及股票数 | <填 signal_unique_stocks> |
| 涉及交易日数 | <填 signal_unique_days> |
| 空仓日 (无信号) | <填 empty_days> / total (<empty_days_pct>%) |

## 三、持有期收益

<把 stats.csv 内容贴成 markdown 表格, 不要截断>

## 四、与大盘对比

<把 bench_compare.csv 贴成 markdown 表格>

## 五、结论

- 5 日胜率 <X%> vs 大盘 <Y%>: <selector 是 + / - / 持平>
- 10 日胜率 ...
- 20 日胜率 ...
- 空仓比例 <Z%>: <过严 / 适中 / 过松>
- 最大回撤 <W%>: <可接受 / 偏大>

**判断**:
- 是否值得继续 (走 B 方案接 daily_engine 或接入策略)? <Yes/No/需要进一步实验>
- 主要风险点: <填>
- 待回测建议: <填，例如换 universe / 改参数 / 加择时>
```

输出贴回执（**完整内容**，不要省略数字）。

### TASK-7. 精确 add + commit

```bash
cd D:/QMT_STRATEGIES
git add huang_main_uptrend_combo/backtest/__init__.py
git add huang_main_uptrend_combo/backtest/huice_loader.py
git add huang_main_uptrend_combo/backtest/run_backtest_huang_combo.py
git add huang_main_uptrend_combo/backtest/tests/__init__.py
git add huang_main_uptrend_combo/backtest/tests/test_huice_loader.py
git add huang_main_uptrend_combo/backtest/tests/test_run_backtest_minimum.py
git add huang_main_uptrend_combo/backtest/reports/backtest_report_3y.md
git add agent_hub/2026-06-23_huang_main_uptrend/Mimo_HUANG_PART3_BACKTEST.md

git diff --cached --name-only
```

**期望 8 行（多一行少一行都不行）**：
```
agent_hub/2026-06-23_huang_main_uptrend/Mimo_HUANG_PART3_BACKTEST.md
huang_main_uptrend_combo/backtest/__init__.py
huang_main_uptrend_combo/backtest/huice_loader.py
huang_main_uptrend_combo/backtest/reports/backtest_report_3y.md
huang_main_uptrend_combo/backtest/run_backtest_huang_combo.py
huang_main_uptrend_combo/backtest/tests/__init__.py
huang_main_uptrend_combo/backtest/tests/test_huice_loader.py
huang_main_uptrend_combo/backtest/tests/test_run_backtest_minimum.py
```

**严禁** `git add .` / `git add -A` / 整目录 add。

```bash
git commit -m "$(cat <<'EOF'
feat(huang_combo): 3 年历史回测脚本 + 报告（A 方案纯选股）

数据源: huicexitong daily_data."行情数据" (2023-06-01 ~ 2026-04-03)
股池: core_100
持有期: 5/10/20 日
输出: F:/backtest_workspace/huang_combo_<run_id>/

新增:
- huang_main_uptrend_combo/backtest/huice_loader.py: 独立 OHLCV 加载器
  (与 huicexitong_reader.py 边界一致, 不进 daily_engine 主路径)
- huang_main_uptrend_combo/backtest/run_backtest_huang_combo.py: 主回测脚本
- 2 个单测 (loader + smoke)
- backtest_report_3y.md: 完整回测报告

不动 backtest/engine/* / huang_main_uptrend_combo/huang_main_uptrend_combo_selector.py。
EOF
)"

git log -1 --stat HEAD
```

把 commit 完整输出贴回执。

### TASK-8. 最终核查

```bash
cd D:/QMT_STRATEGIES
git status --short huang_main_uptrend_combo/
ls -la F:/backtest_workspace/ | grep huang_combo | head -5
```

期望：
- `git status --short` 无输出
- F:/ 下能看到回测产物目录

---

## 二、严禁

1. **严禁** `git add .` / `git add -A` / 整目录 add
2. **严禁** push / amend / --no-verify / --force
3. **严禁** 改 `huang_main_uptrend_combo/huang_main_uptrend_combo_selector.py` 任何一行（selector 已 commit 锁定）
4. **严禁** 改 `adapters/qmt_wrapper.py` / `strategy_*.py` / `core/` / `backtest/engine/*` / `backtest/data_tools/duckdb_reader.py` / `huicexitong_reader.py`
5. **严禁** 写文件到 D:/ 盘除了 `huang_main_uptrend_combo/backtest/` 源码（回测产物只能写 F:/）
6. **严禁** 引入 mock / passorder / xttrader / xtquant / 任何下单接口
7. **严禁** 用 placeholder 时间戳 / placeholder 数字（报告必须真实回填脚本输出）
8. **严禁裸中文 SQL 字面量**（中文表名/列名走 `_huicexitong_names.py` 或本模块 `\u escape`，与 huicexitong_reader.py 边界契约一致）
9. **严禁段加死**: 所有 stats 字段必须都被报告引用
10. **遇任一异常必停**:
   - TASK-1 数据匹配率 < 80% → 停
   - TASK-3 收尾验证抛异常 → 停
   - TASK-4 单测 FAIL → 停
   - TASK-5 运行报错或超 15 分钟未完成 → 停
   - staged 不是 8 个文件 → 停
   - **不得自判"无关"继续**
11. **回执只能在工单 EOF 追加**

---

## 三、完成回执（在工单 EOF 追加）

```markdown

---

## 完成回执

**执行时间**: <真实 date -u 输出>
**MIMO 模型**: <实际名>

### TASK-0: 真实时间戳
<贴 date 输出>

### TASK-1: 预检 + 数据探测
<贴 git log + 数据匹配率输出>

### TASK-2: run_backtest_huang_combo.py
- [ ] 主入口 run_backtest() 完整
- [ ] 命令行参数 6 项 (start/end/universe/benchmark/out-root/hold-periods)
- [ ] 输出 4 个 CSV + summary.json

### TASK-3: huice_loader.py + 收尾验证
- [ ] load_ohlcv_from_huicexitong + load_benchmark_index 函数
- [ ] 无裸中文 SQL 字面量
- 收尾验证输出:
<贴>

### TASK-4: 单测输出
<贴 unittest -v 完整输出>

### TASK-5: 真实 3 年回测 stdout
<贴完整, 含 stats / bench_compare 表格>

### TASK-6: backtest_report_3y.md 内容
<贴完整报告内容>

### TASK-7: git diff --cached --name-only + commit
<贴 8 行 + git log -1 --stat HEAD>

### TASK-8: 最终核查
<贴 git status + F:/ ls 输出>

### 自检
- [ ] 时间戳真跑 date 命令
- [ ] 数据匹配率 ≥ 80%
- [ ] huice_loader 收尾验证 PASS
- [ ] 单测全 PASS
- [ ] 3 年回测完整跑完无错
- [ ] 报告含真实数字 (无 placeholder)
- [ ] staged 只有 8 个文件
- [ ] commit 成功，未 push / amend / --no-verify
- [ ] 未改 selector.py / engine/ / huicexitong_reader.py / adapters/ / strategy_*.py
- [ ] 回测产物只写 F:/, 未写 D:/
- [ ] 回执在工单 EOF 追加
```
