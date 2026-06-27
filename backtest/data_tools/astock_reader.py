# coding: utf-8
"""Astock parquet reader — duck-typed match for DuckDBDailyReader.

Data source: E:\\astock\\daily\\stock_daily.parquet (tushare daily data, 2009+).
Implements the same 4-method duck-typed interface as DuckDBDailyReader:
  load_window / trading_calendar / coverage / close(code, date)

Constraints:
  - Read-only; no writes to E:\\astock\\
  - Output columns aligned with DuckDBDailyReader: date, open, high, low, close, vol, amount
  - Code format: tushare ts_code (e.g. "000001.SZ")
"""
import datetime as _dt
import logging
import os

import pandas as pd

log = logging.getLogger(__name__)

DATA_SOURCE_ASTOCK = "astock"
ASTOCK_DAILY_PATH = "E:/astock/daily/stock_daily.parquet"


class AstockParquetReader(object):
    """Read-only parquet reader for astock daily data.

    Duck-typed to match DuckDBDailyReader interface so the engine
    can consume either reader without code changes.

    Parquet has MultiIndex (trade_date, ts_code).
    All date filtering works via index level accessors.
    """

    def __init__(self, db_path=None, data_source=DATA_SOURCE_ASTOCK):
        if db_path is None:
            db_path = ASTOCK_DAILY_PATH
        if not os.path.isfile(db_path):
            raise FileNotFoundError("astock parquet not found: " + db_path)
        self.db_path = db_path
        self.data_source = data_source
        self.wal_detected = False
        self.wal_warning_message = ""
        self._df = pd.read_parquet(db_path)
        self._df.index.names = ["trade_date", "ts_code"]
        self._dates = pd.to_datetime(self._df.index.get_level_values("trade_date"))
        self._codes = self._df.index.get_level_values("ts_code")
        self._coverage_cache = None

    def load_window(self, codes, start_date, end_date):
        """Load OHLCV for given codes within [start_date, end_date].

        Returns dict: {code: DataFrame(date, open, high, low, close, vol, amount)}
        aligned with DuckDBDailyReader output.
        """
        if not codes:
            raise ValueError("codes is empty")
        dates = self._dates
        codes_idx = self._codes
        mask = (
            (dates >= pd.Timestamp(start_date))
            & (dates <= pd.Timestamp(end_date))
            & (codes_idx.isin(codes))
        )
        sub = self._df.loc[mask].copy()
        if sub.empty:
            raise ValueError(
                "requested range [%s, %s] has no data for %d codes"
                % (start_date, end_date, len(codes))
            )
        out = {}
        for code, grp in sub.groupby(level="ts_code"):
            rows = grp.droplevel("ts_code").reset_index()
            rows["date"] = rows["trade_date"].dt.strftime("%Y-%m-%d")
            rows = rows[["date", "open", "high", "low", "close", "vol", "amount"]]
            rows = rows.sort_values("date").reset_index(drop=True)
            out[code] = rows
        return out

    def trading_calendar(self, start_date, end_date):
        """Return sorted list of trading date strings in [start_date, end_date]."""
        dates = self._dates
        mask = (
            (dates >= pd.Timestamp(start_date))
            & (dates <= pd.Timestamp(end_date))
        )
        unique_dates = sorted(dates[mask].unique())
        return [d.strftime("%Y-%m-%d") for d in unique_dates]

    def coverage(self, codes=None, start_date=None, end_date=None):
        """Return coverage dict; optionally filter to specific codes/date range."""
        if self._coverage_cache is None:
            self._coverage_cache = {
                "data_source": self.data_source,
                "min_date": self._dates.min().strftime("%Y-%m-%d"),
                "max_date": self._dates.max().strftime("%Y-%m-%d"),
                "n_codes": self._codes.nunique(),
                "n_rows_after_dedup": len(self._df),
                "dedup_count": 0,
                "db_mtime": _dt.datetime.fromtimestamp(
                    os.path.getmtime(self.db_path)
                ).isoformat(timespec="seconds"),
            }
        cov = dict(self._coverage_cache)
        if codes is not None:
            sd = pd.Timestamp(start_date) if start_date else pd.Timestamp(cov["min_date"])
            ed = pd.Timestamp(end_date) if end_date else pd.Timestamp(cov["max_date"])
            dates = self._dates
            codes_idx = self._codes
            mask = (
                (dates >= sd)
                & (dates <= ed)
                & (codes_idx.isin(codes))
            )
            present = set(codes_idx[mask].unique())
            missing = [c for c in codes if c not in present]
            cov["universe_coverage"] = {
                "universe_size": len(codes),
                "codes_with_data": len(present),
                "codes_missing": missing,
                "missing_count": len(missing),
            }
        return cov

    def close(self, code=None, date=None):
        """Close price accessor (code, date) or no-op cleanup (no args).

        DuckDBDailyReader.close() closes the DB connection; astock parquet
        is in-memory so no-op is correct. Scripts call reader.close() in
        finally blocks, so this must tolerate zero-arg calls.
        """
        if code is not None and date is not None:
            ts = pd.Timestamp(date)
            try:
                val = self._df.loc[(ts, code), "close"]
                return float(val)
            except KeyError:
                return None
        return None

    def __del__(self):
        self._df = None
        self._dates = None
        self._codes = None
        self._coverage_cache = None
