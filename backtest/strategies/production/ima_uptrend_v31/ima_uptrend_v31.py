# coding: utf-8
"""
IMA Main Uptrend Wave V3.1 -- Signal Core

Implements the 13-factor scoring model + 5 hard gates from IMA knowledge base.
H1 (chip concentration) is pluggable: disabled / turnover_proxy.

Constraints (SPEC v0.1):
  - 3.6-safe: no dict[str, ...], no str | None, no walrus, no match/case, no dataclass
  - No IO / network / xtquant / passorder
  - H1 default disabled
  - 13 factors equal weight 0/1
"""

import math
import numpy as np
import pandas as pd


def compute_ma(close, period):
    """Simple moving average. Returns Series of same length, NaN for insufficient data."""
    if close is None or len(close) < period:
        return pd.Series([np.nan] * len(close) if close is not None else [])
    return close.rolling(window=period, min_periods=period).mean()


def compute_ema(series, period):
    """Exponential moving average."""
    if series is None or len(series) < period:
        return pd.Series([np.nan] * len(series) if series is not None else [])
    return series.ewm(span=period, adjust=False).mean()


def compute_rsi(close, period=14):
    """RSI indicator."""
    if close is None or len(close) < period + 1:
        return pd.Series([np.nan] * len(close) if close is not None else [])
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi


def compute_macd(close, fast=12, slow=26, signal=9):
    """MACD: returns (dif, dea, macd_hist)."""
    ema_fast = compute_ema(close, fast)
    ema_slow = compute_ema(close, slow)
    dif = ema_fast - ema_slow
    dea = compute_ema(dif, signal)
    macd_hist = (dif - dea) * 2
    return dif, dea, macd_hist


def _safe_last(series):
    """Get last non-NaN value, or None."""
    if series is None or len(series) == 0:
        return None
    valid = series.dropna()
    if len(valid) == 0:
        return None
    return float(valid.iloc[-1])


# ---------------------------------------------------------------------------
# Hard gates H2-H5
# ---------------------------------------------------------------------------

def check_h2_ma_bull(ma5, ma10, ma20, ma60):
    """H2: MA5 > MA10 > MA20 > MA60 (multi-head alignment)."""
    v5 = _safe_last(ma5)
    v10 = _safe_last(ma10)
    v20 = _safe_last(ma20)
    v60 = _safe_last(ma60)
    if None in (v5, v10, v20, v60):
        return False
    return v5 > v10 > v20 > v60


def check_h1_price_range_proxy(close, lookback=60, max_range_pct=15.0):
    """H1 price_range_proxy: 60-day price range <= max_range_pct%.

    This is a proxy for chip concentration when float_shares is unavailable.
    Narrow price range suggests chips are concentrated at similar cost levels.

    Note: This is NOT turnover_proxy. It's a price-based alternative.
    """
    if close is None or len(close) < lookback:
        return None
    last60 = close.iloc[-lookback:]
    h60 = float(last60.max())
    l60 = float(last60.min())
    if h60 == 0:
        return None
    range_pct = (h60 - l60) / h60 * 100.0
    return range_pct <= max_range_pct


def check_h3_gain_3d(close, gain_min=5.0, gain_max=25.0):
    """H3: 3-day gain between gain_min% and gain_max%."""
    if close is None or len(close) < 4:
        return False
    c_now = _safe_last(close)
    c_3ago = _safe_last(close.iloc[:-3]) if len(close) > 3 else None
    if c_now is None or c_3ago is None or c_3ago == 0:
        return False
    gain_pct = (c_now / c_3ago - 1.0) * 100.0
    return gain_min <= gain_pct <= gain_max


def check_h4_not_deep_pit_rush(high, low, close, amplitude_18d=16.0, rush_3d_ratio=1.13):
    """H4: NOT (18-day amplitude >= amplitude_18d AND 3-day rush >= rush_3d_ratio)."""
    if high is None or low is None or close is None:
        return True
    if len(high) < 18 or len(low) < 18 or len(close) < 3:
        return True

    h18 = float(high.iloc[-18:].max())
    l18 = float(low.iloc[-18:].min())
    if h18 == 0:
        return True
    amplitude = (h18 - l18) / h18 * 100.0
    has_pit = amplitude >= amplitude_18d

    c_high_3 = float(close.iloc[-3:].max())
    c_low_3 = float(close.iloc[-3:].min())
    if c_low_3 == 0:
        return True
    rush = c_high_3 / c_low_3
    has_rush = rush >= rush_3d_ratio

    return not (has_pit and has_rush)


def check_h5_volume_ceiling(vol, ma_vol_5, ceiling_multiple=5.0):
    """H5: vol <= ma_vol_5 * ceiling_multiple."""
    v = _safe_last(vol)
    m = _safe_last(ma_vol_5)
    if v is None or m is None:
        return False
    return v <= m * ceiling_multiple


# ---------------------------------------------------------------------------
# Scoring factors S1-S13
# ---------------------------------------------------------------------------

def score_s1_ma_bull(ma5, ma10, ma20, ma60):
    """S1: MA5 > MA10 > MA20 > MA60."""
    return 1 if check_h2_ma_bull(ma5, ma10, ma20, ma60) else 0


def score_s2_ma_rising(ma5, ma10, ma20):
    """S2: MA5/MA10/MA20 all rising vs yesterday."""
    if ma5 is None or len(ma5) < 2:
        return 0
    if ma10 is None or len(ma10) < 2:
        return 0
    if ma20 is None or len(ma20) < 2:
        return 0
    c5 = _safe_last(ma5)
    p5 = _safe_last(ma5.iloc[:-1])
    c10 = _safe_last(ma10)
    p10 = _safe_last(ma10.iloc[:-1])
    c20 = _safe_last(ma20)
    p20 = _safe_last(ma20.iloc[:-1])
    if None in (c5, p5, c10, p10, c20, p20):
        return 0
    return 1 if (c5 > p5 and c10 > p10 and c20 > p20) else 0


def score_s3_price_strong(close, low, ma5, ma10):
    """S3: close > MA5 AND low > MA10 * 0.99."""
    c = _safe_last(close)
    l = _safe_last(low)
    m5 = _safe_last(ma5)
    m10 = _safe_last(ma10)
    if None in (c, l, m5, m10):
        return 0
    return 1 if (c > m5 and l > m10 * 0.99) else 0


def score_s4_volume_expand(vol, ma_vol_5, multiple=1.5):
    """S4: vol > ma_vol_5 * multiple."""
    v = _safe_last(vol)
    m = _safe_last(ma_vol_5)
    if v is None or m is None:
        return 0
    return 1 if v > m * multiple else 0


def score_s5_breakout_20h(close, high, ratio=0.998):
    """S5: close >= HHV(high, 20) * ratio."""
    c = _safe_last(close)
    if high is None or len(high) < 20 or c is None:
        return 0
    hh20 = float(high.iloc[-20:].max())
    return 1 if c >= hh20 * ratio else 0


def score_s6_macd_strong(dif, dea):
    """S6: DIF > 0 AND DEA > 0 AND DIF rising."""
    if dif is None or len(dif) < 2:
        return 0
    if dea is None or len(dea) < 1:
        return 0
    d_now = _safe_last(dif)
    d_prev = _safe_last(dif.iloc[:-1]) if len(dif) > 1 else None
    dea_now = _safe_last(dea)
    if None in (d_now, d_prev, dea_now):
        return 0
    return 1 if (d_now > 0 and dea_now > 0 and d_now > d_prev) else 0


def score_s7_rsi_healthy(rsi, rsi_min=45, rsi_max=80):
    """S7: RSI(14) between rsi_min and rsi_max."""
    r = _safe_last(rsi)
    if r is None:
        return 0
    return 1 if rsi_min <= r <= rsi_max else 0


def score_s8_ma_convergence(ma5, ma10, ma20, max_pct=5.0):
    """S8: (max - min) / avg * 100 < max_pct."""
    v5 = _safe_last(ma5)
    v10 = _safe_last(ma10)
    v20 = _safe_last(ma20)
    if None in (v5, v10, v20):
        return 0
    vals = [v5, v10, v20]
    mx = max(vals)
    mn = min(vals)
    avg = sum(vals) / 3.0
    if avg == 0:
        return 0
    return 1 if (mx - mn) / avg * 100.0 < max_pct else 0


def score_s9_volatility_contraction(close, max_pct=5.0):
    """S9: STD(close, 10) / MA(close, 10) * 100 < max_pct."""
    if close is None or len(close) < 10:
        return 0
    last10 = close.iloc[-10:]
    std_val = float(last10.std())
    avg_val = float(last10.mean())
    if avg_val == 0:
        return 0
    return 1 if std_val / avg_val * 100.0 < max_pct else 0


def score_s10_long_trend(ma20, ma60):
    """S10: MA20 > MA60 AND MA20 rising (vs 5 days ago)."""
    if ma20 is None or len(ma20) < 6:
        return 0
    if ma60 is None:
        return 0
    v20 = _safe_last(ma20)
    v60 = _safe_last(ma60)
    p20 = _safe_last(ma20.iloc[:-5]) if len(ma20) > 5 else None
    if None in (v20, v60, p20):
        return 0
    return 1 if (v20 > v60 and v20 > p20) else 0


def score_s11_divergence_accel(ma5, ma10, lookback=3):
    """S11: (MA5 - MA10) > REF(MA5 - MA10, lookback)."""
    if ma5 is None or len(ma5) < lookback + 1:
        return 0
    if ma10 is None or len(ma10) < lookback + 1:
        return 0
    diff_now = _safe_last(ma5) - _safe_last(ma10) if _safe_last(ma5) is not None and _safe_last(ma10) is not None else None
    diff_prev = _safe_last(ma5.iloc[:-lookback]) - _safe_last(ma10.iloc[:-lookback]) if len(ma5) > lookback and len(ma10) > lookback else None
    if diff_now is None or diff_prev is None:
        return 0
    return 1 if diff_now > diff_prev else 0


def score_s12_continuous_strength(close, ma5, window=5, min_count=3):
    """S12: COUNT(close > MA5, window) >= min_count."""
    if close is None or ma5 is None:
        return 0
    n = min(window, len(close), len(ma5))
    if n < window:
        return 0
    c_tail = close.iloc[-window:]
    m_tail = ma5.iloc[-window:]
    count = int((c_tail.values > m_tail.values).sum())
    return 1 if count >= min_count else 0


def score_s13_volume_trend(ma_vol_5, ma_vol_10):
    """S13: MA(V,5) > MA(V,10)."""
    v5 = _safe_last(ma_vol_5)
    v10 = _safe_last(ma_vol_10)
    if v5 is None or v10 is None:
        return 0
    return 1 if v5 > v10 else 0


# ---------------------------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------------------------

def evaluate_ima_day(date, market_window, universe, config):
    """Evaluate IMA V3.1 signals for a single day.

    Args:
        date: str, YYYY-MM-DD
        market_window: dict, code -> DataFrame[date, open, high, low, close, vol, amount]
        universe: list of code strings
        config: dict with keys: hard_filters, factors, strategy

    Returns:
        dict with keys: signals, blocked, diagnostics, logs

    Anti-lookahead:
        Each code's DataFrame is truncated to date <= current_date before
        any factor computation. This prevents T-day signals from seeing
        data beyond T.
    """
    cfg = config or {}
    hard_cfg = cfg.get("hard_filters", {})
    factor_cfg = cfg.get("factors", {})
    strategy_cfg = cfg.get("strategy", {})
    sc_threshold = strategy_cfg.get("sc_threshold", 7)
    h1_mode = strategy_cfg.get("h1_mode", "disabled")

    signals = []
    blocked = []
    factor_pass_counts = {}
    blocked_counts = {}
    logs = []

    for code in universe:
        df = market_window.get(code)
        if df is None:
            blocked.append({
                "date": date,
                "code": code,
                "blocked_by": "no_data",
                "score": 0,
                "reason": "no data for code"
            })
            blocked_counts["no_data"] = blocked_counts.get("no_data", 0) + 1
            continue

        # Defensive truncation: only use data up to and including current_date
        df = df[df["date"] <= date].copy()

        if len(df) < 60:
            blocked.append({
                "date": date,
                "code": code,
                "blocked_by": "insufficient_history",
                "score": 0,
                "reason": "insufficient history (< 60 bars after truncation)"
            })
            blocked_counts["insufficient_history"] = blocked_counts.get("insufficient_history", 0) + 1
            continue

        close = df["close"].astype(float).reset_index(drop=True)
        high = df["high"].astype(float).reset_index(drop=True)
        low = df["low"].astype(float).reset_index(drop=True)
        vol = df["vol"].astype(float).reset_index(drop=True)

        ma5 = compute_ma(close, 5)
        ma10 = compute_ma(close, 10)
        ma20 = compute_ma(close, 20)
        ma60 = compute_ma(close, 60)
        ma_vol_5 = compute_ma(vol, 5)
        ma_vol_10 = compute_ma(vol, 10)
        rsi = compute_rsi(close, 14)
        dif, dea, _ = compute_macd(close)

        # Hard gates H2-H5
        h2 = check_h2_ma_bull(ma5, ma10, ma20, ma60)
        h3 = check_h3_gain_3d(
            close,
            gain_min=hard_cfg.get("gain_3d_min", 5.0),
            gain_max=hard_cfg.get("gain_3d_max", 25.0),
        )
        h4 = check_h4_not_deep_pit_rush(
            high, low, close,
            amplitude_18d=hard_cfg.get("deep_pit_amplitude_18d", 16.0),
            rush_3d_ratio=hard_cfg.get("rush_3d_ratio", 1.13),
        )
        h5 = check_h5_volume_ceiling(
            vol, ma_vol_5,
            ceiling_multiple=hard_cfg.get("volume_ceiling_multiple", 5.0),
        )

        # H1 disabled by default
        h1 = None
        if h1_mode == "disabled":
            h1 = None
        elif h1_mode == "price_range_proxy":
            h1 = check_h1_price_range_proxy(
                close,
                lookback=hard_cfg.get("h1_lookback", 60),
                max_range_pct=hard_cfg.get("h1_max_range_pct", 15.0),
            )
        else:
            h1 = True  # placeholder for future implementation

        # HARD = H2 AND H3 AND H4 AND H5 (H1 excluded when disabled)
        # When h1_mode is price_range_proxy, H1 is included in HARD
        if h1_mode == "disabled":
            hard_pass = h2 and h3 and h4 and h5
        elif h1_mode == "price_range_proxy":
            hard_pass = h1 is True and h2 and h3 and h4 and h5
        else:
            hard_pass = h2 and h3 and h4 and h5

        # Scoring S1-S13
        s1 = score_s1_ma_bull(ma5, ma10, ma20, ma60)
        s2 = score_s2_ma_rising(ma5, ma10, ma20)
        s3 = score_s3_price_strong(close, low, ma5, ma10)
        s4 = score_s4_volume_expand(vol, ma_vol_5, factor_cfg.get("volume_expand_multiple", 1.5))
        s5 = score_s5_breakout_20h(close, high, factor_cfg.get("breakout_20h_ratio", 0.998))
        s6 = score_s6_macd_strong(dif, dea)
        s7 = score_s7_rsi_healthy(rsi, factor_cfg.get("rsi_min", 45), factor_cfg.get("rsi_max", 80))
        s8 = score_s8_ma_convergence(ma5, ma10, ma20, factor_cfg.get("ma_convergence_max", 5.0))
        s9 = score_s9_volatility_contraction(close, factor_cfg.get("volatility_contraction_max", 5.0))
        s10 = score_s10_long_trend(ma20, ma60)
        s11 = score_s11_divergence_accel(ma5, ma10)
        s12 = score_s12_continuous_strength(close, ma5)
        s13 = score_s13_volume_trend(ma_vol_5, ma_vol_10)

        sc = s1 + s2 + s3 + s4 + s5 + s6 + s7 + s8 + s9 + s10 + s11 + s12 + s13

        # Factor pass counts
        for idx, val in enumerate([s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, s11, s12, s13], 1):
            fname = "S%d" % idx
            if val == 1:
                factor_pass_counts[fname] = factor_pass_counts.get(fname, 0) + 1

        # Signal decision
        if hard_pass and sc >= sc_threshold:
            reason_parts = []
            if h2:
                reason_parts.append("H2")
            if h3:
                reason_parts.append("H3")
            if h4:
                reason_parts.append("H4")
            if h5:
                reason_parts.append("H5")
            reason = "%s pass; SC=%d>=%d" % ("+".join(reason_parts), sc, sc_threshold)

            signals.append({
                "date": date,
                "code": code,
                "score": sc,
                "hard_pass": True,
                "h": {"H1": h1, "H2": h2, "H3": h3, "H4": h4, "H5": h5},
                "s": {
                    "S1": s1, "S2": s2, "S3": s3, "S4": s4, "S5": s5,
                    "S6": s6, "S7": s7, "S8": s8, "S9": s9, "S10": s10,
                    "S11": s11, "S12": s12, "S13": s13,
                },
                "h1_mode": h1_mode,
                "reason": reason,
            })
        else:
            # Determine blocked reason
            blocked_by = None
            reason = ""
            if not hard_pass:
                failed = []
                if not h2:
                    failed.append("H2")
                if not h3:
                    failed.append("H3")
                if not h4:
                    failed.append("H4")
                if not h5:
                    failed.append("H5")
                blocked_by = "+".join(failed)
                reason = "hard gate failed: %s" % blocked_by
            else:
                blocked_by = "SC"
                reason = "SC=%d <%d" % (sc, sc_threshold)

            blocked.append({
                "date": date,
                "code": code,
                "blocked_by": blocked_by,
                "score": sc,
                "reason": reason,
            })
            blocked_counts[blocked_by] = blocked_counts.get(blocked_by, 0) + 1

    diagnostics = {
        "signal_count": len(signals),
        "blocked_counts": blocked_counts,
        "factor_pass_counts": factor_pass_counts,
        "warnings": [],
    }

    return {
        "signals": signals,
        "blocked": blocked,
        "diagnostics": diagnostics,
        "logs": logs,
    }
