# coding: utf-8
import pytest
from backtest.data_tools.duckdb_reader import DuckDBDailyReader


def test_coverage_full(sample_db_path):
    r = DuckDBDailyReader(sample_db_path)
    cov = r.coverage()
    for k in ["min_date", "max_date", "n_codes", "n_rows_after_dedup", "dedup_count", "db_mtime"]:
        assert k in cov
    r.close()


def test_coverage_universe_mode(sample_db_path):
    r = DuckDBDailyReader(sample_db_path)
    cov = r.coverage(codes=["000001.SZ", "999999.SZ"], start_date="2025-09-01", end_date="2025-09-30")
    assert cov["universe_coverage"]["universe_size"] == 2
    assert cov["universe_coverage"]["codes_with_data"] == 1
    assert "999999.SZ" in cov["universe_coverage"]["codes_missing"]
    r.close()


def test_out_of_range_raises(sample_db_path):
    r = DuckDBDailyReader(sample_db_path)
    with pytest.raises(ValueError, match="out of coverage"):
        r.load_window(["000001.SZ"], "2024-01-01", "2024-12-31")
    r.close()
