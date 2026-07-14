# -*- coding: utf-8 -*-
"""T005: 主升浪硬规则(F1/F2/F3)接入Pool过滤 - IC/spread验证(快版)

替代任务书"加过滤层跑回测"(慢), 用IC/spread(类T004-step2):
F1 突破60日新高 close>=HHV(close,60)
F2 均线多头 MA5>MA10>MA20>MA60
F3 近5日涨幅<20% 防追高
算各F的spread + 在505过滤基础上加F的增量贡献。
输出: F:/backtest_workspace/results/t005_uptrend_ic.json
"""
import os, sys, json, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'D:/QMT_STRATEGIES')
import numpy as np
import pandas as pd
sys.path.insert(0, 'D:/QMT_STRATEGIES/Project_13_pool白盒化')
from whitebox_pool import check_all_conditions, passes_505_qmt_native
from core.utils import ma

OUT = 'F:/backtest_workspace/results'; os.makedirs(OUT, exist_ok=True)
POOL_FILE = 'D:/QMT_POOL/selectedall.txt'
ASTOCK = 'E:/astock/daily/stock_daily.parquet'
FWD = 5

def log(m): print(m, flush=True)

def spread_metric(pass_arr, fwd_arr):
    """通过组均值 - 未通过组均值(pooled)."""
    p = np.asarray(pass_arr, dtype=float); f = np.asarray(fwd_arr, dtype=float)
    m = p == 1.0
    pf = float(f[m].mean()) if m.any() else 0
    ff = float(f[~m].mean()) if (~m).any() else 0
    return pf - ff, pf, ff, float(m.mean())

# F1/F2/F3 实现
def f1_breakout_60high(hist):
    """close >= HHV(close, 60) (突破60日新高)."""
    if len(hist) < 60: return False
    close = hist['close']
    hhv60 = close.iloc[:-1].rolling(60).max().iloc[-1]  # 前60日最高(不含当日)
    return float(close.iloc[-1]) >= float(hhv60)

def f2_ma_align(hist):
    """MA5>MA10>MA20>MA60 多头排列."""
    c = hist['close']
    if len(c) < 60: return False
    return float(ma(c,5).iloc[-1]) > float(ma(c,10).iloc[-1]) > float(ma(c,20).iloc[-1]) > float(ma(c,60).iloc[-1])

def f3_5d_gain_lt20(hist):
    """近5日涨幅 < 20% 防追高."""
    if len(hist) < 6: return False
    c = hist['close']
    return float(c.iloc[-1] / c.iloc[-6] - 1) < 0.20

# ── 加载池+astock(hfq) ──
import io
raw = io.open(POOL_FILE, 'r', encoding='gbk', errors='replace').read()
pool = []
for l in raw.splitlines():
    p = l.split('\t')
    if len(p) >= 1:
        c = p[0].strip()
        if len(c) == 6 and c[0] in '036':
            pool.append(c + ('.SH' if c.startswith('6') else '.SZ'))
pool = list(dict.fromkeys(pool))
df = pd.read_parquet(ASTOCK).reset_index()
df['trade_date'] = pd.to_datetime(df['trade_date'])
df = df[(df['trade_date'] >= '2021-01-01') & (df['trade_date'] <= '2026-06-22')]
df['ts_code'] = df['ts_code'].astype(str)
df = df[df['ts_code'].isin(set(pool))].copy().rename(columns={'vol': 'volume'})
for col in ['open', 'high', 'low', 'close']:
    df[col] = df[col] * df['adj_factor']
df = df.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
codes = sorted(df['ts_code'].unique())
data = {c: df[df['ts_code'] == c].set_index('trade_date')[['open', 'high', 'low', 'close', 'volume']].dropna() for c in codes}
all_dates = sorted(df['trade_date'].unique())
log(f'池={len(pool)} 有效股票={len(data)} 交易日={len(all_dates)}')

# ── 每10日rebal, 算F1/F2/F3 + 505(C1-C7) + 前向收益 ──
rebal_idx = list(range(0, len(all_dates), 10))
rows = []  # per rebal: {date, F1:[bool], F2, F3, p505, fwd, n}
for ri, di in enumerate(rebal_idx):
    if di + FWD >= len(all_dates): break
    d = all_dates[di]
    f1l, f2l, f3l, p505l, fwdl = [], [], [], [], []
    for c in codes:
        sub = data[c]; hist = sub[sub.index <= d]
        if len(hist) < 60: continue
        fwd_prices = sub[sub.index > d]['close']
        if len(fwd_prices) < FWD: continue
        dfc = hist.tail(120)
        f1l.append(1.0 if f1_breakout_60high(dfc) else 0.0)
        f2l.append(1.0 if f2_ma_align(dfc) else 0.0)
        f3l.append(1.0 if f3_5d_gain_lt20(dfc) else 0.0)
        ok505, _ = passes_505_qmt_native(dfc)
        p505l.append(1.0 if ok505 else 0.0)
        fwdl.append(float(fwd_prices.iloc[FWD-1] / hist['close'].iloc[-1] - 1))
    if len(fwdl) < 20: continue
    rows.append({'date': str(d.date()), 'F1': np.array(f1l), 'F2': np.array(f2l),
                 'F3': np.array(f3l), 'p505': np.array(p505l), 'fwd': np.array(fwdl)})
    if ri % 15 == 0: log(f'  rebal {ri+1}/{len(rebal_idx)} {d.date()} n={len(fwdl)}')
log(f'有效rebal: {len(rows)}')

# ── 各F单独spread + 在505基础上增量 ──
log('=== F1/F2/F3 spread + 增量(505基础上加F) ===')
results = {'n_rebal': len(rows), 'fwd': FWD, 'filters': {}}
for fname, arr_key in [('F1_突破60日新高', 'F1'), ('F2_均线多头', 'F2'), ('F3_5日涨<20%防追高', 'F3')]:
    p = np.concatenate([r[arr_key] for r in rows]); f = np.concatenate([r['fwd'] for r in rows])
    sp, pf, ff, pr = spread_metric(p, f)
    # 增量: 505通过 且 F通过 vs 505通过 但 F不通过
    inc_pass, inc_fail = [], []
    for r in rows:
        m505 = r['p505'] == 1.0; mF = r[arr_key] == 1.0
        both = m505 & mF; only505 = m505 & ~mF
        inc_pass.extend(r['fwd'][both].tolist()); inc_fail.extend(r['fwd'][only505].tolist())
    inc_spread = (float(np.mean(inc_pass)) - float(np.mean(inc_fail))) if inc_pass and inc_fail else 0
    results['filters'][fname] = {
        'pass_rate': round(pr, 4), 'spread': round(sp, 5),
        'pass_fwd': round(pf, 5), 'fail_fwd': round(ff, 5),
        'incremental_over_505': round(inc_spread, 5),
        'n_505andF': len(inc_pass), 'n_505only': len(inc_fail),
    }
    log(f'  {fname:20s} 通过率={pr:.3f} spread={sp:+.5f} | 增量(505+F vs 505only)={inc_spread:+.5f} (n={len(inc_pass)}/{len(inc_fail)})')

# 判定: 增量正=F加正交alpha
results['recommend'] = {}
for fname in results['filters']:
    inc = results['filters'][fname]['incremental_over_505']
    results['recommend'][fname] = '加入(增量正)' if inc > 0.002 else ('不加(增量负或微)' if inc < 0 else '中性')

with open(f'{OUT}/t005_uptrend_ic.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
log(f'\n=== DONE -> {OUT}/t005_uptrend_ic.json ===')
log(json.dumps(results['recommend'], ensure_ascii=False))
