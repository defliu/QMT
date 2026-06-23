# coding: utf-8
"""CLI runner for backtest factory v0.2.

Usage:
    py -3.10 -m backtest.scripts.run_backtest --config backtest/configs/baseline.yaml

Boundaries (night-shift §四):
  - Reads yaml from D:\\QMT_STRATEGIES\\backtest\\configs\\
  - Reads DuckDB from E:\\金策智算\\ (READ-ONLY)
  - Writes 6 result files to F:\\backtest_workspace\\results\\<run_id>_<config>\\
  - Never writes C: or D:.
"""
import argparse
import csv
import json
import os
import sys
import logging

import yaml

from backtest import paths
from backtest.data_tools.duckdb_reader import (
    DuckDBDailyReader, JINCE_ZHISUAN, SUPPORTED_SOURCES,
)
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


def _load_pit_manifest(index_path):
    """Load PIT manifest index.json + per-as_of CSVs.

    Returns (universe_by_date, union_codes).
    universe_by_date: {as_of_str: [codes]} (only snapshots with n_chosen > 0)
    union_codes:      sorted list of unique codes across all snapshots
    """
    with open(index_path, "r", encoding="utf-8") as f:
        idx = json.load(f)
    universe_by_date = {}
    union = set()
    for s in idx.get("snapshots", []):
        if int(s.get("n_chosen", 0)) <= 0:
            continue
        codes = []
        with open(s["csv"], "r", encoding="utf-8-sig") as fc:
            r = csv.DictReader(fc)
            for row in r:
                code = (row.get("code") or "").strip()
                if code:
                    codes.append(code)
        if not codes:
            continue
        universe_by_date[s["as_of"]] = codes
        union.update(codes)
    return universe_by_date, sorted(union)


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

    # v0.4 Phase 1 / MS-A: 顶层 strategy_name + trading_model
    v04_strategy_name = cfg.get("strategy_name") or "production/ima_uptrend_v31"
    v04_trading_model = cfg.get("trading_model") or exec_cfg.get("price", "next_open")

    config_name = bt.get("name", "baseline")
    config_hash = compute_config_hash(raw_text)

    universe_csv = universe_cfg.get("csv")
    pit_manifest = universe_cfg.get("pit_manifest")
    if pit_manifest:
        index_path = _resolve(pit_manifest)
        universe_by_date, universe = _load_pit_manifest(index_path)
        if not universe:
            raise ValueError("PIT manifest produced empty union: %s" % index_path)
        log.info("PIT manifest loaded: %d snapshots, union=%d codes from %s",
                 len(universe_by_date), len(universe), index_path)
    elif universe_csv:
        uni = load_universe(_resolve(universe_csv))
        universe = uni["codes"]
        universe_by_date = None
    else:
        raise ValueError("yaml universe must set either 'csv' or 'pit_manifest'")
    universe_hash = compute_universe_hash(universe)

    db_path = data_cfg.get("path", paths.JINCE_DB_PATH)
    data_source = data_cfg.get("source", JINCE_ZHISUAN)
    if data_source not in SUPPORTED_SOURCES:
        raise ValueError("data.source must be one of %s, got: %s"
                         % (SUPPORTED_SOURCES, data_source))
    reader = DuckDBDailyReader(db_path, data_source=data_source)

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
            benchmark_db_path=bt.get(
                "benchmark_db_path",
                "F:/backtest_workspace/data/duckdb/benchmark_index.duckdb"),
            config_name=config_name,
            config_hash=config_hash,
            universe_hash=universe_hash,
            universe_by_date=universe_by_date,
            strategy_name=v04_strategy_name,
            trading_model=v04_trading_model,
        )
    finally:
        reader.close()

    rd = report.write_all(result, config_name=config_name)
    log.info("backtest complete: %s", rd)
    print(rd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
