# coding: utf-8
"""Tests for backtest.scripts.run_batch (Task 5.2)."""
import csv
import os

import pytest
import yaml

from backtest import paths
from backtest.scripts import run_batch


def test_set_dotted_creates_nested():
    d = {}
    run_batch._set_dotted(d, "a.b.c", 5)
    assert d == {"a": {"b": {"c": 5}}}


def test_set_dotted_overwrites_leaf():
    d = {"strategy": {"max_positions": 5}}
    run_batch._set_dotted(d, "strategy.max_positions", 3)
    assert d["strategy"]["max_positions"] == 3


def test_expand_grid_cartesian_product(tmp_path):
    base = tmp_path / "base.yaml"
    base.write_text(
        "backtest:\n  name: base\nstrategy_params:\n  max_positions: 5\n  min_score: 60\n",
        encoding="utf-8")
    exp_cfg = {
        "batch": {"id": "g", "base": str(base)},
        "grid": {
            "strategy_params.max_positions": [3, 5],
            "strategy_params.min_score":     [55, 60, 65],
        },
    }
    leaves = list(run_batch.expand_grid(exp_cfg))
    assert len(leaves) == 6
    # leaf_index increments
    assert [l[0] for l in leaves] == list(range(6))
    # every leaf has both keys applied
    for _, name, cfg in leaves:
        assert "max_positions=" in name and "min_score=" in name
        assert cfg["strategy_params"]["max_positions"] in (3, 5)
        assert cfg["strategy_params"]["min_score"] in (55, 60, 65)


def test_expand_grid_empty_grid_yields_one(tmp_path):
    base = tmp_path / "base.yaml"
    base.write_text("backtest:\n  name: only\n", encoding="utf-8")
    exp_cfg = {"batch": {"id": "g", "base": str(base)}, "grid": {}}
    leaves = list(run_batch.expand_grid(exp_cfg))
    assert len(leaves) == 1


def test_write_batch_summary_columns(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "BATCH_DIR", str(tmp_path).replace("\\", "/"))
    rows = [
        {"batch_id": "b", "leaf_index": 0, "leaf_name": "x",
         "run_id": "r1", "results_dir": "/x", "start_date": "2025-09-01",
         "end_date": "2025-09-30", "trading_days": 21,
         "config_name": "c", "config_hash": "h",
         "total_return": 0.0, "annual_return": 0.0, "max_drawdown": 0.0,
         "sharpe": 0.0, "calmar": None, "win_rate": 0.0,
         "n_trades": 0, "n_buy": 0, "n_sell": 0,
         "is_short_sample": True, "benchmark_available": False,
         "sector_heat_mode": "zero", "data_dedup_count": 0,
         "data_wal_detected": False},
    ]
    target = run_batch._write_batch_summary("b", "20260614_010101", rows)
    assert os.path.isfile(target)
    with open(target, "r", encoding="utf-8-sig", newline="") as f:
        out = list(csv.reader(f))
    assert out[0] == run_batch._BATCH_COLS
    assert len(out) == 2  # header + one row


def test_run_batch_e2e_two_leaves(sample_db_path, tmp_path, monkeypatch):
    """End-to-end: one base config + 2-element grid -> 2 runs + 1 summary csv."""
    if not os.path.isfile(sample_db_path):
        pytest.skip("sample_db unavailable")

    # Redirect F:/ targets into tmp.
    results = tmp_path / "results"; results.mkdir()
    batch = tmp_path / "batch"; batch.mkdir()
    monkeypatch.setattr(paths, "RESULTS_DIR", str(results).replace("\\", "/"))
    monkeypatch.setattr(paths, "BATCH_DIR", str(batch).replace("\\", "/"))

    universe_csv = os.path.join(paths.BACKTEST_ROOT, "data", "universe",
                                "strategy_pool_base.csv").replace("\\", "/")

    base_yaml = tmp_path / "base.yaml"
    base_yaml.write_text(
        "backtest:\n"
        "  name: e2e\n"
        "  start_date: '2025-09-01'\n"
        "  end_date: '2025-09-30'\n"
        "  initial_cash: 1000000.0\n"
        "  benchmark_code: null\n"
        "data:\n"
        "  source: jince_zhisuan\n"
        "  path: '" + sample_db_path.replace("\\", "/") + "'\n"
        "  adjustment: hfq\n"
        "universe:\n"
        "  csv: '" + universe_csv + "'\n"
        "execution:\n"
        "  price: next_open\n"
        "  slippage: 0.001\n"
        "  commission_rate: 0.00025\n"
        "  tax_rate: 0.0001\n"
        "strategy_params:\n"
        "  max_positions: 5\n"
        "  rebalance_policy: daily\n"
        "  min_score: 60.0\n"
        "  min_core: 32.0\n"
        "  max_bias5: 10.0\n"
        "  max_daily_pct: 9.0\n"
        "  sector_heat_mode: zero\n"
        "  score_gap_threshold: 15.0\n"
        "  early_stop_days: 3\n"
        "  early_stop_loss: -0.05\n"
        "  stop_loss: -0.08\n"
        "  warning_score_threshold: 50.0\n"
        "  early_stop_holding_days: 5\n"
        "  early_stop_min_return: 0.03\n",
        encoding="utf-8")

    exp_yaml = tmp_path / "exp.yaml"
    exp_yaml.write_text(
        "batch:\n  id: e2e_test\n  base: '" + str(base_yaml).replace("\\", "/") + "'\n"
        "grid:\n  strategy_params.max_positions: [3, 5]\n",
        encoding="utf-8")

    rc = run_batch.main(["--experiment", str(exp_yaml)])
    assert rc == 0

    # Two leaf result dirs exist.
    leaf_dirs = sorted(os.listdir(results))
    assert len(leaf_dirs) == 2
    # Each contains the 6 standard files.
    for ld in leaf_dirs:
        files = sorted(os.listdir(results / ld))
        assert files == ["equity_curve.csv", "logs.txt", "positions.csv",
                         "report.md", "summary.json", "trades.csv"]

    # Batch summary written.
    csvs = [f for f in os.listdir(batch) if f.endswith(".csv")]
    assert len(csvs) == 1
    with open(batch / csvs[0], "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == run_batch._BATCH_COLS
    assert len(rows) == 1 + 2  # header + 2 leaves
    # leaf_name column reflects the grid value.
    leaf_names = [r[2] for r in rows[1:]]
    assert any("max_positions=3" in n for n in leaf_names)
    assert any("max_positions=5" in n for n in leaf_names)
