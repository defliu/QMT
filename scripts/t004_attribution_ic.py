# -*- coding: utf-8 -*-
"""T004-step2: pool白盒化逐条件IC归因(快版, 复用T007方法)

替代任务书的"逐条件跑回测"(慢,780股×9条件), 改用per-condition截面IC:
每条505原子条件(C1-C7 QMT可复现)算IC/ICIR/通过率, 量化各条件预测力。
C8/C9筹码TDX-only跳过(无QMT原生值)。
贡献定义(替代): 条件的IC正值=有预测力(正贡献); IC负=反预测; IC≈0=中性过滤。
输出: F:/backtest_workspace/results/t004_attr_ic.json
"""
import os, sys, json, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'D:/QMT_STRATEGIES')
import numpy as np
import pandas as pd
sys.path.insert(0, 'D:/QMT_STRATEGIES/Project_13_pool白盒化')
from whitebox_pool import CONDITIONS, check_all_conditions
from core.utils import ma

OUT = 'F:/backtest_workspace/results'; os.makedirs(OUT, exist_ok=True)
POOL_FILE = 'D:/QMT_POOL/selectedall.txt'
ASTOCK = 'E:/astock/daily/stock_daily.parquet'
FWD = 5

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

# C8/C9跳过(筹码TDX-only), 只归因C1-C7
CONDS = [(k, n, fn, nat, ov) for k, n, fn, nat, ov in CONDITIONS if k in ['C1','C2','C3','C4','C5','C6','C7']]

# ── 加载池 + astock(hfq) ──
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

# ── 每10日rebal, 算每条条件的bool + 前向收益 ──
log(f'=== 每10日rebal, per-condition IC ({FWD}d前向) ===')
rebal_idx = list(range(0, len(all_dates), 10))
# 每条件存 (bool_array, fwd_array) per rebal -> 算IC(bool作为0/1因子)
# 但bool因子IC用Spearman(bool, fwd)意义不大(bool只有2值). 改用: 条件通过组的均值收益 vs 未通过组 -> 贡献
# 更好: 用条件通过率分组的收益差. 这里用: per-rebal, 通过条件i的股票平均fwd vs 未通过 -> spread.
pairs = []  # [{date, conds:{ck: bool_arr}, fwd:arr, codes:[]}]
for ri, di in enumerate(rebal_idx):
    if di + FWD >= len(all_dates): break
    d = all_dates[di]
    cond_vals = {ck: [] for ck, _, _, _, _ in CONDS}
    fwd_list = []; code_list = []
    for c in codes:
        sub = data[c]; hist = sub[sub.index <= d]
        if len(hist) < 60: continue
        fwd_prices = sub[sub.index > d]['close']
        if len(fwd_prices) < FWD: continue
        dfc = hist.tail(120)
        conds = check_all_conditions(dfc)
        fwd = float(fwd_prices.iloc[FWD-1] / hist['close'].iloc[-1] - 1)
        for ck, _, _, _, _ in CONDS:
            cond_vals[ck].append(1.0 if conds.get(ck) is True else 0.0)
        fwd_list.append(fwd)
        code_list.append(c)
    if len(code_list) < 20: continue
    pairs.append({
        'date': str(d.date()),
        'conds': {ck: np.array(cond_vals[ck]) for ck, _, _, _, _ in CONDS},
        'fwd': np.array(fwd_list),
        'n': len(code_list),
    })
    if ri % 15 == 0: log(f'  rebal {ri+1}/{len(rebal_idx)} {d.date()} n={len(code_list)}')
log(f'有效rebal: {len(pairs)}')

# ── per-condition: 通过率 + IC(Spearman bool因子, fwd) + 通过组vs未通过组收益spread ──
log('=== per-condition 归因 ===')
results = {'n_rebal': len(pairs), 'fwd': FWD, 'conds': {}}
for ck, name, _, nat, ov in CONDS:
    ics = [spearman(p['conds'][ck], p['fwd']) for p in pairs]
    ics = [x for x in ics if not np.isnan(x)]
    # 通过率 + 通过组/未通过组收益spread(全聚合)
    pass_fwd = []; fail_fwd = []
    for p in pairs:
        mask = p['conds'][ck] == 1.0
        pass_fwd.extend(p['fwd'][mask].tolist())
        fail_fwd.extend(p['fwd'][~mask].tolist())
    pf = float(np.mean(pass_fwd)) if pass_fwd else 0
    ff = float(np.mean(fail_fwd)) if fail_fwd else 0
    spread = pf - ff  # 正=通过组收益更高(条件有效)
    pass_rate = float(np.mean([np.mean(p['conds'][ck]) for p in pairs]))
    mi = float(np.mean(ics)) if ics else 0
    si = float(np.std(ics, ddof=1)) if len(ics) > 1 else 0
    results['conds'][ck] = {
        'name': name, 'qmt_native': nat, 'overlap_6plus2': ov,
        'pass_rate': round(pass_rate, 4),
        'mean_ic': round(mi, 5), 'icir': round(mi/si, 4) if si > 0 else 0,
        'pass_group_fwd': round(pf, 5), 'fail_group_fwd': round(ff, 5),
        'spread': round(spread, 5),  # 核心: 正=有效alpha来源
        'n_rebal': len(ics),
    }
    log(f'  {ck} {name:20s} 通过率={pass_rate:.3f} IC={mi:.5f} spread(通过-未通过)={spread:+.5f} 通过组fwd={pf:+.5f}')

# 排序: spread正且大=核心alpha来源
ranked = sorted(results['conds'].items(), key=lambda x: -x[1]['spread'])
results['ranking_by_spread'] = [(k, v['name'], v['spread'], v['mean_ic'], v['pass_rate']) for k, v in ranked]
log('\n=== 按spread(通过组-未通过组收益)排序 ===')
for k, v in ranked:
    log(f'  {k} {v["name"]:20s} spread={v["spread"]:+.5f} IC={v["mean_ic"]} 通过率={v["pass_rate"]}')

core = [(k, v) for k, v in ranked if v['spread'] > 0.003]  # 正贡献阈值0.3%
redundant = [(k, v) for k, v in ranked if v['spread'] <= 0]
results['core_conditions'] = [{'cond': k, 'name': v['name'], 'spread': v['spread']} for k, v in core]
results['redundant_conditions'] = [{'cond': k, 'name': v['name'], 'spread': v['spread']} for k, v in redundant]
log(f'\n核心(正贡献spread>0.3%): {[(k, v["spread"]) for k, v in core]}')
log(f'冗余/负贡献(spread<=0): {[(k, v["spread"]) for k, v in redundant]}')

with open(f'{OUT}/t004_attr_ic.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
log(f'\n=== DONE -> {OUT}/t004_attr_ic.json ===')
