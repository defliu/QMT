# coding: utf-8
"""build_core_pit_manifest.py — 生成 point-in-time core_N 月度快照（v0.3 P2.1）。

口径（agent_hub/.../11 Hermes 验收 §六）：
  1) 读 F:/backtest_workspace/data/duckdb/qmt_market_data.duckdb（read_only）
  2) 不调 xtquant；不写 duckdb；不接 passorder/xttrader；不写金策智算
  3) 在 [start_date, end_date] 内每月末 trading day 生成一份 as_of snapshot
  4) 对每个 as_of：仅用 as_of 日及之前的数据，取 past 60 trading days amount sum
     降序，bars >= bars_min（默认 40，因池本身仅 105 codes，120 过严）取 top N
  5) 输出：
     - D:/QMT_STRATEGIES/backtest/data/universe/pit_manifests/<run_label>/
         core_<N>_<as_of>.csv（每月一份）
         index.json（as_of -> csv 路径 + 列表）
     - F:/backtest_workspace/data/sync_reports/build_pit_manifest_<TS>.json

注意：本工具是研究用，**不写 duckdb，不下载新代码**，
仅在既有 qmt_market_data.duckdb 池上做 PIT 重排。
若 Hermes 决定扩 sync 至 PIT 并集，再追加另一条工具链。
"""
import argparse
import csv
import datetime as _dt
import json
import logging
import os
import sys

log = logging.getLogger("build_core_pit_manifest")

DEFAULT_DB = "F:/backtest_workspace/data/duckdb/qmt_market_data.duckdb"
DEFAULT_OUT_ROOT = "D:/QMT_STRATEGIES/backtest/data/universe/pit_manifests"
DEFAULT_REPORT_DIR = "F:/backtest_workspace/data/sync_reports"
DEFAULT_BARS_MIN = 40
DEFAULT_RANK_WINDOW = 60


def _parse_date(s):
    return _dt.datetime.strptime(s, "%Y-%m-%d").date()


def _month_ends(trading_days):
    """Given sorted list of trading day strings (YYYY-MM-DD), return the last
    trading day of each month present in the list."""
    by_month = {}
    for d in trading_days:
        ym = d[:7]
        # later occurrence overwrites
        by_month[ym] = d
    months = sorted(by_month.keys())
    return [by_month[m] for m in months]


def _load_trading_calendar(conn, start_date, end_date):
    rows = conn.execute(
        "SELECT DISTINCT trade_date AS d "
        "FROM dat_day "
        "WHERE trade_date BETWEEN ? AND ? "
        "  AND adjustment = 'hfq' AND source = 'xtquant' "
        "ORDER BY d",
        [start_date, end_date]).fetchall()
    return [str(r[0]) for r in rows]


def _snapshot(conn, as_of, rank_window, bars_min, n):
    """Return list of dicts [{code, name?, n_bars, amount_sum}] top n by amount."""
    # Compute the start date by getting calendar of past `rank_window` trading days.
    start_rows = conn.execute(
        "SELECT DISTINCT trade_date AS d "
        "FROM dat_day "
        "WHERE trade_date <= ? "
        "  AND adjustment = 'hfq' AND source = 'xtquant' "
        "ORDER BY d DESC LIMIT ?", [as_of, rank_window]).fetchall()
    if not start_rows:
        return [], None, None
    win_days = sorted([str(r[0]) for r in start_rows])
    win_start = win_days[0]
    win_end = win_days[-1]

    rows = conn.execute(
        "SELECT code, COUNT(*) AS n_bars, SUM(amount) AS amt_sum "
        "FROM dat_day "
        "WHERE trade_date BETWEEN ? AND ? "
        "  AND adjustment = 'hfq' AND source = 'xtquant' "
        "GROUP BY code", [win_start, win_end]).fetchall()
    survivors = [
        {"code": r[0], "n_bars": int(r[1]), "amount_sum": float(r[2] or 0.0)}
        for r in rows if int(r[1]) >= bars_min
    ]
    survivors.sort(key=lambda r: r["amount_sum"], reverse=True)
    chosen = survivors[:n]
    return chosen, win_start, win_end


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Generate monthly point-in-time core_N manifests "
                    "from qmt_market_data.duckdb (read-only).")
    p.add_argument("--db", default=DEFAULT_DB, help="duckdb path (read-only)")
    p.add_argument("--n", type=int, default=100, help="snapshot size (default 100)")
    p.add_argument("--start-date", required=True, dest="start_date",
                   help="YYYY-MM-DD; first as_of >= this; first PIT snapshot is "
                        "the last trading day of start_date's month")
    p.add_argument("--end-date", required=True, dest="end_date",
                   help="YYYY-MM-DD; last as_of <= this")
    p.add_argument("--rank-window", type=int, default=DEFAULT_RANK_WINDOW,
                   dest="rank_window")
    p.add_argument("--bars-min", type=int, default=DEFAULT_BARS_MIN,
                   dest="bars_min")
    p.add_argument("--label", required=True,
                   help="run label, used as output subdir name "
                        "(e.g. p2_1_pit_top100_monthly)")
    p.add_argument("--out-root", default=DEFAULT_OUT_ROOT, dest="out_root")
    p.add_argument("--report-dir", default=DEFAULT_REPORT_DIR, dest="report_dir")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    out_root = args.out_root.replace("\\", "/")
    out_dir = (out_root.rstrip("/") + "/" + args.label).replace("\\", "/")
    assert out_dir.lower().startswith("d:/qmt_strategies/"), \
        "manifest dir must live under D:/QMT_STRATEGIES/ (got: %s)" % out_dir
    assert "金策智算" not in out_dir, "must not write under 金策智算"
    assert args.report_dir.replace("\\", "/").lower().startswith(
        "f:/backtest_workspace/"), "report dir must be F:/backtest_workspace/"

    import duckdb
    if not os.path.isfile(args.db):
        raise FileNotFoundError("DuckDB not found: " + args.db)
    conn = duckdb.connect(args.db, read_only=True)

    started_at = _dt.datetime.now()
    log.info("db=%s n=%d window=%d bars_min=%d range=%s..%s",
             args.db, args.n, args.rank_window, args.bars_min,
             args.start_date, args.end_date)

    cal = _load_trading_calendar(conn, args.start_date, args.end_date)
    if not cal:
        raise RuntimeError("empty trading calendar in [%s, %s]"
                           % (args.start_date, args.end_date))
    snapshots_dates = _month_ends(cal)
    log.info("trading_days_in_range=%d, monthly_snapshots=%d",
             len(cal), len(snapshots_dates))

    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)

    index = {
        "label":       args.label,
        "n":           args.n,
        "rank_window": args.rank_window,
        "bars_min":    args.bars_min,
        "start_date":  args.start_date,
        "end_date":    args.end_date,
        "snapshots":   [],   # [{as_of, csv, n_chosen, win_start, win_end, top10}]
    }

    for as_of in snapshots_dates:
        chosen, w0, w1 = _snapshot(conn, as_of, args.rank_window,
                                   args.bars_min, args.n)
        csv_name = "core_%d_%s.csv" % (args.n, as_of.replace("-", ""))
        csv_path = (out_dir + "/" + csv_name).replace("\\", "/")
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["code", "name", "sector", "enabled"])
            for r in chosen:
                w.writerow([r["code"], "", "", "true"])
        index["snapshots"].append({
            "as_of":     as_of,
            "csv":       csv_path,
            "n_chosen":  len(chosen),
            "win_start": w0,
            "win_end":   w1,
            "top10":     [
                {"code": r["code"], "n_bars": r["n_bars"],
                 "amount_sum": round(r["amount_sum"], 2)}
                for r in chosen[:10]
            ],
        })
        log.info("snapshot %s: %d codes, win=%s..%s",
                 as_of, len(chosen), w0, w1)

    conn.close()

    index_path = (out_dir + "/index.json").replace("\\", "/")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2, default=str)
    log.info("index: %s", index_path)

    finished_at = _dt.datetime.now()
    report = {
        "generated_at":      finished_at.isoformat(timespec="seconds"),
        "db":                args.db,
        "label":              args.label,
        "out_dir":            out_dir,
        "index_path":         index_path,
        "n_requested":        args.n,
        "rank_window":        args.rank_window,
        "bars_min":           args.bars_min,
        "start_date":         args.start_date,
        "end_date":           args.end_date,
        "trading_days":       len(cal),
        "n_snapshots":        len(snapshots_dates),
        "duration_seconds":   round((finished_at - started_at).total_seconds(), 2),
    }
    if not os.path.isdir(args.report_dir):
        os.makedirs(args.report_dir)
    rep_path = (args.report_dir + "/build_pit_manifest_"
                + finished_at.strftime("%Y%m%d_%H%M%S") + ".json").replace("\\", "/")
    with open(rep_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    log.info("report: %s", rep_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
