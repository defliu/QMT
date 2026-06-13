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
    assert report["schema_version"] == "0.2"
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
