# coding: utf-8
"""Tests for AstockParquetReader (Phase 4a, D5)."""
import os

import pytest

from backtest.data_tools.astock_reader import AstockParquetReader, ASTOCK_DAILY_PATH


ASTOCK_EXISTS = os.path.isfile(ASTOCK_DAILY_PATH)


@pytest.fixture
def reader():
    if not ASTOCK_EXISTS:
        pytest.skip("astock parquet not found at %s" % ASTOCK_DAILY_PATH)
    return AstockParquetReader()


def test_load_window_returns_dict_of_dataframes(reader):
    result = reader.load_window(["000001.SZ"], "2025-09-01", "2025-09-10")
    assert "000001.SZ" in result
    df = result["000001.SZ"]
    assert list(df.columns) == ["date", "open", "high", "low", "close", "vol", "amount"]
    assert len(df) >= 1


def test_load_window_multiple_codes(reader):
    result = reader.load_window(["000001.SZ", "000002.SZ"], "2025-09-01", "2025-09-10")
    assert len(result) == 2
    assert "000001.SZ" in result
    assert "000002.SZ" in result


def test_load_window_empty_codes_raises(reader):
    with pytest.raises(ValueError):
        reader.load_window([], "2025-09-01", "2025-09-10")


def test_trading_calendar(reader):
    cal = reader.trading_calendar("2025-09-01", "2025-09-10")
    assert isinstance(cal, list)
    assert len(cal) >= 1
    assert all(isinstance(d, str) for d in cal)
    assert cal == sorted(cal)


def test_coverage(reader):
    cov = reader.coverage()
    assert "min_date" in cov
    assert "max_date" in cov
    assert "n_codes" in cov
    assert cov["n_codes"] > 0
    assert cov["data_source"] == "astock"


def test_coverage_with_codes(reader):
    cov = reader.coverage(codes=["000001.SZ"], start_date="2025-09-01", end_date="2025-09-10")
    assert "universe_coverage" in cov
    uc = cov["universe_coverage"]
    assert uc["universe_size"] == 1
    assert uc["codes_with_data"] >= 1
    assert uc["missing_count"] == 0


def test_close_price(reader):
    price = reader.close("000001.SZ", "2025-09-05")
    assert price is not None
    assert isinstance(price, float)
    assert price > 0


def test_close_price_missing_code(reader):
    price = reader.close("999999.SZ", "2025-09-05")
    assert price is None


def test_close_no_args_noop(reader):
    result = reader.close()
    assert result is None
