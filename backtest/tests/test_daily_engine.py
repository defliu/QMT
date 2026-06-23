# coding: utf-8
"""Integration tests for daily_engine.run_backtest.

Uses a FakeReader (in-memory pandas frames) to exercise the full pipeline
without requiring the E:\\金策智算 DuckDB. A separate test exercises the
real sample DB (which has only 30 days, so strategy_core blocks all
candidates due to insufficient_history -- good for verifying empty-trade
plumbing).
"""
import os
import numpy as np
import pandas as pd
import pytest

from backtest.engine.daily_engine import run_backtest


class FakeReader(object):
    """In-memory reader compatible with engine's call surface."""

    def __init__(self, market, calendar, db_path="fake.duckdb",
                 db_mtime="2026-06-14T00:00:00", wal=False):
        self.market = market               # {code: DataFrame}
        self.calendar = calendar           # list of YYYY-MM-DD strings
        self.db_path = db_path
        self._db_mtime = db_mtime
        self.wal_detected = wal
        self.wal_warning_message = ""

    def coverage(self, codes=None, start_date=None, end_date=None):
        cov = {
            "min_date":           self.calendar[0],
            "max_date":           self.calendar[-1],
            "n_codes":            len(self.market),
            "n_rows_after_dedup": sum(len(df) for df in self.market.values()),
            "dedup_count":        0,
            "db_mtime":           self._db_mtime,
        }
        if codes is not None:
            present = [c for c in codes if c in self.market]
            missing = [c for c in codes if c not in self.market]
            cov["universe_coverage"] = {
                "universe_size":   len(codes),
                "codes_with_data": len(present),
                "codes_missing":   missing,
                "missing_count":   len(missing),
            }
        return cov

    def trading_calendar(self, start_date, end_date):
        return [d for d in self.calendar if start_date <= d <= end_date]

    def load_window(self, codes, start_date, end_date):
        out = {}
        for code in codes:
            if code not in self.market:
                continue
            df = self.market[code]
            sub = df[(df["date"].astype(str) >= start_date)
                     & (df["date"].astype(str) <= end_date)]
            if len(sub) > 0:
                out[code] = sub.reset_index(drop=True)
        return out


def _build_market(codes, start="2025-06-01", n_days=80, base=10.0, ramp=0.005):
    """Generate synthetic market data with a gentle uptrend.

    n_days >= 60 so strategy_core's insufficient_history filter doesn't blow.
    """
    dates = pd.bdate_range(start=start, periods=n_days).strftime("%Y-%m-%d").tolist()
    market = {}
    rng = np.random.default_rng(seed=42)
    for j, code in enumerate(codes):
        closes = base + np.arange(n_days) * ramp + rng.normal(0, 0.05, n_days)
        opens = closes - rng.normal(0, 0.02, n_days)
        market[code] = pd.DataFrame({
            "date":   dates,
            "open":   opens,
            "high":   np.maximum(opens, closes) + 0.05,
            "low":    np.minimum(opens, closes) - 0.05,
            "close":  closes,
            "vol":    rng.integers(800_000, 1_200_000, n_days),
            "amount": closes * rng.integers(800_000, 1_200_000, n_days),
        })
    return market, dates


_EXEC = {"price": "next_open", "slippage": 0.001,
         "commission_rate": 0.00025, "tax_rate": 0.0001}


def _cfg():
    return {
        "max_positions": 5, "rebalance_policy": "daily",
        "min_score": 0.0, "min_core": 0.0, "max_bias5": 100.0,
        "max_daily_pct": 9.0, "sector_heat_mode": "zero",
        "score_gap_threshold": 15.0,
        "early_stop_days": 3, "early_stop_loss": -0.05,
        "stop_loss": -0.08, "warning_score_threshold": 50.0,
        "early_stop_holding_days": 5, "early_stop_min_return": 0.03,
    }


# ---------- shape / plumbing ----------
def test_run_backtest_returns_full_result_struct():
    universe = ["000001.SZ", "000002.SZ", "000003.SZ"]
    market, dates = _build_market(universe, n_days=80)
    reader = FakeReader(market, dates)
    result = run_backtest(
        reader=reader, universe=universe,
        start_date=dates[0], end_date=dates[-1],
        strategy_config=_cfg(), execution_cfg=_EXEC,
        initial_cash=1_000_000.0, config_name="test",
        universe_hash="ufake", config_hash="cfake",
    )
    assert set(result.keys()) == {
        "summary", "trades", "equity_rows", "positions_rows",
        "logs", "trading_calendar"}
    assert len(result["equity_rows"]) == len(dates)


def test_summary_has_all_top_level_keys_per_04_section_1():
    universe = ["000001.SZ", "000002.SZ"]
    market, dates = _build_market(universe, n_days=70)
    reader = FakeReader(market, dates)
    result = run_backtest(
        reader=reader, universe=universe,
        start_date=dates[0], end_date=dates[-1],
        strategy_config=_cfg(), execution_cfg=_EXEC,
        initial_cash=1_000_000.0, universe_hash="u", config_hash="c",
    )
    s = result["summary"]
    expected_top = {
        "summary_schema_version", "run_id", "run_started_at", "runtime_seconds",
        "config_name", "results_dir", "strategy_core_version",
        "config_hash", "data_hash", "universe_hash",
        "data_source", "data_path", "data_mtime", "data_adjustment",
        "data_coverage_actual", "data_dedup_applied",
        "data_concurrent_sync_warning", "data_wal_detected",
        "data_wal_warning_message",
        "benchmark_code", "benchmark_available", "benchmark_note",
        "sector_heat_available", "sector_heat_mode", "sector_heat_warning",
        "sample_period_warning", "execution", "performance",
        "portfolio_end", "diagnostics_aggregate",
    }
    missing = expected_top - set(s.keys())
    assert not missing, "summary missing keys: %s" % missing


def test_trades_rows_match_04_section_2_columns():
    universe = ["000001.SZ", "000002.SZ", "000003.SZ"]
    market, dates = _build_market(universe, n_days=70)
    reader = FakeReader(market, dates)
    result = run_backtest(
        reader=reader, universe=universe,
        start_date=dates[0], end_date=dates[-1],
        strategy_config=_cfg(), execution_cfg=_EXEC,
        initial_cash=1_000_000.0, universe_hash="u", config_hash="c",
    )
    if not result["trades"]:
        pytest.skip("synthetic data did not pass scorer; trade plumbing tested elsewhere")
    expected_cols = {"run_id", "date", "code", "side", "volume", "price",
                     "amount", "slippage_amt", "commission", "tax",
                     "reason", "layer", "model"}
    for t in result["trades"]:
        assert set(t.keys()) == expected_cols
        assert t["model"] == "next_open"


def test_equity_rows_match_04_section_3():
    universe = ["000001.SZ"]
    market, dates = _build_market(universe, n_days=65)
    reader = FakeReader(market, dates)
    result = run_backtest(
        reader=reader, universe=universe,
        start_date=dates[0], end_date=dates[-1],
        strategy_config=_cfg(), execution_cfg=_EXEC,
        initial_cash=1_000_000.0, universe_hash="u", config_hash="c",
    )
    expected_cols = {"run_id", "date", "total_asset", "cash", "market_value",
                     "daily_return", "benchmark_close", "benchmark_return"}
    for r in result["equity_rows"]:
        assert set(r.keys()) == expected_cols
    assert result["equity_rows"][0]["daily_return"] == 0.0


def test_short_sample_warning_triggers_when_under_252_days():
    universe = ["000001.SZ"]
    market, dates = _build_market(universe, n_days=65)
    reader = FakeReader(market, dates)
    result = run_backtest(
        reader=reader, universe=universe,
        start_date=dates[0], end_date=dates[-1],
        strategy_config=_cfg(), execution_cfg=_EXEC,
        initial_cash=1_000_000.0, universe_hash="u", config_hash="c",
    )
    spw = result["summary"]["sample_period_warning"]
    assert spw["is_short_sample"] is True
    assert spw["trading_days"] == len(dates)
    assert "MVP" in spw["warning"]


def test_benchmark_disabled_path():
    universe = ["000001.SZ"]
    market, dates = _build_market(universe, n_days=65)
    reader = FakeReader(market, dates)
    result = run_backtest(
        reader=reader, universe=universe,
        start_date=dates[0], end_date=dates[-1],
        strategy_config=_cfg(), execution_cfg=_EXEC,
        initial_cash=1_000_000.0, benchmark_code=None,
        universe_hash="u", config_hash="c",
    )
    s = result["summary"]
    assert s["benchmark_available"] is False
    assert s["benchmark_code"] is None
    assert s["performance"]["excess_return"] is None


def test_run_id_format():
    universe = ["000001.SZ"]
    market, dates = _build_market(universe, n_days=65)
    reader = FakeReader(market, dates)
    result = run_backtest(
        reader=reader, universe=universe,
        start_date=dates[0], end_date=dates[-1],
        strategy_config=_cfg(), execution_cfg=_EXEC,
        initial_cash=1_000_000.0, universe_hash="u", config_hash="c",
    )
    rid = result["summary"]["run_id"]
    # YYYYMMDD_HHMMSS_<6 hex>
    parts = rid.split("_")
    assert len(parts) == 3
    assert len(parts[0]) == 8 and parts[0].isdigit()
    assert len(parts[1]) == 6 and parts[1].isdigit()
    assert len(parts[2]) == 6


def test_diagnostics_aggregate_keys():
    universe = ["000001.SZ", "000002.SZ"]
    market, dates = _build_market(universe, n_days=65)
    reader = FakeReader(market, dates)
    result = run_backtest(
        reader=reader, universe=universe,
        start_date=dates[0], end_date=dates[-1],
        strategy_config=_cfg(), execution_cfg=_EXEC,
        initial_cash=1_000_000.0, universe_hash="u", config_hash="c",
    )
    da = result["summary"]["diagnostics_aggregate"]
    assert set(da.keys()) == {
        "warnings_unique",
        "candidate_total_avg_per_day", "candidate_passed_avg_per_day",
        "unfilled_order_count",
        "strategy_specific",
    }
    assert da["unfilled_order_count"] >= 0
    ss = da["strategy_specific"]
    assert set(ss.keys()) == {"ima_uptrend_v31"}
    assert set(ss["ima_uptrend_v31"].keys()) == {
        "filter_counts_avg_per_day", "trigger_counts_total",
    }


def test_no_io_writes_to_workspace(tmp_path, monkeypatch):
    """Engine must NOT touch the filesystem -- file IO is deferred to Phase 4."""
    universe = ["000001.SZ"]
    market, dates = _build_market(universe, n_days=65)
    reader = FakeReader(market, dates)

    # Sentinel: snapshot results dir mtime; engine must not modify it.
    from backtest import paths
    if os.path.isdir(paths.RESULTS_DIR):
        before = sorted(os.listdir(paths.RESULTS_DIR))
    else:
        before = None

    run_backtest(
        reader=reader, universe=universe,
        start_date=dates[0], end_date=dates[-1],
        strategy_config=_cfg(), execution_cfg=_EXEC,
        initial_cash=1_000_000.0, universe_hash="u", config_hash="c",
    )

    if before is not None:
        after = sorted(os.listdir(paths.RESULTS_DIR))
        assert before == after, "engine must not write to results dir in Phase 3"


def test_no_lookahead_window_leaks_future_dates():
    """Verify the window passed to evaluate_day never includes future dates.

    v0.4 起 daily_engine 通过 registry 取 evaluate_day（不再有顶级 eng.evaluate_day），
    所以 spy 直接挂在 strategies._REGISTRY 上拦截。
    """
    seen = []
    from backtest.strategies import _REGISTRY
    name = "production/ima_uptrend_v31"
    real = _REGISTRY[name]

    def spy(current_date, market_window, **kw):
        for code, df in (market_window or {}).items():
            max_date = df["date"].astype(str).max() if len(df) else ""
            seen.append((str(current_date), code, max_date))
        return real(current_date=current_date, market_window=market_window, **kw)

    _REGISTRY[name] = spy
    try:
        universe = ["000001.SZ"]
        market, dates = _build_market(universe, n_days=65)
        reader = FakeReader(market, dates)
        run_backtest(
            reader=reader, universe=universe,
            start_date=dates[0], end_date=dates[-1],
            strategy_config=_cfg(), execution_cfg=_EXEC,
            initial_cash=1_000_000.0, universe_hash="u", config_hash="c",
        )
    finally:
        _REGISTRY[name] = real

    for cur, code, max_d in seen:
        assert max_d <= cur, "window leaked future date %s on day %s for %s" % (max_d, cur, code)
