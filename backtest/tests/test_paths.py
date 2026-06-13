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

def test_v03_open_question_placeholder_exists():
    # 决策 5：v0.3 路径必须以 OPEN_QUESTION 标记保留
    assert hasattr(paths, "PROJECT_MARKET_DB_V03_PLACEHOLDER")
    src = open(paths.__file__, "r", encoding="utf-8").read()
    assert "OPEN_QUESTION" in src
    assert "v0.3" in src
