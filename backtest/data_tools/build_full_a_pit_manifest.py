# coding: utf-8
"""build_full_a_pit_manifest.py — P2.1.b 全 A PIT 月度 top-N manifest 生成器。

口径（agent_hub/.../15 Hermes 评审 §四 + 14 设计 §三）：
  1) 不读 qmt_market_data.duckdb；不写 qmt_market_data.duckdb；不写金策智算
  2) read-only xtquant：拉全 A 1d bars 至 xtquant 自身 cache，内存计算 PIT
  3) 每月末 trading day 取过去 rank_window=60 日 amount sum 降序，
     bars >= bars_min（默认 120）取 top N（默认 100）
  4) 输出：
     - <out-root>/<label>/core_<N>_<YYYYMMDD>.csv（每月一份）
     - <out-root>/<label>/index.json（与 build_core_pit_manifest.py schema 一致）
     - <out-root>/<label>/__union.csv（并集 universe，送给 sync_xtquant_to_duckdb.py）
     - F:/backtest_workspace/data/sync_reports/build_full_a_pit_manifest_<TS>.json

不触：
  - 不调 passorder/xttrader/xtbp
  - 不读/不写 quantifydata.duckdb
  - 不写 qmt_market_data.duckdb
  - 不切 reader 默认源
"""
import argparse
import csv
import datetime as _dt
import json
import logging
import os
import sys

log = logging.getLogger("build_full_a_pit_manifest")

DEFAULT_OUT_ROOT = "D:/QMT_STRATEGIES/backtest/data/universe/pit_manifests"
DEFAULT_REPORT_DIR = "F:/backtest_workspace/data/sync_reports"
DEFAULT_BARS_MIN = 120
DEFAULT_RANK_WINDOW = 60
DEFAULT_HISTORY_WINDOW = 250
DEFAULT_N = 100
ST_KEYWORDS = ("ST", "*ST", "退市", "退")


def _parse_date(s):
    return _dt.datetime.strptime(s, "%Y-%m-%d").date()


def _yyyymmdd(d):
    return d.strftime("%Y%m%d")


def _is_excluded_by_name(name):
    if not name:
        return False
    n = name.replace(" ", "")
    for kw in ST_KEYWORDS:
        if kw in n:
            return True
    return False


def _is_bj(code):
    return code.endswith(".BJ")


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Build full-A PIT monthly top-N manifest (xtquant read-only).")
    p.add_argument("--n", type=int, default=DEFAULT_N)
    p.add_argument("--start-date", required=True, dest="start_date",
                   help="YYYY-MM-DD; first as_of >= last trading day of start month")
    p.add_argument("--end-date", required=True, dest="end_date",
                   help="YYYY-MM-DD; last as_of <= this")
    p.add_argument("--rank-window", type=int, default=DEFAULT_RANK_WINDOW,
                   dest="rank_window")
    p.add_argument("--bars-min", type=int, default=DEFAULT_BARS_MIN,
                   dest="bars_min")
    p.add_argument("--history-window", type=int, default=DEFAULT_HISTORY_WINDOW,
                   dest="history_window",
                   help="bars_min check window in trading days (default 250 ~= 1y)")
    p.add_argument("--label", required=True,
                   help="run label, used as output subdir name "
                        "(e.g. p2_1b_full_a_top100_monthly)")
    p.add_argument("--out-root", default=DEFAULT_OUT_ROOT, dest="out_root")
    p.add_argument("--report-dir", default=DEFAULT_REPORT_DIR, dest="report_dir")
    p.add_argument("--limit-candidates", type=int, default=0,
                   dest="limit_candidates",
                   help="debug: cap full-A candidate pool")
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

    end_d = _parse_date(args.end_date)
    start_d = _parse_date(args.start_date)
    fetch_start = start_d - _dt.timedelta(days=args.history_window + 60)

    started_at = _dt.datetime.now()
    log.info("range=%s..%s (fetch from %s) n=%d rank_window=%d "
             "bars_min=%d history_window=%d",
             start_d, end_d, fetch_start, args.n, args.rank_window,
             args.bars_min, args.history_window)

    from xtquant import xtdata
    log.info("get_stock_list_in_sector('沪深A股') ...")
    raw_codes = xtdata.get_stock_list_in_sector("沪深A股")
    log.info("raw stocks: %d", len(raw_codes))

    candidates = []
    excluded_bj = 0
    excluded_st = 0
    for code in raw_codes:
        if _is_bj(code):
            excluded_bj += 1
            continue
        try:
            d = xtdata.get_instrument_detail(code)
        except Exception:
            d = None
        name = (d or {}).get("InstrumentName", "")
        if _is_excluded_by_name(name):
            excluded_st += 1
            continue
        candidates.append({"code": code, "name": name})
    log.info("after BJ/ST filter: %d (BJ=%d, ST=%d)",
             len(candidates), excluded_bj, excluded_st)

    if args.limit_candidates > 0 and len(candidates) > args.limit_candidates:
        candidates = candidates[:args.limit_candidates]
        log.warning("DEBUG: candidate pool capped at %d", len(candidates))

    cand_codes = [c["code"] for c in candidates]
    name_map = {c["code"]: c["name"] for c in candidates}

    s_yy = _yyyymmdd(fetch_start)
    e_yy = _yyyymmdd(end_d)

    log.info("download_history_data2 (full A, %d codes, %s..%s) ...",
             len(cand_codes), s_yy, e_yy)
    t0 = _dt.datetime.now()
    try:
        xtdata.download_history_data2(
            stock_list=cand_codes, period="1d",
            start_time=s_yy, end_time=e_yy,
            incrementally=False)
    except TypeError:
        xtdata.download_history_data2(cand_codes, "1d", s_yy, e_yy)
    dl_secs = (_dt.datetime.now() - t0).total_seconds()
    log.info("download done in %.1fs", dl_secs)

    log.info("get_market_data_ex (time, amount) ...")
    t1 = _dt.datetime.now()
    market = xtdata.get_market_data_ex(
        field_list=["time", "amount"],
        stock_list=cand_codes,
        period="1d",
        start_time=s_yy,
        end_time=e_yy,
        dividend_type="none",
        fill_data=False,
    )
    fetch_secs = (_dt.datetime.now() - t1).total_seconds()
    log.info("fetch done in %.1fs", fetch_secs)

    code_amts = {}
    parse_fail = 0
    for code in cand_codes:
        df = market.get(code) if isinstance(market, dict) else None
        if df is None or len(df) == 0:
            continue
        try:
            amts = []
            for idx, val in zip(df.index, df["amount"].values):
                s = str(idx)
                if len(s) == 8 and s.isdigit():
                    ds = "%s-%s-%s" % (s[:4], s[4:6], s[6:8])
                else:
                    ds = s[:10]
                try:
                    amt = float(val)
                except Exception:
                    amt = 0.0
                amts.append((ds, amt))
            amts.sort(key=lambda x: x[0])
            if amts:
                code_amts[code] = amts
        except Exception as e:
            parse_fail += 1
            log.debug("parse fail %s: %s", code, e)
    log.info("parsed amount series for %d codes (parse_fail=%d)",
             len(code_amts), parse_fail)

    all_dates = set()
    for amts in code_amts.values():
        for ds, _ in amts:
            all_dates.add(ds)
    cal = sorted(d for d in all_dates
                 if start_d.isoformat() <= d <= end_d.isoformat())
    by_month = {}
    for d in cal:
        by_month[d[:7]] = d
    month_ends = [by_month[m] for m in sorted(by_month.keys())]
    log.info("trading_days_in_range=%d, monthly_snapshots=%d",
             len(cal), len(month_ends))

    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)

    index = {
        "label":          args.label,
        "n":              args.n,
        "rank_window":    args.rank_window,
        "bars_min":       args.bars_min,
        "history_window": args.history_window,
        "start_date":     args.start_date,
        "end_date":       args.end_date,
        "snapshots":      [],
    }

    union_set = set()
    valid_snap_count = 0
    churn = []
    prev_set = None

    for as_of in month_ends:
        win_dates_global = sorted(d for d in all_dates if d <= as_of)
        rank_win = win_dates_global[-args.rank_window:]
        hist_win = win_dates_global[-args.history_window:]
        if not rank_win:
            csv_name = "core_%d_%s.csv" % (args.n, as_of.replace("-", ""))
            csv_path = (out_dir + "/" + csv_name).replace("\\", "/")
            with open(csv_path, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["code", "name", "sector", "enabled"])
            index["snapshots"].append({
                "as_of":     as_of,
                "csv":       csv_path,
                "n_chosen":  0,
                "win_start": "",
                "win_end":   "",
                "top10":     [],
            })
            log.info("snapshot %s: empty (no rank window)", as_of)
            continue
        rank_start = rank_win[0]
        hist_start = hist_win[0] if hist_win else rank_start

        scored = []
        for code, amts in code_amts.items():
            n_hist = sum(1 for ds, _ in amts if hist_start <= ds <= as_of)
            if n_hist < args.bars_min:
                continue
            amt_sum = sum(a for ds, a in amts if rank_start <= ds <= as_of)
            scored.append((code, n_hist, amt_sum))
        scored.sort(key=lambda r: r[2], reverse=True)
        chosen = scored[: args.n]

        csv_name = "core_%d_%s.csv" % (args.n, as_of.replace("-", ""))
        csv_path = (out_dir + "/" + csv_name).replace("\\", "/")
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["code", "name", "sector", "enabled"])
            for code, _n, _a in chosen:
                w.writerow([code, name_map.get(code, ""), "", "true"])

        chosen_set = set(c for c, _, _ in chosen)
        if prev_set is not None:
            added = len(chosen_set - prev_set)
            removed = len(prev_set - chosen_set)
            churn.append({"as_of": as_of, "added": added, "removed": removed})
        prev_set = chosen_set
        union_set |= chosen_set
        if chosen:
            valid_snap_count += 1

        index["snapshots"].append({
            "as_of":     as_of,
            "csv":       csv_path,
            "n_chosen":  len(chosen),
            "win_start": rank_start,
            "win_end":   as_of,
            "top10": [
                {"code": c, "n_bars": int(n), "amount_sum": round(float(a), 2)}
                for c, n, a in chosen[:10]
            ],
        })
        log.info("snapshot %s: %d codes (rank_win=%s..%s)",
                 as_of, len(chosen), rank_start, as_of)

    union_codes = sorted(union_set)
    union_csv_path = (out_dir + "/__union.csv").replace("\\", "/")
    with open(union_csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["code", "name", "sector", "enabled"])
        for code in union_codes:
            w.writerow([code, name_map.get(code, ""), "", "true"])
    log.info("union: %d codes -> %s", len(union_codes), union_csv_path)

    index["union_size"] = len(union_codes)
    index["union_csv"] = union_csv_path
    index["valid_snapshots"] = valid_snap_count
    index["monthly_churn"] = churn
    if churn:
        avg_added = sum(c["added"] for c in churn) / float(len(churn))
        index["avg_monthly_churn_added"] = round(avg_added, 2)
    else:
        index["avg_monthly_churn_added"] = 0

    index_path = (out_dir + "/index.json").replace("\\", "/")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2, default=str)
    log.info("index: %s", index_path)

    finished_at = _dt.datetime.now()
    report = {
        "generated_at":             finished_at.isoformat(timespec="seconds"),
        "label":                    args.label,
        "out_dir":                  out_dir,
        "index_path":               index_path,
        "union_csv":                union_csv_path,
        "union_size":               len(union_codes),
        "valid_snapshots":          valid_snap_count,
        "n_requested":              args.n,
        "rank_window":              args.rank_window,
        "bars_min":                 args.bars_min,
        "history_window":           args.history_window,
        "start_date":               args.start_date,
        "end_date":                 args.end_date,
        "raw_pool_size":            len(raw_codes),
        "candidates_after_bj_st":   len(cand_codes),
        "excluded_bj":              excluded_bj,
        "excluded_st":              excluded_st,
        "parsed_codes":             len(code_amts),
        "trading_days_in_range":    len(cal),
        "monthly_snapshots":        len(month_ends),
        "download_seconds":         round(dl_secs, 1),
        "fetch_seconds":            round(fetch_secs, 1),
        "duration_seconds":         round(
            (finished_at - started_at).total_seconds(), 1),
        "writes_to_qmt_duckdb":     False,
    }
    if not os.path.isdir(args.report_dir):
        os.makedirs(args.report_dir)
    rep_path = (args.report_dir + "/build_full_a_pit_manifest_"
                + finished_at.strftime("%Y%m%d_%H%M%S") + ".json"
                ).replace("\\", "/")
    with open(rep_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    log.info("report: %s", rep_path)
    log.info("DONE: union=%d valid_snapshots=%d duration=%.1fs",
             len(union_codes), valid_snap_count, report["duration_seconds"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
