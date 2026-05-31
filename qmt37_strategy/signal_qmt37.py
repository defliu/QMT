# coding=utf-8
"""
千问3.7版信号函数 — 原版复刻，不做任何逻辑修改。
来源: 双带趋势_新旧双买点QMT代码千文3.7版.txt
"""
import numpy as np
import pandas as pd

# talib 可选，如果不可用则用 numpy 实现等价 EMA/MA/MACD
try:
    import talib
    _HAVE_TALIB = True
except ImportError:
    _HAVE_TALIB = False


def _ema_np(data, period):
    """numpy 实现的 EMA（对齐 talib 结果）"""
    alpha = 2 / (period + 1)
    result = np.zeros_like(data)
    result[0] = data[0]
    for i in range(1, len(data)):
        result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
    return result


def _ma_np(data, period):
    """numpy 实现的 MA"""
    result = pd.Series(data).rolling(period).mean().values
    return result


def _macd_np(data, fast=12, slow=26, signal=9):
    """numpy 实现的 MACD（对齐 talib * 2）"""
    ema_fast = _ema_np(data, fast)
    ema_slow = _ema_np(data, slow)
    dif = ema_fast - ema_slow
    dea = _ema_np(dif, signal)
    macd = (dif - dea) * 2  # 对齐通达信
    return dif, dea, macd


def check_buy_sell(df: pd.DataFrame, n_period: int = 30, intensity: float = 0.22) -> tuple:
    """
    千问3.7版原版信号函数。

    Args:
        df: DataFrame，必须含 close/open/high/low/volume 列
        n_period: 突破N日高点参数（默认30）
        intensity: 筹码密集度阈值（默认0.22，即22%）

    Returns:
        (buy_signal_1, buy_signal_2, sell_signal): 三个布尔值
    """
    # ====== 以下为千问3.7版原版信号逻辑，不做任何修改 ======
    C = df['close'].values.astype(float)
    H = df['high'].values.astype(float)
    L = df['low'].values.astype(float)
    O = df['open'].values.astype(float)

    # 【紫色带】5层EMA嵌套
    if _HAVE_TALIB:
        s1 = talib.EMA(C, timeperiod=10)
        s2 = talib.EMA(s1, timeperiod=3)
        s3 = talib.EMA(s2, timeperiod=3)
        s4 = talib.EMA(s3, timeperiod=3)
        purple_band = talib.EMA(s4, timeperiod=3)

        l1 = talib.EMA(C, timeperiod=45)
        l2 = talib.EMA(l1, timeperiod=3)
        l3 = talib.EMA(l2, timeperiod=3)
        l4 = talib.EMA(l3, timeperiod=3)
        red_band = talib.EMA(l4, timeperiod=3)

        ma5 = talib.MA(C, timeperiod=5)
        ma10 = talib.MA(C, timeperiod=10)
        ma20 = talib.MA(C, timeperiod=20)
        ma60 = talib.MA(C, timeperiod=60)

        dif, dea, macd = talib.MACD(C, fastperiod=12, slowperiod=26, signalperiod=9)
        macd = macd * 2
    else:
        s1 = _ema_np(C, 10)
        s2 = _ema_np(s1, 3)
        s3 = _ema_np(s2, 3)
        s4 = _ema_np(s3, 3)
        purple_band = _ema_np(s4, 3)

        l1 = _ema_np(C, 45)
        l2 = _ema_np(l1, 3)
        l3 = _ema_np(l2, 3)
        l4 = _ema_np(l3, 3)
        red_band = _ema_np(l4, 3)

        ma5 = _ma_np(C, 5)
        ma10 = _ma_np(C, 10)
        ma20 = _ma_np(C, 20)
        ma60 = _ma_np(C, 60)

        _, _, macd = _macd_np(C)

    # MACD共振
    macd_prev = np.roll(macd, 1)
    red_bar_inc = (macd > 0) & (macd_prev > 0) & (macd >= macd_prev)
    green_bar_dec = (macd < 0) & (macd_prev < 0) & (macd > macd_prev)
    first_green_to_red = (macd > 0) & (macd_prev < 0)
    macd_satisfied = red_bar_inc | green_bar_dec | first_green_to_red

    # 多头排列
    long_arrangement = (ma5 > ma10) & (ma10 > ma20) & (ma20 > ma60)

    # 过滤急拉坑底
    pit_bottom = pd.Series(L).rolling(22).min().values
    pit_range = L <= pit_bottom * 1.16
    c_prev = np.roll(C, 1)
    big_rise = (C / c_prev > 1.045) & pit_range
    pit_rise_pull = (pd.Series(big_rise).rolling(2).sum() >= 2).values
    filter_pit = ~pit_rise_pull

    # 【买点1：老版回踩反包】
    pullback_ok = L >= ma5 * 0.98
    is_positive = C > O
    h_prev = np.roll(H, 1)
    fanbao = C > h_prev
    buy_signal_1 = long_arrangement & pullback_ok & is_positive & fanbao & macd_satisfied & filter_pit

    # 【买点2：趋势突破】
    high_90 = pd.Series(H).rolling(90).max().values
    low_90 = pd.Series(L).rolling(90).min().values
    chip_dense = (high_90 - low_90) / low_90 <= intensity

    stage_high = np.roll(pd.Series(H).rolling(n_period).max().values, 1)
    breakout = (C / stage_high > 1.01) & (c_prev / stage_high <= 1.01)

    channel_up = np.roll(pd.Series(H).rolling(60).max().values, 1)
    trend_confirm = C > channel_up * 0.98

    small_k = np.abs(C / c_prev - 1) < 0.03
    accumulate = (pd.Series(small_k).rolling(5).sum() >= 2).values

    ma5_prev = np.roll(ma5, 1)
    ma5_angle = np.degrees(np.arctan((ma5 / ma5_prev - 1) * 100))
    angle_ok = ma5_angle >= 45

    buy_signal_2 = chip_dense & breakout & long_arrangement & trend_confirm & accumulate & angle_ok & is_positive & filter_pit & macd_satisfied

    # 【卖点：跌破五日线风控】
    break_ma5 = C < ma5
    break_ma5_prev = np.roll(break_ma5, 1)
    sell_signal = break_ma5_prev & (C < c_prev)

    # 前几个数据强制设为 False
    buy_signal_1[:2] = False
    buy_signal_2[:2] = False
    sell_signal[:2] = False

    return bool(buy_signal_1[-1]), bool(buy_signal_2[-1]), bool(sell_signal[-1])
