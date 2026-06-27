import os
from backtest import paths

def test_workspace_root_on_f_drive():
    assert paths.WORKSPACE_ROOT.replace("\\", "/").startswith("F:/backtest_workspace")

def test_results_dir_under_workspace():
    assert paths.RESULTS_DIR.startswith(paths.WORKSPACE_ROOT)
    for k in ["RESULTS_DIR", "SAMPLE_DB_DIR", "CACHE_DIR", "LOGS_DIR", "BATCH_DIR", "ARCHIVE_DIR"]:
        assert getattr(paths, k).startswith(paths.WORKSPACE_ROOT)

def test_jince_db_path_pointer_only():
    assert paths.JINCE_DB_PATH.endswith("quantifydata.duckdb")
    assert "金策智算" in paths.JINCE_DB_PATH

def test_v03_market_db_resolved_to_f_drive():
    # D10 / OQ-1 closure: placeholder resolved to actual F: drive path
    assert hasattr(paths, "PROJECT_MARKET_DB")
    assert paths.PROJECT_MARKET_DB.startswith("F:/")
    assert "qmt_market_data.duckdb" in paths.PROJECT_MARKET_DB
