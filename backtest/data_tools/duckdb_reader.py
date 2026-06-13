# coding: utf-8
"""DuckDB read-only reader for backtest factory v0.2.

Constraints (SPEC §1, decisions A/C/D/I):
  - Open with access_mode='read_only'
  - Dedup duplicate (code, date) via QUALIFY ROW_NUMBER on trade_time DESC
  - Never INSERT/UPDATE/DELETE/CREATE/ATTACH on quantifydata.duckdb
  - Detect quantifydata.duckdb.wal -> emit warning (decision: building 1.6)
  - Provide coverage() with optional universe slicing
"""
import os
import datetime as _dt
import logging
import duckdb
import pandas as pd

log = logging.getLogger(__name__)


class DuckDBDailyReader(object):
    def __init__(self, db_path):
        if not os.path.isfile(db_path):
            raise FileNotFoundError("DuckDB not found: " + db_path)
        self.db_path = db_path
        self._conn = duckdb.connect(db_path, read_only=True)
        self._db_mtime = self._read_mtime()
        self.wal_detected = self._check_wal()
        self._coverage_cache = None

    def _read_mtime(self):
        ts = os.path.getmtime(self.db_path)
        return _dt.datetime.fromtimestamp(ts).isoformat(timespec="seconds")

    def _check_wal(self):
        wal = self.db_path + ".wal"
        if os.path.isfile(wal):
            msg = (u"⚠️ 检测到 quantifydata.duckdb.wal，"
                   u"金策智算可能正在同步数据。"
                   u"本次回测的 data_hash 在同步完成前不稳定，"
                   u"请同步结束后重跑确认。")
            log.warning(msg)
            print(msg)
            self.wal_warning_message = msg
            return True
        self.wal_warning_message = ""
        return False

    def load_window(self, codes, start_date, end_date):
        if not codes:
            raise ValueError("codes is empty")
        cov = self.coverage()
        if start_date < cov["min_date"] or end_date > cov["max_date"]:
            raise ValueError(
                "requested range [%s, %s] out of coverage [%s, %s]"
                % (start_date, end_date, cov["min_date"], cov["max_date"]))

        placeholders = ",".join(["?"] * len(codes))
        sql = (
            "SELECT code, CAST(trade_time AS DATE) AS date, "
            "       open, high, low, close, vol, amount "
            "FROM dat_day "
            "WHERE code IN (" + placeholders + ") "
            "  AND CAST(trade_time AS DATE) BETWEEN ? AND ? "
            "QUALIFY ROW_NUMBER() OVER ("
            "    PARTITION BY code, CAST(trade_time AS DATE) "
            "    ORDER BY trade_time DESC) = 1 "
            "ORDER BY code, date"
        )
        params = list(codes) + [start_date, end_date]
        df = self._conn.execute(sql, params).fetchdf()
        df["date"] = df["date"].astype(str)
        out = {}
        for code, sub in df.groupby("code"):
            sub = sub.drop(columns=["code"]).reset_index(drop=True)
            out[code] = sub
        return out

    def trading_calendar(self, start_date, end_date):
        sql = (
            "SELECT DISTINCT CAST(trade_time AS DATE) AS d "
            "FROM dat_day "
            "WHERE CAST(trade_time AS DATE) BETWEEN ? AND ? "
            "ORDER BY d"
        )
        rows = self._conn.execute(sql, [start_date, end_date]).fetchall()
        return [str(r[0]) for r in rows]

    def coverage(self, codes=None, start_date=None, end_date=None):
        if self._coverage_cache is None:
            row = self._conn.execute("""
                WITH dedup AS (
                    SELECT code, CAST(trade_time AS DATE) AS d
                    FROM dat_day
                    QUALIFY ROW_NUMBER() OVER (PARTITION BY code, CAST(trade_time AS DATE)
                                               ORDER BY trade_time DESC) = 1
                )
                SELECT MIN(d), MAX(d), COUNT(DISTINCT code), COUNT(*)
                FROM dedup
            """).fetchone()
            total_raw = self._conn.execute("SELECT COUNT(*) FROM dat_day").fetchone()[0]
            self._coverage_cache = {
                "min_date": str(row[0]),
                "max_date": str(row[1]),
                "n_codes": int(row[2]),
                "n_rows_after_dedup": int(row[3]),
                "dedup_count": int(total_raw - row[3]),
                "db_mtime": self._db_mtime,
            }
        cov = dict(self._coverage_cache)
        if codes is not None:
            ph = ",".join(["?"] * len(codes))
            sd = start_date or cov["min_date"]
            ed = end_date or cov["max_date"]
            present = self._conn.execute(
                "SELECT DISTINCT code FROM dat_day "
                "WHERE code IN (" + ph + ") "
                "  AND CAST(trade_time AS DATE) BETWEEN ? AND ?",
                list(codes) + [sd, ed]).fetchall()
            present_set = {r[0] for r in present}
            missing = [c for c in codes if c not in present_set]
            cov["universe_coverage"] = {
                "universe_size": len(codes),
                "codes_with_data": len(present_set),
                "codes_missing": missing,
                "missing_count": len(missing),
            }
        return cov

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass

    def __del__(self):
        self.close()
