# coding: utf-8
"""Tests for backtest.scripts.validate_data (Task 5.4)."""
import json
import os

import pytest

from backtest import paths
from backtest.scripts import validate_data


def test_build_report_basic(sample_db_path):
    if not os.path.isfile(sample_db_path):
        pytest.skip("sample_db unavailable")
    report = validate_data.build_report(sample_db_path)
    assert report["schema_version"] == "0.3"
    assert report["data_backend"] == "duckdb"
    assert report["data_source"] == "jince_zhisuan"
    assert report["db_path"] == sample_db_path
    assert report["min_date"] != ""
    assert report["max_date"] != ""
    assert report["n_codes"] >= 1
    assert isinstance(report["wal_detected"], bool)
    assert report["universe_coverage"] is None  # no universe given


def test_build_report_with_universe(sample_db_path):
    if not os.path.isfile(sample_db_path):
        pytest.skip("sample_db unavailable")
    universe_csv = os.path.join(paths.BACKTEST_ROOT, "data", "universe",
                                "strategy_pool_base.csv")
    report = validate_data.build_report(sample_db_path,
                                        universe_csv=universe_csv,
                                        start_date="2025-09-01",
                                        end_date="2025-09-30")
    assert report["universe_coverage"] is not None
    uc = report["universe_coverage"]
    assert uc["universe_size"] >= 1
    assert "missing_count" in uc
    assert "codes_missing" in uc


def test_write_report_lands_under_logs_dir(tmp_path):
    report = {"schema_version": "0.2", "x": 1}
    target = validate_data.write_report(report, logs_dir=str(tmp_path))
    assert os.path.isfile(target)
    with open(target, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded["schema_version"] == "0.2"
    assert loaded["x"] == 1


def test_main_writes_to_logs_dir(sample_db_path, tmp_path, monkeypatch):
    if not os.path.isfile(sample_db_path):
        pytest.skip("sample_db unavailable")
    monkeypatch.setattr(paths, "LOGS_DIR", str(tmp_path).replace("\\", "/"))
    rc = validate_data.main(["--db", sample_db_path])
    assert rc == 0
    files = [f for f in os.listdir(str(tmp_path))
             if f.startswith("validate_data_") and f.endswith(".json")]
    assert len(files) == 1


def test_build_report_qmt_self_owned(tmp_path):
    """validate_data 走 qmt_self_owned 路径，输出额外字段。"""
    import datetime as _dt
    import duckdb
    p = str(tmp_path / "qmt.duckdb")
    conn = duckdb.connect(p, read_only=False)
    conn.execute("""
        CREATE TABLE dat_day (
            code VARCHAR NOT NULL, trade_date DATE NOT NULL,
            open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
            vol BIGINT, amount DOUBLE,
            adjustment VARCHAR NOT NULL, source VARCHAR NOT NULL,
            synced_at TIMESTAMP NOT NULL)
    """)
    conn.executemany(
        "INSERT INTO dat_day VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [("000001.SZ", _dt.date(2025, 9, 1), 10, 11, 9, 10.5, 100000, 1e6,
          "hfq", "xtquant", _dt.datetime(2026, 6, 14))])
    conn.close()
    report = validate_data.build_report(p, data_source="qmt_self_owned")
    assert report["schema_version"] == "0.3"
    assert report["data_source"] == "qmt_self_owned"
    assert report["volume_unit"] == "share"
    assert report["adjustment"] == "hfq"
    assert report["source_filter"] == "xtquant"
    assert report["min_date"] == "2025-09-01"
    assert report["n_codes"] == 1


def test_main_rejects_unknown_data_source(sample_db_path, tmp_path, monkeypatch):
    """--data-source 必须在 SUPPORTED_SOURCES 内，argparse choices 严格校验。"""
    if not os.path.isfile(sample_db_path):
        pytest.skip("sample_db unavailable")
    monkeypatch.setattr(paths, "LOGS_DIR", str(tmp_path).replace("\\", "/"))
    with pytest.raises(SystemExit):
        validate_data.main(["--db", sample_db_path, "--data-source", "bogus"])
