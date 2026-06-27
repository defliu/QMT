# coding: utf-8
"""Minute-level signal generators for backtest.

Provides:
  - breakout_signal_at_time: check if price breaks N-day high at a specific time
  - fake_breakout_rate_by_time: compute fake breakout stats across time points
  - gen_chip_signal_from_db: read chip concentration signals from duckdb

All functions output daily-level signals for daily_engine consumption.
"""
import os

import numpy as np
import pandas as pd


def breakout_signal_at_time(df_1min, time_str="10:00", lookback_days=20):
    """Check if price breaks previous N-day high at a specific intraday time.

    Logic:
      For each trading day T in df_1min:
        1. Extract the bar at time_str on day T
        2. Compute highest high over the previous lookback_days trading days
        3. If T's close at time_str > prev N-day high, signal = True

    Args:
        df_1min: DataFrame from AstockMinuteReader.load_minute_window(),
                 must have columns [trade_time, trade_date, high, close]
        time_str: intraday time to check, format "HH:MM" (e.g. "10:00")
        lookback_days: number of previous trading days for high benchmark

    Returns:
        pd.Series(index=trade_date, values=bool), daily-level breakout signal.
        True means breakout at that time_str on that day.
    """
    if df_1min is None or df_1min.empty:
        return pd.Series(dtype=bool)

    df = df_1min.copy()
    if "trade_date" not in df.columns:
        if hasattr(df.index, "names") and "trade_date" in (df.index.names or []):
            df = df.reset_index()
        else:
            return pd.Series(dtype=bool)

    if "trade_time" in df.columns:
        tt = pd.to_datetime(df["trade_time"])
        df["_time_str"] = tt.dt.strftime("%H:%M")
    else:
        return pd.Series(dtype=bool)

    target_bars = df[df["_time_str"] == time_str].copy()
    if target_bars.empty:
        return pd.Series(dtype=bool)

    target_bars["trade_date"] = pd.to_datetime(target_bars["trade_date"])
    daily_dates = sorted(target_bars["trade_date"].unique())

    results = {}
    for i, day in enumerate(daily_dates):
        if i < lookback_days:
            results[day] = False
            continue
        lookback_dates = daily_dates[i - lookback_days : i]
        lookback_mask = df["trade_date"].isin(lookback_dates)
        prev_high = df.loc[lookback_mask, "high"].max()

        day_bar = target_bars[target_bars["trade_date"] == day]
        if day_bar.empty:
            results[day] = False
            continue
        day_close = day_bar["close"].iloc[0]
        results[day] = bool(day_close > prev_high)

    out = pd.Series(results, dtype=bool)
    out.index = [d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10] for d in out.index]
    return out


def fake_breakout_rate_by_time(df_1min, times=None, lookback_days=20, hold_minutes=30):
    """Compute fake breakout rate at various intraday time points.

    A "fake breakout" means:
      - At time T, price breaks the previous N-day high
      - Within the next hold_minutes bars, price falls back below the breakout price

    Used for 10:00 validation of chip-based signals.

    Args:
        df_1min: DataFrame from AstockMinuteReader.load_minute_window()
        times: list of time strings to test, default ["09:30","10:00","13:30","14:30"]
        lookback_days: N-day lookback for high benchmark
        hold_minutes: how many minutes to hold after breakout to check for fade

    Returns:
        dict: {time_str: (fake_count, total_breakouts, fake_rate)}
    """
    if times is None:
        times = ["09:30", "10:00", "13:30", "14:30"]

    if df_1min is None or df_1min.empty:
        return {t: (0, 0, 0.0) for t in times}

    df = df_1min.copy()
    if "trade_date" not in df.columns and hasattr(df.index, "names"):
        df = df.reset_index()

    df["trade_date"] = pd.to_datetime(df["trade_date"])
    if "trade_time" in df.columns:
        tt = pd.to_datetime(df["trade_time"])
        df["_time_str"] = tt.dt.strftime("%H:%M")
        df["_bar_idx"] = tt.dt.hour * 60 + tt.dt.minute
    else:
        return {t: (0, 0, 0.0) for t in times}

    all_dates = sorted(df["trade_date"].unique())
    results = {}

    for time_str in times:
        fake_count = 0
        total_breakouts = 0

        for i, day in enumerate(all_dates):
            if i < lookback_days:
                continue
            lookback_dates = all_dates[i - lookback_days : i]
            lookback_mask = df["trade_date"].isin(lookback_dates)
            prev_high = df.loc[lookback_mask, "high"].max()

            day_mask = df["trade_date"] == day
            time_mask = df["_time_str"] == time_str
            day_bar = df[day_mask & time_mask]
            if day_bar.empty:
                continue
            breakout_price = day_bar["close"].iloc[0]
            if breakout_price <= prev_high:
                continue

            total_breakouts += 1
            target_bar_idx = day_bar["_bar_idx"].iloc[0]
            future_mask = day_mask & (df["_bar_idx"] > target_bar_idx) & (
                df["_bar_idx"] <= target_bar_idx + hold_minutes
            )
            future_bars = df[future_mask]
            if not future_bars.empty and future_bars["low"].min() < breakout_price:
                fake_count += 1

        fake_rate = fake_count / total_breakouts if total_breakouts > 0 else 0.0
        results[time_str] = (fake_count, total_breakouts, fake_rate)

    return results


def gen_chip_signal_from_db(code, dates, chip_db_path):
    """Read chip concentration signals from pre-computed duckdb.

    Args:
        code: ts_code string (e.g. "600000.SH")
        dates: list of date strings to query
        chip_db_path: path to chip_1min_529.duckdb

    Returns:
        pd.Series(index=date_str, values=bool), True if chip signal fires.
        Returns empty Series if db not found or no data.
    """
    if not os.path.isfile(chip_db_path):
        return pd.Series(dtype=bool)

    try:
        import duckdb
    except ImportError:
        return pd.Series(dtype=bool)

    try:
        conn = duckdb.connect(chip_db_path, read_only=True)
        placeholders = ", ".join(["'%s'" % d for d in dates])
        query = (
            "SELECT trade_date, signal FROM chip_signals "
            "WHERE ts_code = '%s' AND trade_date IN (%s)"
            % (code, placeholders)
        )
        result = conn.execute(query).fetchdf()
        conn.close()
    except Exception:
        return pd.Series(dtype=bool)

    if result.empty:
        return pd.Series(dtype=bool)

    out = pd.Series(
        result["signal"].values,
        index=[str(d)[:10] for d in result["trade_date"]],
        dtype=bool,
    )
    return out
