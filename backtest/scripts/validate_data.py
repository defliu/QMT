# coding: utf-8
"""validate_data.py — DuckDB data quality probe (Task 5.4).

Reads quantifydata.duckdb (read-only) and reports:
  * coverage: min_date / max_date / n_codes / n_rows_after_dedup
  * dedup_count: raw rows minus dedup rows
  * wal_detected: presence of quantifydata.duckdb.wal
  * universe_coverage: when --universe is provided, list of codes missing data
                       inside the requested date window

Output:
  * JSON report at F:/backtest_workspace/logs/validate_data_<timestamp>.json
  * Returns exit code 0 always (this is a probe, not a gate). Caller decides.

Boundaries (night-shift §四):
  * Reads E:/金策智算/...quantifydata.duckdb (read_only via DuckDBDailyReader).
  * Writes F:/backtest_workspace/logs/ only.
  * Never writes C:/D:; never E:/金策智算/.
"""
import argparse
import datetime as _dt
import json
import logging
import os
import sys

from backtest import paths
from backtest.data_tools.duckdb_reader import (
    DuckDBDailyReader, JINCE_ZHISUAN, QMT_SELF_OWNED, SUPPORTED_SOURCES,
)
from backtest.data_tools.universe import load_universe
from backtest.scripts import init_workspace

log = logging.getLogger("validate_data")


def build_report(db_path, universe_csv=None, start_date=None, end_date=None,
                 data_source=JINCE_ZHISUAN):
    """Compute the validation report dict (no IO)."""
    reader = DuckDBDailyReader(db_path, data_source=data_source)
    try:
        if universe_csv is not None:
            uni = load_universe(universe_csv)
            cov = reader.coverage(codes=uni["codes"],
                                  start_date=start_date, end_date=end_date)
        else:
            cov = reader.coverage()
        report = {
            "schema_version":   "0.3",
            "generated_at":     _dt.datetime.now().isoformat(timespec="seconds"),
            "data_backend":     "duckdb",
            "data_source":      data_source,
            "db_path":          db_path,
            "db_mtime":         cov.get("db_mtime", ""),
            "wal_detected":     bool(reader.wal_detected),
            "wal_warning_message": getattr(reader, "wal_warning_message", "") or "",
            "min_date":         cov.get("min_date", ""),
            "max_date":         cov.get("max_date", ""),
            "n_codes":          cov.get("n_codes", 0),
            "n_rows_after_dedup": cov.get("n_rows_after_dedup", 0),
            "dedup_count":      cov.get("dedup_count", 0),
            "universe_coverage": cov.get("universe_coverage"),
            "requested_window": {
                "start_date": start_date or "",
                "end_date":   end_date or "",
            },
        }
        if data_source == QMT_SELF_OWNED:
            report["volume_unit"] = "share"
            report["adjustment"] = (
                reader.default_filters.get("adjustment", "hfq"))
            report["source_filter"] = (
                reader.default_filters.get("source", "xtquant"))
        return report
    finally:
        reader.close()


def write_report(report, logs_dir=None):
    """Persist the report under LOGS_DIR. Returns the file path."""
    ldir = logs_dir if logs_dir is not None else paths.LOGS_DIR
    os.makedirs(ldir, exist_ok=True)
    fn = "validate_data_" + _dt.datetime.now().strftime("%Y%m%d_%H%M%S") + ".json"
    target = os.path.join(ldir, fn).replace("\\", "/")
    with open(target, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    return target


def main(argv=None):
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="DuckDB data quality probe")
    parser.add_argument("--db", default=paths.JINCE_DB_PATH,
                        help="path to DuckDB (default: E:/金策智算/...)")
    parser.add_argument("--data-source", default=JINCE_ZHISUAN,
                        choices=list(SUPPORTED_SOURCES),
                        help="explicit data source / schema "
                             "(jince_zhisuan: trade_time TZ; "
                             "qmt_self_owned: trade_date DATE)")
    parser.add_argument("--universe", default=None,
                        help="optional universe csv to compute universe_coverage")
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    args = parser.parse_args(argv)

    init_workspace.ensure_workspace()
    report = build_report(args.db, universe_csv=args.universe,
                          start_date=args.start_date, end_date=args.end_date,
                          data_source=args.data_source)
    target = write_report(report)
    log.info("validation report: %s", target)
    print(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
