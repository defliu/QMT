# coding: utf-8
"""Tests for backtest.engine.execution -- next_open matching layer."""
import pandas as pd
import pytest

from backtest.engine.execution import fill_buy, fill_sell


def _make_window(open_t1=12.50, prev_close=12.40, with_t1=True):
    """Two-bar window: T (signal day) and T+1 (fill day)."""
    rows = [{"date": "2025-09-15", "open": 12.30, "high": 12.45,
             "low": 12.20, "close": prev_close, "vol": 1000000, "amount": 1.24e7}]
    if with_t1:
        rows.append({"date": "2025-09-16", "open": open_t1,
                     "high": open_t1 + 0.1, "low": open_t1 - 0.1,
                     "close": open_t1 + 0.05, "vol": 1100000,
                     "amount": open_t1 * 1.1e6})
    return {"000001.SZ": pd.DataFrame(rows)}


_EXEC = {"price": "next_open", "slippage": 0.001,
         "commission_rate": 0.00025, "tax_rate": 0.0001}


# ---------- fill_buy ----------
def test_fill_buy_basic_lot_floor():
    mw = _make_window(open_t1=12.50, prev_close=12.40)
    cand = {"code": "000001.SZ", "target_cash": 100000.0,
            "reason": "top_candidate"}
    trade, unfilled = fill_buy(cand, mw, "2025-09-16", _EXEC, run_id="R1")
    assert unfilled is None
    # price = 12.50 * 1.001 = 12.5125
    assert trade["price"] == pytest.approx(12.5125)
    # 100000 / 12.5125 = 7991.8  -> floor to 100 lot = 7900
    assert trade["volume"] == 7900
    assert trade["side"] == "buy"
    assert trade["model"] == "next_open"
    assert trade["tax"] == 0.0
    assert trade["amount"] == pytest.approx(12.5125 * 7900, rel=1e-6)


def test_fill_buy_suspended_returns_unfilled():
    mw = _make_window(with_t1=False)
    cand = {"code": "000001.SZ", "target_cash": 100000.0}
    trade, unfilled = fill_buy(cand, mw, "2025-09-16", _EXEC, run_id="R1")
    assert trade is None and unfilled == "suspended"


def test_fill_buy_limit_up_open_blocks_fill():
    # T+1 open at +10% vs prev close 12.40 -> 13.64
    mw = _make_window(open_t1=13.64, prev_close=12.40)
    cand = {"code": "000001.SZ", "target_cash": 100000.0}
    trade, unfilled = fill_buy(cand, mw, "2025-09-16", _EXEC, run_id="R1")
    assert trade is None and unfilled == "limit_up_at_open"


def test_fill_buy_below_min_lot():
    mw = _make_window(open_t1=12.50, prev_close=12.40)
    cand = {"code": "000001.SZ", "target_cash": 500.0}  # < 1 lot at 12.50
    trade, unfilled = fill_buy(cand, mw, "2025-09-16", _EXEC, run_id="R1")
    assert trade is None and unfilled == "below_min_lot"


# ---------- fill_sell ----------
def test_fill_sell_applies_negative_slippage_and_tax():
    mw = _make_window(open_t1=12.50, prev_close=12.40)
    pos = {"code": "000001.SZ", "volume": 1000, "available_volume": 1000,
           "cost_price": 11.00, "entry_date": "2025-09-10", "holding_days": 5,
           "last_price": 12.40, "unrealized_pnl": 1400.0}
    decision = {"code": "000001.SZ", "action": "sell", "target_volume": 0,
                "reason": "stop_loss", "layer": "bottom_line", "priority": 1}
    trade, unfilled = fill_sell(decision, pos, mw, "2025-09-16", _EXEC, run_id="R1")
    assert unfilled is None
    # price = 12.50 * 0.999 = 12.4875
    assert trade["price"] == pytest.approx(12.4875)
    assert trade["volume"] == 1000
    assert trade["tax"] == pytest.approx(12487.5 * 0.0001, rel=1e-6)
    assert trade["side"] == "sell"
    assert trade["layer"] == "bottom_line"


def test_fill_sell_no_available_volume():
    mw = _make_window(open_t1=12.50, prev_close=12.40)
    pos = {"code": "000001.SZ", "volume": 1000, "available_volume": 0,
           "cost_price": 11.0, "entry_date": "2025-09-15", "holding_days": 1,
           "last_price": 12.40, "unrealized_pnl": 0.0}
    decision = {"code": "000001.SZ", "action": "sell", "target_volume": 0,
                "reason": "stop_loss", "layer": "bottom_line", "priority": 1}
    trade, unfilled = fill_sell(decision, pos, mw, "2025-09-16", _EXEC, run_id="R1")
    assert trade is None and unfilled == "no_available_volume"


def test_fill_sell_suspended():
    mw = _make_window(with_t1=False)
    pos = {"code": "000001.SZ", "volume": 1000, "available_volume": 1000,
           "cost_price": 11.0, "entry_date": "2025-09-10", "holding_days": 5,
           "last_price": 12.40, "unrealized_pnl": 0.0}
    decision = {"code": "000001.SZ", "action": "sell", "target_volume": 0,
                "reason": "stop_loss", "layer": "bottom_line", "priority": 1}
    trade, unfilled = fill_sell(decision, pos, mw, "2025-09-16", _EXEC, run_id="R1")
    assert trade is None and unfilled == "suspended"


def test_trade_dict_has_all_13_columns():
    mw = _make_window(open_t1=12.50, prev_close=12.40)
    cand = {"code": "000001.SZ", "target_cash": 100000.0,
            "reason": "top_candidate"}
    trade, _ = fill_buy(cand, mw, "2025-09-16", _EXEC, run_id="R1")
    expected = {"run_id", "date", "code", "side", "volume", "price", "amount",
                "slippage_amt", "commission", "tax", "reason", "layer", "model"}
    assert set(trade.keys()) == expected
