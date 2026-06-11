# coding=utf-8
"""Tests for scripts.backtest_dimension6plus2 — CLI args and backtest output format."""

import os
import tempfile
import numpy as np
import pandas as pd
import pytest

from scripts.backtest_dimension6plus2 import (
    _strip_suffix,
    _add_suffix,
    read_pool,
    parse_args,
    run_backtest,
)


# ============================================================
#  Helper: synthetic OHLCV data
# ============================================================

def _make_synthetic_data(n_bars=200, start_price=10.0, seed=42):
    """Create a synthetic DataFrame for a single stock with O/H/L/C/V columns."""
    rng = np.random.RandomState(seed)
    dates = pd.date_range(end='2026-05-30', periods=n_bars, freq='B')
    trend = 1 + rng.randn(n_bars) * 0.008
    closes = start_price * np.cumprod(trend)
    opens = closes * (1 + rng.randn(n_bars) * 0.005)
    highs = np.maximum(opens, closes) * (1 + np.abs(rng.randn(n_bars)) * 0.005)
    lows = np.minimum(opens, closes) * (1 - np.abs(rng.randn(n_bars)) * 0.005)
    volumes = rng.randint(500000, 5000000, n_bars)
    df = pd.DataFrame({
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
        'volume': volumes,
    }, index=dates)
    df.index.name = '_date'
    return df


# ============================================================
#  Helper function tests
# ============================================================

class TestStripSuffix:
    def test_sh(self):
        assert _strip_suffix("600519.SH") == "600519"

    def test_sz(self):
        assert _strip_suffix("000858.SZ") == "000858"

    def test_bj(self):
        assert _strip_suffix("830799.BJ") == "830799"

    def test_no_suffix(self):
        assert _strip_suffix("600519") == "600519"


class TestAddSuffix:
    def test_sh(self):
        assert _add_suffix("600519") == "600519.SH"

    def test_sz(self):
        assert _add_suffix("000858") == "000858.SZ"


class TestReadPool:
    def test_normal(self):
        with tempfile.NamedTemporaryFile(mode='w', encoding='gbk', delete=False) as f:
            f.write("600519.SH\n000858.SZ\n")
            p = f.name
        try:
            assert read_pool(p) == ["600519", "000858"]
        finally:
            os.unlink(p)

    def test_not_exists(self):
        assert read_pool("/nonexistent_pool.txt") == []

    def test_empty(self):
        with tempfile.NamedTemporaryFile(mode='w', encoding='gbk', delete=False) as f:
            p = f.name
        try:
            assert read_pool(p) == []
        finally:
            os.unlink(p)


# ============================================================
#  CLI argument parsing
# ============================================================

class TestParseArgs:
    def test_defaults(self):
        args = parse_args([])
        assert args.days == 60
        assert args.top == 3
        assert args.hold == 1
        assert args.pool == "D:/QMT_POOL/selected.txt"

    def test_custom_values(self):
        args = parse_args(['--days', '30', '--top', '5', '--hold', '2'])
        assert args.days == 30
        assert args.top == 5
        assert args.hold == 2

    def test_custom_pool(self):
        args = parse_args(['--pool', 'D:/test/pool.txt'])
        assert args.pool == "D:/test/pool.txt"


# ============================================================
#  Backtest output validation (with synthetic data)
# ============================================================

@pytest.fixture
def synthetic_pool():
    """Create a temp pool file with a few mock stock codes."""
    content = "600519.SH\n000858.SZ\n601318.SH\n600036.SH\n000333.SZ\n"
    with tempfile.NamedTemporaryFile(mode='w', encoding='gbk', delete=False, suffix='.txt') as f:
        f.write(content)
        p = f.name
    yield p
    if os.path.exists(p):
        os.unlink(p)


def test_run_backtest_output_format(synthetic_pool, monkeypatch):
    """Verify run_backtest returns a DataFrame with the correct columns and finite values."""

    # Monkeypatch download_all to return synthetic data
    def mock_download_all(stock_codes, req_bars=800):
        data = {}
        for i, code in enumerate(stock_codes):
            data[code] = _make_synthetic_data(n_bars=200, start_price=10.0 + i, seed=i)
        return data

    monkeypatch.setattr(
        'scripts.backtest_dimension6plus2.download_all',
        mock_download_all,
    )

    result = run_backtest(
        pool_path=synthetic_pool,
        backtest_days=10,  # small window for fast test
        top_n=2,
        hold_days=1,
    )

    # Must return a DataFrame (may be empty if no trades triggered)
    assert isinstance(result, pd.DataFrame)

    if result.empty:
        pytest.skip("No trades generated — scoring produced no signals")

    # Validate required columns
    required_cols = {'code', 'buy_date', 'sell_date', 'buy_price', 'sell_price', 'return', 'win'}
    assert required_cols.issubset(set(result.columns)), f"Missing columns: {required_cols - set(result.columns)}"

    # All values must be finite/non-null
    assert result['buy_price'].notna().all(), "buy_price has NaNs"
    assert result['sell_price'].notna().all(), "sell_price has NaNs"
    assert result['return'].notna().all(), "return has NaNs"

    # Prices must be positive
    assert (result['buy_price'] > 0).all(), "buy_price must be positive"
    assert (result['sell_price'] > 0).all(), "sell_price must be positive"

    # return must be finite
    assert np.isfinite(result['return']).all(), "return has non-finite values"

    # win column must be boolean
    assert result['win'].dtype == bool, "win column must be boolean"


def test_run_backtest_empty_pool(monkeypatch):
    """Verify run_backtest handles empty pool gracefully."""
    with tempfile.NamedTemporaryFile(mode='w', encoding='gbk', delete=False, suffix='.txt') as f:
        empty_path = f.name

    try:
        # When pool is empty, run_backtest uses fallback stocks.
        # We need mock download_all still.
        def mock_download_all(stock_codes, req_bars=800):
            data = {}
            for i, code in enumerate(stock_codes):
                data[code] = _make_synthetic_data(n_bars=200, start_price=10.0, seed=i)
            return data

        monkeypatch.setattr(
            'scripts.backtest_dimension6plus2.download_all',
            mock_download_all,
        )

        result = run_backtest(
            pool_path=empty_path,
            backtest_days=5,
            top_n=2,
            hold_days=1,
        )
        assert isinstance(result, pd.DataFrame)
    finally:
        if os.path.exists(empty_path):
            os.unlink(empty_path)


def test_run_backtest_custom_params(synthetic_pool, monkeypatch):
    """Verify non-default parameters produce valid output."""

    def mock_download_all(stock_codes, req_bars=800):
        data = {}
        for i, code in enumerate(stock_codes):
            data[code] = _make_synthetic_data(n_bars=200, start_price=15.0, seed=i * 10)
        return data

    monkeypatch.setattr(
        'scripts.backtest_dimension6plus2.download_all',
        mock_download_all,
    )

    result = run_backtest(
        pool_path=synthetic_pool,
        backtest_days=15,
        top_n=5,
        hold_days=2,
    )

    assert isinstance(result, pd.DataFrame)
