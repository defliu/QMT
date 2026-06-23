# coding: utf-8
"""True no-lookahead tests for IMA V3.1 signal generation.

Tests that evaluate_ima_day on day T only uses data up to day T,
even when the input DataFrame contains future data.
"""

import sys
import os
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backtest.strategies.production.ima_uptrend_v31.ima_uptrend_v31 import evaluate_ima_day


def _make_df_with_future(n_past=60, n_future=30, close_start=10.0):
    """Create a DataFrame where past data is normal, future data is extreme.

    Past: normal uptrend
    Future: massive crash (close drops to 1.0)
    """
    dates_past = pd.date_range("2025-09-01", periods=n_past, freq="B")
    dates_future = pd.date_range(dates_past[-1] + pd.Timedelta(days=1), periods=n_future, freq="B")
    dates_all = dates_past.append(dates_future)

    # Past: normal uptrend
    close_past = close_start + np.arange(n_past) * 0.1
    # Future: crash
    close_future = np.full(n_future, 1.0)

    close_all = np.concatenate([close_past, close_future])
    high_all = close_all + 0.5
    low_all = close_all - 0.5
    vol_all = np.full(n_past + n_future, 1000000.0)

    df = pd.DataFrame({
        "date": dates_all.strftime("%Y-%m-%d"),
        "open": close_all - 0.1,
        "high": high_all,
        "low": low_all,
        "close": close_all,
        "vol": vol_all,
        "amount": close_all * vol_all,
    })
    return df, dates_past[-1].strftime("%Y-%m-%d")


class TestTrueNoLookahead:
    def test_future_data_does_not_affect_signal(self):
        """Signal on day T should be same whether future data exists or not."""
        df_full, cutoff_date = _make_df_with_future(n_past=80, n_future=30)

        # Create truncated version (no future data)
        df_truncated = df_full[df_full["date"] <= cutoff_date].copy()

        market_window_full = {"000001.SZ": df_full}
        market_window_truncated = {"000001.SZ": df_truncated}

        config = {
            "strategy": {"sc_threshold": 0, "h1_mode": "disabled"},
            "hard_filters": {"gain_3d_min": 0, "gain_3d_max": 100},
            "factors": {},
        }

        # Evaluate with full data (includes future crash)
        result_full = evaluate_ima_day(cutoff_date, market_window_full, ["000001.SZ"], config)

        # Evaluate with truncated data (no future)
        result_truncated = evaluate_ima_day(cutoff_date, market_window_truncated, ["000001.SZ"], config)

        # Results should be identical because evaluate_ima_day truncates internally
        assert len(result_full["signals"]) == len(result_truncated["signals"])
        assert len(result_full["blocked"]) == len(result_truncated["blocked"])

        if result_full["signals"]:
            sig_full = result_full["signals"][0]
            sig_trunc = result_truncated["signals"][0]
            assert sig_full["score"] == sig_trunc["score"]
            assert sig_full["h"] == sig_trunc["h"]
            assert sig_full["s"] == sig_trunc["s"]

    def test_anti_lookahead_with_different_futures(self):
        """Two different future scenarios should not affect same-day signals."""
        # Create base past data
        n_past = 80
        dates_past = pd.date_range("2025-09-01", periods=n_past, freq="B")
        close_past = 10.0 + np.arange(n_past) * 0.1

        cutoff_date = dates_past[-1].strftime("%Y-%m-%d")

        # Future scenario A: crash
        n_future = 30
        dates_future = pd.date_range(dates_past[-1] + pd.Timedelta(days=1), periods=n_future, freq="B")
        close_future_a = np.full(n_future, 1.0)

        # Future scenario B: moon
        close_future_b = np.full(n_future, 100.0)

        def build_df(close_future):
            close_all = np.concatenate([close_past, close_future])
            high_all = close_all + 0.5
            low_all = close_all - 0.5
            vol_all = np.full(n_past + n_future, 1000000.0)
            dates_all = dates_past.append(dates_future)
            return pd.DataFrame({
                "date": dates_all.strftime("%Y-%m-%d"),
                "open": close_all - 0.1,
                "high": high_all,
                "low": low_all,
                "close": close_all,
                "vol": vol_all,
                "amount": close_all * vol_all,
            })

        df_a = build_df(close_future_a)
        df_b = build_df(close_future_b)

        config = {
            "strategy": {"sc_threshold": 0, "h1_mode": "disabled"},
            "hard_filters": {"gain_3d_min": 0, "gain_3d_max": 100},
            "factors": {},
        }

        result_a = evaluate_ima_day(cutoff_date, {"000001.SZ": df_a}, ["000001.SZ"], config)
        result_b = evaluate_ima_day(cutoff_date, {"000001.SZ": df_b}, ["000001.SZ"], config)

        # Same-day signals should be identical regardless of future
        assert len(result_a["signals"]) == len(result_b["signals"])
        if result_a["signals"]:
            assert result_a["signals"][0]["score"] == result_b["signals"][0]["score"]
            assert result_a["signals"][0]["s"] == result_b["signals"][0]["s"]

    def test_engine_level_truncation(self):
        """Verify that run_signal_research_ima.py truncates before calling evaluate."""
        # This is a structural test - verify the code path exists
        from backtest.scripts import run_signal_research_ima
        import inspect
        source = inspect.getsource(run_signal_research_ima.main)
        assert "df_full[df_full" in source or "df[df" in source, \
            "Engine must truncate market_window before calling evaluate_ima_day"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
