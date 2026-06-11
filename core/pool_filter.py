# coding=utf-8
"""筹码密集突破选股 — 纯逻辑层，功能冗余（未接入主流程）"""

import numpy as np
import pandas as pd


def select_breakout_stocks(df):
    """
    筹码密集突破选股核心逻辑。

    Conditions:
    1. 60-day amplitude <= 35% (筹码密集)
    2. 60-day CV <= 12% (price convergence)
    3. 60-day avg volume > 100k 手 (exclude dead stocks)
    4. Break above 60-day dense top (gap-up compatible)
    5. Accumulation: >=2 days in last 5 with abs(pct) < 3%
    6. Bullish multi-head: MA5 > MA10 > MA20, MA60 rising
    7. MA5 angle >= 30 degrees
    8. Exclude rapid-pull from pit bottom
    9. Bullish candle (close > open)

    Args:
        df: pandas DataFrame, must contain close/open/high/low/volume columns

    Returns:
        bool: signal triggered or not
    """
    if df is None or len(df) < 60:
        return False

    df = df.copy()
    df.columns = [c.lower() for c in df.columns]

    c = df['close']
    o = df['open']
    h = df['high']
    l = df['low']
    v = df['volume']  # unit: lots (手)

    window = 60

    # --- 1. Price convergence (筹码密集) ---
    high_60 = h.rolling(window).max()
    low_60 = l.rolling(window).min()
    amplitude_60 = (high_60 - low_60) / low_60
    price_ok = amplitude_60 <= 0.35

    ma60 = c.rolling(window).mean()
    std60 = c.rolling(window).std()
    cv_60 = std60 / ma60
    cv_ok = cv_60 <= 0.12

    # Volume: 100k lots minimum
    vol_60 = v.rolling(window).mean()
    base_active = vol_60 > 100000

    is_dense = price_ok & cv_ok & base_active

    # --- 2. Breakout above dense top (gap-up compatible) ---
    dense_high = high_60.shift(1)

    above_today = c > dense_high
    above_yesterday = c.shift(1) > dense_high.shift(1)
    above_day_before = c.shift(2) > dense_high.shift(2)
    breakout_happened = above_today | above_yesterday | above_day_before

    is_above_today = c > dense_high
    below_recent = (c.shift(1) <= dense_high.shift(1)).rolling(5).sum() >= 2

    condition_1 = is_dense & breakout_happened & is_above_today & below_recent

    # --- 3. Accumulation (蓄势) ---
    pct_change = c.pct_change().abs()
    accumulation_days = (pct_change < 0.03).rolling(5).sum()
    accumulated = accumulation_days >= 2

    # --- 4. Multi-head moving average (MA5 > MA10 > MA20, MA60 rising) ---
    ma5 = c.rolling(5).mean()
    ma10 = c.rolling(10).mean()
    ma20 = c.rolling(20).mean()

    short_multi = (ma5 > ma10) & (ma10 > ma20)
    ma60_up = ma60 >= ma60.shift(1)
    multi_head = short_multi & ma60_up

    # --- 5. MA5 angle >= 30 degrees ---
    ma5_slope = (ma5 / ma5.shift(1) - 1) * 100
    angle = np.arctan(ma5_slope) * 180 / np.pi
    angle_ok = angle >= 30

    # --- 6. Exclude rapid-pull from pit bottom ---
    high_18 = h.rolling(18).max()
    low_18 = l.rolling(18).min()
    pit_range = (high_18 - low_18) / high_18 * 100
    has_pit = pit_range >= 20

    high_3 = h.rolling(3).max()
    low_3 = l.rolling(3).min()
    rapid_pull = (high_3 / low_3) >= 1.15
    exclude_pit = has_pit & rapid_pull

    # --- 7. Final signal ---
    is_bullish = c > o  # bullish candle

    final_signal = (
        condition_1 & accumulated & multi_head & angle_ok & is_bullish & (~exclude_pit)
    ).fillna(False)

    return bool(final_signal.iloc[-1])
