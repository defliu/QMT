# coding: utf-8
"""Smoke tests for HuicexitongReader (read-only).

Skips automatically when E:/huicexitong/runtime/sj/gpsj.duckdb is unavailable
(e.g. on CI without the local huice DB). The reader is independent from the
backtest engine, so these tests cover the reader in isolation.
"""
import os

import pytest


HUICE_DB = "E:/huicexitong/runtime/sj/gpsj.duckdb"

pytestmark = pytest.mark.skipif(
    not os.path.isfile(HUICE_DB),
    reason="huicexitong gpsj.duckdb not available on this host"
)


def _reader():
    from backtest.data_tools.huicexitong_reader import HuicexitongReader
    return HuicexitongReader()


def test_reader_open_and_coverage():
    r = _reader()
    try:
        cov = r.coverage()
    finally:
        r.close()
    assert cov["db_path"] == HUICE_DB
    assert cov["db_mtime"]
    tables = cov["tables"]
    assert tables["daily"]["rows"] > 1_000_000
    assert tables["daily"]["max_date"]   # may be stale, but must exist
    assert tables["sw_industry_member"]["rows"] > 1000


def test_load_industry_map_for_known_codes():
    r = _reader()
    try:
        rows = r.load_industry_map(
            ["000001.SZ", "600519.SH", "300750.SZ"], latest_only=True)
    finally:
        r.close()
    by_code = {x["code"]: x for x in rows}
    # all three should map to a SW L1 industry
    for c in ("000001.SZ", "600519.SH", "300750.SZ"):
        assert c in by_code, "missing industry for " + c
        assert by_code[c]["l1_code"]
        assert by_code[c]["l1_name"]


def test_load_daily_aux_window_shape():
    r = _reader()
    try:
        rows = r.load_daily_aux(
            ["000001.SZ", "600519.SH"],
            "2026-01-05", "2026-01-10")
    finally:
        r.close()
    assert rows, "expected daily aux rows for 2026-01-05..10"
    # required keys
    must_have = {"code", "date", "turnover_pct", "circ_shares_wan",
                 "total_mv_wan", "st_flag", "suspend_flag",
                 "limit_up", "limit_down"}
    for row in rows:
        assert must_have.issubset(row.keys())
        # date string format YYYY-MM-DD
        assert len(row["date"]) == 10
        assert row["date"][4] == "-"
        # numeric fields are numbers or None
        for k in ("turnover_pct", "circ_shares_wan", "total_mv_wan"):
            v = row[k]
            assert v is None or isinstance(v, float)


def test_load_daily_aux_empty_input():
    r = _reader()
    try:
        rows = r.load_daily_aux([], "2026-01-01", "2026-01-31")
    finally:
        r.close()
    assert rows == []


def test_dump_report_artifacts_present():
    """If the 305-code dump has been run, sanity-check its report shape."""
    report = "F:/backtest_workspace/aux_data/p2_1b_305_dump_report.json"
    if not os.path.isfile(report):
        pytest.skip("aux_data dump not yet generated")
    import json
    with open(report, "r", encoding="utf-8") as f:
        r = json.load(f)
    assert r["n_codes_input"] == 305
    daily_path = r["outputs"]["daily_aux_parquet"]
    assert os.path.isfile(daily_path), "daily_aux parquet missing"
    # NULL pct per field is bounded for this active universe
    np = r["daily_aux_stats"]["null_pct_per_field"]
    for f, pct in np.items():
        assert pct < 5.0, "field %s NULL pct too high: %s" % (f, pct)
    # all 305 codes have a SW L1 industry mapping
    assert r["industry_stats"]["codes_with_industry"] == 305
