# coding: utf-8
"""Tests for backtest.scripts.validate_universe (Task 6.1)."""
import json
import os

import pytest

from backtest import paths
from backtest.scripts import validate_universe


def _write_uni(path, rows):
    """rows = list of dicts with code/name/sector/enabled."""
    import csv as _csv
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=["code", "name", "sector", "enabled"])
        w.writeheader()
        for r in rows:
            w.writerow(r)


def test_build_report_basic_with_real_universe(sample_db_path):
    if not os.path.isfile(sample_db_path):
        pytest.skip("sample_db unavailable")
    uni_csv = os.path.join(paths.BACKTEST_ROOT, "data", "universe",
                           "strategy_pool_base.csv")
    report = validate_universe.build_report(
        uni_csv, sample_db_path,
        start_date="2025-09-01", end_date="2025-09-30")

    assert report["schema_version"] == "0.2"
    assert report["universe_size_enabled"] == 10
    assert report["rows_dropped_invalid"] == 0
    # All 10 codes present in sample db.
    assert report["duckdb_coverage"]["codes_with_data"] == 10
    assert report["duckdb_coverage"]["missing_count"] == 0
    # Sample window is ~21 trading days; with min_history_bars=60 every code
    # is "thin" (below threshold).
    assert report["history_depth"]["sufficient_count"] == 0
    assert report["history_depth"]["thin_count"] == 10


def test_build_report_flags_invalid_and_disabled(tmp_path, sample_db_path):
    if not os.path.isfile(sample_db_path):
        pytest.skip("sample_db unavailable")
    uni = tmp_path / "u.csv"
    _write_uni(str(uni), [
        {"code": "000001.SZ", "name": "平安银行", "sector": "银行",   "enabled": "true"},
        {"code": "600519.SH", "name": "贵州茅台", "sector": "白酒",   "enabled": "true"},
        {"code": "BADCODE",   "name": "?",         "sector": "",       "enabled": "true"},
        {"code": "000333.SZ", "name": "美的",     "sector": "家电",   "enabled": "false"},
    ])
    report = validate_universe.build_report(
        str(uni), sample_db_path,
        start_date="2025-09-01", end_date="2025-09-30")

    assert report["universe_size_enabled"] == 2          # only the two enabled+valid
    assert report["rows_dropped_invalid"] == 1           # BADCODE
    assert "BADCODE" in report["dropped_invalid_codes"]
    assert report["rows_disabled"] == 1                  # 000333.SZ disabled


def test_build_report_marks_codes_missing_from_duckdb(tmp_path, sample_db_path):
    if not os.path.isfile(sample_db_path):
        pytest.skip("sample_db unavailable")
    uni = tmp_path / "u.csv"
    _write_uni(str(uni), [
        {"code": "000001.SZ", "name": "x", "sector": "银行",     "enabled": "true"},
        {"code": "999999.SH", "name": "y", "sector": "不存在",  "enabled": "true"},
    ])
    report = validate_universe.build_report(
        str(uni), sample_db_path,
        start_date="2025-09-01", end_date="2025-09-30")

    assert report["duckdb_coverage"]["codes_with_data"] == 1
    assert report["duckdb_coverage"]["missing_count"] == 1
    assert "999999.SH" in report["duckdb_coverage"]["codes_missing"]


def test_sector_distribution_sorted_desc(tmp_path, sample_db_path):
    if not os.path.isfile(sample_db_path):
        pytest.skip("sample_db unavailable")
    uni = tmp_path / "u.csv"
    _write_uni(str(uni), [
        {"code": "000001.SZ", "name": "a", "sector": "银行",   "enabled": "true"},
        {"code": "600036.SH", "name": "b", "sector": "银行",   "enabled": "true"},
        {"code": "600519.SH", "name": "c", "sector": "白酒",   "enabled": "true"},
        {"code": "000858.SZ", "name": "d", "sector": "白酒",   "enabled": "true"},
        {"code": "300750.SZ", "name": "e", "sector": "新能源", "enabled": "true"},
    ])
    report = validate_universe.build_report(
        str(uni), sample_db_path,
        start_date="2025-09-01", end_date="2025-09-30")
    dist = report["sector_distribution"]
    counts = [d["count"] for d in dist]
    # Sorted descending by count.
    assert counts == sorted(counts, reverse=True)
    sector_to_n = {d["sector"]: d["count"] for d in dist}
    assert sector_to_n == {"银行": 2, "白酒": 2, "新能源": 1}


def test_history_depth_threshold_partitions_correctly(tmp_path, sample_db_path):
    if not os.path.isfile(sample_db_path):
        pytest.skip("sample_db unavailable")
    uni = tmp_path / "u.csv"
    _write_uni(str(uni), [
        {"code": "000001.SZ", "name": "a", "sector": "x", "enabled": "true"},
        {"code": "600519.SH", "name": "b", "sector": "x", "enabled": "true"},
    ])
    # Threshold below the actual ~21-day sample so both codes are sufficient.
    r1 = validate_universe.build_report(
        str(uni), sample_db_path,
        start_date="2025-09-01", end_date="2025-09-30",
        min_history_bars=10)
    assert r1["history_depth"]["sufficient_count"] == 2
    assert r1["history_depth"]["thin_count"] == 0

    # Threshold above sample so both codes are thin.
    r2 = validate_universe.build_report(
        str(uni), sample_db_path,
        start_date="2025-09-01", end_date="2025-09-30",
        min_history_bars=60)
    assert r2["history_depth"]["sufficient_count"] == 0
    assert r2["history_depth"]["thin_count"] == 2
    # thin_codes carries n_bars, sorted by ascending n_bars.
    bars_seq = [tc["n_bars"] for tc in r2["history_depth"]["thin_codes"]]
    assert bars_seq == sorted(bars_seq)


def test_write_report_lands_under_logs_dir(tmp_path):
    report = {"schema_version": "0.2", "x": 1}
    target = validate_universe.write_report(report, logs_dir=str(tmp_path))
    assert os.path.isfile(target)
    with open(target, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded["schema_version"] == "0.2"


def test_main_writes_to_logs_dir(sample_db_path, tmp_path, monkeypatch):
    if not os.path.isfile(sample_db_path):
        pytest.skip("sample_db unavailable")
    monkeypatch.setattr(paths, "LOGS_DIR", str(tmp_path).replace("\\", "/"))
    uni_csv = os.path.join(paths.BACKTEST_ROOT, "data", "universe",
                           "strategy_pool_base.csv")
    rc = validate_universe.main([
        "--universe", uni_csv,
        "--db", sample_db_path,
        "--start-date", "2025-09-01",
        "--end-date", "2025-09-30",
        "--min-history-bars", "10",
    ])
    assert rc == 0
    files = [f for f in os.listdir(str(tmp_path))
             if f.startswith("validate_universe_") and f.endswith(".json")]
    assert len(files) == 1
