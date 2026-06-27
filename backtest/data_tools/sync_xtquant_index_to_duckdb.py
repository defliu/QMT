# coding: utf-8
"""sync_xtquant_index_to_duckdb.py — 拉主流指数 1d → 独立 DuckDB。

目的：补齐 huicexitong 软件未同步的 2026-04-04 之后指数数据，解锁 P2.2 benchmark。

边界：
  * 只拉历史指数行情；不调 passorder / xttrader；
  * 不写 huice 库 / qmt_market_data.duckdb / 金策智算；
  * 输出独立 DuckDB：F:/backtest_workspace/data/duckdb/benchmark_index.duckdb
  * sync 报告 → F:/backtest_workspace/data/sync_reports/

CLI 独立，不进 reader/engine/run_backtest/run_batch 的 import 链。
"""
import argparse
import csv
import datetime as _dt
import json
import logging
import os
import sys

log = logging.getLogger("sync_xtquant_index")

DEFAULT_TARGET_DB  = "F:/backtest_workspace/data/duckdb/benchmark_index.duckdb"
DEFAULT_REPORT_DIR = "F:/backtest_workspace/data/sync_reports"
DEFAULT_PERIOD     = "1d"

DEFAULT_INDEX_CODES = [
    "000300.SH",  # 沪深300
    "000905.SH",  # 中证500
    "000852.SH",  # 中证1000
    "000001.SH",  # 上证指数
    "000016.SH",  # 上证50
    "000688.SH",  # 科创50
    "399001.SZ",  # 深证成指
    "399006.SZ",  # 创业板指
]

DDL_INDEX_DAILY = """
CREATE TABLE IF NOT EXISTS index_daily (
    code         VARCHAR NOT NULL,
    trade_date   DATE    NOT NULL,
    open         DOUBLE,
    high         DOUBLE,
    low          DOUBLE,
    close        DOUBLE,
    pre_close    DOUBLE,
    volume       BIGINT,
    amount       DOUBLE,
    source       VARCHAR NOT NULL,
    synced_at    TIMESTAMP NOT NULL,
    PRIMARY KEY (code, trade_date, source)
)
"""

DDL_SYNC_LOG = """
CREATE TABLE IF NOT EXISTS sync_log (
    sync_id      VARCHAR PRIMARY KEY,
    started_at   TIMESTAMP NOT NULL,
    finished_at  TIMESTAMP,
    n_codes      INTEGER,
    n_rows       INTEGER,
    start_date   DATE,
    end_date     DATE,
    status       VARCHAR,
    note         VARCHAR
)
"""


def _yyyymmdd(d):
    return d.strftime("%Y%m%d")


def _parse_date(s):
    return _dt.datetime.strptime(s, "%Y-%m-%d").date()


def _read_codes_csv(path):
    if not os.path.isfile(path):
        raise FileNotFoundError("codes csv not found: " + path)
    out = []
    with open(path, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            c = (row.get("code") or "").strip()
            if c:
                out.append(c)
    return out


def main(argv=None):
    p = argparse.ArgumentParser(
        description="sync xtquant index 1d bars to independent duckdb")
    p.add_argument("--target", default=DEFAULT_TARGET_DB)
    p.add_argument("--report-dir", default=DEFAULT_REPORT_DIR)
    p.add_argument("--start-date", required=True)
    p.add_argument("--end-date", required=True)
    p.add_argument("--codes", nargs="*", default=None,
                   help="explicit code list; default = built-in 8 mainstream")
    p.add_argument("--codes-csv", default=None,
                   help="optional csv file with `code` column")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    target = args.target.replace("\\", "/")
    report_dir = args.report_dir.replace("\\", "/")
    assert "金策智算" not in target, "target MUST NOT live under 金策智算"
    assert target.lower().startswith("f:/backtest_workspace/"), \
        "target must be under F:/backtest_workspace/"
    assert report_dir.lower().startswith("f:/backtest_workspace/"), \
        "report_dir must be under F:/backtest_workspace/"

    if args.codes_csv:
        codes = _read_codes_csv(args.codes_csv)
    elif args.codes:
        codes = list(args.codes)
    else:
        codes = list(DEFAULT_INDEX_CODES)
    assert len(codes) > 0, "no codes to sync"

    start_d = _parse_date(args.start_date)
    end_d = _parse_date(args.end_date)
    assert start_d <= end_d, "start_date must be <= end_date"

    started_at = _dt.datetime.now()
    sync_id = started_at.strftime("idx_%Y%m%d_%H%M%S")
    log.info("sync_id=%s codes=%d range=%s..%s target=%s",
             sync_id, len(codes), start_d, end_d, target)

    # xtquant
    log.info("connecting xtquant ...")
    from xtquant import xtdata
    s_yy = _yyyymmdd(start_d)
    e_yy = _yyyymmdd(end_d)

    log.info("download_history_data2 (%d codes, %s..%s) ...",
             len(codes), s_yy, e_yy)
    t0 = _dt.datetime.now()
    try:
        xtdata.download_history_data2(
            stock_list=codes, period="1d",
            start_time=s_yy, end_time=e_yy, incrementally=False)
    except TypeError:
        xtdata.download_history_data2(codes, "1d", s_yy, e_yy)
    dl_secs = (_dt.datetime.now() - t0).total_seconds()
    log.info("download done in %.1fs", dl_secs)

    log.info("get_market_data_ex ...")
    t1 = _dt.datetime.now()
    market = xtdata.get_market_data_ex(
        field_list=["time", "open", "high", "low", "close",
                    "preClose", "volume", "amount"],
        stock_list=codes, period="1d",
        start_time=s_yy, end_time=e_yy,
        dividend_type="none", fill_data=False)
    fetch_secs = (_dt.datetime.now() - t1).total_seconds()
    log.info("fetch done in %.1fs", fetch_secs)

    # parse
    rows = []
    per_code_rows = {}
    for code in codes:
        df = market.get(code) if isinstance(market, dict) else None
        if df is None or len(df) == 0:
            per_code_rows[code] = 0
            continue
        n = 0
        for idx, r in df.iterrows():
            s = str(idx)
            if len(s) == 8 and s.isdigit():
                ds = "%s-%s-%s" % (s[:4], s[4:6], s[6:8])
            else:
                ds = s[:10]
            try:
                trade_date = _dt.datetime.strptime(ds, "%Y-%m-%d").date()
            except Exception:
                continue
            if trade_date < start_d or trade_date > end_d:
                continue
            rows.append((
                code, trade_date,
                float(r.get("open", 0.0)) if r.get("open") is not None else None,
                float(r.get("high", 0.0)) if r.get("high") is not None else None,
                float(r.get("low", 0.0)) if r.get("low") is not None else None,
                float(r.get("close", 0.0)) if r.get("close") is not None else None,
                float(r.get("preClose", 0.0)) if r.get("preClose") is not None else None,
                int(r.get("volume", 0)) if r.get("volume") is not None else None,
                float(r.get("amount", 0.0)) if r.get("amount") is not None else None,
                "xtquant",
                started_at,
            ))
            n += 1
        per_code_rows[code] = n

    log.info("parsed %d rows across %d codes", len(rows), len(codes))

    # write duckdb
    target_dir = os.path.dirname(target)
    if not os.path.isdir(target_dir):
        os.makedirs(target_dir)

    import duckdb
    con = duckdb.connect(target, read_only=False)
    try:
        con.execute(DDL_INDEX_DAILY)
        con.execute(DDL_SYNC_LOG)

        # delete the (code, date_range, source='xtquant') overlapping rows then insert
        con.execute("BEGIN")
        for code in codes:
            con.execute(
                "DELETE FROM index_daily "
                "WHERE code = ? AND trade_date BETWEEN ? AND ? AND source = 'xtquant'",
                [code, start_d, end_d])
        if rows:
            con.executemany(
                "INSERT INTO index_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows)
        con.execute(
            "INSERT INTO sync_log VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [sync_id, started_at, _dt.datetime.now(),
             len(codes), len(rows), start_d, end_d, "ok",
             "xtquant index 1d, codes=%d" % len(codes)])
        con.execute("COMMIT")

        coverage = con.execute(
            "SELECT code, COUNT(*) AS n_rows, MIN(trade_date), MAX(trade_date) "
            "FROM index_daily WHERE source = 'xtquant' "
            "AND trade_date BETWEEN ? AND ? "
            "GROUP BY code ORDER BY code", [start_d, end_d]).fetchall()
    finally:
        con.close()

    finished_at = _dt.datetime.now()
    report = {
        "sync_id":          sync_id,
        "generated_at":     finished_at.isoformat(timespec="seconds"),
        "target":           target,
        "scope":            "xtquant_index_1d",
        "n_codes":          len(codes),
        "n_rows":           len(rows),
        "start_date":       args.start_date,
        "end_date":         args.end_date,
        "download_seconds": round(dl_secs, 1),
        "fetch_seconds":    round(fetch_secs, 1),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 1),
        "per_code_rows":    per_code_rows,
        "coverage":         [{"code": r[0], "n_rows": r[1],
                              "min_date": str(r[2]), "max_date": str(r[3])}
                             for r in coverage],
    }
    if not os.path.isdir(report_dir):
        os.makedirs(report_dir)
    rep_path = (report_dir + "/sync_xtquant_index_"
                + finished_at.strftime("%Y%m%d_%H%M%S") + ".json"
                ).replace("\\", "/")
    with open(rep_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    log.info("report: %s", rep_path)
    log.info("OK: %d codes / %d rows in %.1fs",
             len(codes), len(rows), report["duration_seconds"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
