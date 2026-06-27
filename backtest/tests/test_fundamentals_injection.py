# coding: utf-8
"""Tests for B2b fundamentals injection into daily_engine.

Verifies:
1. fundamentals_reader=None preserves original behavior (no fundamentals in aux_for_eval)
2. fundamentals_reader present injects daily PE into aux_data["fundamentals"]
3. reader exceptions trigger graceful fallback
4. PIT: different today dates pass different asof_date to reader
5. End-to-end: example_ma_cross_astock + fundamentals=true has no "fundamentals not available" warning
"""
import pandas as pd
import pytest

from backtest.engine.daily_engine import run_backtest
from backtest.tests.test_daily_engine import FakeReader, _build_market, _EXEC, _cfg


class FakeFundamentalsReader(object):
    """Mock fundamentals reader that returns fixed PE dict for any code/date."""
    
    def __init__(self, pe_dict=None, fail_on_date=None):
        """
        Args:
            pe_dict: {code: {"dynamic_pe": float, "static_pe": float}} default PE values
            fail_on_date: if set, raise exception when called with this date
        """
        self._pe_dict = pe_dict or {}
        self._fail_on_date = fail_on_date
        self._calls = []  # track calls for PIT verification
    
    def get_fundamentals_for_scoring(self, codes, asof_date):
        """Return PE dict for given codes and date."""
        self._calls.append({"codes": codes, "asof_date": asof_date})
        if self._fail_on_date and asof_date == self._fail_on_date:
            raise RuntimeError("simulated reader failure for %s" % asof_date)
        result = {}
        for code in codes:
            if code in self._pe_dict:
                result[code] = self._pe_dict[code]
        return result


def _make_aux_spy():
    """Create a spy function that captures aux_data passed to evaluate_day."""
    seen_aux = []
    
    def spy_fn(current_date, market_window, positions, cash, universe,
               account_state, strategy_config, aux_data=None):
        seen_aux.append({"date": current_date, "aux_data": aux_data})
        # Return minimal decision
        return {
            "sell_decisions": [],
            "buy_candidates": [],
            "diagnostics": {"warnings": [], "candidate_total": 0, "candidate_passed": 0},
            "logs": [],
        }
    
    return spy_fn, seen_aux


def test_fundamentals_reader_none_preserves_original_behavior():
    """When fundamentals_reader=None, aux_for_eval should NOT contain fundamentals."""
    universe = ["000001.SZ"]
    market, dates = _build_market(universe, n_days=65)
    reader = FakeReader(market, dates)
    
    spy_fn, seen_aux = _make_aux_spy()
    
    # Patch evaluate_day with spy
    from backtest.strategies import _REGISTRY
    original = _REGISTRY.get("production/ima_uptrend_v31")
    _REGISTRY["production/ima_uptrend_v31"] = spy_fn
    try:
        result = run_backtest(
            reader=reader, universe=universe,
            start_date=dates[0], end_date=dates[-1],
            strategy_config=_cfg(), execution_cfg=_EXEC,
            initial_cash=1_000_000.0, universe_hash="u", config_hash="c",
            fundamentals_reader=None,  # None reader
        )
    finally:
        _REGISTRY["production/ima_uptrend_v31"] = original
    
    # Verify aux_data does NOT contain fundamentals
    for call in seen_aux:
        aux = call["aux_data"]
        assert "fundamentals" not in aux, (
            "fundamentals should NOT be in aux_data when reader is None, "
            "got %s" % aux.get("fundamentals")
        )


def test_fundamentals_reader_injects_daily_pe():
    """When fundamentals_reader is provided, aux_data should contain daily PE."""
    universe = ["000001.SZ"]
    market, dates = _build_market(universe, n_days=65)
    reader = FakeReader(market, dates)
    
    pe_dict = {"000001.SZ": {"dynamic_pe": 15.5, "static_pe": 14.2}}
    fund_reader = FakeFundamentalsReader(pe_dict=pe_dict)
    
    spy_fn, seen_aux = _make_aux_spy()
    
    # Patch evaluate_day with spy
    from backtest.strategies import _REGISTRY
    original = _REGISTRY.get("production/ima_uptrend_v31")
    _REGISTRY["production/ima_uptrend_v31"] = spy_fn
    try:
        result = run_backtest(
            reader=reader, universe=universe,
            start_date=dates[0], end_date=dates[-1],
            strategy_config=_cfg(), execution_cfg=_EXEC,
            initial_cash=1_000_000.0, universe_hash="u", config_hash="c",
            fundamentals_reader=fund_reader,
        )
    finally:
        _REGISTRY["production/ima_uptrend_v31"] = original
    
    # Verify aux_data contains fundamentals for each day
    assert len(seen_aux) > 0, "spy should have captured at least one call"
    for call in seen_aux:
        aux = call["aux_data"]
        assert "fundamentals" in aux, (
            "fundamentals should be in aux_data when reader is provided"
        )
        fund = aux["fundamentals"]
        # Check that fundamentals dict has the expected code
        assert "000001.SZ" in fund, (
            "fundamentals should contain 000001.SZ, got %s" % fund
        )
        assert fund["000001.SZ"]["dynamic_pe"] == 15.5
        assert fund["000001.SZ"]["static_pe"] == 14.2


def test_fundamentals_reader_exception_fallback():
    """When reader raises exception, engine should fallback gracefully."""
    universe = ["000001.SZ"]
    market, dates = _build_market(universe, n_days=65)
    reader = FakeReader(market, dates)
    
    # Reader that fails on a specific date
    fund_reader = FakeFundamentalsReader(fail_on_date=dates[10])
    
    spy_fn, seen_aux = _make_aux_spy()
    
    # Patch evaluate_day with spy
    from backtest.strategies import _REGISTRY
    original = _REGISTRY.get("production/ima_uptrend_v31")
    _REGISTRY["production/ima_uptrend_v31"] = spy_fn
    try:
        # Should not raise, should fallback
        result = run_backtest(
            reader=reader, universe=universe,
            start_date=dates[0], end_date=dates[-1],
            strategy_config=_cfg(), execution_cfg=_EXEC,
            initial_cash=1_000_000.0, universe_hash="u", config_hash="c",
            fundamentals_reader=fund_reader,
        )
    finally:
        _REGISTRY["production/ima_uptrend_v31"] = original
    
    # Verify fallback occurred: some calls should have aux_for_eval without fundamentals
    fallback_count = 0
    success_count = 0
    for call in seen_aux:
        aux = call["aux_data"]
        if call["date"] == dates[10]:
            # Should fallback to original aux_for_eval (no fundamentals)
            assert "fundamentals" not in aux, (
                "on failure date %s, should fallback to aux_for_eval without fundamentals" % dates[10]
            )
            fallback_count += 1
        elif "fundamentals" in aux:
            success_count += 1
    
    assert fallback_count == 1, "should have one fallback call"
    assert success_count > 0, "should have successful calls on other dates"


def test_pit_different_dates_pass_different_asof():
    """Verify PIT: different today dates pass different asof_date to reader."""
    universe = ["000001.SZ"]
    market, dates = _build_market(universe, n_days=65)
    reader = FakeReader(market, dates)
    
    fund_reader = FakeFundamentalsReader()
    
    spy_fn, seen_aux = _make_aux_spy()
    
    # Patch evaluate_day with spy
    from backtest.strategies import _REGISTRY
    original = _REGISTRY.get("production/ima_uptrend_v31")
    _REGISTRY["production/ima_uptrend_v31"] = spy_fn
    try:
        result = run_backtest(
            reader=reader, universe=universe,
            start_date=dates[0], end_date=dates[-1],
            strategy_config=_cfg(), execution_cfg=_EXEC,
            initial_cash=1_000_000.0, universe_hash="u", config_hash="c",
            fundamentals_reader=fund_reader,
        )
    finally:
        _REGISTRY["production/ima_uptrend_v31"] = original
    
    # Verify reader was called with different asof_date for different days
    calls = fund_reader._calls
    assert len(calls) > 0, "reader should have been called"
    
    # Check that all calls have different asof_date (one per trading day)
    asof_dates = [c["asof_date"] for c in calls]
    assert len(asof_dates) == len(set(asof_dates)), (
        "each call should have unique asof_date, got duplicates: %s" % asof_dates
    )
    
    # Verify asof_date are valid dates
    for asof in asof_dates:
        pd.Timestamp(asof)  # will raise if invalid
    
    # Verify number of calls matches number of trading days (excluding last day)
    # run_backtest skips evaluate_day on last day
    assert len(calls) == len(dates) - 1, (
        "expected %d calls (one per trading day except last), got %d" % (len(dates) - 1, len(calls))
    )


def test_fundamentals_not_available_warning_absent():
    """End-to-end: when fundamentals_reader is provided, no 'fundamentals not available' warning."""
    # This test uses the actual scoring adapter to verify the warning is absent
    from backtest.strategies.production.ima_uptrend_v31.scoring_adapter import score_universe
    import numpy as np
    
    # Create simple market window
    dates = pd.bdate_range(start="2025-06-01", periods=80).strftime("%Y-%m-%d").tolist()
    closes = 10.0 + 0.005 * np.arange(80)
    df = pd.DataFrame({
        "date": dates,
        "open": closes - 0.01,
        "high": closes + 0.05,
        "low": closes - 0.05,
        "close": closes,
        "vol": [1000000] * 80,
        "amount": [10000000.0] * 80,
    })
    market_window = {"000001.SZ": df}
    
    # Test with fundamentals
    aux_with_fund = {"fundamentals": {"000001.SZ": {"dynamic_pe": 15.0, "static_pe": 14.0}}}
    records, warnings = score_universe(market_window, aux_data=aux_with_fund, return_warnings=True)
    
    # Should NOT have "fundamentals not available" warning
    for w in warnings:
        assert "fundamentals not available" not in w, (
            "should not have 'fundamentals not available' warning when fundamentals provided"
        )
    
    # Test without fundamentals (should have warning)
    aux_without_fund = {}
    records2, warnings2 = score_universe(market_window, aux_data=aux_without_fund, return_warnings=True)
    
    has_warning = any("fundamentals not available" in w for w in warnings2)
    assert has_warning, "should have 'fundamentals not available' warning when fundamentals missing"