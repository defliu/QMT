# coding: utf-8
"""通达信筹码函数 1min 严格复刻 (方案A).

依据: agent_hub/2026-06-25_chip_replication_arch/HERMES_ARCHITECT_PLAN.md (方案A)

用 1min OHLCV 构建价格-成交量分布, 严格复刻 COST/WINNER/SCR/PPART.
精度目标: 90%+ (相对通达信真实值).

数据要求: astock 1min parquet, 字段 ts_code/open/high/low/close/vol/amount/adj_factor/trade_date/trade_time
无未来函数: T 日值只用 T 日及之前的 1min 数据.
"""
import numpy as np
import pandas as pd

MIN_LOOKBACK = 20  # 交易日数不足阈值


def _bar_price(df_min, adj_mode='qfq', ref_adj=None):
    """1min bar 代表价 = (open+high+low+close)/4, 按指定复权方式调整.

    adj_mode:
      'raw'  不复权
      'hfq'  后复权 (×adj_factor, 以上市首日为基准) — astock adj_factor 口径
      'qfq'  前复权 (×adj/ref_adj, 以最新日为基准) — 与通达信默认前复权一致

    通达信筹码分布默认前复权, 用 'qfq' 对齐. 前复权下最新价不变,
    历史价按比例调低, 长牛股最新价在分布高端, WINNER 才正确.
    """
    raw = (df_min['open'] + df_min['high'] + df_min['low'] + df_min['close']) / 4.0
    if adj_mode == 'raw':
        return raw
    adj = df_min['adj_factor'] if 'adj_factor' in df_min.columns else 1.0
    if adj_mode == 'hfq':
        return raw * adj
    # qfq: 前复权
    if ref_adj is None:
        ref_adj = adj.iloc[-1] if hasattr(adj, 'iloc') else adj
    return raw * (adj / ref_adj)


def _daily_chip_dist(df_min, lookback=250, adj_mode='qfq'):
    """构建每个交易日的价格-成交量分布.

    对每个交易日 T, 取 [T-lookback+1, T] 的所有 1min bar,
    按 (代表价, 成交量) 聚合, 返回每日的排序后 (price, vol) 数组.

    Args:
        df_min: 1min DataFrame, 含 trade_date, open/high/low/close, vol, adj_factor
        lookback: 回看交易日数
        adj_mode: 'qfq'(前复权,默认,对齐通达信) / 'hfq' / 'raw'
    Returns:
        dict {trade_date: (sorted_prices, sorted_vols)}, 仅含 lookback 足够的日期
    """
    df = df_min.copy()
    # 前复权基准: 用整个 df 的最新 adj_factor (定点复权, 基准=数据末日)
    adj = df['adj_factor'] if 'adj_factor' in df.columns else None
    ref_adj = adj.iloc[-1] if adj is not None else None
    df['price'] = _bar_price(df, adj_mode=adj_mode, ref_adj=ref_adj)
    df['trade_date'] = pd.to_datetime(df['trade_date']).dt.normalize()
    # 按交易日聚合 bar
    grouped = df.groupby('trade_date')
    # 交易日列表(升序)
    days = sorted(grouped.groups.keys())
    # 每日的 (price, vol) 列表
    day_bars = {}
    for d in days:
        g = grouped.get_group(d)
        day_bars[d] = (g['price'].to_numpy(dtype=float),
                       g['vol'].to_numpy(dtype=float))

    result = {}
    for i, d in enumerate(days):
        if i + 1 < MIN_LOOKBACK:
            continue
        # 取最近 lookback 个交易日; 数据不足 lookback 时用全部可用
        start = max(0, i + 1 - lookback)
        window_days = days[start: i + 1]
        prices = []
        vols = []
        for wd in window_days:
            p, v = day_bars[wd]
            prices.append(p)
            vols.append(v)
        all_p = np.concatenate(prices)
        all_v = np.concatenate(vols)
        # 按 price 排序
        order = np.argsort(all_p)
        result[d] = (all_p[order], all_v[order])
    return result


def _cost_from_dist(sorted_p, sorted_v, n_percent):
    """从排序分布算 COST(N): 累积 vol 达到 n_percent% 时的价格(线性插值)."""
    total = sorted_v.sum()
    if total <= 0:
        return np.nan
    cum = np.cumsum(sorted_v)
    target = (n_percent / 100.0) * total
    idx = np.searchsorted(cum, target, side='left')
    if idx >= len(cum):
        return float(sorted_p[-1])
    if idx == 0:
        return float(sorted_p[0])
    # 在 idx-1 和 idx 之间插值
    c0 = cum[idx - 1]
    c1 = cum[idx]
    p0 = sorted_p[idx - 1]
    p1 = sorted_p[idx]
    if c1 == c0:
        return float(p1)
    frac = (target - c0) / (c1 - c0)
    return float(p0 + frac * (p1 - p0))


def _winner_from_dist(sorted_p, sorted_v, close_price):
    """WINNER(C): close 价以下的累积 vol 占比."""
    total = sorted_v.sum()
    if total <= 0:
        return np.nan
    # 累积到 price <= close 的部分
    idx = np.searchsorted(sorted_p, close_price, side='right')
    below = sorted_v[:idx].sum()
    return float(below / total)


def compute_chip_1min(df_min, lookback=250, adj_mode='qfq'):
    """计算每日 COST(5/95)/WINNER/SCR/PPART(90).

    Args:
        df_min: 1min DataFrame
        lookback: 回看交易日数
    Returns:
        DataFrame, index=trade_date, 列:
          cost_5, cost_50, cost_95, cost_ratio_95_5, winner_close, scr, ppart_90
    """
    dists = _daily_chip_dist(df_min, lookback=lookback, adj_mode=adj_mode)
    rows = []
    for d, (sp, sv) in sorted(dists.items()):
        c5 = _cost_from_dist(sp, sv, 5)
        c50 = _cost_from_dist(sp, sv, 50)
        c95 = _cost_from_dist(sp, sv, 95)
        # 当日收盘价: 取该日最后一根 bar 的 close
        # (从 dist 重建不易, 这里用 sp 末尾近似不对; 需外部传 close)
        # 改: winner/scr 不在此算 close, 留给调用方
        rows.append({
            'trade_date': d,
            'cost_5': c5, 'cost_50': c50, 'cost_95': c95,
            'cost_ratio_95_5': (c95 / c5) if c5 and c5 > 0 else np.nan,
        })
    return pd.DataFrame(rows).set_index('trade_date')


def compute_chip_1min_full(df_min, lookback=250, adj_mode='qfq'):
    """完整版: 含 WINNER/SCR/PPART, 需每日收盘价.

    Args:
        df_min: 1min DataFrame
        lookback: 回看交易日数
        adj_mode: 'qfq'(前复权,默认,对齐通达信) / 'hfq' / 'raw'
    Returns:
        DataFrame, index=trade_date, 列:
          cost_5, cost_50, cost_95, cost_ratio_95_5, winner_close, scr, ppart_90, close
    """
    df = df_min.copy()
    df['trade_date'] = pd.to_datetime(df['trade_date']).dt.normalize()
    # 每日收盘 (与分布同口径): 前复权 close = close × (adj/ref_adj)
    adj = df['adj_factor'] if 'adj_factor' in df.columns else pd.Series(1.0, index=df.index)
    ref_adj = adj.iloc[-1]
    if adj_mode == 'qfq':
        df['_close_adj'] = df['close'] * (adj / ref_adj)
    elif adj_mode == 'hfq':
        df['_close_adj'] = df['close'] * adj
    else:
        df['_close_adj'] = df['close']
    daily_close = df.groupby('trade_date')['_close_adj'].last()

    dists = _daily_chip_dist(df_min, lookback=lookback, adj_mode=adj_mode)
    rows = []
    for d, (sp, sv) in sorted(dists.items()):
        c5 = _cost_from_dist(sp, sv, 5)
        c50 = _cost_from_dist(sp, sv, 50)
        c95 = _cost_from_dist(sp, sv, 95)
        close = float(daily_close.get(d, np.nan))
        winner = _winner_from_dist(sp, sv, close) if not np.isnan(close) else np.nan
        # SCR = (COST95-COST5)/((COST95+COST5)/2)*100
        mid = (c95 + c5) / 2.0
        scr = ((c95 - c5) / mid * 100.0) if mid and mid > 0 else np.nan
        # PPART(90): 从 close 向两侧扩, 最小对称区间覆盖>=90% vol
        ppart = _ppart_from_dist(sp, sv, close) if not np.isnan(close) else np.nan
        rows.append({
            'trade_date': pd.Timestamp(d),
            'cost_5': c5, 'cost_50': c50, 'cost_95': c95,
            'cost_ratio_95_5': (c95 / c5) if (c5 and c5 > 0) else np.nan,
            'close': close,
            'winner_close': winner,
            'scr': scr,
            'ppart_90': ppart,
        })
    if not rows:
        return pd.DataFrame(columns=['trade_date','cost_5','cost_50','cost_95','cost_ratio_95_5','close','winner_close','scr','ppart_90']).set_index('trade_date')
    out = pd.DataFrame(rows)
    out['trade_date'] = pd.to_datetime(out['trade_date'])
    return out.set_index('trade_date')


def _ppart_from_dist(sorted_p, sorted_v, close_price, pct=90):
    """PPART(pct): 从 close 向两侧扩展, 找最小对称区间覆盖 >= pct% vol.

    区间宽度 / close = 筹码密集度.
    """
    total = sorted_v.sum()
    if total <= 0 or np.isnan(close_price):
        return np.nan
    target = (pct / 100.0) * total
    # 以 close 为中心, 二分搜索半宽
    lo, hi = 0.0, float(sorted_p[-1] - sorted_p[0])
    for _ in range(50):
        mid = (lo + hi) / 2.0
        mask = (sorted_p >= close_price - mid) & (sorted_p <= close_price + mid)
        if sorted_v[mask].sum() >= target:
            hi = mid
        else:
            lo = mid
    width = hi * 2.0
    return float(width / close_price) if close_price > 0 else np.nan
