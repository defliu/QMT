# coding: utf-8
"""Tests for backtest.strategy_core.scoring_adapter.score_universe.

Contract: 03_interface_freeze.md section 6 diagnostics.scores schema.
"""
import numpy as np
import pandas as pd
import pytest

from backtest.strategy_core.scoring_adapter import score_universe


def _mw(code, n=80, base=10.0):
    """Build n rows of mock OHLCV with reader-style 'vol' column."""
    idx = pd.date_range("2025-08-01", periods=n)
    rng = np.random.default_rng(seed=hash(code) & 0xFFFF)
    closes = base + np.cumsum(rng.normal(0, 0.05, n))
    highs = closes + 0.1
    lows = closes - 0.1
    opens = closes + rng.normal(0, 0.02, n)
    return pd.DataFrame({
        "date":   idx.strftime("%Y-%m-%d"),
        "open":   opens,
        "high":   highs,
        "low":    lows,
        "close":  closes,
        "vol":    rng.integers(800_000, 1_200_000, n),
        "amount": closes * rng.integers(800_000, 1_200_000, n),
    })


def test_score_universe_returns_records():
    mw = {"000001.SZ": _mw("000001.SZ"), "600519.SH": _mw("600519.SH")}
    out = score_universe(mw, sector_heat_mode="zero")
    assert isinstance(out, list)
    assert len(out) == 2
    expected_keys = {"code", "score_total", "score_breakout", "score_trend",
                     "score_consolidation", "score_volumeprice", "score_macd",
                     "score_valuation", "score_sentiment", "score_sector",
                     "bias5", "signal"}
    for rec in out:
        assert set(rec.keys()) == expected_keys
        assert rec["code"] in {"000001.SZ", "600519.SH"}


def test_zero_mode_score_sector_is_zero():
    mw = {"000001.SZ": _mw("000001.SZ")}
    out = score_universe(mw, sector_heat_mode="zero")
    assert out[0]["score_sector"] == 0.0


def test_zero_mode_total_excludes_sector():
    mw = {"000001.SZ": _mw("000001.SZ")}
    out = score_universe(mw, sector_heat_mode="zero")
    rec = out[0]
    expected_total = (rec["score_breakout"] + rec["score_trend"]
                      + rec["score_consolidation"] + rec["score_volumeprice"]
                      + rec["score_macd"] + rec["score_valuation"]
                      + rec["score_sentiment"] + rec["score_sector"])
    assert abs(rec["score_total"] - expected_total) < 1e-6


def test_non_zero_sector_mode_raises():
    with pytest.raises(NotImplementedError):
        score_universe({}, sector_heat_mode="static")


def test_insufficient_data_warns_and_skips():
    short_df = _mw("X", n=30)  # < 60 rows
    mw = {"000001.SZ": short_df, "600519.SH": _mw("600519.SH", n=80)}
    out, warns = score_universe(mw, sector_heat_mode="zero", return_warnings=True)
    assert len(out) == 1
    assert out[0]["code"] == "600519.SH"
    assert any("insufficient" in w.lower() for w in warns)


def test_fundamentals_missing_warning():
    mw = {"000001.SZ": _mw("000001.SZ")}
    out, warns = score_universe(mw, sector_heat_mode="zero", aux_data={}, return_warnings=True)
    assert any("fundamental" in w.lower() or "valuation" in w.lower() for w in warns)


def test_signal_default_hold_at_task22():
    """Task 2.2 emits signal='hold'; Task 2.3 decision layer rewrites it."""
    mw = {"000001.SZ": _mw("000001.SZ")}
    out = score_universe(mw, sector_heat_mode="zero")
    assert out[0]["signal"] == "hold"


def test_empty_market_window():
    out = score_universe({}, sector_heat_mode="zero")
    assert out == []


def test_none_market_window():
    """Passing None must not crash."""
    out = score_universe(None, sector_heat_mode="zero")
    assert out == []


def test_reader_compatible_vol_column():
    """Reader emits 'vol' column; adapter must accept it."""
    mw = {"000001.SZ": _mw("000001.SZ")}
    out = score_universe(mw, sector_heat_mode="zero")
    assert len(out) == 1


def test_volume_column_also_works():
    """Direct 'volume' column (forward-compat) must also work."""
    mw = {"000001.SZ": _mw("000001.SZ").rename(columns={"vol": "volume"})}
    out = score_universe(mw, sector_heat_mode="zero")
    assert len(out) == 1
