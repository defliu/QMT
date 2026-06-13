import os
from backtest.data_tools.duckdb_reader import DuckDBDailyReader

def test_wal_detected(sample_db_path, tmp_path):
    wal = sample_db_path + ".wal"
    open(wal, "w").write("")
    try:
        r = DuckDBDailyReader(sample_db_path)
        assert r.wal_detected is True
        assert "金策智算可能正在同步" in r.wal_warning_message
        r.close()
    finally:
        os.remove(wal)

def test_wal_absent(sample_db_path):
    r = DuckDBDailyReader(sample_db_path)
    assert r.wal_detected is False
    r.close()
