# coding=gbk
# QMT Multi-Factor IC Strategy (standalone, for simulation account verification)
# Factors: BP(30%) + reversal_1m(25%) + low_vol_60d(25%) + ROE(20%)
# Universe: small-cap with float_mv <= 30e8 (dynamic, by rebalance date)
# Rebalance: bi-monthly (2M); equal-weight; per-stock cap 2%; capital-adaptive N
# Risk: stop-loss -12% (D-1 close trigger), min amount 20e6, ST/suspended filter
#
# IMPORTANT (CC notes for deployment):
#  - This file is a STANDALONE QMT strategy. It does NOT go through build_strategy.py
#    and does NOT touch strategy_main.py / core / adapters. Deploy it as a separate
#    strategy file in the simulation terminal (account 67014907).
#  - Data layer is REAL (not a stub). Two sources, assembled by _assemble():
#      * OHLCV history -> QMT xtdata.get_market_data_ex (period='1d')
#      * Fundamentals   -> D:/QMT_POOL/mf_fundamentals.csv (current snapshot,
#                         yuan units) + mf_financials.csv (quarterly ROE series)
#    Refresh the CSVs daily via scripts/refresh_mf_fundamentals.py
#    (reads E:/astock, same source as the offline backtest). If the CSVs are
#    missing the strategy logs and skips (does NOT crash).
#  - Core factor/score functions (compute_all_factors, score, select_top) only depend
#    on a (panel, fin_ffill) data structure identical to research/multi_factor_ic, so
#    they were verified against astock offline (see qmt_mf_verify.py, T6).
import os
import json
import time
import math
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

# ============================================================
#  Parameters (final live params from KNOWLEDGE.md 10w backtest)
# ============================================================
ACCOUNT_ID = '67014907'
STRATEGY_NAME = 'MF_IC'

REBALANCE_MONTHS = 2          # bi-monthly
TOP_N_HARD_CAP = 80           # max holdings
STOP_LOSS = -0.12             # -12%
MAX_WEIGHT_PER_STOCK = 0.02   # 2% single-stock cap
MIN_AMOUNT = 20e6             # 2000w turnover filter
UNIVERSE_MV_MAX = 30e8        # 30yi float mv ceiling (0-30yi small cap)
FIN_LOOKAHEAD_DAYS = 45       # financial disclosure lag
WINSOR_LO = 0.01
WINSOR_HI = 0.99

FACTOR_WEIGHTS = {
    'BP': 0.30,
    'reversal_1m': 0.25,
    'volatility_60d': 0.25,
    'ROE': 0.20,
}

# Paths (QMT has no __file__; use absolute paths)
POOL_DIR = 'D:/QMT_POOL/'
STATE_FILE = POOL_DIR + 'mf_state.json'

# QMT global functions (provided at runtime by QMT exec environment):
#   passorder, get_trade_detail_data, get_market_data_ex, get_full_tick,
#   get_stock_list_in_sector, get_current_time, get_stock_name
BUY_CODE = 23
SELL_CODE = 24


# ============================================================
#  Global state
# ============================================================
_g_trader = None
_g_state = {
    'holdings': {},        # code -> {entry_price, shares}
    'last_rebal_ym': 0,    # last rebalance year*12+month
    'rebal_done_this_month': False,
}


# ============================================================
#  Code / name / time utilities
# ============================================================
def _std_to_tq(code):
    if code.endswith('.SH'):
        return '1' + code[:6]
    if code.endswith('.SZ'):
        return '0' + code[:6]
    if code.endswith('.BJ'):
        return '2' + code[:6]
    return code


def _code6_to_std(code6):
    code = str(code6).strip().zfill(6)
    if len(code) != 6 or not code.isdigit():
        return None
    if code.startswith('6') or code.startswith('5') or code.startswith('688') or code.startswith('689'):
        return code + '.SH'
    if code.startswith('0') or code.startswith('002') or code.startswith('003') \
       or code.startswith('300') or code.startswith('301'):
        return code + '.SZ'
    if code.startswith('4') or code.startswith('8'):
        return code + '.BJ'
    return None


def _is_st_name(name):
    if not name:
        return False
    return 'ST' in str(name).upper()


def _get_qmt_time(C):
    try:
        return C.get_current_time()
    except Exception:
        pass
    return datetime.now()


def _market_now(C):
    # Prefer QMT market time (device clock unreliable on some boxes)
    try:
        dt = _get_qmt_time(C)
        if dt is not None and dt.year >= 2020:
            return dt
    except Exception:
        pass
    return datetime.now()


# ============================================================
#  Factor utilities
# ============================================================
def winsorize(series, lower=WINSOR_LO, upper=WINSOR_HI):
    lo = series.quantile(lower)
    hi = series.quantile(upper)
    return series.clip(lo, hi)


def standardize(series):
    return (series - series.mean()) / series.std(ddof=0)


# ============================================================
#  Factor computation (translated from research/multi_factor_ic/factors.py)
#  Look-ahead controls (verified):
#   - momentum uses date-1 close; vol/turn/liq windows end at prev_date
#   - ROE uses financial data as of (date - 45 days)
# ============================================================
def compute_all_factors(panel, fin_ffill, date):
    result = {}
    trade_dates = sorted(panel.index.get_level_values('trade_date').unique())
    date_series = panel.loc[date]

    # EP / BP / dividend yield (same-day, no look-ahead)
    ep = 1.0 / date_series['pe_ttm'].replace(0, np.nan)
    result['EP'] = ep
    bp = 1.0 / date_series['pb'].replace(0, np.nan)
    result['BP'] = bp
    result['dividend_yield'] = date_series['dv_ratio']

    # ROE (financial as of date - 45 days, forward-filled)
    fin_dates = fin_ffill.index
    lookup_date = pd.Timestamp(date) - pd.Timedelta(days=FIN_LOOKAHEAD_DAYS)
    valid = fin_dates[fin_dates <= lookup_date]
    if len(valid) > 0:
        roe = fin_ffill.loc[valid[-1], 'roe']
        gpm = fin_ffill.loc[valid[-1], 'grossprofit_margin']
    else:
        roe = pd.Series(np.nan, index=date_series.index)
        gpm = pd.Series(np.nan, index=date_series.index)
    result['ROE'] = roe.reindex(date_series.index)
    result['grossprofit_margin'] = gpm.reindex(date_series.index)

    # Momentum (exclude current day: use date-1 close)
    date_idx = trade_dates.index(date)
    prev_idx = max(0, date_idx - 1)
    prev_date = trade_dates[prev_idx]
    prev_close = panel.loc[prev_date, 'close']
    for name, w in [('momentum_1m', 20), ('momentum_3m', 60), ('momentum_6m', 120)]:
        if date_idx >= w:
            start = trade_dates[date_idx - w]
            start_close = panel.loc[start, 'close']
            common = prev_close.index.intersection(start_close.index)
            ret = prev_close[common] / start_close[common] - 1.0
            result[name] = ret.reindex(date_series.index)
        else:
            result[name] = pd.Series(0.0, index=date_series.index)

    # Turnover change (near 20d / near 60d mean, exclude current day)
    if date_idx > 60:
        s20 = panel.loc[trade_dates[date_idx - 20]:prev_date, 'turnover_rate'].groupby('ts_code').mean()
        s60 = panel.loc[trade_dates[date_idx - 60]:prev_date, 'turnover_rate'].groupby('ts_code').mean()
        tc = s20 / s60.replace(0, np.nan) - 1.0
        result['turnover_change'] = tc.reindex(date_series.index)
    else:
        result['turnover_change'] = pd.Series(0.0, index=date_series.index)

    # Volatility 60d (exclude current day)
    if date_idx > 60:
        pct = panel.loc[trade_dates[date_idx - 60]:prev_date, 'pct_chg']
        vol = pct.groupby('ts_code').std()
        result['volatility_60d'] = vol.reindex(date_series.index)
    else:
        result['volatility_60d'] = pd.Series(0.0, index=date_series.index)

    # Liquidity 20d avg log amount (exclude current day)
    if date_idx > 20:
        amt = panel.loc[trade_dates[date_idx - 20]:prev_date, 'amount']
        la = np.log(amt.groupby('ts_code').mean().replace(0, np.nan))
        result['liquidity_avg'] = la.reindex(date_series.index)
    else:
        result['liquidity_avg'] = pd.Series(0.0, index=date_series.index)

    return result


# ============================================================
#  Scorer (translated from research/multi_factor_ic/scoring.py)
#  Uses FACTOR_WEIGHTS: BP / reversal_1m / volatility_60d / ROE
#  Fix note: top_picks() in research had a key mismatch (score_lowvol vs
#  score_volatility) that dropped the 25% low-vol weight. We use score()
#  main path only, which is correct; weights align with sub_scores keys.
# ============================================================
def score(panel, fin_ffill, date, cap_mask=None):
    raw = compute_all_factors(panel, fin_ffill, date)

    date_data = panel.loc[date]
    idx = date_data.index

    # Base safety filter (always on)
    base_mask = (date_data['pe_ttm'] > 0) & (date_data['pb'] > 0)
    fin_dates = fin_ffill.index
    lookup_date = pd.Timestamp(date) - pd.Timedelta(days=FIN_LOOKAHEAD_DAYS)
    valid = fin_dates[fin_dates <= lookup_date]
    if len(valid) > 0:
        roe = fin_ffill.loc[valid[-1], 'roe'].reindex(idx, fill_value=-np.inf)
        base_mask = base_mask & (roe >= -20)
    else:
        base_mask = base_mask & pd.Series(True, index=idx)

    if cap_mask is not None:
        if isinstance(cap_mask, pd.Series):
            cap_mask = cap_mask.reindex(idx, fill_value=False)
        else:
            cap_mask = pd.Series(cap_mask, index=idx).fillna(False)
    else:
        cap_mask = pd.Series(True, index=idx)

    final_mask = base_mask & cap_mask

    for name in raw:
        raw[name] = raw[name].where(final_mask, other=np.nan)

    # Sub-scores
    bp = raw['BP']
    sub_scores = {}
    sub_scores['BP'] = _normalize(bp, reverse=False)
    rev = raw['momentum_1m']
    sub_scores['reversal_1m'] = _normalize(rev, reverse=True)
    vol = raw['volatility_60d']
    sub_scores['volatility_60d'] = _normalize(vol, reverse=True)
    roe = raw['ROE']
    sub_scores['ROE'] = _normalize(roe, reverse=False)

    active_weights = FACTOR_WEIGHTS
    total = pd.Series(np.nan, index=bp.index)
    weight_sum = 0.0
    for name, w in active_weights.items():
        s = sub_scores.get(name)
        if s is not None and len(s.dropna()) > 0:
            total = total.add(s * w, fill_value=0)
            weight_sum += w
    if weight_sum > 0:
        total = total / weight_sum * 100.0
    return total


def _normalize(series, reverse=False):
    s = winsorize(series)
    s = standardize(s)
    if reverse:
        s = -s
    return s


# ============================================================
#  Data source (xtquant). Core functions above are data-structure
#  agnostic; this layer builds the same (panel, fin_ffill) structure
#  that research/multi_factor_ic uses (MultiIndex panel with level
#  names 'trade_date' and 'ts_code').
# ============================================================
def _load_fundamentals():
    """Load current fundamentals snapshot from D:/QMT_POOL/mf_fundamentals.csv.

    Returns dict code -> {pe_ttm, pb, dv_ratio, circ_mv(yuan), is_st,
    suspend_type}, or None if missing.
    """
    path = POOL_DIR + 'mf_fundamentals.csv'
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path, dtype={'ts_code': str})
        fund = {}
        for _, r in df.iterrows():
            fund[r['ts_code']] = {
                'pe_ttm': r['pe_ttm'],
                'pb': r['pb'],
                'dv_ratio': r['dv_ratio'],
                'circ_mv': r['circ_mv'],
                'is_st': bool(r['is_st']),
                'suspend_type': str(r['suspend_type']),
            }
        return fund
    except Exception as e:
        print('[data] load fundamentals failed: %s' % e)
        return None


def _load_financials():
    """Load quarterly ROE/grossprofit series from D:/QMT_POOL/mf_financials.csv.

    Returns DataFrame [ts_code, end_date(datetime), roe, grossprofit_margin],
    or None if missing.
    """
    path = POOL_DIR + 'mf_financials.csv'
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path, dtype={'ts_code': str})
        df['end_date'] = pd.to_datetime(df['end_date'], format='%Y%m%d')
        return df
    except Exception as e:
        print('[data] load financials failed: %s' % e)
        return None


def _assemble(panel_hist, fund_map, fin_series):
    """Assemble (panel, fin_ffill) with research-identical structure.

    Inputs:
      panel_hist : DataFrame MultiIndex(trade_date, ts_code) with at least
                   open/high/low/close/volume/amount. Factor columns
                   (pe_ttm/pb/dv_ratio/circ_mv/is_st) come from fund_map.
      fund_map    : dict code -> {pe_ttm, pb, dv_ratio, circ_mv, is_st,
                   suspend_type}. circ_mv in YUAN.
      fin_series  : DataFrame [ts_code, end_date(datetime), roe,
                   grossprofit_margin] (quarterly).
    Returns (panel, fin_ffill) matching research build_panel so that
    compute_all_factors / score / select_top work unchanged.
    """
    panel = panel_hist.copy()
    # normalize volume column name (xtdata: 'volume'; astock parquet: 'vol')
    if 'volume' not in panel.columns and 'vol' in panel.columns:
        panel['volume'] = panel['vol']
    elif 'vol' not in panel.columns and 'volume' in panel.columns:
        panel['vol'] = panel['volume']
    codes_level = panel.index.get_level_values('ts_code')
    if fund_map:
        fund_df = pd.DataFrame.from_dict(fund_map, orient='index')
        for col in ['pe_ttm', 'pb', 'dv_ratio', 'circ_mv', 'is_st']:
            if col in fund_df.columns:
                panel[col] = codes_level.map(fund_df[col])
        if 'suspend_type' in fund_df.columns:
            susp = codes_level.map(fund_df['suspend_type'])
        else:
            susp = pd.Series(['N'] * len(panel), index=panel.index)
    else:
        for col in ['pe_ttm', 'pb', 'dv_ratio', 'circ_mv', 'is_st']:
            panel[col] = np.nan
        susp = pd.Series(['N'] * len(panel), index=panel.index)

    # Drop ST / suspended (mirror research build_panel)
    if 'is_st' in panel.columns:
        is_st_bool = panel['is_st'].fillna(False).astype(bool)
    else:
        is_st_bool = pd.Series([False] * len(panel), index=panel.index)
    susp = susp.fillna('N').astype(str)
    susp_mask = susp.isin(['S', 'R', 'R&S'])
    panel = panel.loc[~is_st_bool & ~susp_mask]

    # pct_chg from close (deterministic; QMT may not return it)
    panel['pct_chg'] = panel.groupby(level='ts_code')['close'].pct_change() * 100.0
    panel['pct_chg'] = panel['pct_chg'].fillna(0.0)
    # turnover_rate: use source if present else derive vol*close/circ_mv
    if 'turnover_rate' not in panel.columns or panel['turnover_rate'].isna().all():
        with np.errstate(divide='ignore', invalid='ignore'):
            tr = (panel['volume'] * panel['close']) / panel['circ_mv'].replace(0, np.nan)
        panel['turnover_rate'] = tr.fillna(0.0)
    else:
        panel['turnover_rate'] = panel['turnover_rate'].fillna(0.0)

    # fin_ffill: pivot(end_date, ts_code) + ffill onto trade_dates (research-identical)
    if fin_series is not None and len(fin_series) > 0:
        fp = fin_series.pivot_table(index='end_date', columns='ts_code',
                                   values=['roe', 'grossprofit_margin'])
        tds = pd.DatetimeIndex(sorted(panel.index.get_level_values('trade_date').unique()))
        fin_ffill = fp.reindex(tds, method='ffill')
    else:
        fin_ffill = pd.DataFrame(index=pd.DatetimeIndex(
            sorted(panel.index.get_level_values('trade_date').unique())))
    return panel, fin_ffill


def _build_panel_via_xt(C, codes, count=130):
    """Build (panel, fin_ffill) from QMT xtdata + precomputed fundamentals.

    OHLCV history -> get_market_data_ex(period='1d').
    Fundamentals  -> D:/QMT_POOL/mf_fundamentals.csv (current snapshot,
                      yuan units) + mf_financials.csv (quarterly ROE series).
    Assembly        -> _assemble() (research-identical structure).

    Refresh the CSVs daily via scripts/refresh_mf_fundamentals.py
    (reads E:/astock, the same source as the offline backtest).
    If the CSVs are missing, returns (None, None) -> caller skips (no crash).
    """
    fund_map = _load_fundamentals()
    fin_series = _load_financials()
    if fund_map is None or fin_series is None:
        print('[data] fundamentals CSV missing; skip (run refresh_mf_fundamentals.py)')
        return None, None

    frames = {}
    batch = 200
    for i in range(0, len(codes), batch):
        sub = codes[i:i + batch]
        try:
            data = C.get_market_data_ex(stock_code=sub, period='1d', count=count)
        except Exception as e:
            print('[data] batch failed: %s' % e)
            continue
        if data:
            frames.update(data)
    if not frames:
        print('[data] get_market_data_ex returned nothing')
        return None, None

    rows = []
    for code, df in frames.items():
        if df is None or len(df) == 0:
            continue
        tmp = df.copy()
        tmp['ts_code'] = code
        rows.append(tmp)
    if not rows:
        return None, None

    full = pd.concat(rows)
    full = full.reset_index()
    # ensure required OHLCV columns exist (fill unknowns with NaN)
    for col in ['open', 'high', 'low', 'close', 'volume', 'amount',
                'turnover_rate', 'pct_chg']:
        if col not in full.columns:
            full[col] = np.nan
    # date column may be named 'trade_date' / 'date' / 'time' / reset-index 'index'
    date_col = None
    for cand in ['trade_date', 'date', 'time']:
        if cand in full.columns:
            date_col = cand
            break
    if date_col is None:
        date_col = full.columns[0]
    full = full.rename(columns={date_col: 'trade_date'})
    full['trade_date'] = pd.to_datetime(full['trade_date'])
    full = full.set_index(['trade_date', 'ts_code']).sort_index()
    return _assemble(full, fund_map, fin_series)


# ============================================================
#  Universe + selection
# ============================================================
def _universe_mask(panel, date, mv_max):
    date_data = panel.loc[date]
    mv = date_data['circ_mv']
    mask = (mv > 0) & (mv <= mv_max)
    return mask


def select_top(panel, fin_ffill, date, mv_max=UNIVERSE_MV_MAX,
               top_n_cap=TOP_N_HARD_CAP, min_amount=MIN_AMOUNT):
    """Select top-N stocks for a rebalance date.

    Returns list of (code, score) sorted descending.
    """
    trade_dates = sorted(panel.index.get_level_values('trade_date').unique())
    if date not in trade_dates:
        return []

    date_data = panel.loc[date]

    # Universe: small-cap float mv
    umask = _universe_mask(panel, date, mv_max)
    # Liquidity filter: avg amount over last 20 days >= min_amount
    date_idx = trade_dates.index(date)
    if date_idx > 20:
        amt = panel.loc[trade_dates[date_idx - 20]:date, 'amount'].groupby('ts_code').mean()
    else:
        amt = date_data['amount']
    liq_mask = amt >= min_amount
    liq_mask = liq_mask.reindex(date_data.index).fillna(False)

    # Suspend / ST filter (is_st column if present; else keep)
    if 'is_st' in date_data.columns:
        st_mask = ~date_data['is_st'].astype(bool)
    else:
        st_mask = pd.Series(True, index=date_data.index)

    cap_mask = umask & liq_mask & st_mask

    scores = score(panel, fin_ffill, date, cap_mask=cap_mask)
    scores = scores.dropna().sort_values(ascending=False)
    if len(scores) == 0:
        return []
    top = scores.head(top_n_cap)
    return [(code, float(val)) for code, val in top.items()]


# ============================================================
#  Trader (passorder + async order-id lookup, ported from
#  adapters/qmt_wrapper.py Trader)
# ============================================================
class Trader:
    def __init__(self, context, account_id, account_type='STOCK'):
        self.C = context
        self.acct = account_id
        self.acct_type = account_type
        self.BUY_CODE = BUY_CODE
        self.SELL_CODE = SELL_CODE

    def _passorder(self, order_type, stock_code, volume, remark='', price_type=5, price=-1):
        if volume <= 0:
            return False
        vol = int(volume)
        full_remark = '%s|%s' % (STRATEGY_NAME, remark) if remark else STRATEGY_NAME
        try:
            order_id = passorder(order_type, 1101, self.acct, stock_code,
                                 price_type, price, vol, full_remark, 2, '', self.C)
            return order_id
        except Exception as e:
            err = str(e).strip().split('\n')[0]
            print('[trade] order failed: %s' % err)
            return None

    def buy(self, stock_code, volume, remark=''):
        vol = (int(volume) // 100) * 100
        if vol < 100:
            print('[trade] buy %s skipped: <100 shares' % stock_code)
            return None
        t_before = time.time()
        self._passorder(self.BUY_CODE, stock_code, vol, remark)
        order_id = None
        for _i in range(15):
            order_id = self._lookup_recent_order_id(stock_code, vol, 'buy', t_before)
            if order_id is not None:
                break
            time.sleep(0.2)
        if order_id is None:
            print('[trade] buy %s %d lookup failed' % (stock_code, vol))
            return None
        return order_id

    def sell(self, stock_code, volume, remark='', use_market=True):
        vol = int(volume)
        if vol <= 0:
            return None
        t_before = time.time()
        if use_market:
            self._passorder(self.SELL_CODE, stock_code, vol, remark, price_type=5, price=-1)
        else:
            self._passorder(self.SELL_CODE, stock_code, vol, remark, price_type=0, price=-1)
        order_id = None
        for _i in range(15):
            order_id = self._lookup_recent_order_id(stock_code, vol, 'sell', t_before)
            if order_id is not None:
                break
            time.sleep(0.2)
        if order_id is None:
            print('[trade] sell %s %d lookup failed' % (stock_code, vol))
            return None
        return order_id

    def _lookup_recent_order_id(self, stock_code, expected_vol, direction, t_before):
        try:
            orders = get_trade_detail_data(self.acct, self.acct_type, 'order')
            if not orders:
                return None
            t_struct = time.localtime(t_before)
            t_before_hms = t_struct.tm_hour * 10000 + t_struct.tm_min * 100 + t_struct.tm_sec
            t_threshold = t_before_hms - 1
            candidates = []
            for o in reversed(orders):
                code = '%s.%s' % (getattr(o, 'm_strInstrumentID', ''), getattr(o, 'm_strExchangeID', ''))
                if code != stock_code:
                    continue
                vol = getattr(o, 'm_nOrderVolume', 0)
                if vol and vol != expected_vol:
                    continue
                status = getattr(o, 'm_nOrderStatus', None)
                if status in (54, 55, 57):
                    continue
                op_name = getattr(o, 'm_strOptName', '')
                if direction == 'sell' and op_name and '��' not in op_name and 'sell' not in op_name.lower():
                    continue
                if direction == 'buy' and op_name and '��' not in op_name and 'buy' not in op_name.lower():
                    continue
                ot_str = getattr(o, 'm_strInsertTime', '')
                ot_hms = None
                if ot_str:
                    try:
                        ot_hms = int(ot_str[-6:])
                    except Exception:
                        ot_hms = None
                    if ot_hms is not None and ot_hms < t_threshold:
                        continue
                remark = getattr(o, 'm_strRemark', '')
                remark_match = 1 if STRATEGY_NAME in remark else 0
                candidates.append((remark_match, ot_hms if ot_hms is not None else -1, o))
            if not candidates:
                return None
            candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
            return getattr(candidates[0][2], 'm_nOrderID', None)
        except Exception as e:
            print('[trade] lookup %s failed: %s' % (stock_code, e))
            return None

    def get_position(self, stock_code):
        try:
            positions = get_trade_detail_data(self.acct, self.acct_type, 'position')
            for pos in positions:
                code = '%s.%s' % (pos.m_strInstrumentID, pos.m_strExchangeID)
                if code == stock_code:
                    return {
                        'volume': getattr(pos, 'm_nVolume', 0),
                        'can_use': getattr(pos, 'm_nCanUseVolume', 0),
                        'cost': getattr(pos, 'm_dOpenPrice', 0),
                    }
        except Exception as e:
            print('[trade] position query failed: %s' % e)
        return None

    def get_holdings(self):
        holdings = {}
        try:
            positions = get_trade_detail_data(self.acct, self.acct_type, 'position')
            for pos in positions:
                code = '%s.%s' % (pos.m_strInstrumentID, pos.m_strExchangeID)
                holdings[code] = {
                    'volume': getattr(pos, 'm_nVolume', 0),
                    'can_use': getattr(pos, 'm_nCanUseVolume', 0),
                    'cost': getattr(pos, 'm_dOpenPrice', 0),
                }
        except Exception as e:
            print('[trade] holdings query failed: %s' % e)
        return holdings

    def get_available_cash(self):
        try:
            accounts = get_trade_detail_data(self.acct, self.acct_type, 'account')
            if accounts:
                return float(accounts[0].m_dAvailable)
        except Exception as e:
            print('[trade] cash query failed: %s' % e)
        return 0.0

    def get_total_asset(self):
        try:
            accounts = get_trade_detail_data(self.acct, self.acct_type, 'account')
            if accounts:
                acct = accounts[0]
                for attr in ('m_dAssetBalance', 'm_dBalance', 'm_dAssureAsset',
                             'm_dTotalAsset', 'totalAsset', 'm_dTotal'):
                    val = getattr(acct, attr, None)
                    if val is not None and float(val) > 0:
                        return float(val)
                avail = float(getattr(acct, 'm_dAvailable', 0) or 0)
                mv = float(getattr(acct, 'm_dStockValue', 0) or
                           getattr(acct, 'm_dInstrumentValue', 0) or 0)
                if avail > 0 or mv > 0:
                    return avail + mv
        except Exception as e:
            print('[trade] asset query failed: %s' % e)
        return 0.0


# ============================================================
#  Rebalance scheduling (bi-monthly)
# ============================================================
def _should_rebalance(C, now):
    ym = now.year * 12 + (now.month - 1)
    if _g_state.get('last_rebal_ym', 0) == 0:
        return True
    return (ym - _g_state.get('last_rebal_ym', 0)) >= REBALANCE_MONTHS


def _mark_rebalanced(now):
    ym = now.year * 12 + (now.month - 1)
    _g_state['last_rebal_ym'] = ym


# ============================================================
#  Rebalance execution (buy new, sell exited)
# ============================================================
def _do_rebalance(C, trader, selected):
    """selected: list of (code, score). Buy up to capital-adaptive N."""
    selected_codes = [c for c, _s in selected]
    sel_set = set(selected_codes)

    holdings = trader.get_holdings()
    held_codes = set(holdings.keys())

    # Sell positions not in new selection
    to_sell = [c for c in held_codes if c not in sel_set]
    for code in to_sell:
        pos = holdings.get(code)
        if pos and pos['volume'] > 0:
            trader.sell(code, pos['volume'], remark='rebalance_exit')
            print('[rebal] sell %s (exited selection)' % code)

    # Capital-adaptive sizing
    cash = trader.get_available_cash()
    total_asset = trader.get_total_asset()
    if total_asset <= 0:
        total_asset = cash
    per_stock_cap = total_asset * MAX_WEIGHT_PER_STOCK
    n_target = min(TOP_N_HARD_CAP, len(selected_codes))

    # Buy new selections (skip already held); equal-weight with 2% cap
    bought = 0
    for code in selected_codes:
        if code in held_codes:
            continue
        if bought >= n_target:
            break
        # price: last close from panel if available else skip
        price = _last_close(code)
        if price is None or price <= 0:
            continue
        # allocate: min(per_stock_cap, remaining cash / remaining slots)
        remaining_slots = max(1, n_target - bought)
        alloc = min(per_stock_cap, cash / remaining_slots)
        if alloc < price * 100:
            continue
        shares = int(alloc / price / 100) * 100
        if shares < 100:
            continue
        trader.buy(code, shares, remark='rebalance_buy')
        cash -= shares * price
        bought += 1
        print('[rebal] buy %s %d shares @~%.2f' % (code, shares, price))


# ============================================================
#  Stop-loss monitor (per bar). Trigger when D-1 close drop <= STOP_LOSS
#  vs entry price; sell and replace with highest-scored unheld stock.
# ============================================================
def _check_stop_loss(C, trader, panel, fin_ffill):
    holdings = trader.get_holdings()
    if not holdings:
        return
    trade_dates = sorted(panel.index.get_level_values('trade_date').unique())
    last_date = trade_dates[-1]
    prev_date = trade_dates[-2] if len(trade_dates) >= 2 else last_date
    prev_close = panel.loc[prev_date, 'close']

    held_set = set(holdings.keys())
    # current candidates for replacement
    selected_all = select_top(panel, fin_ffill, last_date)
    cand_rank = {c: s for c, s in selected_all}

    for code in list(holdings.keys()):
        pos = holdings[code]
        if pos['volume'] <= 0:
            continue
        entry = pos['cost']
        if entry <= 0:
            continue
        pc = prev_close.get(code)
        if pc is None or pc == 0:
            continue
        ret = pc / entry - 1.0
        if ret <= STOP_LOSS:
            trader.sell(code, pos['volume'], remark='stoploss')
            print('[stoploss] sell %s drop=%.2f%%' % (code, ret * 100))
            # replace with best unheld candidate
            for cand, _s in selected_all:
                if cand not in held_set:
                    price = _last_close(cand)
                    if price is None or price <= 0:
                        continue
                    cash = trader.get_available_cash()
                    alloc = min(trader.get_total_asset() * MAX_WEIGHT_PER_STOCK, cash)
                    shares = int(alloc / price / 100) * 100
                    if shares >= 100:
                        trader.buy(cand, shares, remark='stoploss_replace')
                        print('[stoploss] replace %s -> %s' % (code, cand))
                    break


# ============================================================
#  Price helper (last close from panel cache)
# ============================================================
_g_panel_cache = None


def _last_close(code):
    if _g_panel_cache is None:
        return None
    try:
        df = _g_panel_cache.xs(code, level='ts_code')
        if len(df) > 0:
            return float(df['close'].iloc[-1])
    except Exception:
        pass
    return None


# ============================================================
#  State persistence (absolute path, no __file__)
# ============================================================
def _load_state():
    global _g_state
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            _g_state.update(data)
            print('[state] loaded: %d holdings' % len(_g_state.get('holdings', {})))
    except Exception as e:
        print('[state] load failed: %s' % e)


def _save_state():
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(_g_state, f, ensure_ascii=False)
    except Exception as e:
        print('[state] save failed: %s' % e)


# ============================================================
#  QMT lifecycle
# ============================================================
def init(C):
    global _g_trader
    _g_trader = Trader(C, ACCOUNT_ID)
    _load_state()
    print('[MF_IC] init done, account=%s' % ACCOUNT_ID)


def handlebar(C):
    global _g_panel_cache
    now = _market_now(C)
    # Only act in the last 5 minutes of the trading session (14:55-15:00)
    now_str = now.strftime('%H%M')
    if not ('1455' <= now_str <= '1500'):
        return

    trader = _g_trader
    if trader is None:
        return

    # Refresh data for selection (use QMT xtdata)
    codes = []
    try:
        all_codes = C.get_stock_list_in_sector('����A��')
        codes = [c for c in all_codes if c.endswith('.SH') or c.endswith('.SZ')]
    except Exception as e:
        print('[MF_IC] get_stock_list_in_sector failed: %s' % e)
        return

    panel, fin_ffill = _build_panel_via_xt(C, codes, count=130)
    if panel is None:
        print('[MF_IC] data build failed, skip')
        return
    _g_panel_cache = panel

    # Stop-loss check first (uses latest two bars)
    try:
        _check_stop_loss(C, trader, panel, fin_ffill)
    except Exception as e:
        print('[MF_IC] stoploss check error: %s' % e)

    # Rebalance if due
    if _should_rebalance(C, now):
        try:
            last_date = sorted(panel.index.get_level_values('trade_date').unique())[-1]
            selected = select_top(panel, fin_ffill, last_date)
            if selected:
                print('[MF_IC] rebalance: %d candidates, top=%s' % (len(selected), selected[0][0]))
                _do_rebalance(C, trader, selected)
                _mark_rebalanced(now)
                _save_state()
            else:
                print('[MF_IC] rebalance: no candidates')
        except Exception as e:
            print('[MF_IC] rebalance error: %s' % e)
    else:
        print('[MF_IC] no rebalance due (last_ym=%d)' % _g_state.get('last_rebal_ym', 0))


def exit(C):
    _save_state()
    print('[MF_IC] exit, state saved')
