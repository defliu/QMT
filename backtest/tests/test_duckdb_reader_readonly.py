# coding: utf-8
import duckdb
import pytest
from backtest.data_tools.duckdb_reader import DuckDBDailyReader


def test_reader_opens_read_only(sample_db_path):
    r = DuckDBDailyReader(sample_db_path)
    mode = r._conn.execute("SELECT current_setting('access_mode')").fetchone()[0]
    assert mode.lower() == "read_only"
    r.close()


def test_reader_refuses_write(sample_db_path):
    r = DuckDBDailyReader(sample_db_path)
    with pytest.raises(Exception):
        r._conn.execute("CREATE TABLE foo(x INT)")
    r.close()
