# coding: utf-8
"""validate_universe.py — universe CSV quality probe (Task 6.1).

Cross-checks a universe CSV against the read-only DuckDB to surface
schema, coverage, sector-balance and history-depth issues *before* a
backtest is launched.

Checks performed:
  1. Schema validation (delegates to data_tools.universe.load_universe;
     captures dropped_codes for invalid syntax and counts disabled rows).
  2. DuckDB cross-check: which codes have any rows; which codes have
     fewer than `--min-history-bars` (default 60) bars in the requested
     window — strategy_core's INSUFFICIENT_HISTORY threshold.
  3. Sector distribution: count of enabled codes per sector.

Output:
  * JSON report at F:/backtest_workspace/logs/validate_universe_<ts>.json
  * Always exit 0; this is a probe, not a gate.

Boundaries (night-shift §四):
  * Reads universe csv from D:; reads DuckDB read-only.
  * Writes JSON report only under F:/backtest_workspace/logs/.
  * Never writes C:/D:; never F:/金策智算/.
"""
import argparse
import collections
import csv
import datetime as _dt
import json
import logging
import os
import sys

from backtest import paths
from backtest.data_tools.duckdb_reader import DuckDBDailyReader
from backtest.data_tools.universe import load_universe
from backtest.scripts import init_workspace

log = logging.getLogger("validate_universe")


def _read_sectors(universe_csv):
    """Return list of (code, sector) for ALL enabled rows that passed schema."""
    pairs = []
    with open(universe_csv, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = (row.get("code") or "").strip()
            sector = (row.get("sector") or "").strip()
            enabled = (row.get("enabled") or "true").strip().lower()
            if enabled in ("false", "0", "no", ""):
                continue
            pairs.append((code, sector))
    return pairs


def _count_disabled_rows(universe_csv):
    n = 0
    with open(universe_csv, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            v = (row.get("enabled") or "true").strip().lower()
            if v in ("false", "0", "no", ""):
                n += 1
    return n


def _bars_per_code(reader, codes, start_date, end_date):
    """Return {code: n_bars} for codes inside [start_date, end_date]."""
    if not codes:
        return {}
    placeholders = ",".join(["?"] * len(codes))
    sql = (
        "SELECT code, COUNT(DISTINCT CAST(trade_time AS DATE)) AS n "
        "FROM dat_day "
        "WHERE code IN (" + placeholders + ") "
        "  AND CAST(trade_time AS DATE) BETWEEN ? AND ? "
        "GROUP BY code"
    )
    rows = reader._conn.execute(sql, list(codes) + [start_date, end_date]).fetchall()
    out = {c: 0 for c in codes}
    for code, n in rows:
        out[code] = int(n)
    return out


def build_report(universe_csv, db_path, start_date=None, end_date=None,
                 min_history_bars=60):
    """Compute the universe validation report dict. No file IO."""
    uni = load_universe(universe_csv)
    enabled_codes = uni["codes"]
    dropped_invalid = uni.get("dropped_codes", [])

    sector_pairs = _read_sectors(universe_csv)
    sector_counts = collections.Counter(s for _, s in sector_pairs)
    by_sector = sorted(((s, n) for s, n in sector_counts.items()),
                       key=lambda kv: (-kv[1], kv[0]))

    reader = DuckDBDailyReader(db_path)
    try:
        cov = reader.coverage()
        sd = start_date or cov["min_date"]
        ed = end_date or cov["max_date"]

        cov_uni = reader.coverage(codes=enabled_codes,
                                  start_date=sd, end_date=ed)
        uc = cov_uni.get("universe_coverage") or {}
        codes_missing = list(uc.get("codes_missing") or [])
        codes_with_data = [c for c in enabled_codes if c not in set(codes_missing)]

        bars = _bars_per_code(reader, codes_with_data, sd, ed)
        thin = sorted([(c, n) for c, n in bars.items() if n < min_history_bars],
                      key=lambda kv: (kv[1], kv[0]))
        sufficient = sum(1 for n in bars.values() if n >= min_history_bars)

        report = {
            "schema_version":   "0.2",
            "generated_at":     _dt.datetime.now().isoformat(timespec="seconds"),
            "universe_csv":     universe_csv,
            "db_path":          db_path,
            "db_mtime":         cov.get("db_mtime", ""),
            "requested_window": {"start_date": sd, "end_date": ed},
            "universe_size_enabled":  len(enabled_codes),
            "rows_dropped_invalid":   len(dropped_invalid),
            "rows_disabled":          _count_disabled_rows(universe_csv),
            "dropped_invalid_codes":  dropped_invalid,
            "sector_distribution":    [{"sector": s, "count": n} for s, n in by_sector],
            "duckdb_coverage": {
                "codes_with_data": len(codes_with_data),
                "codes_missing":   codes_missing,
                "missing_count":   len(codes_missing),
            },
            "history_depth": {
                "min_history_bars":  min_history_bars,
                "sufficient_count":  sufficient,
                "thin_count":        len(thin),
                "thin_codes":        [{"code": c, "n_bars": n} for c, n in thin],
            },
        }
        return report
    finally:
        reader.close()


def write_report(report, logs_dir=None):
    ldir = logs_dir if logs_dir is not None else paths.LOGS_DIR
    os.makedirs(ldir, exist_ok=True)
    fn = "validate_universe_" + _dt.datetime.now().strftime("%Y%m%d_%H%M%S") + ".json"
    target = os.path.join(ldir, fn).replace("\\", "/")
    with open(target, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    return target


def main(argv=None):
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Universe CSV quality probe")
    parser.add_argument("--universe", required=True,
                        help="path to universe csv")
    parser.add_argument("--db", default=paths.JINCE_DB_PATH,
                        help="path to quantifydata.duckdb (default: F:/金策智算/...)")
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--min-history-bars", type=int, default=60,
                        help="threshold below which a code is flagged as thin (default 60)")
    args = parser.parse_args(argv)

    init_workspace.ensure_workspace()
    report = build_report(args.universe, args.db,
                          start_date=args.start_date,
                          end_date=args.end_date,
                          min_history_bars=args.min_history_bars)
    target = write_report(report)
    log.info("universe validation report: %s", target)
    print(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
