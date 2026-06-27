# coding: utf-8
"""Astock 1min parquet reader — lazy-load per code.

Each code has its own file at <minute_dir>/<code>.parquet.
Supports raw/qfq/hfq adjustment, same logic as AstockParquetReader.

Constraints:
  - Lazy-load: only reads parquet when load_minute_window is called for a code.
  - Never reads all codes into memory at once.
  - Read-only; no writes.
"""
import logging
import os

import pandas as pd

log = logging.getLogger(__name__)

ASTOCK_MINUTE_DIR = "E:/astock/minute/1min"


class AstockMinuteReader(object):
    """Lazy-loading 1min parquet reader for astock data.

    Each code is stored as a separate parquet file:
        <minute_dir>/<code>.parquet

    Parquet structure:
        Index: MultiIndex (trade_date, trade_time)
        Columns: ts_code, open, high, low, close, vol, amount, adj_factor
        trade_time is datetime (e.g. 2009-01-05 09:30:00)
    """

    def __init__(self, minute_dir=None, adjustment="raw"):
        if adjustment not in ("raw", "qfq", "hfq"):
            raise ValueError(
                "adjustment must be one of raw/qfq/hfq, got: %s" % adjustment
            )
        if minute_dir is None:
            minute_dir = ASTOCK_MINUTE_DIR
        self.minute_dir = minute_dir
        self.adjustment = adjustment
        self._cache = {}

    def _file_path(self, code):
        return os.path.join(self.minute_dir, code + ".parquet")

    def _load_raw(self, code):
        if code in self._cache:
            return self._cache[code]
        fp = self._file_path(code)
        if not os.path.isfile(fp):
            return None
        df = pd.read_parquet(fp)
        if df.index.names != ["trade_date", "trade_time"]:
            if len(df.index.names) >= 2:
                df.index.names = ["trade_date", "trade_time"] + list(
                    df.index.names[2:]
                )
        self._cache[code] = df
        return df

    def _apply_adjustment(self, df, code):
        if df is None or df.empty:
            return df
        out = df.copy()
        if self.adjustment != "raw" and "adj_factor" in out.columns:
            adj = out["adj_factor"].values
            price_cols = ["open", "high", "low", "close"]
            if self.adjustment == "hfq":
                for col in price_cols:
                    if col in out.columns:
                        out[col] = out[col] * adj
            elif self.adjustment == "qfq":
                latest_adj = adj[-1]
                if latest_adj > 0:
                    for col in price_cols:
                        if col in out.columns:
                            out[col] = out[col] * (adj / latest_adj)
        return out

    def load_minute_window(self, code, start_date, end_date):
        """Load 1min OHLCV for a single code within [start_date, end_date].

        Args:
            code: ts_code string (e.g. "600000.SH")
            start_date: date string "YYYY-MM-DD"
            end_date: date string "YYYY-MM-DD"

        Returns:
            DataFrame with columns [trade_time, open, high, low, close, vol, amount]
            and optional adj_factor. Index is integer range.
            Returns None if file not found or no data in range.
        """
        df = self._load_raw(code)
        if df is None:
            return None
        sd = pd.Timestamp(start_date)
        ed = pd.Timestamp(end_date)
        dates = df.index.get_level_values("trade_date")
        mask = (dates >= sd) & (dates <= ed)
        sub = df.loc[mask]
        if sub.empty:
            return None
        sub = sub.copy()
        sub = self._apply_adjustment(sub, code)
        sub = sub.reset_index()
        if "trade_time" in sub.columns:
            sub = sub.sort_values("trade_time").reset_index(drop=True)
        keep_cols = ["trade_time", "open", "high", "low", "close", "vol", "amount"]
        if "trade_date" in sub.columns:
            keep_cols.append("trade_date")
        if "adj_factor" in sub.columns:
            keep_cols.append("adj_factor")
        sub = sub[keep_cols]
        return sub

    def available_codes(self):
        """List codes that have 1min parquet files in minute_dir."""
        if not os.path.isdir(self.minute_dir):
            return []
        codes = []
        for fn in os.listdir(self.minute_dir):
            if fn.endswith(".parquet"):
                codes.append(fn[: -len(".parquet")])
        return sorted(codes)
