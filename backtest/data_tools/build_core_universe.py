# coding: utf-8
"""build_core_universe.py — 生成 core_N universe（v0.3 P0-B1 起）。

口径（agent_hub/.../08 Hermes 验收 §四 §10）：
  1) 候选池：xtquant.get_stock_list_in_sector('沪深A股')，排除北交所、ST/*ST、退市整理
  2) bars >= 120：从 lookback 起到 end_date，至少 120 个 1d bar
  3) 排序：近 60 个交易日（按 end_date 倒推）amount 之和降序，取 top N

**严格独立 CLI**：临时下载到内存，不写 DuckDB；不调用 passorder/xttrader；
仅向输出 CSV 写盘（默认 D:/QMT_STRATEGIES/backtest/data/universe/core_<N>.csv）。
"""
import argparse
import csv
import datetime as _dt
import json
import logging
import os
import sys

log = logging.getLogger("build_core_universe")

DEFAULT_OUT_DIR = "D:/QMT_STRATEGIES/backtest/data/universe"
DEFAULT_REPORT_DIR = "F:/backtest_workspace/data/sync_reports"
DEFAULT_BARS_MIN = 120
DEFAULT_RANK_WINDOW = 60
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
    p = argparse.ArgumentParser(description="Generate core_N universe CSV.")
    p.add_argument("--n", type=int, default=100,
                   help="universe size (default 100)")
    p.add_argument("--end-date", required=True, dest="end_date",
                   help="YYYY-MM-DD; 60-day amount window ends here")
    p.add_argument("--lookback-days", type=int, default=180, dest="lookback_days",
                   help="calendar days back from end-date (default 180)")
    p.add_argument("--bars-min", type=int, default=DEFAULT_BARS_MIN,
                   dest="bars_min")
    p.add_argument("--rank-window", type=int, default=DEFAULT_RANK_WINDOW,
                   dest="rank_window")
    p.add_argument("--out", default=None,
                   help="output CSV path (default core_<N>.csv under universe dir)")
    p.add_argument("--report-dir", default=DEFAULT_REPORT_DIR, dest="report_dir")
    p.add_argument("--limit-candidates", type=int, default=0,
                   dest="limit_candidates",
                   help="debug: cap candidate pool size (0=no cap)")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    end_d = _parse_date(args.end_date)
    start_d = end_d - _dt.timedelta(days=args.lookback_days)
    out_path = args.out or os.path.join(DEFAULT_OUT_DIR,
                                        "core_%d.csv" % args.n).replace("\\", "/")

    assert out_path.lower().startswith("d:/qmt_strategies/"), \
        "universe csv must live under D:/QMT_STRATEGIES/ (got: %s)" % out_path
    assert "金策智算" not in out_path, "must not write under 金策智算"
    assert args.report_dir.replace("\\", "/").lower().startswith(
        "f:/backtest_workspace/"), "report dir must be F:/backtest_workspace/"

    started_at = _dt.datetime.now()
    log.info("end_date=%s lookback=%dd bars_min=%d rank_window=%d",
             end_d, args.lookback_days, args.bars_min, args.rank_window)

    from xtquant import xtdata
    log.info("loading 沪深A股 stock list...")
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
    log.info("after BJ/ST filter: %d (BJ excluded=%d, ST excluded=%d)",
             len(candidates), excluded_bj, excluded_st)

    if args.limit_candidates > 0 and len(candidates) > args.limit_candidates:
        candidates = candidates[:args.limit_candidates]
        log.warning("DEBUG: candidate pool capped at %d", len(candidates))

    cand_codes = [c["code"] for c in candidates]
    name_map = {c["code"]: c["name"] for c in candidates}

    s_yyyymmdd = _yyyymmdd(start_d)
    e_yyyymmdd = _yyyymmdd(end_d)

    log.info("download_history_data2: %d codes, %s..%s",
             len(cand_codes), s_yyyymmdd, e_yyyymmdd)
    t0 = _dt.datetime.now()
    try:
        xtdata.download_history_data2(
            stock_list=cand_codes, period="1d",
            start_time=s_yyyymmdd, end_time=e_yyyymmdd,
            incrementally=False)
    except TypeError:
        xtdata.download_history_data2(cand_codes, "1d", s_yyyymmdd, e_yyyymmdd)
    dt_dl = (_dt.datetime.now() - t0).total_seconds()
    log.info("download_history_data2 done in %.1fs", dt_dl)

    log.info("get_market_data_ex (close+amount, dividend_type=none)...")
    t1 = _dt.datetime.now()
    d = xtdata.get_market_data_ex(
        field_list=["time", "close", "amount"],
        stock_list=cand_codes,
        period="1d",
        start_time=s_yyyymmdd,
        end_time=e_yyyymmdd,
        dividend_type="none",
        fill_data=False,
    )
    dt_get = (_dt.datetime.now() - t1).total_seconds()
    log.info("get_market_data_ex done in %.1fs", dt_get)

    survivors = []
    dropped_bars = 0
    dropped_no_data = 0
    for code in cand_codes:
        df = d.get(code) if isinstance(d, dict) else None
        if df is None or len(df) == 0:
            dropped_no_data += 1
            continue
        n_bars = int(len(df))
        if n_bars < args.bars_min:
            dropped_bars += 1
            continue
        tail = df.tail(args.rank_window)
        try:
            amt_sum = float(tail["amount"].sum())
        except Exception:
            amt_sum = 0.0
        survivors.append({
            "code": code,
            "name": name_map.get(code, ""),
            "n_bars": n_bars,
            "amount_sum": amt_sum,
        })
    log.info("after bars_min=%d filter: %d (no_data=%d, bars<min=%d)",
             args.bars_min, len(survivors), dropped_no_data, dropped_bars)

    survivors.sort(key=lambda r: r["amount_sum"], reverse=True)
    chosen = survivors[: args.n]
    if len(chosen) < args.n:
        log.warning("only %d codes survived; requested %d", len(chosen), args.n)

    out_dir = os.path.dirname(out_path)
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["code", "name", "sector", "enabled"])
        for r in chosen:
            w.writerow([r["code"], r["name"], "", "true"])
    log.info("wrote universe csv: %s (%d rows)", out_path, len(chosen))

    finished_at = _dt.datetime.now()
    report = {
        "generated_at": finished_at.isoformat(timespec="seconds"),
        "end_date": args.end_date,
        "lookback_days": args.lookback_days,
        "bars_min": args.bars_min,
        "rank_window": args.rank_window,
        "n_requested": args.n,
        "n_chosen": len(chosen),
        "raw_pool_size": len(raw_codes),
        "candidates_after_bj_st_filter": len(cand_codes),
        "excluded_bj": excluded_bj,
        "excluded_st": excluded_st,
        "dropped_no_data": dropped_no_data,
        "dropped_bars_below_min": dropped_bars,
        "survivors_after_bars_filter": len(survivors),
        "out_csv": out_path,
        "duration_seconds": round((finished_at - started_at).total_seconds(), 2),
        "top10_preview": [
            {"code": r["code"], "name": r["name"],
             "n_bars": r["n_bars"],
             "amount_sum_60d": round(r["amount_sum"], 2)}
            for r in chosen[:10]
        ],
    }
    if not os.path.isdir(args.report_dir):
        os.makedirs(args.report_dir)
    rep_path = os.path.join(
        args.report_dir,
        "build_core_universe_" + finished_at.strftime("%Y%m%d_%H%M%S") + ".json"
    ).replace("\\", "/")
    with open(rep_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    log.info("report: %s", rep_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
