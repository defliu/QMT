# coding: utf-8
"""Tests for backtest.engine.portfolio -- bookkeeping + T+1 + snapshots."""
import pandas as pd
import pytest

from backtest.engine.portfolio import Portfolio


def _mw(close_by_date):
    """close_by_date: dict[date_str -> close]. open=high=low=close for simplicity."""
    rows = []
    for d, c in sorted(close_by_date.items()):
        rows.append({"date": d, "open": c, "high": c, "low": c, "close": c,
                     "vol": 1e6, "amount": c * 1e6})
    return {"000001.SZ": pd.DataFrame(rows)}


def _trade_buy(code="000001.SZ", date="2025-09-16", price=12.5125, volume=1000):
    return {"run_id": "R1", "date": date, "code": code, "side": "buy",
            "volume": volume, "price": price,
            "amount": price * volume, "slippage_amt": 0.0,
            "commission": price * volume * 0.00025, "tax": 0.0,
            "reason": "top_candidate", "layer": "", "model": "next_open"}


def _trade_sell(code="000001.SZ", date="2025-09-22", price=12.4875, volume=1000):
    return {"run_id": "R1", "date": date, "code": code, "side": "sell",
            "volume": volume, "price": price,
            "amount": price * volume, "slippage_amt": 0.0,
            "commission": price * volume * 0.00025,
            "tax": price * volume * 0.0001,
            "reason": "stop_loss", "layer": "bottom_line", "model": "next_open"}


def test_initial_state():
    pf = Portfolio(initial_cash=1_000_000.0)
    assert pf.cash == 1_000_000.0
    assert pf.market_value() == 0.0
    assert pf.total_asset() == 1_000_000.0
    assert pf.position_list() == []


def test_apply_buy_creates_position_with_t1_lock():
    pf = Portfolio(1_000_000.0)
    t = _trade_buy(price=12.5125, volume=1000)
    pf.apply_trade(t)
    assert "000001.SZ" in pf.positions
    p = pf.positions["000001.SZ"]
    assert p["volume"] == 1000
    assert p["available_volume"] == 0     # T+1 lock
    assert p["holding_days"] == 1
    assert pf.cash < 1_000_000.0  # cash decreased


def test_advance_holding_days_unfreezes_t1():
    pf = Portfolio(1_000_000.0)
    pf.apply_trade(_trade_buy(volume=1000))
    pf.advance_holding_days()
    p = pf.positions["000001.SZ"]
    assert p["available_volume"] == 1000
    assert p["holding_days"] == 2


def test_apply_sell_removes_when_volume_zero():
    pf = Portfolio(1_000_000.0)
    pf.apply_trade(_trade_buy(volume=1000))
    pf.advance_holding_days()              # available = 1000
    pf.apply_trade(_trade_sell(volume=1000))
    assert "000001.SZ" not in pf.positions
    # cash returned net of fees + tax
    assert pf.cash > 0


def test_partial_sell_keeps_position():
    pf = Portfolio(1_000_000.0)
    pf.apply_trade(_trade_buy(volume=2000))
    pf.advance_holding_days()
    pf.apply_trade(_trade_sell(volume=1000))
    p = pf.positions["000001.SZ"]
    assert p["volume"] == 1000
    assert p["available_volume"] == 1000


def test_buy_then_buy_same_code_averages_cost():
    pf = Portfolio(1_000_000.0)
    pf.apply_trade(_trade_buy(price=12.0, volume=1000))
    pf.advance_holding_days()
    pf.apply_trade(_trade_buy(price=14.0, volume=1000))
    p = pf.positions["000001.SZ"]
    assert p["volume"] == 2000
    # second buy stays locked on same day
    assert p["available_volume"] == 1000   # only the original 1000 was unlocked
    # cost is between 12 and 14
    assert 12.0 < p["cost_price"] < 14.0


def test_mark_to_market_updates_last_price_and_pnl():
    pf = Portfolio(1_000_000.0)
    pf.apply_trade(_trade_buy(price=12.5125, volume=1000))
    mw = _mw({"2025-09-16": 13.0})
    pf.mark_to_market(mw, "2025-09-16")
    p = pf.positions["000001.SZ"]
    assert p["last_price"] == pytest.approx(13.0)
    assert p["unrealized_pnl"] == pytest.approx((13.0 - p["cost_price"]) * 1000)


def test_mark_to_market_falls_back_when_suspended():
    pf = Portfolio(1_000_000.0)
    pf.apply_trade(_trade_buy(price=12.5125, volume=1000))
    mw = _mw({"2025-09-16": 13.0})  # only one bar, no 09-17
    pf.mark_to_market(mw, "2025-09-17")  # suspended
    p = pf.positions["000001.SZ"]
    # Falls back to last known close (13.0)
    assert p["last_price"] == pytest.approx(13.0)


def test_equity_row_first_day_zero_return():
    pf = Portfolio(1_000_000.0)
    row = pf.equity_row("R1", "2025-09-01")
    assert row["total_asset"] == 1_000_000.0
    assert row["daily_return"] == 0.0
    assert row["benchmark_close"] == ""


def test_equity_row_second_day_computes_return():
    pf = Portfolio(1_000_000.0)
    pf.equity_row("R1", "2025-09-01")
    pf.apply_trade(_trade_buy(price=12.5, volume=1000))
    mw = _mw({"2025-09-02": 13.0})
    pf.mark_to_market(mw, "2025-09-02")
    row = pf.equity_row("R1", "2025-09-02")
    # Position value 13000 + cash; total_asset > initial because price rose
    assert row["daily_return"] != 0.0


def test_position_list_shape_matches_03_section_2():
    pf = Portfolio(1_000_000.0)
    pf.apply_trade(_trade_buy(volume=1000))
    pos = pf.position_list()
    assert len(pos) == 1
    expected = {"code", "volume", "available_volume", "cost_price",
                "entry_date", "holding_days", "last_price", "unrealized_pnl"}
    assert set(pos[0].keys()) == expected


def test_positions_rows_match_04_section_4():
    pf = Portfolio(1_000_000.0)
    pf.apply_trade(_trade_buy(volume=1000))
    rows = pf.positions_rows("R1", "2025-09-16")
    assert len(rows) == 1
    expected = {"run_id", "date", "code", "volume", "available_volume",
                "cost_price", "last_price", "unrealized_pnl", "holding_days"}
    assert set(rows[0].keys()) == expected
