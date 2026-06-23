# coding=utf-8
"""huicexitong OHLCV loader (huang combo backtest).

Boundary (consistent with huicexitong_reader.py):
- read_only; never write gpsj.duckdb
- standalone module, not referenced by backtest/engine/daily_engine
- Chinese table/column names via _huicexitong_names.py (ASCII + \\u escape), no bare Chinese literals
- Selector required columns: open, high, low, close, volume (mapped to Chinese fields)
"""
import duckdb
import pandas as pd

from backtest.data_tools._huicexitong_names import (
    T_DAILY, C_CODE, C_DATE,
)

HUICE_DB = 'E:/huicexitong/runtime/sj/gpsj.duckdb'
# BENCH_DB: F:/backtest_workspace/data/duckdb/benchmark_index.duckdb (只覆盖 2025-01 起)
# Part 4: 改用 huicexitong basic_data."板块指数" (000001.SH 覆盖 2004-01 起)

_C_OPEN  = '\u5f00\u76d8\u4ef7'        # open price
_C_HIGH  = '\u6700\u9ad8\u4ef7'        # high price
_C_LOW   = '\u6700\u4f4e\u4ef7'        # low price
_C_CLOSE = '\u6536\u76d8\u4ef7'        # close price
_C_VOL   = '\u6210\u4ea4\u91cf(\u624b)'  # volume (lots)


def load_ohlcv_from_huicexitong(codes, start_date, end_date, db_path=HUICE_DB):
    """Load OHLCV, return dict {code: DataFrame(index=date, columns=[open/high/low/close/volume])}.

    Args:
        codes: list of '600000.SH' etc.
        start_date, end_date: 'YYYY-MM-DD'
    """
    con = duckdb.connect(db_path, read_only=True)
    try:
        q = (
            'SELECT "%s" AS code, "%s" AS date, '
            '"%s" AS open, "%s" AS high, "%s" AS low, "%s" AS close, "%s" AS volume '
            'FROM daily_data."%s" '
            'WHERE "%s" = ANY(?) AND "%s" BETWEEN ? AND ? '
            'ORDER BY "%s", "%s"'
        ) % (
            C_CODE, C_DATE,
            _C_OPEN, _C_HIGH, _C_LOW, _C_CLOSE, _C_VOL,
            T_DAILY,
            C_CODE, C_DATE,
            C_CODE, C_DATE,
        )
        df = con.execute(q, [codes, start_date, end_date]).fetchdf()
    finally:
        con.close()

    result = {}
    for code, sub in df.groupby('code'):
        sub = sub.drop(columns=['code']).copy()
        sub['date'] = pd.to_datetime(sub['date'])
        sub = sub.set_index('date').sort_index()
        sub = sub.dropna(subset=['open', 'high', 'low', 'close'])
        sub = sub[(sub['open'] > 0) & (sub['high'] > 0) & (sub['low'] > 0) & (sub['close'] > 0)]
        if len(sub) > 0:
            result[code] = sub
    return result


_T_INDEX = '\u677f\u5757\u6307\u6570'  # 板块指数
_C_INDEX_CLOSE = '\u6536\u76d8\u4ef7'  # 收盘价


def load_benchmark_index(code, start_date, end_date, db_path=HUICE_DB):
    """Read benchmark index, return DataFrame(index=date, columns=[close]).

    Part 4: 改用 huicexitong basic_data."板块指数" 表 (000001.SH 覆盖 2004 起).
    旧 F:/backtest_workspace/data/duckdb/benchmark_index.duckdb 只覆盖 2025-01 起,
    用它会让 2023-06~2024-12 段 selector 的 double_大盘_ok 全 False.
    """
    con = duckdb.connect(db_path, read_only=True)
    try:
        q = (
            'SELECT "%s" AS date, "%s" AS close '
            'FROM basic_data."%s" '
            'WHERE "%s" = ? AND "%s" BETWEEN ? AND ? '
            'ORDER BY "%s"'
        ) % (
            C_DATE, _C_INDEX_CLOSE,
            _T_INDEX,
            C_CODE, C_DATE,
            C_DATE,
        )
        rows = con.execute(q, [code, start_date, end_date]).fetchall()
    finally:
        con.close()
    if not rows:
        raise ValueError('benchmark %s 无数据 (%s ~ %s)' % (code, start_date, end_date))
    df = pd.DataFrame(rows, columns=['date', 'close'])
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()
    return df
