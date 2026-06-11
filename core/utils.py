# coding=utf-8
"""通用工具：均线角度、乖离率、阳线比例 + 全部纯计算指标函数"""

import math
import numpy as np
import pandas as pd


# ============================================================
#  原有函数（保留，测试依赖）
# ============================================================

def calc_ma_angle(ma_values, window=5):
    """计算均线角度（度），返回 0-90 的 float

    使用 arctan 计算均线最近 window 个点的斜率角度。
    angle = arctan(abs(diff) / (window-1) / v0 * 100)
    """
    if len(ma_values) < window or window < 2:
        return 0.0
    recent = ma_values[-window:]
    diff = recent[-1] - recent[0]
    if recent[0] == 0:
        return 0.0
    angle_rad = math.atan(abs(diff) / (window - 1) / recent[0] * 100)
    angle_deg = math.degrees(angle_rad)
    return min(angle_deg, 90.0)


def calc_bias(price, ma):
    """计算乖离率（百分比）

    bias = (price - ma) / ma * 100
    """
    if ma == 0:
        return 0.0
    return (float(price) - float(ma)) / float(ma) * 100


def calc_up_ratio(closes, period=20):
    """计算阳线比例（0-1）

    阳线定义为收盘价高于前一根收盘价。
    up_ratio = 上涨天数 / 周期
    """
    if len(closes) < 2 or period < 1:
        return 0.0
    n = min(period, len(closes) - 1)
    if n <= 0:
        return 0.0
    up_count = 0
    for i in range(-n, 0):
        if closes[i] >= closes[i - 1]:
            up_count += 1
    return up_count / n


# ============================================================
#  技术指标
# ============================================================

def calc_kdj(close, high, low, n=9, m1=3, m2=3):
    """
    计算 KDJ 指标。
    返回 (k_series, d_series, j_series)，长度与输入一致。
    """
    L = low.rolling(n).min()
    H = high.rolling(n).max()
    rsv = (close - L) / (H - L) * 100
    rsv = rsv.fillna(50)

    k = rsv.ewm(alpha=1/m1, adjust=False).mean()
    d = k.ewm(alpha=1/m2, adjust=False).mean()
    j = 3 * k - 2 * d

    k = k.fillna(50)
    d = d.fillna(50)
    j = j.fillna(50)
    return k, d, j


def calc_atr(close, high, low, n=14):
    """
    计算真实波幅 ATR。
    标准算法: max(|H-L|, |H-prevC|, |L-prevC|) 的 n 日 EMA。
    """
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(span=n, adjust=False).mean()
    return atr


def calc_volume_ratio(volume, vol_ma_period=5):
    """计算当日成交量 / 均量，返回比值序列。"""
    vol_ma = volume.rolling(vol_ma_period).mean()
    return volume / vol_ma.replace(0, np.nan)


def detect_long_upper_shadow(high, close, open_, shadow_ratio=0.5):
    """
    检测长上影线。
    上影线长度 = (最高 - 最大值(收盘, 开盘))
    上影线比例 = 上影线 / (最高 - 最低)
    返回布尔序列。
    """
    candle_high = high
    candle_body_top = pd.concat([close, open_], axis=1).max(axis=1)
    upper_shadow = candle_high - candle_body_top
    total_range = high - pd.concat([close, open_], axis=1).min(axis=1)
    total_range = total_range.replace(0, np.nan)
    ratio = upper_shadow / total_range
    return ratio.fillna(0) >= shadow_ratio


def detect_volume_price_divergence(close, volume, lookback=5, volume_diverge_threshold=0.70):
    """
    检测量价背离：价格创 lookback 日新高，但成交量较前日萎缩。
    返回 (是否背离, 量缩比例)。
    """
    if len(close) < 2:
        return False, 0.0
    price_high = close.iloc[-1] >= close.iloc[-lookback:].max()
    if not price_high:
        return False, 0.0
    vol_ratio = volume.iloc[-1] / volume.iloc[-2] if volume.iloc[-2] > 0 else 1
    if vol_ratio < volume_diverge_threshold:
        return True, float(vol_ratio)
    return False, float(vol_ratio)


def detect_last_3_negative_vol(close, open_, lookback_days=3):
    """
    检测最近 N 日是否连续缩量收阴（用于 B3 高位天量收阴后确认）。
    返回 bool。
    """
    if len(close) < lookback_days:
        return False
    recent = close.iloc[-lookback_days:]
    recent_o = open_.iloc[-lookback_days:]
    negative_days = (recent < recent_o).sum()
    return negative_days >= 2


# ============================================================
#  均线角度（独立函数，与类内方法同名）
# ============================================================

def calc_angle_simple(ma_series):
    """计算均线角度（度），返回最后一根的值。"""
    if len(ma_series) < 3:
        return None
    try:
        prev = float(ma_series.iloc[-2])
        curr = float(ma_series.iloc[-1])
        if prev <= 0:
            return None
        pct_change = (curr - prev) / prev
        rad = np.arctan(pct_change * 100)
        deg = float(rad * 180 / np.pi)
        return deg
    except Exception:
        return None


def trading_days_between(date1_str, date2_str, df):
    """计算两个日期之间的交易日数（基于 DataFrame 索引）。"""
    try:
        dates = pd.to_datetime(df.index)
        d1 = pd.Timestamp(date1_str)
        d2 = pd.Timestamp(date2_str)
        return len(dates[(dates > d1) & (dates <= d2)])
    except Exception:
        return 999


# ============================================================
#  基础指标
# ============================================================

def ema(series, n):
    return series.ewm(span=n, adjust=False).mean()


def ma(series, n):
    return series.rolling(n).mean()


def calc_macd(close):
    diff = ema(close, 12) - ema(close, 26)
    dea = ema(diff, 9)
    macd = 2 * (diff - dea)
    return diff, dea, macd


def calc_cmf(high, low, close, volume, period=20):
    denom = (high - low).replace(0, np.nan)
    mfm = (2 * close - high - low) / denom
    mfm = mfm.fillna(0)
    mfv = mfm * volume
    with np.errstate(divide='ignore', invalid='ignore'):
        cmf = mfv.rolling(period).sum() / volume.rolling(period).sum()
    return cmf.fillna(0)


def calc_angle(ma_series):
    """计算均线角度序列（返回 Series）。"""
    prev = ma_series.shift(1).replace(0, np.nan)
    ratio = ma_series / prev - 1
    angle = np.arctan(ratio.fillna(0) * 100) * 180 / np.pi
    return angle


def safe_last(series):
    if series is None or len(series) == 0:
        return 0.0
    val = series.iloc[-1]
    return float(val) if not pd.isna(val) else 0.0


def calc_rsi(close, n=14):
    """计算RSI指标"""
    if close is None or len(close) < n + 1:
        n = len(close) if close is not None else 0
        return pd.Series([50.0] * n, index=close.index) if close is not None else None
    diff = close.diff()
    gain = diff.clip(lower=0)
    loss = -diff.clip(upper=0)
    avg_gain = gain.rolling(n).mean()
    avg_loss = loss.rolling(n).mean().replace(0, np.nan)
    rs = avg_gain / avg_loss
    rsi = 100 - 100 / (1 + rs)
    return rsi.fillna(50)


def calc_rating(total_score):
    """根据总分返回评级"""
    if total_score >= 90:
        return 'A+'
    elif total_score >= 80:
        return 'A'
    elif total_score >= 70:
        return 'B+'
    elif total_score >= 40:
        return 'B'
    elif total_score >= 50:
        return 'C'
    else:
        return 'D'
