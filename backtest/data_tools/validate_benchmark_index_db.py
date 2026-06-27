# coding: utf-8
"""validate_benchmark_index_db.py — 验证 benchmark_index.duckdb 与 huice 重叠日是否一致。"""
import duckdb

bench_db = "F:/backtest_workspace/data/duckdb/benchmark_index.duckdb"
huice_db = "E:/huicexitong/runtime/sj/gpsj.duckdb"

bcon = duckdb.connect(bench_db, read_only=True)
hcon = duckdb.connect(huice_db, read_only=True)

print("=== benchmark_index.duckdb 覆盖 ===")
for r in bcon.execute(
    "SELECT code, COUNT(*) n, MIN(trade_date), MAX(trade_date) "
    "FROM index_daily GROUP BY code ORDER BY code"
).fetchall():
    print(" ", r)

print()
print("=== 4-6 月每月行数（确认补全 huice 缺口）===")
for r in bcon.execute(
    "SELECT date_trunc('month', trade_date) m, code, COUNT(*) "
    "FROM index_daily WHERE trade_date >= '2026-03-01' "
    "GROUP BY 1, 2 ORDER BY 1, 2"
).fetchall():
    print(" ", r)

print()
print("=== 与 huice 板块指数 重叠日交叉校验 (2026-03-01 → 2026-04-03) ===")
print("  code        date         xtquant_close   huice_close   diff%")
for code in ["000300.SH", "000905.SH", "000001.SH"]:
    bench_rows = bcon.execute(
        "SELECT trade_date, close FROM index_daily "
        "WHERE code = ? AND trade_date BETWEEN '2026-03-01' AND '2026-04-03' "
        "ORDER BY trade_date", [code]).fetchall()
    huice_rows = hcon.execute(
        'SELECT 交易日期, 收盘价 FROM basic_data."板块指数" '
        "WHERE 股票代码 = ? AND 交易日期 BETWEEN '2026-03-01' AND '2026-04-03' "
        "ORDER BY 交易日期", [code]).fetchall()
    bm = {d: c for d, c in bench_rows}
    hm = {d: c for d, c in huice_rows}
    common = sorted(set(bm.keys()) & set(hm.keys()))
    if common:
        # only show first 3 + last 3
        sample = common[:3] + common[-3:] if len(common) > 6 else common
        for d in sample:
            xc = bm[d]
            hc = hm[d]
            diff = (xc - hc) / hc * 100 if hc else 0
            print("  %s  %s   %12.4f   %12.4f   %+.4f%%" % (
                code, d, xc, hc, diff))
    print()

print("=== 4-6 月 xtquant 数据样例 (000300.SH 最后 5 天) ===")
for r in bcon.execute(
    "SELECT trade_date, open, high, low, close, volume, amount "
    "FROM index_daily WHERE code='000300.SH' "
    "ORDER BY trade_date DESC LIMIT 5"
).fetchall():
    print(" ", r)

bcon.close()
hcon.close()
