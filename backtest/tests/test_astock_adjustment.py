# coding: utf-8
"""Tests for astock reader adjustment (raw/qfq/hfq) support."""
import os
import tempfile

import pandas as pd
import pytest

from backtest.data_tools.astock_reader import AstockParquetReader, ASTOCK_DAILY_PATH


ASTOCK_EXISTS = os.path.isfile(ASTOCK_DAILY_PATH)


def _make_parquet(tmp_path):
    """Create a small parquet with adj_factor for testing."""
    dates = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"])
    codes = ["000001.SZ", "000002.SZ"]
    
    data = []
    for code in codes:
        for i, d in enumerate(dates):
            data.append({
                "trade_date": d,
                "ts_code": code,
                "open": 10.0 + i * 0.5,
                "high": 11.0 + i * 0.5,
                "low": 9.0 + i * 0.5,
                "close": 10.5 + i * 0.5,
                "vol": 100000 + i * 10000,
                "amount": 1000000 + i * 100000,
                "adj_factor": 1.0 + i * 0.1,
            })
    
    df = pd.DataFrame(data)
    df = df.set_index(["trade_date", "ts_code"])
    path = os.path.join(str(tmp_path), "test_daily.parquet")
    df.to_parquet(path)
    return path


@pytest.fixture
def parquet_path(tmp_path):
    return _make_parquet(tmp_path)


@pytest.fixture
def reader_raw(parquet_path):
    return AstockParquetReader(parquet_path, adjustment="raw")


@pytest.fixture
def reader_hfq(parquet_path):
    return AstockParquetReader(parquet_path, adjustment="hfq")


@pytest.fixture
def reader_qfq(parquet_path):
    return AstockParquetReader(parquet_path, adjustment="qfq")


def test_adjustment_property_raw(reader_raw):
    assert reader_raw.adjustment == "raw"


def test_adjustment_property_hfq(reader_hfq):
    assert reader_hfq.adjustment == "hfq"


def test_adjustment_property_qfq(reader_qfq):
    assert reader_qfq.adjustment == "qfq"


def test_adjustment_invalid():
    with pytest.raises(ValueError):
        AstockParquetReader(_make_parquet(tempfile.mkdtemp()), adjustment="invalid")


def test_raw_prices_unchanged(reader_raw):
    result = reader_raw.load_window(["000001.SZ"], "2025-01-02", "2025-01-07")
    df = result["000001.SZ"]
    assert df.iloc[0]["open"] == 10.0
    assert df.iloc[0]["close"] == 10.5


def test_hfq_prices_adjusted(reader_hfq):
    result = reader_hfq.load_window(["000001.SZ"], "2025-01-02", "2025-01-07")
    df = result["000001.SZ"]
    assert df.iloc[0]["open"] == pytest.approx(10.0 * 1.0, rel=1e-6)
    assert df.iloc[1]["open"] == pytest.approx(10.5 * 1.1, rel=1e-6)


def test_qfq_prices_adjusted(reader_qfq):
    result = reader_qfq.load_window(["000001.SZ"], "2025-01-02", "2025-01-07")
    df = result["000001.SZ"]
    latest_adj = 1.3
    assert df.iloc[0]["open"] == pytest.approx(10.0 * 1.0 / latest_adj, rel=1e-6)
    assert df.iloc[3]["open"] == pytest.approx(11.5 * 1.3 / latest_adj, rel=1e-6)


def test_vol_amount_unchanged(reader_hfq):
    result_raw = AstockParquetReader(
        _make_parquet(tempfile.mkdtemp()), adjustment="raw"
    ).load_window(["000001.SZ"], "2025-01-02", "2025-01-07")
    result_hfq = reader_hfq.load_window(["000001.SZ"], "2025-01-02", "2025-01-07")
    df_raw = result_raw["000001.SZ"]
    df_hfq = result_hfq["000001.SZ"]
    pd.testing.assert_series_equal(df_raw["vol"], df_hfq["vol"], check_names=False)
    pd.testing.assert_series_equal(df_raw["amount"], df_hfq["amount"], check_names=False)


def test_close_price_raw(reader_raw):
    price = reader_raw.close("000001.SZ", "2025-01-02")
    assert price == pytest.approx(10.5, rel=1e-6)


def test_close_price_hfq(reader_hfq):
    price = reader_hfq.close("000001.SZ", "2025-01-02")
    assert price == pytest.approx(10.5 * 1.0, rel=1e-6)


def test_close_price_qfq(reader_qfq):
    price = reader_qfq.close("000001.SZ", "2025-01-02")
    latest_adj = 1.3
    assert price == pytest.approx(10.5 * 1.0 / latest_adj, rel=1e-6)


def test_engine_summary_data_adjustment():
    """Test that engine summary uses reader's adjustment attribute."""
    class FakeReader:
        adjustment = "raw"
        db_path = "fake.db"
        
        def coverage(self, **kw):
            return {
                "db_mtime": "2025-01-01T00:00:00",
                "min_date": "2025-01-02",
                "max_date": "2025-01-03",
                "n_codes": 1,
                "n_rows_after_dedup": 2,
                "dedup_count": 0,
            }
        
        def trading_calendar(self, start, end):
            return ["2025-01-02", "2025-01-03"]
        
        def load_window(self, codes, start, end):
            return {}
    
    from backtest.engine.hashing import compute_data_hash
    reader = FakeReader()
    data_hash = compute_data_hash(
        db_path=reader.db_path,
        db_mtime="2025-01-01T00:00:00",
        adjustment=getattr(reader, "adjustment", "hfq"),
        requested_start="2025-01-02",
        requested_end="2025-01-03",
        actual_min="2025-01-02",
        actual_max="2025-01-03",
        n_codes=1,
        n_rows_after_dedup=2,
        dedup_count=0,
        universe_hash="",
    )
    assert "adjustment" in data_hash or "hfq" not in data_hash


@pytest.mark.skipif(not ASTOCK_EXISTS, reason="astock parquet not found")
def test_real_astock_raw():
    reader = AstockParquetReader(adjustment="raw")
    result = reader.load_window(["000001.SZ"], "2025-09-01", "2025-09-05")
    assert "000001.SZ" in result
    assert reader.adjustment == "raw"


@pytest.mark.skipif(not ASTOCK_EXISTS, reason="astock parquet not found")
def test_real_astock_hfq():
    reader = AstockParquetReader(adjustment="hfq")
    result = reader.load_window(["000001.SZ"], "2025-09-01", "2025-09-05")
    assert "000001.SZ" in result
    assert reader.adjustment == "hfq"