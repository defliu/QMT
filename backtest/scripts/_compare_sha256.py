# coding: utf-8
"""一次性 sha256 比对工具（Phase 1 / Milestone C · Hotfix v2）。

用法: py -3.10 _compare_sha256.py <run_old_dir> <run_new_dir>

对比 trades.csv / equity_curve.csv / positions.csv 的**业务列** sha256。
按 SPEC §6.1 验收口径：业务数据一致（时间/code/方向/价/量/净值/现金/市值/持仓），
run_id 列是运行 identity 元数据，每次跑必不同，从 sha 输入中剥除。

summary.json 因 version / run_id / timestamps 等运行元数据天然不同，单独对
关键业务数值（total_return / annualized_return / sharpe / max_drawdown）做断言。
"""
import csv
import hashlib
import io
import json
import os
import sys


_HARD_BIT_IDENTICAL = ["trades.csv", "equity_curve.csv", "positions.csv"]

_NON_BUSINESS_COLS = {"run_id"}


def _read_csv_stripped(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        return b""
    header = rows[0]
    keep_idx = [i for i, c in enumerate(header) if c not in _NON_BUSINESS_COLS]
    out_io = io.StringIO()
    writer = csv.writer(out_io, lineterminator="\n")
    for row in rows:
        writer.writerow([row[i] for i in keep_idx])
    return out_io.getvalue().encode("utf-8")


def _sha256_business(path):
    data = _read_csv_stripped(path)
    return hashlib.sha256(data).hexdigest()


def main(argv):
    if len(argv) != 3:
        print("Usage: _compare_sha256.py <old_dir> <new_dir>")
        return 2
    old = argv[1]
    new = argv[2]
    bad = []
    print("=== sha256 business-cols bit-identical compare (SPEC §6.1) ===")
    for fn in _HARD_BIT_IDENTICAL:
        po = os.path.join(old, fn)
        pn = os.path.join(new, fn)
        if not os.path.exists(po):
            print("  %-20s OLD MISSING: %s" % (fn, po))
            bad.append(fn)
            continue
        if not os.path.exists(pn):
            print("  %-20s NEW MISSING: %s" % (fn, pn))
            bad.append(fn)
            continue
        h_old = _sha256_business(po)
        h_new = _sha256_business(pn)
        mark = "OK " if h_old == h_new else "DIFF"
        print("  %-20s %s  old=%s  new=%s" % (fn, mark, h_old[:12], h_new[:12]))
        if h_old != h_new:
            bad.append(fn)

    print()
    print("=== summary.json business numerics compare ===")
    so_path = os.path.join(old, "summary.json")
    sn_path = os.path.join(new, "summary.json")
    if os.path.exists(so_path) and os.path.exists(sn_path):
        with open(so_path, "r", encoding="utf-8") as f:
            so = json.load(f)
        with open(sn_path, "r", encoding="utf-8") as f:
            sn = json.load(f)
        for k in ("total_return", "annualized_return", "sharpe",
                  "max_drawdown", "n_trades"):
            v_old = so.get(k, "<MISSING>")
            v_new = sn.get(k, "<MISSING>")
            mark = "OK" if v_old == v_new else "DIFF"
            print("  %-22s %s  old=%r  new=%r" % (k, mark, v_old, v_new))
            if v_old != v_new and v_old != "<MISSING>":
                bad.append("summary." + k)
        v_old = so.get("_STRATEGY_CORE_VERSION") or so.get("schema_version")
        v_new = sn.get("_STRATEGY_CORE_VERSION") or sn.get("schema_version")
        print("  version (allowed-diff)  old=%r  new=%r" % (v_old, v_new))
    else:
        print("  summary.json missing on one side")
        bad.append("summary.json")

    print()
    if bad:
        print("RESULT: FAIL — bad items: %s" % bad)
        return 1
    print("RESULT: PASS — trades/equity/positions business cols bit-identical; summary numerics OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
