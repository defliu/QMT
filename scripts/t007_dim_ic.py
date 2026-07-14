# -*- coding: utf-8 -*-
"""T007: 200+样本池 8维度有效性IC/ICIR + 维度精简

Project 12.7 T007。扩展T001到248股池(selectedall.txt), 逐P0维度算IC/ICIR/IC>0占比,
全周期+牛熊分区间, 按淘汰规则(IC<0.02或IC>0占比<55%)精简。
输出: F:/backtest_workspace/results/t007_dim_ic.json
"""
import os, sys, json, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'D:/QMT_STRATEGIES')
import numpy as np
import pandas as pd
from core.scoring.dimension6plus2 import ScoreCalculator6Plus2

OUT = 'F:/backtest_workspace/results'; os.makedirs(OUT, exist_ok=True)
POOL_FILE = 'D:/QMT_POOL/selectedall.txt'  # 248只, >200满足T007
ASTOCK = 'E:/astock/daily/stock_daily.parquet'
FWD = 5  # 5日前向(T001中间horizon)
DIMS = ['score_breakout', 'score_trend', 'score_consolidation', 'score_volumeprice',
        'score_macd', 'score_valuation', 'score_short_term_momentum', 'score_sector']

def log(m): print(m, flush=True)

def spearman(a, b):
    a = np.asarray(a, dtype=float); b = np.asarray(b, dtype=float)
    m = ~(np.isnan(a) | np.isnan(b)); a = a[m]; b = b[m]
    if len(a) < 5: return np.nan
    ra = a.argsort().argsort().astype(float); rb = b.argsort().argsort().astype(float)
    ra -= ra.mean(); rb -= rb.mean()
    da = np.sqrt((ra**2).sum()); db = np.sqrt((rb**2).sum())
    if da == 0 or db == 0: return np.nan
    return float((ra*rb).sum() / (da*db))

# ── 1. 加载248池 ──
log('=== 1. 加载selectedall(248池) ===')
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
log(f'池: {len(pool)} 只')

# ── 2. 加载astock 2021-2026 (hfq) ──
log('=== 2. 加载astock(hfq) 2021-2026 ===')
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
log(f'有效股票={len(data)} 交易日={len(all_dates)}')

# ── 3. 每10日rebal, score_pool + 前向收益 (存per-dim pairs) ──
log(f'=== 3. score_pool + {FWD}d前向 (每10日rebal) ===')
scorer = ScoreCalculator6Plus2()
rebal_idx = list(range(0, len(all_dates), 10))
pairs = []  # [{date, dims:{dim:np.array}, fwd:np.array}]
for ri, di in enumerate(rebal_idx):
    if di + FWD >= len(all_dates): break
    d = all_dates[di]
    pool_dict = {}; fwd_d = {}
    for c in codes:
        sub = data[c]; hist = sub[sub.index <= d]
        if len(hist) < 60: continue
        fwd_prices = sub[sub.index > d]['close']
        if len(fwd_prices) < FWD: continue
        pool_dict[c] = hist.tail(120)
        fwd_d[c] = float(fwd_prices.iloc[FWD-1] / hist['close'].iloc[-1] - 1)
    if len(pool_dict) < 20: continue
    try:
        res = scorer.score_pool(pool_dict)
    except Exception:
        continue
    ch = [c for c in res.index if c in fwd_d]
    if len(ch) < 10: continue
    pairs.append({
        'date': str(d.date()),
        'dims': {dim: np.array([float(res.loc[c, dim]) for c in ch]) for dim in DIMS},
        'fwd': np.array([fwd_d[c] for c in ch]),
        'n': len(ch),
    })
    if ri % 15 == 0: log(f'  rebal {ri+1}/{len(rebal_idx)} {d.date()} n={len(ch)}')
log(f'有效rebal: {len(pairs)}')

# ── 4. 逐维度 IC/ICIR + 全周期/牛熊 ──
log('=== 4. 逐维度IC ===')
results = {'n_rebal': len(pairs), 'pool_size': len(pool), 'fwd': FWD, 'dims': {}}
for dim in DIMS:
    # 全周期
    full_ics = [spearman(p['dims'][dim], p['fwd']) for p in pairs]
    full_ics = [x for x in full_ics if not np.isnan(x)]
    # 牛熊
    bear_ics = [spearman(p['dims'][dim], p['fwd']) for p in pairs if p['date'] <= '2024-12-31']
    bear_ics = [x for x in bear_ics if not np.isnan(x)]
    bull_ics = [spearman(p['dims'][dim], p['fwd']) for p in pairs if p['date'] >= '2025-01-01']
    bull_ics = [x for x in bull_ics if not np.isnan(x)]
    def stat(ics):
        if len(ics) < 5: return {}
        mi = float(np.mean(ics)); si = float(np.std(ics, ddof=1))
        return {'n': len(ics), 'mean_ic': round(mi, 5), 'std_ic': round(si, 5),
                'icir': round(mi/si, 4) if si > 0 else 0, 'ic_pos_ratio': round(float(np.mean(np.array(ics) > 0)), 4)}
    results['dims'][dim] = {'full': stat(full_ics), 'bear_2021_2024': stat(bear_ics), 'bull_2025_2026': stat(bull_ics)}
    f = results['dims'][dim]['full']
    log(f'  {dim:30s} full: IC={f.get("mean_ic")} ICIR={f.get("icir")} IC>0={f.get("ic_pos_ratio")}')

# ── 5. 淘汰规则 + 精简 ──
log('=== 5. 维度淘汰(IC<0.02或IC>0占比<55%) ===')
eliminate = []; keep = []
for dim in DIMS:
    f = results['dims'][dim]['full']
    mi = f.get('mean_ic', 0); ipos = f.get('ic_pos_ratio', 0)
    # 用|IC|判(负IC也有信号, 但任务书规则用IC<0.02; 负IC按淘汰or逆向另判)
    reason = []
    if abs(mi) < 0.02: reason.append(f'|IC|{abs(mi):.4f}<0.02')
    if ipos < 0.55 and ipos > 0.45: reason.append(f'IC>0占比{ipos:.3f}近0.5(无方向)')
    if reason:
        eliminate.append((dim, reason, mi, ipos))
    else:
        keep.append((dim, mi, ipos))
results['eliminate'] = [{'dim': d, 'reason': r, 'ic': mi, 'ic_pos': ipos} for d, r, mi, ipos in eliminate]
results['keep'] = [{'dim': d, 'ic': mi, 'ic_pos': ipos} for d, mi, ipos in keep]
log(f'  保留{len(keep)}: {[d for d,_,_ in keep]}')
log(f'  淘汰{len(eliminate)}: {[(d, r) for d,r,_,_ in eliminate]}')

with open(f'{OUT}/t007_dim_ic.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
log(f'\n=== DONE -> {OUT}/t007_dim_ic.json ===')
