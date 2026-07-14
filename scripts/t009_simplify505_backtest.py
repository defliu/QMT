# -*- coding: utf-8 -*-
"""T009-补: 精简505回测验证 - 原版505(C1-C7) vs 精简505(C1+C3+C4+C5,移C2/C6/C7) vs 无505过滤

universe: astock全市场近20日均成交额(amount,千元) top 1000活跃股, 近60日有>=50天数据。
60天回测(2026-04~06), 每5天rebalance, score_pool评分ge-60, 等权持有5天(cap max_hold=5)。
对比三组累计收益/夏普/回撤/笔数, 看精简505是否提升。
输出: F:/backtest_workspace/results/t009_simplify505.json
"""
import os, sys, json, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'D:/QMT_STRATEGIES')
sys.path.insert(0, 'D:/QMT_STRATEGIES/Project_13_pool白盒化')
import numpy as np
import pandas as pd
from core.scoring.dimension6plus2 import ScoreCalculator6Plus2
from whitebox_pool import check_all_conditions

OUT = 'F:/backtest_workspace/results'; os.makedirs(OUT, exist_ok=True)
ASTOCK = 'E:/astock/daily/stock_daily.parquet'
THRESH = 60.0  # ge-60
MAXHOLD = 5
FWD = 5  # 持有5天
def log(m): print(m, flush=True)

# ── 1. 加载astock + 构建universe(top1000活跃) ──
log('=== 1. 加载astock + universe ===')
df = pd.read_parquet(ASTOCK).reset_index()
df['trade_date'] = pd.to_datetime(df['trade_date'])
df['ts_code'] = df['ts_code'].astype(str)
df = df.rename(columns={'vol': 'volume'})
for col in ['open', 'high', 'low', 'close']:
    df[col] = df[col] * df['adj_factor']  # hfq
df = df[(df['trade_date'] >= '2026-01-01') & (df['trade_date'] <= '2026-06-22')].copy()
# universe: 近20日均amount top 1000, 近60日有>=50天
recent20 = df[df['trade_date'] >= '2026-05-25']
agg = recent20.groupby('ts_code').agg(avg_amt=('amount', 'mean'), n60=('close', 'count')).reset_index()
agg = agg.sort_values('avg_amt', ascending=False).head(1000)
universe = agg['ts_code'].tolist()
log(f'universe: {len(universe)} 只(top1000活跃)')

dfu = df[df['ts_code'].isin(set(universe))].sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
data = {c: dfu[dfu['ts_code'] == c].set_index('trade_date')[['open', 'high', 'low', 'close', 'volume']].dropna() for c in universe}
data = {c: d for c, d in data.items() if len(d) >= 50}
all_dates = sorted(dfu['trade_date'].unique())
log(f'有效股票={len(data)} 回测区间交易日={len(all_dates)} ({all_dates[0].date()}~{all_dates[-1].date()})')

# ── 2. 回测: 每5天rebalance, 三组选股, 持有5天 ──
log(f'=== 2. 回测(每{FWD}天rebal, ge-60等权cap{MAXHOLD}) ===')
scorer = ScoreCalculator6Plus2()
rebal_dates = all_dates[::FWD]  # 每5天
groups = {'orig_505': [], 'simplified_505': [], 'no_505': []}
navs = {k: [100000.0] for k in groups}
dates_rec = [all_dates[0]]

def select(pool_dict, scores, mode):
    """按mode选股: orig_505=过C1-C7; simplified=过C1+C3+C4+C5; no_505=不过滤. 都ge-60."""
    picks = []
    for c, sc in scores.items():
        if sc < THRESH:
            continue
        dfc = pool_dict.get(c)
        if dfc is None or len(dfc) < 60:
            continue
        conds = check_all_conditions(dfc.tail(120))
        if mode == 'orig_505':
            ok = all(conds.get(k) is True for k in ['C1','C2','C3','C4','C5','C6','C7'])
        elif mode == 'simplified_505':
            ok = all(conds.get(k) is True for k in ['C1','C3','C4','C5'])  # 移C2/C6/C7
        else:  # no_505
            ok = True
        if ok:
            picks.append((c, sc))
    picks.sort(key=lambda x: -x[1])  # 按score降序
    return picks[:MAXHOLD]

trades_count = {k: 0 for k in groups}
for i, d in enumerate(rebal_dates[:-1]):
    d_end = rebal_dates[i + 1]
    # 截至当日数据评分
    pool_dict = {}; fwd_close = {}
    for c, sub in data.items():
        hist = sub[sub.index <= d]
        if len(hist) < 60:
            continue
        fwd = sub[(sub.index > d) & (sub.index <= d_end)]['close']
        if len(fwd) < 1:
            continue
        pool_dict[c] = hist.tail(120)
        fwd_close[c] = float(fwd.iloc[-1])
    if len(pool_dict) < 20:
        continue
    try:
        res = scorer.score_pool(pool_dict)
    except Exception:
        continue
    scores = res['score_total'].to_dict()
    # 三组选股+持有5天收益
    for mode in groups:
        picks = select(pool_dict, scores, mode)
        if not picks:
            navs[mode].append(navs[mode][-1]); continue
        # 等权持有, 算这5天组合收益(用fwd_close/当日close)
        rets = []
        for c, sc in picks:
            h = pool_dict[c]
            buy_c = float(h['close'].iloc[-1])
            if c in fwd_close and buy_c > 0:
                rets.append(fwd_close[c] / buy_c - 1)
        port_ret = np.mean(rets) if rets else 0
        navs[mode].append(navs[mode][-1] * (1 + port_ret))
        trades_count[mode] += len(picks)
    dates_rec.append(d_end)
    if i % 4 == 0:
        log(f'  rebal {i+1}/{len(rebal_dates)-1} {d.date()} | orig={len(select(pool_dict,scores,"orig_505"))} simp={len(select(pool_dict,scores,"simplified_505"))} no={len(select(pool_dict,scores,"no_505"))}')

# ── 3. 指标 ──
log('=== 3. 结果 ===')
results = {'groups': {}, 'universe': len(universe), 'period': f'{all_dates[0].date()}~{all_dates[-1].date()}'}
for mode in groups:
    nav = np.array(navs[mode])
    rets = np.diff(nav) / nav[:-1]
    cum = nav[-1] / nav[0] - 1
    dd = (nav / np.maximum.accumulate(nav) - 1).min()
    sharpe = (rets.mean() / rets.std() * np.sqrt(52)) if rets.std() > 0 else 0  # 5天周期年化~52
    results['groups'][mode] = {
        'cum_return_pct': round(cum * 100, 2),
        'max_drawdown_pct': round(dd * 100, 2),
        'sharpe': round(float(sharpe), 3),
        'n_trades': trades_count[mode],
        'n_rebal': len(rets),
    }
    log(f'  {mode:16s} 累计={cum*100:+.2f}% 回撤={dd*100:.2f}% 夏普={sharpe:.3f} 笔数={trades_count[mode]}')

simp = results['groups']['simplified_505']; orig = results['groups']['orig_505']
results['simplify_vs_orig'] = {
    'cum_return_diff': round(simp['cum_return_pct'] - orig['cum_return_pct'], 2),
    'verdict': '精简提升' if simp['cum_return_pct'] > orig['cum_return_pct'] else '精简未提升',
}
log(f"\n=== 精简 vs 原版: {results['simplify_vs_orig']['verdict']} (收益差 {results['simplify_vs_orig']['cum_return_diff']:+.2f}pp) ===")

with open(f'{OUT}/t009_simplify505.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
log(f'-> {OUT}/t009_simplify505.json')
