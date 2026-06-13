# coding: utf-8
from backtest.data_tools.duckdb_reader import DuckDBDailyReader


def test_dedup_unique_per_code_date(sample_db_path):
    r = DuckDBDailyReader(sample_db_path)
    out = r.load_window(["000001.SZ"], "2025-09-01", "2025-09-30")
    df = out["000001.SZ"]
    assert df["date"].is_unique
    cov = r.coverage()
    assert cov["dedup_count"] >= 5  # injected dup pairs
    r.close()
