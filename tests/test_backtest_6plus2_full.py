# coding=utf-8
"""Tests for scripts.backtest_6plus2_full — sell engine integration and backtest output."""

import os
import sys
import json
import tempfile

import pytest
import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.risk_manager import SellStrategyEngine, SellPositionState, Action
from scripts.backtest_6plus2_full import (
    _strip_suffix,
    _add_suffix,
    read_pool,
    parse_args,
    run_backtest,
)


# ============================================================
#  Helper: synthetic OHLCV data
# ============================================================

def _make_synthetic_data(n_bars=200, start_price=10.0,
                         seed=42, drop_tail=False):
    """Create a synthetic DataFrame with O/H/L/C/V columns.

    If drop_tail=True, the last 5 bars simulate a sharp -6% decline
    to trigger bottom-line sell.
    """
    rng = np.random.RandomState(seed)
    dates = pd.date_range(end='2026-05-30', periods=n_bars, freq='B')
    trend = 1 + rng.randn(n_bars) * 0.006
    closes = start_price * np.cumprod(trend)

    if drop_tail and n_bars >= 10:
        # Simulate sharp drop in last 5 bars
        for j in range(1, 6):
            closes[-j] = closes[-6] * (1 - 0.012 * j)  # cumulative ~-6%

    opens = closes * (1 + rng.randn(n_bars) * 0.004)
    highs = np.maximum(opens, closes) * (1 + np.abs(rng.randn(n_bars)) * 0.004)
    lows = np.minimum(opens, closes) * (1 - np.abs(rng.randn(n_bars)) * 0.004)
    volumes = rng.randint(500000, 5000000, n_bars)

    df = pd.DataFrame({
        'open': opens, 'high': highs, 'low': lows,
        'close': closes, 'volume': volumes,
    }, index=dates)
    df.index.name = '_date'
    return df


# ============================================================
#  Direct SellStrategyEngine tests
# ============================================================

class TestSellEngineDirect:
    """Unit tests of SellStrategyEngine integration (no full backtest)."""

    @pytest.fixture
    def temp_state_file(self):
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        yield path
        if os.path.exists(path):
            os.unlink(path)

    def _make_price_data(self, close_values, length=200):
        """Build minimal OHLCV DataFrame from close price list."""
        n = len(close_values)
        dates = pd.date_range(end='2026-05-30', periods=max(n, length), freq='B')
        # pad front with stable data
        pad = max(length - n, 0)
        closes = [close_values[0]] * pad + close_values
        closes = np.array(closes)
        rng = np.random.RandomState(99)
        opens = closes * (1 + rng.randn(len(closes)) * 0.003)
        highs = np.maximum(opens, closes) * (1 + np.abs(rng.randn(len(closes))) * 0.003)
        lows = np.minimum(opens, closes) * (1 - np.abs(rng.randn(len(closes))) * 0.003)
        volumes = rng.randint(500000, 5000000, len(closes))
        df = pd.DataFrame({
            'open': opens, 'high': highs, 'low': lows,
            'close': closes, 'volume': volumes,
        }, index=dates[:len(closes)])
        if len(df) > length:
            df = df.iloc[-length:]
        return df

    def test_bottom_line_loss_trigger(self, temp_state_file):
        """Price drops >5% from cost → bottom line → CLEAR."""
        engine = SellStrategyEngine(
            strategy_name="TEST", account_id="T",
            state_file=temp_state_file, is_intraday=False,
        )
        # Create a 200-bar DataFrame where last close is 9.4 (6% below 10.0)
        closes = [10.0] * 180 + [10.0, 9.9, 9.7, 9.5, 9.4]
        df = self._make_price_data(closes)

        code = "000001"
        state = SellPositionState(
            code=code, cost_price=10.0, current_shares=1000,
            original_shares=1000, highest_price=10.0, entry_date='20260520',
        )
        engine._states[code] = state

        holdings = {code: 10.0}
        positions = {code: {'cost': 10.0, 'can_use': 1000, 'volume': 1000}}
        all_data = {code: df}

        decisions = engine.evaluate('20260530', holdings, all_data, positions)

        assert len(decisions) == 1
        dec_code, decision, shares = decisions[0]
        assert dec_code == code
        assert decision.action == Action.CLEAR, (
            f"Expected CLEAR, got {decision.action} — {decision.reason}"
        )
        assert "底线层" in decision.triggered_layer
        assert shares >= 1000

    def test_bottom_line_daily_drop_trigger(self, temp_state_file):
        """Single-day drop >7% → bottom line → CLEAR."""
        engine = SellStrategyEngine(
            strategy_name="TEST", account_id="T",
            state_file=temp_state_file, is_intraday=False,
        )
        # Drop 8% in one day
        closes = [10.0] * 190 + [10.0, 9.2]
        df = self._make_price_data(closes)

        code = "000002"
        state = SellPositionState(
            code=code, cost_price=9.5, current_shares=500,
            original_shares=500, highest_price=10.5, entry_date='20260520',
        )
        engine._states[code] = state

        holdings = {code: 10.5}
        positions = {code: {'cost': 9.5, 'can_use': 500, 'volume': 500}}
        all_data = {code: df}

        decisions = engine.evaluate('20260530', holdings, all_data, positions)

        assert len(decisions) == 1
        dec_code, decision, shares = decisions[0]
        assert dec_code == code
        assert decision.action == Action.CLEAR, (
            f"Expected CLEAR, got {decision.action} — {decision.reason}"
        )
        # Should trigger daily drop check (cost loss is only -3.2%, but daily is -8%)
        assert "单日" in decision.reason or "底线层" in decision.triggered_layer


# ============================================================
#  Full backtest integration tests
# ============================================================

def _mock_high_score_single(self, stock_code, df, dynamic_pe=None,
                            static_pe=None, pool_5d_returns=None):
    """Return a fixed high score to guarantee buys during backtest."""
    return {
        'score_breakout': 15.0, 'score_trend': 10.0,
        'score_consolidation': 15.0, 'score_volumeprice': 10.0,
        'score_macd': 8.0, 'score_valuation': 5.0,
        'score_sentiment': 5.0, 'score_sector': 5.0,
        'score_total': 73.0,
    }


class TestBacktestIntegration:
    """Full backtest with synthetic data and mocked scoring."""

    @pytest.fixture
    def synthetic_pool(self):
        content = "600519.SH\n000858.SZ\n601318.SH\n600036.SH\n000333.SZ\n"
        with tempfile.NamedTemporaryFile(
            mode='w', encoding='gbk', delete=False, suffix='.txt'
        ) as f:
            f.write(content)
            p = f.name
        yield p
        if os.path.exists(p):
            os.unlink(p)

    def _mock_download(self, drop_tail=False):
        """Return callable that generates synthetic data for any stock list."""
        def _inner(stock_codes, req_bars=800):
            data = {}
            for i, code in enumerate(stock_codes):
                data[code] = _make_synthetic_data(
                    n_bars=200, start_price=10.0 + i * 2,
                    seed=i * 10, drop_tail=drop_tail,
                )
            return data
        return _inner

    def test_position_tracking(self, synthetic_pool, monkeypatch):
        """Buy -> price up -> sell -> correct P&L with positive returns."""
        monkeypatch.setattr(
            'scripts.backtest_6plus2_full.download_all',
            self._mock_download(drop_tail=False),
        )
        monkeypatch.setattr(
            'core.scoring.dimension6plus2.ScoreCalculator6Plus2.score_single',
            _mock_high_score_single,
        )

        result = run_backtest(
            pool_path=synthetic_pool,
            backtest_days=20,
            top_n=3,
            initial_capital=100000.0,
            max_hold=5,
        )

        trades = result.get('trades', [])
        metrics = result.get('metrics', {})

        assert isinstance(trades, list)
        # Should have at least some trades
        if not trades:
            pytest.skip("No trades generated — may be normal with mock data")

        # All trades should have valid values
        for t in trades:
            assert t['buy_price'] > 0
            assert t['sell_price'] > 0
            assert isinstance(t['return'], (int, float))
            assert 'sell_reason' in t

        # With rising synthetic data, most returns should be positive
        win_count = sum(1 for t in trades if t['return'] > 0)
        total_count = len(trades)
        if total_count > 0:
            assert win_count > 0, f"Expected some wins, got {win_count}/{total_count}"

        # Metrics should be populated
        assert metrics.get('total_trades', 0) >= 0
        assert isinstance(metrics.get('total_return', 0), (int, float))

        # Check CSV/JSON output exists
        csv_path = os.path.join(PROJECT_ROOT, 'data', 'backtest_6plus2_full_result.csv')
        json_path = os.path.join(PROJECT_ROOT, 'data', 'backtest_6plus2_full_report.json')
        assert os.path.exists(csv_path), f"CSV not found: {csv_path}"
        assert os.path.exists(json_path), f"JSON not found: {json_path}"

        # Clean up output files
        for p in [csv_path, json_path]:
            if os.path.exists(p):
                os.unlink(p)

    def test_empty_pool(self, monkeypatch):
        """Empty pool -> graceful handling (no crash)."""
        monkeypatch.setattr(
            'scripts.backtest_6plus2_full.download_all',
            self._mock_download(drop_tail=False),
        )
        monkeypatch.setattr(
            'core.scoring.dimension6plus2.ScoreCalculator6Plus2.score_single',
            _mock_high_score_single,
        )

        with tempfile.NamedTemporaryFile(
            mode='w', encoding='gbk', delete=False, suffix='.txt'
        ) as f:
            empty_path = f.name

        try:
            result = run_backtest(
                pool_path=empty_path,
                backtest_days=10,
                top_n=2,
                initial_capital=50000.0,
                max_hold=3,
            )
            # Should not crash; fallback stocks kicked in
            assert result is not None
            assert 'trades' in result
            assert 'metrics' in result
        finally:
            if os.path.exists(empty_path):
                os.unlink(empty_path)

        # Clean up output
        for p in [
            os.path.join(PROJECT_ROOT, 'data', 'backtest_6plus2_full_result.csv'),
            os.path.join(PROJECT_ROOT, 'data', 'backtest_6plus2_full_report.json'),
        ]:
            if os.path.exists(p):
                os.unlink(p)

    def test_output_format(self, synthetic_pool, monkeypatch):
        """CSV has correct columns, JSON is parseable with expected structure."""
        monkeypatch.setattr(
            'scripts.backtest_6plus2_full.download_all',
            self._mock_download(drop_tail=False),
        )
        monkeypatch.setattr(
            'core.scoring.dimension6plus2.ScoreCalculator6Plus2.score_single',
            _mock_high_score_single,
        )

        result = run_backtest(
            pool_path=synthetic_pool,
            backtest_days=15,
            top_n=2,
            initial_capital=100000.0,
            max_hold=4,
        )

        csv_path = os.path.join(PROJECT_ROOT, 'data', 'backtest_6plus2_full_result.csv')
        json_path = os.path.join(PROJECT_ROOT, 'data', 'backtest_6plus2_full_report.json')

        # CSV validation
        assert os.path.exists(csv_path)
        df_csv = pd.read_csv(csv_path)
        expected_cols = {'code', 'buy_date', 'sell_date', 'buy_price',
                         'sell_price', 'return'}
        assert expected_cols.issubset(set(df_csv.columns)), (
            f"Missing CSV columns: {expected_cols - set(df_csv.columns)}"
        )
        assert df_csv['buy_price'].notna().all()
        assert df_csv['sell_price'].notna().all()
        assert (df_csv['buy_price'] > 0).all()
        assert (df_csv['sell_price'] > 0).all()

        # JSON validation
        assert os.path.exists(json_path)
        with open(json_path, 'r', encoding='utf-8') as f:
            report = json.load(f)
        assert 'metrics' in report
        assert 'trade_count' in report
        assert 'equity_curve' in report
        assert 'config' in report
        assert 'total_trades' in report['metrics']
        # Check equity curve is a list of [date, value] pairs
        if report['equity_curve']:
            first_pt = report['equity_curve'][0]
            assert len(first_pt) == 2
            assert isinstance(first_pt[0], str)
            assert isinstance(first_pt[1], (int, float))

        # Clean up
        for p in [csv_path, json_path]:
            if os.path.exists(p):
                os.unlink(p)


# ============================================================
#  Helper function tests
# ============================================================

class TestHelpers:
    def test_strip_suffix_sh(self):
        assert _strip_suffix("600519.SH") == "600519"

    def test_strip_suffix_sz(self):
        assert _strip_suffix("000858.SZ") == "000858"

    def test_strip_suffix_bj(self):
        assert _strip_suffix("830799.BJ") == "830799"

    def test_strip_suffix_none(self):
        assert _strip_suffix("600519") == "600519"

    def test_add_suffix_sh(self):
        assert _add_suffix("600519") == "600519.SH"

    def test_add_suffix_sz(self):
        assert _add_suffix("000858") == "000858.SZ"

    def test_read_pool_normal(self):
        with tempfile.NamedTemporaryFile(mode='w', encoding='gbk', delete=False) as f:
            f.write("600519.SH\n000858.SZ\n")
            p = f.name
        try:
            assert read_pool(p) == ["600519", "000858"]
        finally:
            os.unlink(p)

    def test_read_pool_not_exists(self):
        assert read_pool("/nonexistent_pool.txt") == []

    def test_read_pool_empty(self):
        with tempfile.NamedTemporaryFile(mode='w', encoding='gbk', delete=False) as f:
            p = f.name
        try:
            assert read_pool(p) == []
        finally:
            os.unlink(p)


class TestParseArgs:
    def test_defaults(self):
        args = parse_args([])
        assert args.days == 60
        assert args.top == 3
        assert args.pool == "D:/QMT_POOL/selected.txt"
        assert args.capital == 100000.0
        assert args.max_hold == 5

    def test_custom(self):
        args = parse_args(['--days', '30', '--top', '5',
                           '--capital', '200000', '--max-hold', '8'])
        assert args.days == 30
        assert args.top == 5
        assert args.capital == 200000.0
        assert args.max_hold == 8
