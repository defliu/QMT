# coding: utf-8
"""DeepseekReader — AstockParquetReader 子类。

override load_window：保留日线基本面列（turnover_rate/circ_mv/is_st/
listed_days）+ hfq 复权 + 一次性预算全部指标列（compute_indicators）。

为什么放 reader：engine 按日切片（_slice_window_up_to 只过滤行不动列），
所以在 load_window 一次预算好的指标列会原样流到 evaluate_day，把
O(codes×days×window) 降到 O(codes×days) 常数查表。PIT 安全：rolling 只用过去。

内存优化（OOM 修复）：
  - __init__ 列裁剪读 parquet（只读需要的 11 列，不读全部 30+ 列）
  - load_window 末尾丢弃指标计算后不再需要的列（high/low/vol/amount/circ_mv）

零侵入：不改 engine / 不改 AstockParquetReader 核心，仅子类化。
"""

import logging

import pandas as pd

from backtest.data_tools.astock_reader import AstockParquetReader
from backtest.strategies.research.deepseek.factors import compute_indicators

log = logging.getLogger(__name__)

# parquet 中需要读出的列（含索引 trade_date/ts_code 由 read_parquet 自动带）
_READ_COLS = ["open", "high", "low", "close", "vol", "amount",
              "turnover_rate", "circ_mv", "is_st", "listed_days", "adj_factor"]

# 指标算完后，strategy 不再需要的列（drop 以省内存）
_DROP_AFTER = ["high", "low", "vol", "amount", "circ_mv"]


class DeepseekReader(AstockParquetReader):
    """astock parquet reader + 指标预算。adjustment 固定 hfq（PIT 安全）。"""

    def __init__(self, db_path=None, adjustment="hfq"):
        # 强制 hfq：后复权第 T 天价格只依赖截至 T 日的复权因子，无 look-ahead。
        # qfq（前复权）用末端价格回算历史，会引入未来信息（P0 H12 雷区）。
        # 不调父类 __init__（父类会全列读 parquet），自行列裁剪读取。
        import datetime as _dt
        import os as _os
        if adjustment not in ("raw", "qfq", "hfq"):
            raise ValueError("adjustment must be one of raw/qfq/hfq, got: %s" % adjustment)
        if db_path is None:
            db_path = ASTOCK_DAILY_PATH if False else "E:/astock/daily/stock_daily.parquet"
        if not _os.path.isfile(db_path):
            raise FileNotFoundError("astock parquet not found: " + db_path)
        self.db_path = db_path
        self.data_source = "astock"
        self.adjustment = adjustment
        self.wal_detected = False
        self.wal_warning_message = ""
        # 列裁剪读取（省 ~60% 内存）
        self._df = pd.read_parquet(db_path, columns=_READ_COLS)
        self._df.index.names = ["trade_date", "ts_code"]
        # 日期下限裁剪：所有回测 start=2019 + 500 日 warmup ≈ 2017-08，
        # 2016 之前的行用不到，裁掉省 ~45% 内存（让 3 并行不 OOM）。
        _DATE_FLOOR = pd.Timestamp("2016-01-01")
        dates_all = pd.to_datetime(self._df.index.get_level_values("trade_date"))
        self._df = self._df.loc[dates_all >= _DATE_FLOOR]
        self._dates = pd.to_datetime(self._df.index.get_level_values("trade_date"))
        self._codes = self._df.index.get_level_values("ts_code")
        self._coverage_cache = None

    def load_window(self, codes, start_date, end_date):
        """返回 {code: df}，df 含 OHLCV + 基本面列 + 预算指标列。"""
        if not codes:
            raise ValueError("codes is empty")
        dates = self._dates
        codes_idx = self._codes
        mask = (
            (dates >= pd.Timestamp(start_date))
            & (dates <= pd.Timestamp(end_date))
            & (codes_idx.isin(codes))
        )
        sub = self._df.loc[mask]
        if sub.empty:
            raise ValueError(
                "requested range [%s, %s] has no data for %d codes"
                % (start_date, end_date, len(codes)))

        out = {}
        for code, grp in sub.groupby(level="ts_code"):
            rows = grp.droplevel("ts_code").reset_index()
            rows["date"] = pd.to_datetime(rows["trade_date"]).dt.strftime("%Y-%m-%d")
            rows = rows.sort_values("date").reset_index(drop=True)

            # hfq 复权（价格列 × adj_factor）
            if "adj_factor" in rows.columns and self.adjustment == "hfq":
                adj_factor = rows["adj_factor"].values
                for col in ("open", "high", "low", "close"):
                    if col in rows.columns:
                        rows[col] = rows[col] * adj_factor
            rows = rows.drop(columns=["adj_factor", "trade_date"], errors="ignore")

            # 预算指标列（vectorized rolling，PIT 安全）
            rows = compute_indicators(rows)

            # 丢弃指标算完后不再需要的列，省内存
            rows = rows.drop(columns=[c for c in _DROP_AFTER if c in rows.columns],
                             errors="ignore")

            out[code] = rows
        return out
