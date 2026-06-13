# coding: utf-8
"""Batch runner for backtest factory v0.2 — Task 5.2.

Reads an experiment yaml of the form:

    batch:
      id:   baseline_grid
      base: backtest/configs/baseline.yaml
    grid:
      strategy.max_positions: [3, 5]
      strategy.min_score:      [55.0, 60.0]

Expands `grid` into the full cartesian product, applies each combination on top
of the base config, runs `run_backtest.main` per leaf, and aggregates a summary
CSV under F:/backtest_workspace/batch_summary/.

Usage:
    py -3.10 -m backtest.scripts.run_batch \\
        --experiment backtest/configs/experiments/baseline_grid.yaml

Boundaries (night-shift §四):
  * Reads yaml from D:\\QMT_STRATEGIES\\backtest\\configs\\.
  * Writes leaf yaml + leaf results under F:\\backtest_workspace\\.
  * Never writes C:/D:; never F:/金策智算/.
  * Does NOT import clean_results (硬约束 #6).
"""
import argparse
import csv
import datetime as _dt
import itertools
import json
import logging
import os
import sys

import yaml

from backtest import paths
from backtest.engine import report
from backtest.engine.hashing import compute_config_hash, compute_universe_hash
from backtest.data_tools.duckdb_reader import DuckDBDailyReader
from backtest.data_tools.universe import load_universe
from backtest.engine.daily_engine import run_backtest
from backtest.scripts import init_workspace

log = logging.getLogger("run_batch")

# Top-level columns of batch_summary CSV (kept narrow; deeper detail lives in
# each run's summary.json which the row points to via results_dir).
_BATCH_COLS = [
    "batch_id", "leaf_index", "leaf_name",
    "run_id", "results_dir",
    "start_date", "end_date", "trading_days",
    "config_name", "config_hash",
    "total_return", "annual_return", "max_drawdown", "sharpe", "calmar",
    "win_rate", "n_trades", "n_buy", "n_sell",
    "is_short_sample", "benchmark_available", "sector_heat_mode",
    "data_dedup_count", "data_wal_detected",
]


def _load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _resolve(rel):
    if os.path.isabs(rel):
        return rel
    return os.path.join(paths.BACKTEST_ROOT, "..", rel)


def _set_dotted(d, dotted_key, value):
    """Set nested dict value by 'a.b.c' path; create intermediate dicts as needed."""
    parts = dotted_key.split(".")
    cur = d
    for p in parts[:-1]:
        if p not in cur or not isinstance(cur[p], dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value


def _deep_copy(obj):
    return json.loads(json.dumps(obj))


def expand_grid(experiment_cfg):
    """Yield (leaf_index, leaf_name_suffix, leaf_cfg_dict) for each combination.

    leaf_name_suffix is a deterministic short slug, e.g. "max_positions=3__min_score=55.0".
    """
    base_path = experiment_cfg["batch"]["base"]
    base_cfg = _load_yaml(_resolve(base_path))
    grid = experiment_cfg.get("grid", {}) or {}
    if not grid:
        yield 0, "default", base_cfg
        return

    keys = sorted(grid.keys())
    value_lists = [grid[k] for k in keys]
    for idx, combo in enumerate(itertools.product(*value_lists)):
        leaf = _deep_copy(base_cfg)
        slug_parts = []
        for k, v in zip(keys, combo):
            _set_dotted(leaf, k, v)
            short_key = k.split(".")[-1]
            slug_parts.append(short_key + "=" + str(v))
        leaf_name = "__".join(slug_parts)
        yield idx, leaf_name, leaf


def _run_one_leaf(leaf_cfg, batch_id, leaf_index, leaf_name):
    """Run a single leaf (one full backtest). Returns the row dict for batch_summary CSV."""
    bt = leaf_cfg.get("backtest", {})
    data_cfg = leaf_cfg.get("data", {})
    universe_cfg = leaf_cfg.get("universe", {})
    exec_cfg = leaf_cfg.get("execution", {})
    strat_cfg = leaf_cfg.get("strategy", {})

    base_name = bt.get("name", "baseline")
    config_name = base_name + "__" + leaf_name
    raw_text = json.dumps(leaf_cfg, sort_keys=True, ensure_ascii=False)
    config_hash = compute_config_hash(raw_text)

    universe_csv = _resolve(universe_cfg.get("csv"))
    uni = load_universe(universe_csv)
    universe_hash = compute_universe_hash(uni["codes"])

    db_path = data_cfg.get("path", paths.JINCE_DB_PATH)
    reader = DuckDBDailyReader(db_path)
    try:
        result = run_backtest(
            reader=reader,
            universe=uni["codes"],
            start_date=bt["start_date"],
            end_date=bt["end_date"],
            strategy_config=strat_cfg,
            execution_cfg=exec_cfg,
            initial_cash=float(bt.get("initial_cash", 1_000_000.0)),
            aux_data=None,
            benchmark_code=bt.get("benchmark_code"),
            config_name=config_name,
            config_hash=config_hash,
            universe_hash=universe_hash,
        )
    finally:
        reader.close()

    rd = report.write_all(result, config_name=config_name)

    s = result["summary"]
    perf = s.get("performance", {})
    cov = s.get("data_coverage_actual", {})
    spw = s.get("sample_period_warning", {})

    row = {
        "batch_id":           batch_id,
        "leaf_index":         leaf_index,
        "leaf_name":          leaf_name,
        "run_id":             s.get("run_id", ""),
        "results_dir":        rd,
        "start_date":         bt.get("start_date", ""),
        "end_date":           bt.get("end_date", ""),
        "trading_days":       spw.get("trading_days", 0),
        "config_name":        config_name,
        "config_hash":        config_hash,
        "total_return":       perf.get("total_return"),
        "annual_return":      perf.get("annual_return"),
        "max_drawdown":       perf.get("max_drawdown"),
        "sharpe":             perf.get("sharpe"),
        "calmar":             perf.get("calmar"),
        "win_rate":           perf.get("win_rate"),
        "n_trades":           perf.get("n_trades", 0),
        "n_buy":              perf.get("n_buy", 0),
        "n_sell":             perf.get("n_sell", 0),
        "is_short_sample":    spw.get("is_short_sample", False),
        "benchmark_available": s.get("benchmark_available", False),
        "sector_heat_mode":   s.get("sector_heat_mode", "zero"),
        "data_dedup_count":   cov.get("dedup_count", 0),
        "data_wal_detected":  s.get("data_wal_detected", False),
    }
    return row


def _write_batch_summary(batch_id, batch_started, rows):
    """Write the aggregated CSV to F:/backtest_workspace/batch_summary/."""
    os.makedirs(paths.BATCH_DIR, exist_ok=True)
    fn = batch_id + "_" + batch_started + ".csv"
    target = os.path.join(paths.BATCH_DIR, fn).replace("\\", "/")
    with open(target, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_BATCH_COLS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return target


def main(argv=None):
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Backtest factory v0.2 batch runner")
    parser.add_argument("--experiment", required=True,
                        help="path to experiment yaml (e.g. backtest/configs/experiments/baseline_grid.yaml)")
    args = parser.parse_args(argv)

    init_workspace.ensure_workspace()

    exp_cfg = _load_yaml(args.experiment)
    batch_id = exp_cfg["batch"]["id"]
    batch_started = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")

    rows = []
    for idx, leaf_name, leaf_cfg in expand_grid(exp_cfg):
        log.info("batch %s leaf %d/%s starting", batch_id, idx, leaf_name)
        row = _run_one_leaf(leaf_cfg, batch_id, idx, leaf_name)
        rows.append(row)
        log.info("batch %s leaf %d/%s done -> %s", batch_id, idx, leaf_name,
                 row["results_dir"])

    target = _write_batch_summary(batch_id, batch_started, rows)
    log.info("batch summary written: %s", target)
    print(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
