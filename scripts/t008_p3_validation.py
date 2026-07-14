# -*- coding: utf-8 -*-
"""T008: P3维度(ATR/流通市值/资金流向)历史IC验证 + 共线性 + 灰度方案

P3四维: ATR/流通市值/资金流向(历史可算) + 龙虎榜(仅当日实时, 无历史, 跳过IC)。
算P3三维的IC/ICIR + 与8个P0维度的相关系数(共线性)。
淘汰: IC<0.02 或 相关系数>0.7。
灰度方案(不实施): 10%资金+pool过滤后≥60分标的+熔断(连续3天IC负/单周回撤>2%)。
输出: F:/backtest_workspace/results/t008_p3_ic.json
"""
import os, sys, json, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'D:/QMT_STRATEGIES')
import numpy as np
import pandas as pd
from core.scoring.dimension6plus2 import ScoreCalculator6Plus2
from core.utils import ma, safe_last

OUT = 'F:/backtest_workspace/results'; os.makedirs(OUT, exist_ok=True)
POOL_FILE = 'D:/QMT_POOL/selectedall.txt'
ASTOCK = 'E:/astock/daily/stock_daily.parquet'
FWD = 5
P0_DIMS = ['score_breakout', 'score_trend', 'score_consolidation', 'score_volumeprice',
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

# P3维度计算
def score_atr(df):
    """ATR(14)/close 波动率分档(低波动加分). 4分."""
    if len(df) < 15: return np.nan
    h, l, c = df['high'], df['low'], df['close']
    tr = pd.concat([h-l, (h-c.shift(1)).abs(), (l-c.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    cl = safe_last(c)
    if cl <= 0: return np.nan
    ap = safe_last(atr) / cl
    if ap < 0.03: return 4.0
    if ap < 0.06: return 3.0
    if ap < 0.10: return 2.0
    return 1.0

def score_circ_mv(df):
    """流通市值分档(中小盘加分). 3分. 需circ_mv列."""
    if 'circ_mv' not in df.columns or len(df) < 1: return np.nan
    mv = safe_last(df['circ_mv'])
    if pd.isna(mv) or mv <= 0: return np.nan
    mvy = mv / 1e8  # 亿元
    if mvy < 50: return 3.0
    if mvy < 200: return 2.0
    return 1.0

def score_fund_flow(df):
    """资金流向(量价代理). 5分. ret_5d + vol_ratio."""
    if len(df) < 6: return np.nan
    c = df['close']; v = df['volume'] if 'volume' in df.columns else df.get('vol', pd.Series([0]*len(df)))
    ret5 = safe_last(c) / c.iloc[-6] - 1 if len(c) >= 6 else 0
    vma5 = safe_last(v.rolling(5).mean())
    vr = safe_last(v) / vma5 if vma5 > 0 else 1.0
    if ret5 > 0.03 and vr > 1.2: return 3.5
    if ret5 > 0 and vr > 1.0: return 2.5
    return 1.5

# ── 加载池+astock(含circ_mv) ──
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
    df[col] = df[col] * df['adj_factor']  # OHLC hfq; circ_mv不调(市值绝对值)
codes = sorted(df['ts_code'].unique())
# 保留circ_mv用于P3
data = {c: df[df['ts_code'] == c].set_index('trade_date')[['open','high','low','close','volume','circ_mv']].dropna() for c in codes}
all_dates = sorted(df['trade_date'].unique())
log(f'池={len(pool)} 有效股票={len(data)} 交易日={len(all_dates)}')

scorer = ScoreCalculator6Plus2()
rebal_idx = list(range(0, len(all_dates), 10))
pairs = []  # per rebal: P3 scores + P0 scores + fwd
for ri, di in enumerate(rebal_idx):
    if di + FWD >= len(all_dates): break
    d = all_dates[di]
    pool_dict = {}; fwd_d = {}; p3 = {'atr':{}, 'circ_mv':{}, 'fund_flow':{}}
    for c in codes:
        sub = data[c]; hist = sub[sub.index <= d]
        if len(hist) < 60: continue
        fwd_prices = sub[sub.index > d]['close']
        if len(fwd_prices) < FWD: continue
        dfc = hist.tail(120)
        pool_dict[c] = dfc[['open','high','low','close','volume']]
        p3['atr'][c] = score_atr(dfc)
        p3['circ_mv'][c] = score_circ_mv(dfc)
        p3['fund_flow'][c] = score_fund_flow(dfc)
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
        'p0': {dim: np.array([float(res.loc[c, dim]) for c in ch]) for dim in P0_DIMS},
        'p3': {k: np.array([v.get(c, np.nan) for c in ch]) for k, v in p3.items()},
        'fwd': np.array([fwd_d[c] for c in ch]),
    })
    if ri % 15 == 0: log(f'  rebal {ri+1}/{len(rebal_idx)} {d.date()} n={len(ch)}')
log(f'有效rebal: {len(pairs)}')

# ── P3 IC + 共线性 ──
log('=== P3维度 IC + 与P0共线性 ===')
results = {'n_rebal': len(pairs), 'p3_dims': {}}
for p3k in ['atr', 'circ_mv', 'fund_flow']:
    ics = [spearman(p['p3'][p3k], p['fwd']) for p in pairs]
    ics = [x for x in ics if not np.isnan(x)]
    mi = float(np.mean(ics)) if ics else 0
    si = float(np.std(ics, ddof=1)) if len(ics) > 1 else 0
    # 共线性: P3与各P0维度的相关(聚合)
    corr = {}
    for dim in P0_DIMS:
        all_p3 = np.concatenate([p['p3'][p3k] for p in pairs])
        all_p0 = np.concatenate([p['p0'][dim] for p in pairs])
        m = ~(np.isnan(all_p3) | np.isnan(all_p0))
        if m.sum() < 20: corr[dim] = 0; continue
        c = np.corrcoef(all_p3[m], all_p0[m])[0, 1]
        corr[dim] = round(float(c), 3) if not np.isnan(c) else 0
    max_corr_dim = max(corr, key=lambda k: abs(corr[k]))
    max_corr = corr[max_corr_dim]
    eliminate = (abs(mi) < 0.02) or (abs(max_corr) > 0.7)
    results['p3_dims'][p3k] = {
        'mean_ic': round(mi, 5), 'icir': round(mi/si, 4) if si > 0 else 0,
        'n_rebal': len(ics),
        'corr_with_p0': corr, 'max_corr_dim': max_corr_dim, 'max_corr': max_corr,
        'eliminate': bool(eliminate),
        'reason': (f'IC弱|{mi:.4f}|<0.02' if abs(mi)<0.02 else '') + (f' + 共线性{max_corr_dim}={max_corr}>0.7' if abs(max_corr)>0.7 else ''),
    }
    log(f'  {p3k:12s} IC={mi:.5f} ICIR={mi/si if si>0 else 0:.4f} | max corr={max_corr_dim}({max_corr}) | 淘汰={eliminate}')

# 龙虎榜说明
results['lhb'] = {'historical': '不可得(akshare龙虎榜仅当日实时, 无可靠历史)', 'ic': 'skip', 'note': '仅做当日实时信号, 不做历史IC'}

# 灰度方案(不实施)
results['greybox_plan'] = {
    '资金': '账户总资金10%',
    '标的': '仅在pool过滤后≥60分标的中启用P3',
    '熔断1': '连续3天IC为负 -> 立刻关闭灰度',
    '熔断2': '单周回撤>2% -> 立刻关闭灰度',
    '前提': '待回测工厂v0.3 P2真实业绩验证后再评估启动; 当前P3 IC弱/共线性高, 不建议启动',
}

with open(f'{OUT}/t008_p3_ic.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
log(f'\n=== DONE -> {OUT}/t008_p3_ic.json ===')
log(f'淘汰: {[(k, v["reason"]) for k, v in results["p3_dims"].items() if v["eliminate"]]}')
log(f'保留: {[k for k, v in results["p3_dims"].items() if not v["eliminate"]]}')
