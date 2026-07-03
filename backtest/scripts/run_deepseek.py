# coding: utf-8
"""DeepSeek 策略自定义 runner。

为什么不用 run_backtest.py：标准 runner 把 aux_data 写死 None，且 reader 由
data.source 分发（astock → AstockParquetReader，不带指标列）。DeepSeek 需要
DeepseekReader（带预算指标列），故写独立 runner 直调 engine.run_backtest。

零侵入：不改 engine / 不改 run_backtest.py。

Usage:
    py -3.10 -m backtest.scripts.run_deepseek --config backtest/configs/deepseek_v4.yaml
"""
import argparse
import logging
import os
import sys

import yaml

from backtest import paths
from backtest.data_tools.universe import load_universe
from backtest.engine.daily_engine import run_backtest
from backtest.engine import report
from backtest.engine.hashing import compute_config_hash, compute_universe_hash
from backtest.strategies.research.deepseek.reader import DeepseekReader

log = logging.getLogger("run_deepseek")


def _load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    return yaml.safe_load(text), text


def _resolve(rel):
    if os.path.isabs(rel):
        return rel
    return os.path.join(paths.BACKTEST_ROOT, "..", rel)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--smoke", action="store_true",
                    help="冒烟：覆盖为 core_100 + 3 个月，验证管线")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    cfg, raw_text = _load_yaml(args.config)
    bt = cfg.get("backtest", {})
    data_cfg = cfg.get("data", {})
    exec_cfg = cfg.get("execution", {})
    strat_cfg = cfg.get("strategy_params", {})
    universe_cfg = cfg.get("universe", {})
    v04_strategy = cfg.get("strategy") or "research/deepseek"
    v04_model = cfg.get("trading_model") or exec_cfg.get("price", "next_open")

    config_name = bt.get("name", "deepseek")
    config_hash = compute_config_hash(raw_text)

    start_date = bt["start_date"]
    end_date = bt["end_date"]
    universe_csv = universe_cfg["csv"]

    if args.smoke:
        config_name = config_name + "_smoke"
        strat_cfg = dict(strat_cfg)
        strat_cfg["_warmup_calendar_days"] = 120
        start_date = "2025-01-01"
        end_date = "2025-03-31"
        universe_csv = "backtest/data/universe/core_100.csv"

    uni = load_universe(_resolve(universe_csv))
    universe = uni["codes"]
    universe_hash = compute_universe_hash(universe)

    reader = DeepseekReader(db_path=data_cfg.get("path"), adjustment="hfq")

    try:
        result = run_backtest(
            reader=reader,
            universe=universe,
            start_date=start_date,
            end_date=end_date,
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
            strategy_name=v04_strategy,
            trading_model=v04_model,
        )
    finally:
        reader.close()

    rd = report.write_all(result, config_name=config_name)
    summary = result.get("summary", {})
    perf = summary.get("performance", {})
    log.info("=== %s done ===", config_name)
    log.info("results_dir: %s", rd)
    log.info("trades: %d", len(result.get("trades", [])))
    log.info("total_return: %s", perf.get("total_return"))
    log.info("annual_return: %s", perf.get("annual_return"))
    log.info("max_drawdown: %s", perf.get("max_drawdown"))
    log.info("sharpe: %s", perf.get("sharpe"))
    print("RESULTS_DIR=" + rd)
    print("SUMMARY_JSON=" + os.path.join(rd, "summary.json"))


if __name__ == "__main__":
    main()
