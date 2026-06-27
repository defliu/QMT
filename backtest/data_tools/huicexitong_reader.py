# coding: utf-8
"""HuicexitongReader -- read-only auxiliary data source.

This reader exposes huicexitong (E:/huicexitong/runtime/sj/gpsj.duckdb) as
an aux_data feed for evaluate_day. It is intentionally NOT plugged into the
backtest engine's primary OHLCV path; qmt_self_owned remains the default reader.

Boundary contract (16_cc_huicexitong_probe_acceptance.md):
  * read_only=True; never writes a byte to gpsj.duckdb.
  * Independent module; not imported by daily_engine / portfolio / metrics.
  * No xtquant / passorder / QMT imports.
  * Stale dates are surfaced explicitly via coverage() so callers can decide
    whether a given backtest window is within huice's update horizon.

Source-encoding caveat: all Chinese identifiers come from a side file
`huicexitong_names.py` that uses pure ASCII plus \\u escape sequences, so this
module stays free of raw multi-byte literals (which trip GBK-default shells).
"""
import datetime as _dt
import logging
import os

from backtest.data_tools._huicexitong_names import (
    T_DAILY, T_MEMBER, T_TINGFU, T_LIMIT,
    C_CODE, C_DATE,
    C_TURNOVER, C_TURNOVER_FF,
    C_CIRC_SHARES, C_FF_SHARES,
    C_TOTAL_MV, C_CIRC_MV,
    C_ST, C_SUSP,
    C_LIMIT_UP, C_LIMIT_DOWN,
    C_INDUSTRY_L1_CODE, C_INDUSTRY_L1_NAME,
    C_INCLUDED, C_REMOVED, C_LATEST,
)

log = logging.getLogger(__name__)

DEFAULT_HUICE_DB = "E:/huicexitong/runtime/sj/gpsj.duckdb"


class HuicexitongReader(object):
    """Read-only reader for huicexitong gpsj.duckdb.

    Not for primary OHLCV. Use qmt_self_owned for that. This class only exposes
    auxiliary fields the engine cannot get from xtquant: industry, real
    turnover, circulating shares, ST/suspend flags, limit-up/down prices.
    """

    def __init__(self, db_path=DEFAULT_HUICE_DB):
        if not os.path.isfile(db_path):
            raise FileNotFoundError("huicexitong DuckDB not found: " + db_path)
        import duckdb
        self.db_path = db_path
        self._conn = duckdb.connect(db_path, read_only=True)
        self._db_mtime = _dt.datetime.fromtimestamp(
            os.path.getmtime(db_path)).isoformat(timespec="seconds")
        log.info("HuicexitongReader open db=%s mtime=%s",
                 db_path, self._db_mtime)

    @property
    def db_mtime(self):
        return self._db_mtime

    def coverage(self):
        """Return per-table date coverage so callers can detect staleness."""
        out = {"db_path": self.db_path, "db_mtime": self._db_mtime,
               "tables": {}}
        r = self._conn.execute(
            'SELECT COUNT(*), MIN("' + C_DATE + '"), MAX("' + C_DATE + '")'
            ' FROM daily_data."' + T_DAILY + '"').fetchone()
        out["tables"]["daily"] = {
            "rows": int(r[0] or 0),
            "min_date": str(r[1]) if r[1] else "",
            "max_date": str(r[2]) if r[2] else "",
        }
        r = self._conn.execute(
            'SELECT COUNT(*), MIN(trade_date), MAX(trade_date)'
            ' FROM basic_data."' + T_TINGFU + '"').fetchone()
        out["tables"]["suspend"] = {
            "rows": int(r[0] or 0),
            "min_date": str(r[1]) if r[1] else "",
            "max_date": str(r[2]) if r[2] else "",
        }
        r = self._conn.execute(
            'SELECT COUNT(*), MIN("' + C_DATE + '"), MAX("' + C_DATE + '")'
            ' FROM basic_data."' + T_LIMIT + '"').fetchone()
        out["tables"]["limit_price"] = {
            "rows": int(r[0] or 0),
            "min_date": str(r[1]) if r[1] else "",
            "max_date": str(r[2]) if r[2] else "",
        }
        r = self._conn.execute(
            'SELECT COUNT(*) FROM basic_data."' + T_MEMBER + '"').fetchone()
        out["tables"]["sw_industry_member"] = {"rows": int(r[0] or 0)}
        return out

    def load_daily_aux(self, codes, start_date, end_date):
        """Return per-day per-stock aux dict rows (English keys)."""
        if not codes:
            return []
        placeholders = ",".join("?" * len(codes))
        params = list(codes) + [start_date, end_date]
        sql = (
            'SELECT '
            '"' + C_CODE + '"        AS code, '
            '"' + C_DATE + '"        AS d, '
            '"' + C_TURNOVER + '"    AS turnover_pct, '
            '"' + C_TURNOVER_FF + '" AS turnover_ff_pct, '
            '"' + C_CIRC_SHARES + '" AS circ_shares_wan, '
            '"' + C_FF_SHARES + '"   AS ff_shares_wan, '
            '"' + C_TOTAL_MV + '"    AS total_mv_wan, '
            '"' + C_CIRC_MV + '"     AS circ_mv_wan, '
            '"' + C_ST + '"          AS st_flag, '
            '"' + C_SUSP + '"        AS suspend_flag, '
            '"' + C_LIMIT_UP + '"    AS limit_up, '
            '"' + C_LIMIT_DOWN + '"  AS limit_down '
            'FROM daily_data."' + T_DAILY + '" '
            'WHERE "' + C_CODE + '" IN (' + placeholders + ') '
            '  AND "' + C_DATE + '" BETWEEN ? AND ? '
            'ORDER BY "' + C_CODE + '", "' + C_DATE + '"'
        )
        rows = self._conn.execute(sql, params).fetchall()
        keys = ["code", "date", "turnover_pct", "turnover_ff_pct",
                "circ_shares_wan", "ff_shares_wan",
                "total_mv_wan", "circ_mv_wan",
                "st_flag", "suspend_flag",
                "limit_up", "limit_down"]
        out = []
        for row in rows:
            d = dict(zip(keys, row))
            d["date"] = str(d["date"]) if d["date"] is not None else ""
            for k in ("turnover_pct", "turnover_ff_pct",
                      "circ_shares_wan", "ff_shares_wan",
                      "total_mv_wan", "circ_mv_wan",
                      "limit_up", "limit_down"):
                if d[k] is not None:
                    d[k] = float(d[k])
            for k in ("st_flag", "suspend_flag"):
                if d[k] is not None:
                    d[k] = int(d[k])
            out.append(d)
        return out

    def load_industry_map(self, codes, latest_only=True):
        """Return list of dicts: code, l1_code, l1_name, included, removed, latest."""
        if not codes:
            return []
        placeholders = ",".join("?" * len(codes))
        clause = (' AND "' + C_LATEST + '"=\'Y\'') if latest_only else ''
        sql = (
            'SELECT '
            '"' + C_CODE + '"               AS code, '
            '"' + C_INDUSTRY_L1_CODE + '"   AS l1_code, '
            '"' + C_INDUSTRY_L1_NAME + '"   AS l1_name, '
            '"' + C_INCLUDED + '"           AS included, '
            '"' + C_REMOVED + '"            AS removed, '
            '"' + C_LATEST + '"             AS latest '
            'FROM basic_data."' + T_MEMBER + '" '
            'WHERE "' + C_CODE + '" IN (' + placeholders + ')' + clause
        )
        rows = self._conn.execute(sql, list(codes)).fetchall()
        keys = ["code", "l1_code", "l1_name", "included", "removed", "latest"]
        return [dict(zip(keys, r)) for r in rows]

    def load_suspend(self, codes, start_date, end_date):
        """Return list of dicts: code, date (suspend records)."""
        if not codes:
            return []
        placeholders = ",".join("?" * len(codes))
        sql = (
            'SELECT ts_code AS code, trade_date AS d '
            'FROM basic_data."' + T_TINGFU + '" '
            'WHERE ts_code IN (' + placeholders + ') '
            '  AND trade_date BETWEEN ? AND ? '
            'ORDER BY ts_code, trade_date'
        )
        rows = self._conn.execute(
            sql, list(codes) + [start_date, end_date]).fetchall()
        return [{"code": r[0], "date": str(r[1])} for r in rows]

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass

    def __del__(self):
        self.close()
