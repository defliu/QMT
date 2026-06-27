# coding: utf-8
"""通达信筹码函数日线量价加权代理 (方案B).

依据: agent_hub/2026-06-25_chip_replication_arch/HERMES_ARCHITECT_PLAN.md

实现 COST_proxy / WINNER_proxy / SCR_proxy:
- 用日线 (high+low+close)/3 作为每日代表价, volume 作为权重
- 取最近 lookback 个交易日构建价格-成交量分布
- 严格无未来函数: T 日值只用 T 日及之前数据
- 向量化 (numpy sliding_window_view), 适合全A股批量计算

精度: 方案B 约 60-75% (相对通达信真实 COST/WINNER/SCR), 未做对照验证.
"""
import numpy as np
import pandas as pd

MIN_LOOKBACK = 20  # 数据不足阈值, < MIN_LOOKBACK 返回 NaN


def _get_vol(df):
    """兼容 'volume' / 'vol' 两种列名."""
    if 'volume' in df.columns:
        return df['volume'].to_numpy(dtype=float)
    if 'vol' in df.columns:
        return df['vol'].to_numpy(dtype=float)
    raise KeyError("df 需含 'volume' 或 'vol' 列")


def _sliding(arr, lookback):
    """返回 sliding_window_view [N-L+1, L], 若 N<L 返回 None."""
    if len(arr) < lookback:
        return None
    return np.lib.stride_tricks.sliding_window_view(arr, window_shape=lookback)


def COST_proxy(df, n_percent, lookback=250):
    """COST(N) 日线代理: 累积成交量达到 n_percent% 时的价格.

    Args:
        df: DataFrame 含 high/low/close/volume(或vol), 升序, index 为日期
        n_percent: 0-100 目标百分位
        lookback: 回看交易日数, 默认 250
    Returns:
        pd.Series (同 df.index), 数据不足返回 NaN
    """
    tp = ((df['high'] + df['low'] + df['close']) / 3.0).to_numpy(dtype=float)
    vol = _get_vol(df)
    n = len(tp)
    out = np.full(n, np.nan)
    need = max(lookback, MIN_LOOKBACK)
    if n < need:
        return pd.Series(out, index=df.index)

    W_tp = _sliding(tp, lookback)      # [R, L], R = n-L+1
    W_vol = _sliding(vol, lookback)
    order = np.argsort(W_tp, axis=1)
    sorted_tp = np.take_along_axis(W_tp, order, axis=1)
    sorted_vol = np.take_along_axis(W_vol, order, axis=1)
    cumvol = np.cumsum(sorted_vol, axis=1)
    total = cumvol[:, -1]
    valid = total > 0
    target = (n_percent / 100.0) * total

    # 首个 cumvol >= target 的列
    ge = cumvol >= target[:, None]
    any_ge = ge.any(axis=1)
    idx = np.argmax(ge, axis=1)  # first True (若全 False 返回 0, 后面 any_ge 过滤)

    rows = np.where(valid & any_ge)[0]
    if len(rows) == 0:
        return pd.Series(out, index=df.index)
    r = rows
    i = idx[r]
    c1 = cumvol[r, i]
    p1 = sorted_tp[r, i]
    i_prev = np.maximum(i - 1, 0)
    c0 = cumvol[r, i_prev]
    p0 = sorted_tp[r, i_prev]
    denom = c1 - c0
    safe = denom > 0
    frac = np.zeros_like(denom, dtype=float)
    frac[safe] = (target[r][safe] - c0[safe]) / denom[safe]
    price_win = np.where(i == 0, p1, p0 + frac * (p1 - p0))
    # 窗口 r 对应日期索引 r + lookback - 1
    date_idx = r + lookback - 1
    out[date_idx] = price_win
    return pd.Series(out, index=df.index)


def WINNER_proxy(df, lookback=250):
    """WINNER(C) 日线代理: T 日收盘价以下的累积成交量占比 (0-1).

    Args:
        df: 含 high/low/close/volume(或vol), 升序
        lookback: 回看日数
    Returns:
        pd.Series (0-1), 不足返回 NaN
    """
    tp = ((df['high'] + df['low'] + df['close']) / 3.0).to_numpy(dtype=float)
    vol = _get_vol(df)
    close = df['close'].to_numpy(dtype=float)
    n = len(tp)
    out = np.full(n, np.nan)
    need = max(lookback, MIN_LOOKBACK)
    if n < need:
        return pd.Series(out, index=df.index)

    W_tp = _sliding(tp, lookback)
    W_vol = _sliding(vol, lookback)
    total = W_vol.sum(axis=1)
    # close 对齐到窗口末尾: close[lookback-1:]
    close_win = close[lookback - 1:]  # [R]
    mask = W_tp <= close_win[:, None]
    winbelow = (W_vol * mask).sum(axis=1)
    winner = np.where(total > 0, winbelow / np.where(total > 0, total, 1), np.nan)
    out[lookback - 1:] = winner
    return pd.Series(out, index=df.index)


def SCR_proxy(df, lookback=250):
    """SCR 日线代理: 筹码集中度, 越小越集中.

    公式: (COST(95)-COST(5)) / ((COST(95)+COST(5))/2) * 100
    Returns:
        pd.Series (百分比), 不足返回 NaN
    """
    c95 = COST_proxy(df, 95, lookback)
    c5 = COST_proxy(df, 5, lookback)
    mid = (c95 + c5) / 2.0
    scr = (c95 - c5) / mid.replace(0, np.nan) * 100.0
    return scr


def COST_ratio(df, lookback=250):
    """529 版用: COST(95)/COST(5) 集中度比, 越接近 1 越密集."""
    c95 = COST_proxy(df, 95, lookback)
    c5 = COST_proxy(df, 5, lookback)
    return c95 / c5.replace(0, np.nan)
