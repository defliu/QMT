# coding: utf-8
"""
Build mini sample DuckDB for tests by sampling from the read-only source.
MUST inject:
  - 5+ (code, date) pairs with both 00:00+08 and 08:00+08 timestamps (dedup test)
  - 1 stock with 5 missing trade days (suspended-stock / calendar test)
Source DB is opened READ-ONLY; never written.
"""
import os
import duckdb
from backtest import paths

SAMPLE_CODES = [
    "000001.SZ", "600519.SH", "300750.SZ", "000858.SZ", "601318.SH",
    "002594.SZ", "600036.SH", "000333.SZ", "601012.SH", "300059.SZ",
]
SAMPLE_START = "2025-09-01"
SAMPLE_END   = "2025-09-30"
DUP_TARGETS  = [("000001.SZ", "2025-09-01"), ("600519.SH", "2025-09-02"),
                ("300750.SZ", "2025-09-03"), ("000858.SZ", "2025-09-04"),
                ("601318.SH", "2025-09-05")]
SUSPENDED_CODE = "300059.SZ"
SUSPENDED_DAYS = ["2025-09-15", "2025-09-16", "2025-09-17", "2025-09-18", "2025-09-19"]


def build_sample_db(target=None, source=None):
    target = target or (paths.SAMPLE_DB_DIR + "/sample_quantifydata.duckdb")
    source = source or paths.JINCE_DB_PATH
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if os.path.isfile(target):
        os.remove(target)

    src = duckdb.connect(source, read_only=True)
    rows = src.execute("""
        SELECT code, trade_time, open, high, low, close, vol, amount
        FROM dat_day
        WHERE code IN ({}) AND trade_time BETWEEN ? AND ?
    """.format(",".join("?" * len(SAMPLE_CODES))),
        SAMPLE_CODES + [SAMPLE_START + " 00:00:00", SAMPLE_END + " 23:59:59"]
    ).fetchall()
    src.close()

    tgt = duckdb.connect(target)  # writable for fixture
    tgt.execute("""
        CREATE TABLE dat_day (
            code VARCHAR, trade_time TIMESTAMPTZ,
            open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
            vol BIGINT, amount DOUBLE
        )
    """)
    tgt.executemany("INSERT INTO dat_day VALUES (?,?,?,?,?,?,?,?)", rows)

    # Inject duplicate timestamps. Source rows are at 00:00+08; insert a mirror
    # row at 08:00+08 with identical OHLCV so each target (code, date) has both
    # timestamps (per SPEC §4.4 dedup-injection requirement).
    for code, day in DUP_TARGETS:
        existing = tgt.execute(
            "SELECT open,high,low,close,vol,amount FROM dat_day "
            "WHERE code=? AND CAST(trade_time AS DATE)=? LIMIT 1",
            [code, day]).fetchone()
        if existing:
            tgt.execute(
                "INSERT INTO dat_day VALUES (?, CAST(? AS TIMESTAMPTZ), ?,?,?,?,?,?)",
                [code, day + " 08:00:00+08", existing[0], existing[1],
                 existing[2], existing[3], existing[4], existing[5]])

    # Inject suspension: delete rows for suspended code on suspended days
    for d in SUSPENDED_DAYS:
        tgt.execute("DELETE FROM dat_day WHERE code=? AND CAST(trade_time AS DATE)=?",
                    [SUSPENDED_CODE, d])

    tgt.close()
    return target


if __name__ == "__main__":
    print("sample db:", build_sample_db())
