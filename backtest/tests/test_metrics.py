# coding: utf-8
"""Tests for backtest.engine.metrics -- performance dict per 04 §1.4."""
import pytest

from backtest.engine.metrics import compute_metrics


def _eq(date, total, daily_ret):
    return {"run_id": "R1", "date": date, "total_asset": total,
            "cash": 0.0, "market_value": total, "daily_return": daily_ret,
            "benchmark_close": "", "benchmark_return": ""}


def _buy(code, date, price, volume):
    amt = price * volume
    return {"run_id": "R1", "date": date, "code": code, "side": "buy",
            "volume": volume, "price": price, "amount": amt,
            "slippage_amt": 0.0, "commission": amt * 0.00025, "tax": 0.0,
            "reason": "top_candidate", "layer": "", "model": "next_open"}


def _sell(code, date, price, volume):
    amt = price * volume
    return {"run_id": "R1", "date": date, "code": code, "side": "sell",
            "volume": volume, "price": price, "amount": amt,
            "slippage_amt": 0.0, "commission": amt * 0.00025,
            "tax": amt * 0.0001,
            "reason": "stop_loss", "layer": "bottom_line", "model": "next_open"}


def test_total_return_basic():
    eq = [_eq("D1", 1_000_000, 0.0), _eq("D2", 1_050_000, 0.05)]
    perf = compute_metrics(eq, [], ["D1", "D2"], 1_000_000.0)
    assert perf["total_return"] == pytest.approx(0.05)
    assert perf["n_trades"] == 0


def test_max_drawdown_negative():
    eq = [_eq("D1", 1_000_000, 0.0),
          _eq("D2", 1_100_000, 0.10),
          _eq("D3", 990_000, -0.10),
          _eq("D4", 1_080_000, 0.0909)]
    perf = compute_metrics(eq, [], ["D1", "D2", "D3", "D4"], 1_000_000.0)
    # peak 1.1M -> 990k = -10%
    assert perf["max_drawdown"] == pytest.approx(-0.1, rel=1e-3)


def test_sharpe_zero_when_constant():
    eq = [_eq("D%d" % i, 1_000_000, 0.0) for i in range(5)]
    perf = compute_metrics(eq, [], ["D0", "D1", "D2", "D3", "D4"], 1_000_000.0)
    assert perf["sharpe"] == 0.0


def test_calmar_none_when_no_drawdown():
    eq = [_eq("D1", 1_000_000, 0.0), _eq("D2", 1_010_000, 0.01)]
    perf = compute_metrics(eq, [], ["D1", "D2"], 1_000_000.0)
    assert perf["calmar"] is None
    assert perf["max_drawdown"] == 0.0


def test_win_rate_paired_trades():
    trades = [
        _buy("000001.SZ", "D1", 10.0, 1000),   # cost 10000
        _sell("000001.SZ", "D5", 11.0, 1000),  # proceeds ~11000 -> win
        _buy("000002.SZ", "D2", 20.0, 500),    # cost 10000
        _sell("000002.SZ", "D6", 19.0, 500),   # proceeds ~9500 -> loss
    ]
    cal = ["D1", "D2", "D3", "D4", "D5", "D6"]
    eq = [_eq(d, 1_000_000, 0.0) for d in cal]
    perf = compute_metrics(eq, trades, cal, 1_000_000.0)
    assert perf["n_trades"] == 4
    assert perf["n_buy"] == 2
    assert perf["n_sell"] == 2
    assert perf["win_rate"] == 0.5


def test_avg_holding_days_uses_trading_calendar():
    trades = [_buy("000001.SZ", "D1", 10.0, 1000),
              _sell("000001.SZ", "D5", 11.0, 1000)]
    cal = ["D1", "D2", "D3", "D4", "D5"]
    eq = [_eq(d, 1_000_000, 0.0) for d in cal]
    perf = compute_metrics(eq, trades, cal, 1_000_000.0)
    # D5 - D1 = 4 trading days
    assert perf["avg_holding_days"] == 4.0


def test_benchmark_fields_are_none_when_unavailable():
    eq = [_eq("D1", 1_000_000, 0.0), _eq("D2", 1_010_000, 0.01)]
    perf = compute_metrics(eq, [], ["D1", "D2"], 1_000_000.0,
                           benchmark_available=False)
    assert perf["excess_return"] is None
    assert perf["information_ratio"] is None
    assert perf["tracking_error"] is None


def test_performance_dict_has_all_expected_keys():
    eq = [_eq("D1", 1_000_000, 0.0), _eq("D2", 1_005_000, 0.005)]
    perf = compute_metrics(eq, [], ["D1", "D2"], 1_000_000.0)
    expected = {"total_return", "annual_return", "max_drawdown", "sharpe",
                "calmar", "win_rate", "n_trades", "n_buy", "n_sell",
                "avg_holding_days", "excess_return", "information_ratio",
                "tracking_error"}
    assert set(perf.keys()) == expected
