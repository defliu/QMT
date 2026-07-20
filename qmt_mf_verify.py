# coding=utf-8
# T6 verification: compare translated qmt_mf_strategy against verified
# research/multi_factor_ic implementation, using astock data.
import sys, os
sys.path.insert(0, 'D:/QMT_STRATEGIES')
import pandas as pd
import numpy as np

import research.multi_factor_ic.data_loader as dl
import research.multi_factor_ic.config as cfg
import research.multi_factor_ic.scoring as sc
import qmt_mf_strategy as mf

# short window to speed up (build_panel still reads full parquet then filters)
cfg.START_DATE = '2023-01-01'
cfg.END_DATE = '2023-07-01'
dl.START_DATE = '2023-01-01'
dl.END_DATE = '2023-07-01'

print('[verify] building panel (astock)...')
univ = dl.load_universe()
panel, fin_ffill = dl.build_panel(univ)
print('[verify] panel shape', panel.shape, 'fin_ffill shape', fin_ffill.shape)

# Normalize astock units to YUAN so select_top's yuan-based thresholds apply:
#   astock circ_mv is in 万元 (x1e4), amount is in 千元 (x1e3)
panel['circ_mv'] = panel['circ_mv'] * 1e4
panel['amount'] = panel['amount'] * 1e3
print('[verify] normalized circ_mv/amount to yuan')

_tds = sorted(panel.index.get_level_values('trade_date').unique())
print('[verify] trade_date dtype sample:', type(_tds[-1]).__name__, repr(_tds[-1]))
date = _tds[-1]   # use an actual trade date from the panel, whatever its type
print('[verify] rebal date', date)

# ---- factor-level comparison ----
rf = sc.compute_all_factors(panel, fin_ffill, date)
mf_f = mf.compute_all_factors(panel, fin_ffill, date)
print('\n=== factor corr (research vs translated) ===')
for k in ['BP', 'momentum_1m', 'momentum_3m', 'momentum_6m',
          'turnover_change', 'volatility_60d', 'liquidity_avg', 'ROE',
          'dividend_yield']:
    if k in rf and k in mf_f:
        a = rf[k].dropna()
        b = mf_f[k].dropna()
        common = a.index.intersection(b.index)
        if len(common) > 5:
            c = np.corrcoef(a[common].values, b[common].values)[0, 1]
            print('  %-16s corr=%.4f  n=%d' % (k, c, len(common)))

# ---- score-level comparison ----
scorer = sc.MultiFactorScorer()
r = scorer.score(panel, fin_ffill, date)
m = mf.score(panel, fin_ffill, date)
r_top = r.dropna().sort_values(ascending=False).head(20)
m_top = m.dropna().sort_values(ascending=False).head(20)
print('\n=== score comparison ===')
print('  research top5:', list(r_top.index)[:5])
print('  mine     top5:', list(m_top.index)[:5])
print('  overlap top20:', len(set(r_top.index) & set(m_top.index)), '/20')
common = r.dropna().index.intersection(m.dropna().index)
if len(common) > 5:
    c = np.corrcoef(r[common].values, m[common].values)[0, 1]
    print('  score corr over %d stocks: %.4f' % (len(common), c))

# ---- select_top on 0-30yi universe ----
print('\n=== select_top (0-30yi small cap) ===')
dd = panel.loc[date]
mv = dd['circ_mv']
print('[dbg] circ_mv  min=%.3e med=%.3e max=%.3e' % (mv.min(), mv.median(), mv.max()))
print('[dbg] amount   min=%.3e med=%.3e max=%.3e' % (dd['amount'].min(), dd['amount'].median(), dd['amount'].max()))
print('[dbg] UNIVERSE_MV_MAX=%.3e  MIN_AMOUNT=%.3e' % (mf.UNIVERSE_MV_MAX, mf.MIN_AMOUNT))
umask = (mv > 0) & (mv <= mf.UNIVERSE_MV_MAX)
print('[dbg] umask count:', int(umask.sum()))
if 'is_st' in dd.columns:
    print('[dbg] is_st True count:', int(dd['is_st'].astype(bool).sum()))
# base mask (PE>0 & PB>0 & ROE>=-20)
base = (dd['pe_ttm'] > 0) & (dd['pb'] > 0)
print('[dbg] base(PE>0&PB>0) count:', int(base.sum()))
selected = mf.select_top(panel, fin_ffill, date)
print('  selected count:', len(selected))
if selected:
    print('  top5:', [(c, round(s, 1)) for c, s in selected[:5]])
# sanity: all selected should be <= 30yi float mv on date
mv = panel.loc[date, 'circ_mv']
sel_mv = mv.reindex([c for c, _ in selected])
over_cap = sel_mv[(sel_mv > mf.UNIVERSE_MV_MAX)].index.tolist()
print('  over 30yi cap (should be 0):', len(over_cap))


# ============================================================
#  Data-layer verification (T6-bis): prove mf._assemble() -- the live
#  data path -- produces the SAME (panel, fin_ffill) structure as
#  research build_panel, so select_top yields identical results.
#
#  We feed _assemble the SAME astock inputs the live path would use:
#    panel_hist = astock OHLCV history (xtdata-equivalent)
#    fund_map   = astock current fundamentals @ snapshot date (the CSV content)
#    fin_series = astock quarterly ROE series (the CSV content)
#  and compare its select_top to research truth at the SAME snapshot date.
# ============================================================
SNAP_DATE = '2026-06-08'   # the snapshot date the refresh script picked


def verify_data_layer():
    print('\n========== data-layer (_assemble) verification ==========')
    cfg.START_DATE = '2018-01-01'
    cfg.END_DATE = '2026-06-30'
    dl.START_DATE = '2018-01-01'
    dl.END_DATE = '2026-06-30'
    univ = dl.load_universe()
    panel_ref, fin_ref = dl.build_panel(univ)
    print('[dl] reference panel', panel_ref.shape, 'fin_ffill', fin_ref.shape)

    date = pd.Timestamp(SNAP_DATE)
    tds = sorted(panel_ref.index.get_level_values('trade_date').unique())
    if date not in tds:
        date = tds[-1]
        print('[warn] SNAP_DATE not in panel, use', date)
    print('[data] test date =', date)

    # ---- build panel_hist (OHLCV) from astock, window [date-130, date] ----
    daily = pd.read_parquet(cfg.DAILY_PATH)
    daily = daily.loc[daily.index.get_level_values('ts_code').isin(univ)].copy()
    di = daily.index
    start = date - pd.Timedelta(days=130)
    dmask = (di.get_level_values('trade_date') >= start) & (di.get_level_values('trade_date') <= date)
    hist = daily.loc[dmask][['open', 'high', 'low', 'close', 'vol', 'amount']].copy()
    hist['amount'] = hist['amount'] * 1e3  # astock 千元 -> 元
    print('[data] panel_hist rows', hist.shape)

    # ---- fund_map @ snapshot date (current fundamentals) ----
    sd = di.get_level_values('trade_date') == date
    snap = daily.loc[sd]
    fund_map = {}
    for code in snap.index.get_level_values('ts_code'):
        row = snap.loc[snap.index.get_level_values('ts_code') == code]
        if len(row) == 0:
            continue
        r = row.iloc[0]
        fund_map[code] = {
            'pe_ttm': float(r['pe_ttm']) if pd.notna(r['pe_ttm']) else np.nan,
            'pb': float(r['pb']) if pd.notna(r['pb']) else np.nan,
            'dv_ratio': float(r['dv_ratio']) if pd.notna(r['dv_ratio']) else np.nan,
            'circ_mv': float(r['circ_mv']) * 1e4 if pd.notna(r['circ_mv']) else np.nan,
            'is_st': bool(r['is_st']) if pd.notna(r['is_st']) else False,
            'suspend_type': str(r['suspend_type']) if pd.notna(r['suspend_type']) else 'N',
        }

    # ---- fin_series (quarterly ROE) from astock ----
    fin = pd.read_parquet(cfg.FINANCE_PATH)
    fin = fin[fin['ts_code'].isin(univ)][['ts_code', 'end_date', 'roe', 'grossprofit_margin']].copy()
    fin['end_date'] = pd.to_datetime(fin['end_date'], format='%Y%m%d')
    fin = fin.sort_values(['ts_code', 'end_date']).groupby(['ts_code', 'end_date'], as_index=False).last()
    print('[data] fin_series rows', fin.shape)

    # ---- live-style assembly ----
    panel_live, fin_live = mf._assemble(hist, fund_map, fin)

    # reference in live units (circ_mv 万元->元, amount 千元->元)
    panel_ref = panel_ref.copy()
    panel_ref['circ_mv'] = panel_ref['circ_mv'] * 1e4
    panel_ref['amount'] = panel_ref['amount'] * 1e3
    rmask = panel_ref.index.get_level_values('trade_date') <= date
    panel_ref_s = panel_ref.loc[rmask]

    # ---- compare select_top ----
    sel_live = mf.select_top(panel_live, fin_live, date)
    sel_ref = mf.select_top(panel_ref_s, fin_ref, date)
    print('\n=== select_top compare (live-assembled vs research) ===')
    print('  live count:', len(sel_live))
    print('  ref  count:', len(sel_ref))
    if sel_live and sel_ref:
        cl = [c for c, _ in sel_live]
        cr = [c for c, _ in sel_ref]
        print('  top5 live:', cl[:5])
        print('  top5 ref :', cr[:5])
        print('  overlap top20: %d/20' % len(set(cl[:20]) & set(cr[:20])))
        sv = dict(sel_live); rv = dict(sel_ref)
        common = set(sv) & set(rv)
        if len(common) > 5:
            a = np.array([sv[c] for c in common])
            b = np.array([rv[c] for c in common])
            print('  score corr over %d: %.4f' % (len(common), np.corrcoef(a, b)[0, 1]))
        # diagnostic: which ref-top20 are missing from live, and by how much
        live20 = set(cl[:20]); ref20 = set(cr[:20])
        miss = ref20 - live20
        if miss:
            print('  ref-top20 missing in live: %s' % sorted(miss))
            for c in sorted(miss):
                print('    %s  live=%.2f  ref=%.2f' % (c, sv.get(c, float('nan')), rv.get(c, float('nan'))))

    tds_live = panel_live.index.get_level_values('trade_date')
    mv = panel_live.loc[date, 'circ_mv'] if date in tds_live else None
    if mv is not None:
        sel_codes = [c for c, _ in sel_live]
        sel_mv = mv.reindex(sel_codes)
        over = sel_mv[(sel_mv > mf.UNIVERSE_MV_MAX)].index.tolist()
        print('  live over 30yi cap (should be 0):', len(over))
    else:
        print('  [warn] date row missing in panel_live')


if __name__ == '__main__':
    verify_data_layer()
