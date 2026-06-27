# coding: utf-8
import os, pathlib, tempfile
from backtest import paths
from backtest.scripts import init_workspace

def test_results_dir_on_f_drive():
    assert paths.RESULTS_DIR.replace("\\", "/").lower().startswith("f:/")

def test_no_results_dir_under_d_code():
    bad = pathlib.Path(paths.BACKTEST_ROOT) / "results"
    assert not bad.exists(), "D:/.../backtest/results MUST NOT exist (decision J)"

def test_jince_dir_unchanged_after_reader_round_trip(sample_db_path):
    from backtest.data_tools.duckdb_reader import DuckDBDailyReader
    jince_dir = os.path.dirname(paths.JINCE_DB_PATH)
    if not os.path.isdir(jince_dir):
        return  # CI 环境无金策智算时跳过
    before = sorted(os.listdir(jince_dir))
    r = DuckDBDailyReader(paths.JINCE_DB_PATH)
    r.coverage()
    r.close()
    after = sorted(os.listdir(jince_dir))
    assert before == after, "E:/金策智算/ MUST NOT be written (decision I)"

def test_tempfile_redirected():
    init_workspace.redirect_tempdir()
    assert tempfile.gettempdir().replace("\\", "/").startswith(paths.CACHE_DIR.replace("\\", "/"))
