# coding: utf-8
"""CLI runner for backtest factory v0.2.

Usage:
    py -3.10 -m backtest.scripts.run_backtest --config backtest/configs/baseline.yaml

Boundaries (night-shift §四):
  - Reads yaml from D:\\QMT_STRATEGIES\\backtest\\configs\\
  - Reads DuckDB from F:\\金策智算\\ (READ-ONLY)
  - Writes 6 result files to F:\\backtest_workspace\\results\\<run_id>_<config>\\
  - Never writes C: or D:.
"""
import argparse
import os
import sys
import logging

import yaml

from backtest import paths
from backtest.data_tools.duckdb_reader import DuckDBDailyReader
from backtest.data_tools.universe import load_universe
from backtest.engine.daily_engine import run_backtest
from backtest.engine.hashing import compute_config_hash, compute_universe_hash
from backtest.engine import report
from backtest.scripts import init_workspace

log = logging.getLogger("run_backtest")


def _load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    cfg = yaml.safe_load(text)
    return cfg, text


def _resolve(rel):
    if os.path.isabs(rel):
        return rel
    return os.path.join(paths.BACKTEST_ROOT, "..", rel)


def main(argv=None):
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Backtest factory v0.2 runner")
    parser.add_argument("--config", required=True,
                        help="path to yaml config (e.g. backtest/configs/baseline.yaml)")
    args = parser.parse_args(argv)

    init_workspace.ensure_workspace()

    cfg, raw_text = _load_yaml(args.config)
    bt = cfg.get("backtest", {})
    data_cfg = cfg.get("data", {})
    universe_cfg = cfg.get("universe", {})
    exec_cfg = cfg.get("execution", {})
    strat_cfg = cfg.get("strategy", {})

    config_name = bt.get("name", "baseline")
    config_hash = compute_config_hash(raw_text)

    universe_csv = _resolve(universe_cfg.get("csv"))
    uni = load_universe(universe_csv)
    universe = uni["codes"]
    universe_hash = compute_universe_hash(universe)

    db_path = data_cfg.get("path", paths.JINCE_DB_PATH)
    reader = DuckDBDailyReader(db_path)

    try:
        result = run_backtest(
            reader=reader,
            universe=universe,
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
    log.info("backtest complete: %s", rd)
    print(rd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
