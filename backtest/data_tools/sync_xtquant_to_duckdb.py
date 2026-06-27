# coding: utf-8
"""xtquant -> 项目自管 DuckDB 历史日线同步脚本（v0.3 P0-B 起）。

本脚本独立 CLI，**严禁进入** reader/engine/run_backtest/run_batch 的 import 链。
设计文档：D:/QMT_STRATEGIES/agent_hub/2026-06-14_backtest_v03/04_xtquant_sync_design.md

边界（02_hermes_v03_data_sync_update §四）：
  * 只拉历史行情；不调 passorder / xttrader / 任何交易接口
  * 不写 F:/金策智算/、不以读写打开金策智算库
  * 大产物只写 F:/backtest_workspace/data/...

验收（Hermes §七 + 设计 §11）：B0 通过条件参见 04 设计文档第 11 节。
"""
import argparse
import csv
import datetime as _dt
import json
import logging
import os
import sys
import uuid

log = logging.getLogger("sync_xtquant")

DEFAULT_TARGET_DB    = "F:/backtest_workspace/data/duckdb/qmt_market_data.duckdb"
DEFAULT_REPORT_DIR   = "F:/backtest_workspace/data/sync_reports"
DEFAULT_PERIOD       = "1d"
DEFAULT_ADJUSTMENT   = "hfq"
MAX_CODES_HARD_LIMIT = 400  # P2.1.b: raised from 200 by Hermes 2026-06-14
                              # (manual gating still required via --max-codes)

ADJUSTMENT_TO_DIVIDEND = {
    "hfq":  "back",
    "none": "none",
}


def _read_universe(csv_path):
    if not os.path.isfile(csv_path):
        raise FileNotFoundError("universe csv not found: " + csv_path)
    codes = []
    with open(csv_path, "r", encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        for row in rdr:
            code = (row.get("code") or "").strip()
            if not code:
                continue
            enabled = (row.get("enabled") or "true").strip().lower()
            if enabled in ("false", "0", "no"):
                continue
            codes.append(code)
    return codes


def _safety_assert(args, codes):
    target = args.target.replace("\\", "/")
    report_dir = args.report_dir.replace("\\", "/")
    assert "金策智算" not in target, "target db MUST NOT live under 金策智算"
    assert target.lower().startswith("f:/backtest_workspace/"), \
        "target db must be under F:/backtest_workspace/ (got: %s)" % target
    assert report_dir.lower().startswith("f:/backtest_workspace/"), \
        "report dir must be under F:/backtest_workspace/ (got: %s)" % report_dir
    assert args.period == "1d", "v0.3 only supports period=1d"
    assert args.adjustment in ADJUSTMENT_TO_DIVIDEND, \
        "adjustment must be hfq or none, got: " + args.adjustment
    assert len(codes) <= args.max_codes <= MAX_CODES_HARD_LIMIT, \
        "code count %d > max_codes %d (hard limit %d)" % (
            len(codes), args.max_codes, MAX_CODES_HARD_LIMIT)
    assert len(codes) >= 1, "no codes after filtering universe csv"


def _ensure_dirs(target_db, report_dir):
    db_dir = os.path.dirname(target_db)
    if db_dir and not os.path.isdir(db_dir):
        os.makedirs(db_dir)
    if report_dir and not os.path.isdir(report_dir):
        os.makedirs(report_dir)


def _ddl(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dat_day (
            code        VARCHAR    NOT NULL,
            trade_date  DATE       NOT NULL,
            open        DOUBLE,
            high        DOUBLE,
            low         DOUBLE,
            close       DOUBLE,
            vol         BIGINT,
            amount      DOUBLE,
            adjustment  VARCHAR    NOT NULL,
            source      VARCHAR    NOT NULL,
            synced_at   TIMESTAMP  NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_dat_day_code_date ON dat_day(code, trade_date)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sync_log (
            sync_id          VARCHAR    NOT NULL,
            scope            VARCHAR    NOT NULL,
            source           VARCHAR    NOT NULL,
            start_date       DATE       NOT NULL,
            end_date         DATE       NOT NULL,
            period           VARCHAR    NOT NULL,
            adjustment       VARCHAR    NOT NULL,
            started_at       TIMESTAMP  NOT NULL,
            finished_at      TIMESTAMP,
            duration_seconds DOUBLE,
            n_codes_in       INTEGER,
            n_codes_ok       INTEGER,
            n_rows_inserted  BIGINT,
            n_rows_updated   BIGINT,
            n_rows_skipped   BIGINT,
            failed_codes     VARCHAR,
            status           VARCHAR    NOT NULL,
            notes            VARCHAR
        )
    """)


def _xtquant_probe():
    """Return (xtdata_module, xtquant_version, miniqmt_status)."""
    from xtquant import xtdata
    import xtquant
    version = getattr(xtquant, "__version__", "unknown")
    try:
        client = xtdata.get_client()
        connected = bool(client) and getattr(client, "is_connected", lambda: True)()
        status = "running" if connected else "not_detected"
    except Exception as e:
        status = "error:" + type(e).__name__
    return xtdata, version, status


VOLUME_PROBE_CODES = ("000001.SZ", "600519.SH", "300750.SZ")
VOLUME_PROBE_FIELDS = ["time", "open", "high", "low", "close", "volume", "amount"]


def _probe_volume_unit(xtdata, start_yyyymmdd, end_yyyymmdd,
                      probe_codes=None):
    """硬验证 xtquant vol 单位。返回 evidence dict（不抛异常）。

    用 dividend_type='none' 拉 raw 数据，ratio = amount / vol_raw / close_raw。
      ratio≈100 → "lot"  (multiplier=100)
      ratio≈1   → "share"(multiplier=1)
      其它      → "unknown"(multiplier=None)
    """
    codes = list(probe_codes) if probe_codes else list(VOLUME_PROBE_CODES)
    obs = []
    ratios = []
    for code in codes:
        try:
            xtdata.download_history_data(
                code, "1d", start_yyyymmdd, end_yyyymmdd, incrementally=False)
        except Exception as e:
            log.warning("probe download failed for %s: %r", code, e)
            continue
        try:
            d = xtdata.get_market_data_ex(
                field_list=VOLUME_PROBE_FIELDS,
                stock_list=[code],
                period="1d",
                start_time=start_yyyymmdd,
                end_time=end_yyyymmdd,
                dividend_type="none",
                fill_data=False,
            )
        except Exception as e:
            log.warning("probe get_market_data_ex failed for %s: %r", code, e)
            continue
        df = d.get(code) if isinstance(d, dict) else None
        if df is None or len(df) == 0:
            continue
        sample = df.head(5)
        for _, row in sample.iterrows():
            try:
                close = float(row["close"])
                vol_raw = float(row["volume"])
                amt = float(row["amount"])
            except Exception:
                continue
            if vol_raw == 0 or close == 0:
                continue
            ratio = amt / vol_raw / close
            obs.append({
                "code": code, "time": int(row["time"]),
                "close_raw": close, "vol_raw": vol_raw, "amount": amt,
                "ratio_amount_div_vol_div_close": round(ratio, 4),
            })
            ratios.append(ratio)

    if not ratios:
        unit, multiplier = "unknown", None
        mean_r = mn = mx = None
    else:
        mean_r = sum(ratios) / len(ratios)
        mn, mx = min(ratios), max(ratios)
        if 80 <= mean_r <= 120 and all(50 <= r <= 200 for r in ratios):
            unit, multiplier = "lot", 100
        elif 0.5 <= mean_r <= 1.5 and all(0.3 <= r <= 2.0 for r in ratios):
            unit, multiplier = "share", 1
        else:
            unit, multiplier = "unknown", None

    return {
        "method": "amount_div_vol_div_close",
        "dividend_type": "none",
        "sample_codes": codes,
        "sample_range": "%s..%s" % (start_yyyymmdd, end_yyyymmdd),
        "n_observations": len(obs),
        "mean_ratio": round(mean_r, 4) if mean_r is not None else None,
        "min_ratio":  round(mn, 4)     if mn     is not None else None,
        "max_ratio":  round(mx, 4)     if mx     is not None else None,
        "inferred_source_volume_unit": unit,
        "stored_volume_unit": "share",
        "volume_multiplier": multiplier,
        "observations": obs,
    }


def _normalize_market_df(code, df, adjustment, source, synced_at,
                         volume_multiplier=1):
    """xtquant get_market_data_ex 返回的 DataFrame 转标准化行列表。

    df columns 期望: time, open, high, low, close, volume, amount
    time 单位: 1d 周期下为毫秒时间戳（设计 §6 注：首只 code 实测核对）。
    volume_multiplier: 落库前对 vol 的乘数（lot→100, share→1）。
    """
    import pandas as pd
    if df is None or len(df) == 0:
        return [], "empty_dataframe"
    cols = set(df.columns)
    needed = {"time", "open", "high", "low", "close", "volume", "amount"}
    missing = needed - cols
    if missing:
        return [], "missing_columns:" + ",".join(sorted(missing))

    t_raw = df["time"].iloc[0]
    if t_raw > 1e12:
        dates = pd.to_datetime(df["time"], unit="ms").dt.date
    elif t_raw > 1e9:
        dates = pd.to_datetime(df["time"], unit="s").dt.date
    else:
        dates = pd.to_datetime(df["time"].astype(str), format="%Y%m%d").dt.date

    vol_stored = (df["volume"].astype("int64") * int(volume_multiplier))

    out_df = pd.DataFrame({
        "code":       code,
        "trade_date": dates,
        "open":       df["open"].astype(float),
        "high":       df["high"].astype(float),
        "low":        df["low"].astype(float),
        "close":      df["close"].astype(float),
        "vol":        vol_stored,
        "amount":     df["amount"].astype(float),
        "adjustment": adjustment,
        "source":     source,
        "synced_at":  synced_at,
    })
    out_df = out_df.dropna(subset=["open", "high", "low", "close"])
    out_df = out_df[~((out_df["vol"] == 0) & (out_df["amount"] == 0))]
    rows = list(out_df.itertuples(index=False, name=None))
    return rows, "ok"


def _upsert_code(conn, code, rows, adjustment, source, start_date, end_date):
    """DELETE 匹配键 + INSERT 清洗后行（设计 §4.2）。返回 (n_inserted, n_updated)。"""
    deleted = conn.execute(
        "SELECT COUNT(*) FROM dat_day "
        "WHERE code = ? AND adjustment = ? AND source = ? "
        "  AND trade_date BETWEEN ? AND ?",
        [code, adjustment, source, start_date, end_date]
    ).fetchone()[0]
    conn.execute(
        "DELETE FROM dat_day "
        "WHERE code = ? AND adjustment = ? AND source = ? "
        "  AND trade_date BETWEEN ? AND ?",
        [code, adjustment, source, start_date, end_date]
    )
    if rows:
        conn.executemany(
            "INSERT INTO dat_day "
            "(code, trade_date, open, high, low, close, vol, amount, "
            " adjustment, source, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows
        )
    inserted = len(rows)
    updated = min(deleted, inserted)
    return inserted, updated


def _gen_sync_id():
    now = _dt.datetime.now()
    return now.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]


def _format_date(s):
    return _dt.datetime.strptime(s, "%Y-%m-%d").date()


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Sync xtquant historical 1d bars to project-owned DuckDB.")
    p.add_argument("--scope", required=True,
                   help='e.g. "B0_smoke10", "B1_core100"')
    p.add_argument("--universe", required=True,
                   help="path to universe csv")
    p.add_argument("--start-date", required=True, dest="start_date",
                   help="YYYY-MM-DD")
    p.add_argument("--end-date", required=True, dest="end_date",
                   help="YYYY-MM-DD")
    p.add_argument("--period", default=DEFAULT_PERIOD)
    p.add_argument("--adjustment", default=DEFAULT_ADJUSTMENT)
    p.add_argument("--target", default=DEFAULT_TARGET_DB)
    p.add_argument("--report-dir", default=DEFAULT_REPORT_DIR, dest="report_dir")
    p.add_argument("--max-codes", type=int, default=MAX_CODES_HARD_LIMIT,
                   dest="max_codes")
    p.add_argument("--dry-run", action="store_true", dest="dry_run")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    start_d = _format_date(args.start_date)
    end_d   = _format_date(args.end_date)
    assert start_d <= end_d, "start_date must be <= end_date"

    codes = _read_universe(args.universe)
    _safety_assert(args, codes)
    _ensure_dirs(args.target, args.report_dir)

    sync_id = _gen_sync_id()
    started_at = _dt.datetime.now()

    log.info("sync_id=%s scope=%s codes=%d range=%s..%s adjustment=%s",
             sync_id, args.scope, len(codes), start_d, end_d, args.adjustment)

    xtdata, xtq_version, miniqmt_status = _xtquant_probe()
    log.info("xtquant=%s miniqmt_status=%s", xtq_version, miniqmt_status)

    if miniqmt_status != "running":
        report = _build_failed_report(
            sync_id, args, codes, started_at,
            xtq_version, miniqmt_status,
            "miniqmt_not_running")
        _write_report(args.report_dir, sync_id, report)
        log.error("MiniQMT not running; aborted.")
        return 1

    probe_start = args.start_date.replace("-", "")
    probe_end = args.end_date.replace("-", "")
    volume_evidence = _probe_volume_unit(xtdata, probe_start, probe_end)
    inferred_unit = volume_evidence["inferred_source_volume_unit"]
    volume_multiplier = volume_evidence["volume_multiplier"]
    log.info("volume_unit_evidence: inferred=%s multiplier=%s mean_ratio=%s n=%d",
             inferred_unit, volume_multiplier,
             volume_evidence["mean_ratio"], volume_evidence["n_observations"])

    if inferred_unit == "unknown" or volume_multiplier is None:
        report = _build_failed_report(
            sync_id, args, codes, started_at,
            xtq_version, miniqmt_status,
            "volume_unit_unknown")
        report["volume_unit_evidence"] = volume_evidence
        _write_report(args.report_dir, sync_id, report)
        log.error("volume unit could not be inferred (mean_ratio=%s); aborted.",
                  volume_evidence["mean_ratio"])
        return 1

    if args.dry_run:
        log.info("dry-run; no DB write, no xtquant download.")
        return 0

    import duckdb
    conn = duckdb.connect(args.target, read_only=False)
    try:
        _ddl(conn)
    except Exception as e:
        conn.close()
        raise

    per_code = []
    failed_codes = []
    rows_inserted_total = 0
    rows_updated_total  = 0

    dividend_type = ADJUSTMENT_TO_DIVIDEND[args.adjustment]
    actual_adjustment = dividend_type
    field_list = ["time", "open", "high", "low", "close", "volume", "amount"]

    for i, code in enumerate(codes, 1):
        code_synced_at = _dt.datetime.now()
        log.info("[%d/%d] %s downloading...", i, len(codes), code)
        try:
            xtdata.download_history_data(
                code, args.period,
                args.start_date.replace("-", ""),
                args.end_date.replace("-", ""),
                incrementally=False)
        except Exception as e:
            log.warning("download_history_data failed for %s: %r", code, e)
            failed_codes.append(code)
            per_code.append({
                "code": code, "status": "download_failed",
                "error": type(e).__name__ + ": " + str(e)})
            continue

        try:
            d = xtdata.get_market_data_ex(
                field_list=field_list,
                stock_list=[code],
                period=args.period,
                start_time=args.start_date.replace("-", ""),
                end_time=args.end_date.replace("-", ""),
                dividend_type=dividend_type,
                fill_data=False,
            )
            df = d.get(code) if isinstance(d, dict) else None
        except Exception as e:
            log.warning("get_market_data_ex failed for %s: %r", code, e)
            failed_codes.append(code)
            per_code.append({
                "code": code, "status": "get_market_data_failed",
                "error": type(e).__name__ + ": " + str(e)})
            continue

        rows, msg = _normalize_market_df(
            code, df, args.adjustment, "xtquant", code_synced_at,
            volume_multiplier=volume_multiplier)

        if msg != "ok":
            failed_codes.append(code)
            per_code.append({"code": code, "status": "normalize_failed", "error": msg})
            continue

        try:
            conn.execute("BEGIN")
            inserted, updated = _upsert_code(
                conn, code, rows, args.adjustment, "xtquant", start_d, end_d)
            conn.execute("COMMIT")
        except Exception as e:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            log.error("upsert failed for %s: %r", code, e)
            failed_codes.append(code)
            per_code.append({
                "code": code, "status": "upsert_failed",
                "error": type(e).__name__ + ": " + str(e)})
            continue

        rows_inserted_total += inserted
        rows_updated_total  += updated
        if rows:
            mn = min(r[1] for r in rows)
            mx = max(r[1] for r in rows)
        else:
            mn = mx = None
        per_code.append({
            "code": code, "status": "ok",
            "n_bars": inserted,
            "min_date": mn.isoformat() if mn else None,
            "max_date": mx.isoformat() if mx else None,
        })

    finished_at = _dt.datetime.now()
    duration = (finished_at - started_at).total_seconds()
    success_count = sum(1 for r in per_code if r["status"] == "ok")
    failed_count  = len(codes) - success_count

    actual_min = conn.execute(
        "SELECT MIN(trade_date), MAX(trade_date), COUNT(DISTINCT trade_date) "
        "FROM dat_day WHERE source = 'xtquant' "
        "  AND adjustment = ? AND code IN ({})".format(
            ",".join(["?"] * len(codes))),
        [args.adjustment] + codes).fetchone()
    n_codes_total, n_rows_total = conn.execute(
        "SELECT COUNT(DISTINCT code), COUNT(*) FROM dat_day").fetchone()
    size_after = os.path.getsize(args.target) if os.path.isfile(args.target) else 0

    if failed_count == 0:
        status = "ok"
    elif success_count == 0:
        status = "failed"
    else:
        status = "partial"

    conn.execute(
        "INSERT INTO sync_log "
        "(sync_id, scope, source, start_date, end_date, period, adjustment, "
        " started_at, finished_at, duration_seconds, n_codes_in, n_codes_ok, "
        " n_rows_inserted, n_rows_updated, n_rows_skipped, failed_codes, status, notes) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [sync_id, args.scope, "xtquant", start_d, end_d, args.period,
         args.adjustment, started_at, finished_at, duration,
         len(codes), success_count, rows_inserted_total, rows_updated_total, 0,
         json.dumps(failed_codes), status, ""])
    conn.close()

    report = {
        "sync_id": sync_id,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "duration_seconds": round(duration, 3),
        "input": {
            "scope": args.scope,
            "universe_file": args.universe,
            "universe_size": len(codes),
            "codes": codes,
            "start_date": args.start_date,
            "end_date": args.end_date,
            "period": args.period,
            "requested_adjustment": args.adjustment,
        },
        "actual": {
            "adjustment": actual_adjustment,
            "xtquant_api_used": "download_history_data + get_market_data_ex(dividend_type=" + dividend_type + ")",
            "xtquant_version": xtq_version,
            "miniqmt_status": miniqmt_status,
        },
        "result": {
            "success_count": success_count,
            "failed_count": failed_count,
            "failed_codes": failed_codes,
            "rows_inserted": rows_inserted_total,
            "rows_updated":  rows_updated_total,
            "rows_skipped_duplicate": 0,
            "min_date_actual": actual_min[0].isoformat() if actual_min and actual_min[0] else None,
            "max_date_actual": actual_min[1].isoformat() if actual_min and actual_min[1] else None,
            "n_trading_days_actual": int(actual_min[2]) if actual_min and actual_min[2] else 0,
            "per_code": per_code,
        },
        "target_db": {
            "path": args.target.replace("\\", "/"),
            "size_after_bytes": size_after,
            "n_codes_total": int(n_codes_total) if n_codes_total else 0,
            "n_rows_total": int(n_rows_total) if n_rows_total else 0,
        },
        "volume_unit_evidence": volume_evidence,
        "sync_log_inserted": True,
        "status": status,
    }

    _write_report(args.report_dir, sync_id, report)
    log.info("sync %s; success=%d/%d; rows_inserted=%d rows_updated=%d duration=%.1fs",
             status, success_count, len(codes),
             rows_inserted_total, rows_updated_total, duration)
    return 0 if status == "ok" else 1


def _build_failed_report(sync_id, args, codes, started_at,
                         xtq_version, miniqmt_status, reason):
    finished_at = _dt.datetime.now()
    return {
        "sync_id": sync_id,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "duration_seconds": (finished_at - started_at).total_seconds(),
        "input": {
            "scope": args.scope,
            "universe_file": args.universe,
            "universe_size": len(codes),
            "codes": codes,
            "start_date": args.start_date,
            "end_date": args.end_date,
            "period": args.period,
            "requested_adjustment": args.adjustment,
        },
        "actual": {
            "adjustment": None,
            "xtquant_api_used": None,
            "xtquant_version": xtq_version,
            "miniqmt_status": miniqmt_status,
        },
        "result": {
            "success_count": 0,
            "failed_count": len(codes),
            "failed_codes": codes,
            "rows_inserted": 0, "rows_updated": 0, "rows_skipped_duplicate": 0,
            "min_date_actual": None, "max_date_actual": None,
            "n_trading_days_actual": 0,
            "per_code": [],
        },
        "target_db": {
            "path": args.target.replace("\\", "/"),
            "size_after_bytes": 0,
            "n_codes_total": 0, "n_rows_total": 0,
        },
        "sync_log_inserted": False,
        "status": "failed",
        "abort_reason": reason,
    }


def _write_report(report_dir, sync_id, report):
    if not os.path.isdir(report_dir):
        os.makedirs(report_dir)
    out = os.path.join(report_dir, "sync_report_" + sync_id + ".json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    log.info("sync_report: %s", out)
    return out


if __name__ == "__main__":
    sys.exit(main())
