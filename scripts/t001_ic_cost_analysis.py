# -*- coding: utf-8 -*-
"""T001: 交易成本校准 + IC显著性检验(置换检验) + 牛熊分区间IC/ICIR  (v2高效版)

Project 12.7 T001。纯分析脚本,不改策略源。
- 固定505池(selected.txt 50只)在2021-2026上算 score_pool + 前向收益 -> IC (score_pool只算1次存pairs)
- 置换检验1000次(每日打乱score)得95%/99%分位+p值
- 牛熊分区间(2021-2024熊/2025-2026牛)IC/ICIR
- 成本校准(单边滑点0.5%+佣金万1+印花税千1卖出)应用于trades CSV
输出: F:/backtest_workspace/results/t001_ic_cost.json
"""
import os, sys, json, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'D:/QMT_STRATEGIES')
import numpy as np
import pandas as pd
from core.scoring.dimension6plus2 import ScoreCalculator6Plus2

OUT = 'F:/backtest_workspace/results'; os.makedirs(OUT, exist_ok=True)
POOL_FILE = 'D:/QMT_POOL/selected.txt'
ASTOCK = 'E:/astock/daily/stock_daily.parquet'
TRADES_CSV = 'D:/QMT_STRATEGIES/data/backtest_6plus2_full_result.csv'
N_PERM = 500
FWD_DAYS = [1, 5, 20]

def log(m): print(m, flush=True)

def spearman(a, b):
    """纯numpy Spearman(argsort rank, ~10x快于pandas)."""
    a = np.asarray(a, dtype=float); b = np.asarray(b, dtype=float)
    mask = ~(np.isnan(a) | np.isnan(b))
    a = a[mask]; b = b[mask]
    if len(a) < 5: return np.nan
    ra = a.argsort().argsort().astype(float); rb = b.argsort().argsort().astype(float)
    ra -= ra.mean(); rb -= rb.mean()
    da = np.sqrt((ra**2).sum()); db = np.sqrt((rb**2).sum())
    if da == 0 or db == 0: return np.nan
    return float((ra*rb).sum() / (da*db))

# ── 1. 加载池 ──
log('=== 1. 加载505池 ===')
pool = []
with open(POOL_FILE, 'r') as f:
    for line in f:
        p = line.strip().split('\t')
        if len(p) >= 1:
            c = p[0].strip()
            if len(c) == 6 and c[0] in '036':
                pool.append(c + ('.SH' if c.startswith('6') else '.SZ'))
pool = list(dict.fromkeys(pool))[:50]
log(f'池: {len(pool)} 只')

# ── 2. 加载astock数据 2021-2026 ──
log('=== 2. 加载astock数据(2021-2026) ===')
df = pd.read_parquet(ASTOCK).reset_index()
df['trade_date'] = pd.to_datetime(df['trade_date'])
df = df[(df['trade_date'] >= '2021-01-01') & (df['trade_date'] <= '2026-06-22')]
df['ts_code'] = df['ts_code'].astype(str)
df = df[df['ts_code'].isin(set(pool))].copy().rename(columns={'vol': 'volume'})
# hfq后复权: OHLC *= adj_factor (volume不调). 与 check_overlap 的 AstockParquetReader(adjustment='hfq') 一致
for col in ['open', 'high', 'low', 'close']:
    df[col] = df[col] * df['adj_factor']
df = df.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
log(f'过滤后(hfq): {df.shape}, 股票数={df["ts_code"].nunique()}, 日期={df["trade_date"].min()}~{df["trade_date"].max()}')

codes = sorted(df['ts_code'].unique())
data = {c: df[df['ts_code'] == c].set_index('trade_date')[['open', 'high', 'low', 'close', 'volume']].dropna() for c in codes}
all_dates = sorted(df['trade_date'].unique())
log(f'有效股票={len(data)} 交易日数={len(all_dates)}')

# ── 3. 一次性算所有rebal的 (score, fwd) pairs ──
log('=== 3. 算score_pool + 前向收益 pairs (每5日rebal) ===')
scorer = ScoreCalculator6Plus2()
max_fwd = max(FWD_DAYS)
rebal_idx = list(range(0, len(all_dates), 5))
pairs = []  # [{date, scores:np.array, fwd:{n:np.array}, n}]
for ri, di in enumerate(rebal_idx):
    if di + max_fwd >= len(all_dates): break
    d = all_dates[di]
    pool_dict = {}; fwd_d = {}
    for c in codes:
        sub = data[c]; hist = sub[sub.index <= d]
        if len(hist) < 60: continue
        fwd_prices = sub[sub.index > d]['close']
        if len(fwd_prices) < max_fwd: continue
        pool_dict[c] = hist.tail(120)
        fwd_d[c] = {n: float(fwd_prices.iloc[n-1] / hist['close'].iloc[-1] - 1) for n in FWD_DAYS}
    if len(pool_dict) < 10: continue
    try:
        res = scorer.score_pool(pool_dict)
    except Exception:
        continue
    s = res['score_total']
    ch = [c for c in s.index if c in fwd_d]
    if len(ch) < 5: continue
    pairs.append({
        'date': str(d.date()),
        'scores': np.array([float(s[c]) for c in ch]),
        'fwd': {n: np.array([fwd_d[c][n] for c in ch]) for n in FWD_DAYS},
        'n': len(ch),
    })
    if ri % 20 == 0: log(f'  rebal {ri+1}/{len(rebal_idx)} {d.date()} n={len(ch)}')
log(f'有效rebal点: {len(pairs)}')

# ── 4. IC统计 + 置换检验 ──
log('=== 4. IC统计 + 置换检验(1000次) ===')
results = {'n_rebal': len(pairs), 'fwd_horizons': {}}
rng = np.random.RandomState(42)
for n in FWD_DAYS:
    real_ics = [spearman(p['scores'], p['fwd'][n]) for p in pairs]
    real_ics = [x for x in real_ics if not np.isnan(x)]
    if len(real_ics) < 10: continue
    mean_ic = float(np.mean(real_ics))
    std_ic = float(np.std(real_ics, ddof=1))
    icir = mean_ic / std_ic if std_ic > 0 else 0.0
    ic_pos = float(np.mean(np.array(real_ics) > 0))
    # 置换: 每rebal打乱score重算IC, 聚合mean
    perm_means = np.zeros(N_PERM)
    for pi in range(N_PERM):
        perm_ics = []
        for p in pairs:
            sv = rng.permutation(p['scores'])
            ic_p = spearman(sv, p['fwd'][n])
            if not np.isnan(ic_p): perm_ics.append(ic_p)
        perm_means[pi] = np.mean(perm_ics) if perm_ics else 0.0
        if pi % 100 == 0: log(f'    [{n}d] perm {pi}/{N_PERM}...')
    abs_perm = np.abs(perm_means); abs_real = abs(mean_ic)
    p_val = float(np.mean(abs_perm >= abs_real))
    q95 = float(np.percentile(abs_perm, 95)); q99 = float(np.percentile(abs_perm, 99))
    results['fwd_horizons'][f'{n}d'] = {
        'mean_ic': round(mean_ic, 5), 'std_ic': round(std_ic, 5), 'icir': round(icir, 4),
        'ic_pos_ratio': round(ic_pos, 4), 'n_rebal': len(real_ics),
        'perm_p_value': round(p_val, 5), 'perm_abs_q95': round(q95, 5), 'perm_abs_q99': round(q99, 5),
        'significant_0.05': bool(p_val < 0.05), 'significant_0.01': bool(p_val < 0.01),
    }
    log(f'  [{n}d] IC={mean_ic:.5f} ICIR={icir:.4f} IC>0={ic_pos:.3f} | perm p={p_val:.4f} q95={q95:.5f} q99={q99:.5f} 显著(0.05)={bool(p_val<0.05)}')

# ── 5. 牛熊分区间IC/ICIR (5d) ──
log('=== 5. 牛熊分区间IC/ICIR (5d) ===')
bb = {}
for label, (lo, hi) in [('bear_2021_2024', ('2021-01-01', '2024-12-31')), ('bull_2025_2026', ('2025-01-01', '2026-06-22'))]:
    sub_ics = [spearman(p['scores'], p['fwd'][5]) for p in pairs if lo <= p['date'] <= hi]
    sub_ics = [x for x in sub_ics if not np.isnan(x)]
    if len(sub_ics) < 5:
        bb[label] = {'n': len(sub_ics)}; continue
    mi = float(np.mean(sub_ics)); si = float(np.std(sub_ics, ddof=1))
    bb[label] = {'n': len(sub_ics), 'mean_ic': round(mi, 5), 'icir': round(mi/si, 4) if si > 0 else 0,
                 'ic_pos_ratio': round(float(np.mean(np.array(sub_ics) > 0)), 4)}
    log(f'  {label}: n={len(sub_ics)} IC={mi:.5f} ICIR={mi/si if si>0 else 0:.4f}')
results['bull_bear_5d'] = bb

# ── 6. 成本校准 ──
log('=== 6. 成本校准 ===')
cost = {}
if os.path.exists(TRADES_CSV):
    tr = pd.read_csv(TRADES_CSV)
    tr['buy_eff'] = tr['buy_price'] * 1.0051; tr['sell_eff'] = tr['sell_price'] * 0.9939
    tr['ret_raw'] = tr['sell_price'] / tr['buy_price'] - 1
    tr['ret_cost'] = tr['sell_eff'] / tr['buy_eff'] - 1
    tr['pnl_cost'] = tr['ret_cost'] * tr['buy_price'] * tr['shares']
    n_tr = len(tr)
    cost = {
        'n_trades': n_tr,
        'avg_ret_raw_pct': round(float(tr['ret_raw'].mean()*100), 2),
        'avg_ret_cost_pct': round(float(tr['ret_cost'].mean()*100), 2),
        'cost_drag_per_trade_pct': round(float((tr['ret_raw']-tr['ret_cost']).mean()*100), 2),
        'win_rate_raw_pct': round(int((tr['ret_raw']>0).sum())/n_tr*100, 2),
        'win_rate_cost_pct': round(int((tr['ret_cost']>0).sum())/n_tr*100, 2),
        'total_pnl_raw': round(float(tr['pnl'].sum()), 0),
        'total_pnl_cost': round(float(tr['pnl_cost'].sum()), 0),
        'note': '单边滑点0.5%+佣金万1(买卖)+印花税千1(卖); 组合总收益需equity curve重构',
    }
    log(f'  trades={n_tr} avg_ret raw={cost["avg_ret_raw_pct"]}% -> cost={cost["avg_ret_cost_pct"]}% (drag {cost["cost_drag_per_trade_pct"]}%/笔)')
else:
    cost = {'error': f'{TRADES_CSV} not found'}
results['cost_calibration'] = cost

results['pool_size'] = len(pool)
results['date_range'] = f'{all_dates[0].date()}~{all_dates[-1].date()}'
results['n_perm'] = N_PERM
with open(f'{OUT}/t001_ic_cost.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
log(f'\n=== DONE -> {OUT}/t001_ic_cost.json ===')
log(json.dumps(results, ensure_ascii=False, indent=2))
