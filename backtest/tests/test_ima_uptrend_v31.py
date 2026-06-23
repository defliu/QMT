# coding: utf-8
"""Unit tests for IMA Main Uptrend Wave V3.1 signal core."""

import sys
import os
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backtest.strategies.production.ima_uptrend_v31.ima_uptrend_v31 import (
    compute_ma, compute_ema, compute_rsi, compute_macd,
    check_h2_ma_bull, check_h3_gain_3d, check_h4_not_deep_pit_rush, check_h5_volume_ceiling,
    score_s1_ma_bull, score_s2_ma_rising, score_s3_price_strong, score_s4_volume_expand,
    score_s5_breakout_20h, score_s6_macd_strong, score_s7_rsi_healthy, score_s8_ma_convergence,
    score_s9_volatility_contraction, score_s10_long_trend, score_s11_divergence_accel,
    score_s12_continuous_strength, score_s13_volume_trend,
    evaluate_ima_day,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_close(values):
    return pd.Series(values, dtype=float)


def _make_df(n=100, close_start=10.0, trend="up"):
    """Generate a synthetic OHLCV DataFrame."""
    dates = pd.date_range("2025-09-01", periods=n, freq="B")
    if trend == "up":
        close = close_start + np.arange(n) * 0.1
    elif trend == "flat":
        close = np.full(n, close_start)
    else:
        close = close_start - np.arange(n) * 0.1

    high = close + 0.5
    low = close - 0.5
    vol = np.full(n, 1000000.0)
    amount = close * vol

    df = pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "open": close - 0.1,
        "high": high,
        "low": low,
        "close": close,
        "vol": vol,
        "amount": amount,
    })
    return df


# ---------------------------------------------------------------------------
# MA / EMA / RSI / MACD
# ---------------------------------------------------------------------------

class TestComputeMA:
    def test_basic(self):
        s = _make_close([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        ma3 = compute_ma(s, 3)
        assert len(ma3) == 10
        assert np.isnan(ma3.iloc[0])
        assert np.isnan(ma3.iloc[1])
        assert abs(ma3.iloc[2] - 2.0) < 1e-10

    def test_insufficient_data(self):
        s = _make_close([1, 2])
        ma5 = compute_ma(s, 5)
        assert all(np.isnan(ma5))


class TestComputeRSI:
    def test_basic(self):
        np.random.seed(42)
        s = _make_close(np.cumsum(np.random.randn(30)) + 20)
        rsi = compute_rsi(s, 14)
        assert len(rsi) == 30
        last_rsi = float(rsi.dropna().iloc[-1])
        assert 0 <= last_rsi <= 100


class TestComputeMACD:
    def test_basic(self):
        s = _make_close(np.arange(1, 60, dtype=float))
        dif, dea, hist = compute_macd(s)
        assert len(dif) == 59
        assert len(dea) == 59
        assert len(hist) == 59


# ---------------------------------------------------------------------------
# Hard gates H2-H5
# ---------------------------------------------------------------------------

class TestH2:
    def test_bull_pass(self):
        ma5 = _make_close([5, 6, 7, 8, 9, 10])
        ma10 = _make_close([4, 5, 6, 7, 8, 9])
        ma20 = _make_close([3, 4, 5, 6, 7, 8])
        ma60 = _make_close([1, 2, 3, 4, 5, 6])
        assert check_h2_ma_bull(ma5, ma10, ma20, ma60) is True

    def test_bear_fail(self):
        ma5 = _make_close([5, 4, 3, 2, 1])
        ma10 = _make_close([6, 5, 4, 3, 2])
        ma20 = _make_close([7, 6, 5, 4, 3])
        ma60 = _make_close([8, 7, 6, 5, 4])
        assert check_h2_ma_bull(ma5, ma10, ma20, ma60) is False

    def test_insufficient_data(self):
        assert check_h2_ma_bull(_make_close([1]), _make_close([2]), _make_close([3]), _make_close([4])) is False


class TestH3:
    def test_in_range(self):
        close = _make_close([10, 10, 10, 11, 12])
        assert check_h3_gain_3d(close, 5.0, 25.0) is True

    def test_below_min(self):
        close = _make_close([10, 10, 10, 10.1, 10.2])
        assert check_h3_gain_3d(close, 5.0, 25.0) is False

    def test_above_max(self):
        close = _make_close([10, 10, 10, 12, 13])
        assert check_h3_gain_3d(close, 5.0, 25.0) is False


class TestH4:
    def test_no_pit_pass(self):
        high = _make_close(np.full(20, 12.0))
        low = _make_close(np.full(20, 10.0))
        close = _make_close(np.full(20, 11.0))
        assert check_h4_not_deep_pit_rush(high, low, close) is True

    def test_insufficient_data(self):
        assert check_h4_not_deep_pit_rush(_make_close([1]), _make_close([1]), _make_close([1])) is True


class TestH5:
    def test_normal_pass(self):
        vol = _make_close([100])
        ma_vol = _make_close([100])
        assert check_h5_volume_ceiling(vol, ma_vol, 5.0) is True

    def test_ceiling_fail(self):
        vol = _make_close([600])
        ma_vol = _make_close([100])
        assert check_h5_volume_ceiling(vol, ma_vol, 5.0) is False


# ---------------------------------------------------------------------------
# Scoring factors S1-S13
# ---------------------------------------------------------------------------

class TestS1:
    def test_bull(self):
        ma5 = _make_close([5, 6, 7, 8, 9, 10])
        ma10 = _make_close([4, 5, 6, 7, 8, 9])
        ma20 = _make_close([3, 4, 5, 6, 7, 8])
        ma60 = _make_close([1, 2, 3, 4, 5, 6])
        assert score_s1_ma_bull(ma5, ma10, ma20, ma60) == 1

    def test_bear(self):
        ma5 = _make_close([5, 4, 3, 2, 1])
        ma10 = _make_close([6, 5, 4, 3, 2])
        ma20 = _make_close([7, 6, 5, 4, 3])
        ma60 = _make_close([8, 7, 6, 5, 4])
        assert score_s1_ma_bull(ma5, ma10, ma20, ma60) == 0


class TestS2:
    def test_rising(self):
        ma5 = _make_close([1, 2, 3, 4, 5])
        ma10 = _make_close([1, 2, 3, 4, 5])
        ma20 = _make_close([1, 2, 3, 4, 5])
        assert score_s2_ma_rising(ma5, ma10, ma20) == 1

    def test_falling(self):
        ma5 = _make_close([5, 4, 3, 2, 1])
        ma10 = _make_close([5, 4, 3, 2, 1])
        ma20 = _make_close([5, 4, 3, 2, 1])
        assert score_s2_ma_rising(ma5, ma10, ma20) == 0


class TestS4:
    def test_expand(self):
        vol = _make_close([200])
        ma_vol = _make_close([100])
        assert score_s4_volume_expand(vol, ma_vol, 1.5) == 1

    def test_no_expand(self):
        vol = _make_close([100])
        ma_vol = _make_close([100])
        assert score_s4_volume_expand(vol, ma_vol, 1.5) == 0


class TestS7:
    def test_healthy(self):
        rsi = _make_close([60])
        assert score_s7_rsi_healthy(rsi, 45, 80) == 1

    def test_overbought(self):
        rsi = _make_close([90])
        assert score_s7_rsi_healthy(rsi, 45, 80) == 0

    def test_oversold(self):
        rsi = _make_close([30])
        assert score_s7_rsi_healthy(rsi, 45, 80) == 0


class TestS8:
    def test_converged(self):
        ma5 = _make_close([10.0])
        ma10 = _make_close([10.1])
        ma20 = _make_close([10.2])
        assert score_s8_ma_convergence(ma5, ma10, ma20, 5.0) == 1

    def test_diverged(self):
        ma5 = _make_close([12.0])
        ma10 = _make_close([10.0])
        ma20 = _make_close([8.0])
        assert score_s8_ma_convergence(ma5, ma10, ma20, 5.0) == 0


class TestS9:
    def test_low_volatility(self):
        close = _make_close(np.full(10, 10.0))
        assert score_s9_volatility_contraction(close, 5.0) == 1

    def test_high_volatility(self):
        close = _make_close(np.arange(1, 11) * 2.0)
        assert score_s9_volatility_contraction(close, 5.0) == 0


class TestS12:
    def test_strong(self):
        close = _make_close([11, 12, 13, 14, 15])
        ma5 = _make_close([10, 10, 10, 10, 10])
        assert score_s12_continuous_strength(close, ma5, 5, 3) == 1

    def test_weak(self):
        close = _make_close([9, 8, 7, 6, 5])
        ma5 = _make_close([10, 10, 10, 10, 10])
        assert score_s12_continuous_strength(close, ma5, 5, 3) == 0


class TestS13:
    def test_trend_up(self):
        ma5 = _make_close([200])
        ma10 = _make_close([100])
        assert score_s13_volume_trend(ma5, ma10) == 1

    def test_trend_down(self):
        ma5 = _make_close([100])
        ma10 = _make_close([200])
        assert score_s13_volume_trend(ma5, ma10) == 0


# ---------------------------------------------------------------------------
# evaluate_ima_day integration
# ---------------------------------------------------------------------------

class TestEvaluateImaDay:
    def test_basic_signal(self):
        df = _make_df(100, close_start=10.0, trend="up")
        market_window = {"000001.SZ": df}
        config = {
            "strategy": {"sc_threshold": 7, "h1_mode": "disabled"},
            "hard_filters": {"gain_3d_min": 5, "gain_3d_max": 25},
            "factors": {},
        }
        result = evaluate_ima_day("2025-12-31", market_window, ["000001.SZ"], config)
        assert "signals" in result
        assert "blocked" in result
        assert "diagnostics" in result

    def test_insufficient_history(self):
        df = _make_df(10, close_start=10.0)
        market_window = {"000001.SZ": df}
        config = {
            "strategy": {"sc_threshold": 7, "h1_mode": "disabled"},
            "hard_filters": {},
            "factors": {},
        }
        result = evaluate_ima_day("2025-09-15", market_window, ["000001.SZ"], config)
        assert len(result["blocked"]) == 1
        assert result["blocked"][0]["blocked_by"] == "insufficient_history"

    def test_h1_disabled_no_h1_block(self):
        df = _make_df(100, close_start=10.0, trend="up")
        market_window = {"000001.SZ": df}
        config = {
            "strategy": {"sc_threshold": 7, "h1_mode": "disabled"},
            "hard_filters": {"gain_3d_min": 5, "gain_3d_max": 25},
            "factors": {},
        }
        result = evaluate_ima_day("2025-12-31", market_window, ["000001.SZ"], config)
        for sig in result["signals"]:
            assert sig["h"]["H1"] is None
            assert sig["h1_mode"] == "disabled"

    def test_sc_threshold_boundary(self):
        df = _make_df(100, close_start=10.0, trend="up")
        market_window = {"000001.SZ": df}

        config_high = {
            "strategy": {"sc_threshold": 13, "h1_mode": "disabled"},
            "hard_filters": {"gain_3d_min": 0, "gain_3d_max": 100},
            "factors": {},
        }
        result_high = evaluate_ima_day("2025-12-31", market_window, ["000001.SZ"], config_high)
        assert len(result_high["signals"]) == 0

        config_low = {
            "strategy": {"sc_threshold": 0, "h1_mode": "disabled"},
            "hard_filters": {"gain_3d_min": 0, "gain_3d_max": 100},
            "factors": {},
        }
        result_low = evaluate_ima_day("2025-12-31", market_window, ["000001.SZ"], config_low)
        assert len(result_low["signals"]) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
