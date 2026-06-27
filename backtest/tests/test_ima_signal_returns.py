# coding: utf-8
"""Unit tests for IMA V3.1 signal returns computation."""

import sys
import os
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backtest.scripts.run_signal_research_ima import compute_signal_returns, get_next_trading_day


def _make_df(n=100, close_start=10.0):
    dates = pd.date_range("2025-09-01", periods=n, freq="B")
    close = close_start + np.arange(n) * 0.1
    high = close + 0.5
    low = close - 0.5
    vol = np.full(n, 1000000.0)

    df = pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "open": close - 0.1,
        "high": high,
        "low": low,
        "close": close,
        "vol": vol,
        "amount": close * vol,
    })
    return df


class TestGetNextTradingDay:
    def test_basic(self):
        calendar = ["2025-09-01", "2025-09-02", "2025-09-03"]
        assert get_next_trading_day("2025-09-01", calendar) == "2025-09-02"

    def test_last_day(self):
        calendar = ["2025-09-01", "2025-09-02", "2025-09-03"]
        assert get_next_trading_day("2025-09-03", calendar) is None


class TestComputeSignalReturns:
    def test_basic(self):
        df = _make_df(30)
        calendar = df["date"].tolist()
        market_window = {"000001.SZ": df}

        signals = [{
            "date": calendar[0],
            "code": "000001.SZ",
            "score": 8,
            "h1_mode": "disabled",
        }]

        returns = compute_signal_returns(signals, market_window, calendar, [1, 3, 5, 10])
        assert len(returns) == 1
        r = returns[0]
        assert r["status"] == "filled"
        assert r["entry_date"] == calendar[1]
        assert r["ret_1d"] is not None

    def test_unfilled_last_day(self):
        df = _make_df(30)
        calendar = df["date"].tolist()
        market_window = {"000001.SZ": df}

        signals = [{
            "date": calendar[-1],
            "code": "000001.SZ",
            "score": 8,
            "h1_mode": "disabled",
        }]

        returns = compute_signal_returns(signals, market_window, calendar, [1, 3, 5, 10])
        assert len(returns) == 1
        assert returns[0]["status"] == "unfilled"

    def test_return_calculation(self):
        df = _make_df(30)
        calendar = df["date"].tolist()
        market_window = {"000001.SZ": df}

        signals = [{
            "date": calendar[0],
            "code": "000001.SZ",
            "score": 8,
            "h1_mode": "disabled",
        }]

        returns = compute_signal_returns(signals, market_window, calendar, [1])
        r = returns[0]
        # Entry is calendar[1], 1d exit is calendar[2]
        entry_open = float(df[df["date"] == r["entry_date"]]["open"].iloc[0])
        exit_close = float(df[df["date"] == calendar[2]]["close"].iloc[0])
        expected = (exit_close / entry_open - 1.0) * 100.0
        assert abs(r["ret_1d"] - expected) < 1e-10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
