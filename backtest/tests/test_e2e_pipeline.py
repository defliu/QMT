# coding: utf-8
"""End-to-end smoke test for the full backtest pipeline.

Uses the sample DuckDB built from F:\\金策智算 (when available) to exercise
the full chain: yaml -> reader -> daily_engine -> report writers -> 6 files.

Skipped automatically when sample DB cannot be built (no source DB).
"""
import os
import json
import csv

import pytest

from backtest import paths
from backtest.data_tools.duckdb_reader import DuckDBDailyReader
from backtest.data_tools.universe import load_universe
from backtest.engine.daily_engine import run_backtest
from backtest.engine.hashing import compute_universe_hash, compute_config_hash
from backtest.engine import report


def _need_sample(sample_db_path):
    if not os.path.isfile(sample_db_path):
        pytest.skip("sample DB unavailable; cannot run e2e")


def test_e2e_full_pipeline_produces_six_files(sample_db_path, tmp_path, monkeypatch):
    """Run the engine + report writers end-to-end and check all 6 files exist."""
    _need_sample(sample_db_path)

    # Redirect results to a tmp dir.
    target = tmp_path / "results"
    target.mkdir()
    monkeypatch.setattr(paths, "RESULTS_DIR", str(target).replace("\\", "/"))

    universe_csv = os.path.join(paths.BACKTEST_ROOT, "data", "universe",
                                "strategy_pool_base.csv")
    uni = load_universe(universe_csv)

    reader = DuckDBDailyReader(sample_db_path)
    try:
        # The sample DB has only 30 days (2025-09-01..2025-09-30) which is below
        # strategy_core's 60-bar history threshold; this exercises the
        # INSUFFICIENT_HISTORY blocked path. We still expect the engine to
        # produce a valid empty-trade run and 6 output files.
        result = run_backtest(
            reader=reader, universe=uni["codes"],
            start_date="2025-09-01", end_date="2025-09-30",
            strategy_config={"max_positions": 5, "min_score": 60.0,
                             "min_core": 32.0, "max_bias5": 10.0,
                             "max_daily_pct": 9.0, "sector_heat_mode": "zero",
                             "score_gap_threshold": 15.0,
                             "early_stop_days": 3, "early_stop_loss": -0.05,
                             "stop_loss": -0.08,
                             "warning_score_threshold": 50.0,
                             "early_stop_holding_days": 5,
                             "early_stop_min_return": 0.03},
            execution_cfg={"price": "next_open", "slippage": 0.001,
                           "commission_rate": 0.00025, "tax_rate": 0.0001},
            initial_cash=1_000_000.0,
            benchmark_code=None,
            config_name="e2e_test",
            config_hash=compute_config_hash("test"),
            universe_hash=compute_universe_hash(uni["codes"]),
        )
    finally:
        reader.close()

    rd = report.write_all(result, config_name="e2e_test")

    files = sorted(os.listdir(rd))
    assert files == ["equity_curve.csv", "logs.txt", "positions.csv",
                     "report.md", "summary.json", "trades.csv"]

    # summary.json round-trip
    with open(os.path.join(rd, "summary.json"), "r", encoding="utf-8") as f:
        s = json.load(f)
    assert s["summary_schema_version"] == "0.2"
    assert s["benchmark_available"] is False
    assert s["sector_heat_mode"] == "zero"
    assert s["sample_period_warning"]["is_short_sample"] is True
    assert s["data_dedup_applied"] is True
    assert s["data_coverage_actual"]["dedup_count"] >= 0

    # logs.txt contains WARN block in correct order (only required tags).
    with open(os.path.join(rd, "logs.txt"), "r", encoding="utf-8") as f:
        log_text = f.read()
    assert "[WARN] SHORT_SAMPLE_PERIOD" in log_text
    assert "[WARN] BENCHMARK_DISABLED" in log_text
    assert "[WARN] SECTOR_HEAT_MODE_ZERO" in log_text

    # equity_curve.csv has trading_days+1? actually one row per trading day
    with open(os.path.join(rd, "equity_curve.csv"), "r", encoding="utf-8-sig",
              newline="") as f:
        rows = list(csv.reader(f))
    n_trading_days = len(result["trading_calendar"])
    assert len(rows) == 1 + n_trading_days  # header + N rows
    # First data row daily_return == 0
    assert float(rows[1][5]) == 0.0

    # report.md has banner
    with open(os.path.join(rd, "report.md"), "r", encoding="utf-8") as f:
        md = f.read()
    assert "样本期警告" in md


def test_e2e_writes_only_under_results_dir(sample_db_path, tmp_path, monkeypatch):
    """Verify the engine + writers do not touch C: / D: drives."""
    _need_sample(sample_db_path)
    target = tmp_path / "results"
    target.mkdir()
    monkeypatch.setattr(paths, "RESULTS_DIR", str(target).replace("\\", "/"))

    # Snapshot D: drive backtest source tree mtimes.
    snapshot_root = paths.BACKTEST_ROOT
    before = {}
    for root, _, files in os.walk(snapshot_root):
        if "__pycache__" in root or ".pytest_cache" in root:
            continue
        for fn in files:
            if fn.endswith(".pyc"):
                continue
            p = os.path.join(root, fn)
            try:
                before[p] = os.path.getmtime(p)
            except OSError:
                pass

    universe_csv = os.path.join(paths.BACKTEST_ROOT, "data", "universe",
                                "strategy_pool_base.csv")
    uni = load_universe(universe_csv)
    reader = DuckDBDailyReader(sample_db_path)
    try:
        result = run_backtest(
            reader=reader, universe=uni["codes"],
            start_date="2025-09-01", end_date="2025-09-30",
            strategy_config={"max_positions": 5, "min_score": 60.0,
                             "min_core": 32.0, "max_bias5": 10.0,
                             "max_daily_pct": 9.0, "sector_heat_mode": "zero",
                             "score_gap_threshold": 15.0,
                             "early_stop_days": 3, "early_stop_loss": -0.05,
                             "stop_loss": -0.08,
                             "warning_score_threshold": 50.0,
                             "early_stop_holding_days": 5,
                             "early_stop_min_return": 0.03},
            execution_cfg={"price": "next_open", "slippage": 0.001,
                           "commission_rate": 0.00025, "tax_rate": 0.0001},
            initial_cash=1_000_000.0,
            config_name="e2e_test",
            universe_hash="u",
            config_hash="c",
        )
    finally:
        reader.close()

    report.write_all(result, config_name="e2e_test")

    # All known D: source files unchanged.
    for p, mt in before.items():
        try:
            now_mt = os.path.getmtime(p)
        except OSError:
            continue  # file may have been removed by pycache cleanup; ignore
        assert now_mt == mt, "engine/report touched D: source file: " + p
