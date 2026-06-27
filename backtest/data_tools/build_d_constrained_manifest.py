# coding: utf-8
"""build_d_constrained_manifest.py -- derive D-stage PIT manifests by applying
huicexitong industry / circ_mv constraints to the P2.1.b base snapshots.

This script does NOT touch strategy_core / evaluate_day / 6-file schema. It only
produces a new manifest directory that batch_run can consume via the
universe.pit_manifest config knob.

Boundary:
  * Reads: P2.1.b __union/index/snapshot CSVs (D:/), huice gpsj.duckdb (E:/)
  * Writes: a new manifest dir under D:/.../pit_manifests/<label>/  (code disk)
            + a derive report under F:/backtest_workspace/data/sync_reports/
  * Stays out of reader/engine import chains.

Usage:
  # D1: industry-cap = 10 (each SW L1 industry contributes <= 10 codes per snapshot)
  py -3.10 build_d_constrained_manifest.py --variant industry_cap10
  # D2: circ-mv floor = 5,000,000 (wan yuan) = 50 亿
  py -3.10 build_d_constrained_manifest.py --variant mv_floor_50yi
"""
import argparse
import csv
import datetime as _dt
import json
import logging
import os
import sys

sys.path.insert(0,
    r"C:\Users\Administrator\AppData\Local\Programs\Python\Python310\Lib\site-packages")
sys.path.insert(0, r"D:\QMT_STRATEGIES")

from backtest.data_tools.huicexitong_reader import HuicexitongReader

DEFAULT_BASE_LABEL = "p2_1b_full_a_top100_monthly"
DEFAULT_BASE_ROOT = "D:/QMT_STRATEGIES/backtest/data/universe/pit_manifests"
DEFAULT_REPORT_DIR = "F:/backtest_workspace/data/sync_reports"

log = logging.getLogger("build_d_manifest")


def _read_snapshot_csv(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        rd = csv.DictReader(f)
        for r in rd:
            rows.append(r)
    return rows


def _write_snapshot_csv(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["code", "name", "sector", "enabled"])
        for r in rows:
            w.writerow([r["code"], r.get("name", ""),
                        r.get("sector", ""), r.get("enabled", "true")])


def _load_industry_map(codes):
    hr = HuicexitongReader()
    try:
        rows = hr.load_industry_map(list(codes), latest_only=True)
    finally:
        hr.close()
    out = {}
    for r in rows:
        c = r["code"]
        if c and c not in out:
            out[c] = {"l1_code": r["l1_code"], "l1_name": r["l1_name"]}
    return out


def _load_latest_circ_mv(codes, end_date):
    """For each code, return the most recent circ_mv_wan in [start..end_date]
    (fallback: most recent across full range). Used for D2 mv-floor.
    """
    hr = HuicexitongReader()
    try:
        rows = hr.load_daily_aux(list(codes), "2025-01-01", end_date)
    finally:
        hr.close()
    latest = {}
    for r in rows:
        c = r["code"]
        mv = r["circ_mv_wan"]
        d = r["date"]
        if mv is None:
            continue
        prev = latest.get(c)
        if prev is None or d > prev[1]:
            latest[c] = (mv, d)
    return {c: v[0] for c, v in latest.items()}


def _apply_industry_cap(rows, industry_map, cap):
    counts = {}
    out = []
    for r in rows:
        code = r["code"]
        ind = industry_map.get(code, {}).get("l1_code") or "<unmapped>"
        n = counts.get(ind, 0)
        if n >= cap:
            continue
        counts[ind] = n + 1
        out.append(r)
    return out


def _apply_mv_floor(rows, code_to_mv, floor_wan):
    out = []
    for r in rows:
        mv = code_to_mv.get(r["code"])
        if mv is None or mv < floor_wan:
            continue
        out.append(r)
    return out


VARIANTS = {
    "industry_cap10": {
        "label": "p2_1b_d_industry_cap10_monthly",
        "description": "P2.1.b base + SW L1 industry cap=10 per snapshot",
        "industry_cap": 10,
    },
    "mv_floor_50yi": {
        "label": "p2_1b_d_mv_floor_50yi_monthly",
        "description": "P2.1.b base + circ_mv floor 50 亿 (5,000,000 wan)",
        "mv_floor_wan": 5_000_000.0,
    },
}


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--variant", required=True, choices=list(VARIANTS.keys()))
    p.add_argument("--base-label", default=DEFAULT_BASE_LABEL)
    p.add_argument("--base-root", default=DEFAULT_BASE_ROOT)
    p.add_argument("--report-dir", default=DEFAULT_REPORT_DIR)
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    started = _dt.datetime.now()
    spec = VARIANTS[args.variant]
    base_dir = args.base_root + "/" + args.base_label
    base_index = base_dir + "/index.json"
    if not os.path.isfile(base_index):
        raise FileNotFoundError("base index missing: " + base_index)
    with open(base_index, "r", encoding="utf-8") as f:
        base = json.load(f)
    out_label = spec["label"]
    out_dir = args.base_root + "/" + out_label
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)

    union_path = base_dir + "/__union.csv"
    union_codes = [r["code"] for r in _read_snapshot_csv(union_path)]
    log.info("base union: %d codes", len(union_codes))

    industry_map = _load_industry_map(union_codes)
    log.info("loaded industry map: %d/%d codes", len(industry_map),
             len(union_codes))

    code_to_mv = None
    if "mv_floor_wan" in spec:
        code_to_mv = _load_latest_circ_mv(union_codes, base.get("end_date"))
        log.info("loaded circ_mv: %d codes have non-null mv",
                 len(code_to_mv))

    new_snapshots = []
    union_kept = set()
    per_snap_stats = []

    for snap in base["snapshots"]:
        as_of = snap["as_of"]
        rows = _read_snapshot_csv(snap["csv"])
        before_n = len(rows)
        if "industry_cap" in spec:
            rows = _apply_industry_cap(rows, industry_map,
                                       spec["industry_cap"])
        if "mv_floor_wan" in spec:
            rows = _apply_mv_floor(rows, code_to_mv, spec["mv_floor_wan"])
        after_n = len(rows)
        out_csv = out_dir + "/core_d_" + as_of.replace("-", "") + ".csv"
        _write_snapshot_csv(out_csv, rows)
        for r in rows:
            union_kept.add(r["code"])
        new_snapshots.append({
            "as_of":     as_of,
            "csv":       out_csv,
            "n_chosen":  after_n,
            "win_start": snap.get("win_start"),
            "win_end":   snap.get("win_end"),
        })
        per_snap_stats.append({
            "as_of": as_of, "before": before_n, "after": after_n,
        })

    new_index = {
        "label":         out_label,
        "derived_from":  args.base_label,
        "description":   spec["description"],
        "n":             base.get("n"),
        "rank_window":   base.get("rank_window"),
        "bars_min":      base.get("bars_min"),
        "history_window": base.get("history_window"),
        "start_date":    base.get("start_date"),
        "end_date":      base.get("end_date"),
        "snapshots":     new_snapshots,
        "union_size":    len(union_kept),
        "union_csv":     out_dir + "/__union.csv",
        "valid_snapshots": len(new_snapshots),
    }
    with open(out_dir + "/index.json", "w", encoding="utf-8") as f:
        json.dump(new_index, f, ensure_ascii=False, indent=2)

    union_rows = []
    for c in sorted(union_kept):
        union_rows.append({"code": c, "name": "", "sector": "",
                           "enabled": "true"})
    _write_snapshot_csv(out_dir + "/__union.csv", union_rows)

    duration = (_dt.datetime.now() - started).total_seconds()
    report = {
        "generated_at":     started.isoformat(timespec="seconds"),
        "duration_seconds": round(duration, 2),
        "variant":          args.variant,
        "spec":             spec,
        "base_label":       args.base_label,
        "out_label":        out_label,
        "out_dir":          out_dir,
        "base_union_size":  len(union_codes),
        "out_union_size":   len(union_kept),
        "snapshots":        per_snap_stats,
        "writes_to_qmt_duckdb":  False,
        "writes_to_huice_db":    False,
    }
    if not os.path.isdir(args.report_dir):
        os.makedirs(args.report_dir)
    report_path = (args.report_dir + "/build_d_manifest_" + args.variant +
                   "_" + started.strftime("%Y%m%d_%H%M%S") + ".json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    log.info("D manifest derive complete: variant=%s out=%s union=%d snapshots=%d",
             args.variant, out_dir, len(union_kept), len(new_snapshots))
    print(json.dumps({"variant": args.variant, "out_dir": out_dir,
                      "union_size": len(union_kept),
                      "snapshots": len(new_snapshots),
                      "report": report_path}, indent=2))


if __name__ == "__main__":
    main()
