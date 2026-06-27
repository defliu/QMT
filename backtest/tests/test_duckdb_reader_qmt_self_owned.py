# coding: utf-8
"""Reader tests for qmt_self_owned schema (v0.3 main path).

Covers:
  - construct with data_source='qmt_self_owned' against trade_date DATE schema
  - explicit data_source required (no auto detection)
  - default filters (adjustment='hfq', source='xtquant') applied
  - load_window / coverage / trading_calendar all return correct shape
  - missing data_source raises
"""
import datetime as _dt
import duckdb
import pytest

from backtest.data_tools.duckdb_reader import (
    DuckDBDailyReader, JINCE_ZHISUAN, QMT_SELF_OWNED, SUPPORTED_SOURCES,
)


def _build_qmt_self_owned_db(tmp_path):
    p = str(tmp_path / "qmt.duckdb")
    conn = duckdb.connect(p, read_only=False)
    conn.execute("""
        CREATE TABLE dat_day (
            code        VARCHAR    NOT NULL,
            trade_date  DATE       NOT NULL,
            open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
            vol BIGINT, amount DOUBLE,
            adjustment VARCHAR NOT NULL,
            source VARCHAR NOT NULL,
            synced_at TIMESTAMP NOT NULL
        )
    """)
    rows = []
    sync_at = _dt.datetime(2026, 6, 14)
    for code in ("000001.SZ", "600519.SH"):
        for i in range(5):
            d = _dt.date(2025, 9, 1) + _dt.timedelta(days=i)
            rows.append((code, d, 10.0+i, 11.0, 9.0, 10.5, 100000+i*1000,
                         1_000_000.0, "hfq", "xtquant", sync_at))
    # 加一行 adjustment=none / source=other 验证默认 filter 起作用
    rows.append(("000001.SZ", _dt.date(2025, 9, 1), 99.0, 99.0, 99.0, 99.0,
                 99, 99.0, "none", "other", sync_at))
    conn.executemany(
        "INSERT INTO dat_day VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.close()
    return p


def test_unknown_data_source_rejected(tmp_path):
    p = _build_qmt_self_owned_db(tmp_path)
    with pytest.raises(ValueError, match="data_source"):
        DuckDBDailyReader(p, data_source="unknown")


def test_supported_sources_constants():
    assert JINCE_ZHISUAN in SUPPORTED_SOURCES
    assert QMT_SELF_OWNED in SUPPORTED_SOURCES


def test_qmt_self_owned_load_window(tmp_path):
    p = _build_qmt_self_owned_db(tmp_path)
    r = DuckDBDailyReader(p, data_source=QMT_SELF_OWNED)
    out = r.load_window(["000001.SZ", "600519.SH"], "2025-09-01", "2025-09-05")
    assert sorted(out.keys()) == ["000001.SZ", "600519.SH"]
    df = out["000001.SZ"]
    assert len(df) == 5
    # 默认 filter 应当过滤掉 adjustment='none' / source='other' 的脏数据
    assert all(df["close"] == 10.5)
    r.close()


def test_qmt_self_owned_coverage(tmp_path):
    p = _build_qmt_self_owned_db(tmp_path)
    r = DuckDBDailyReader(p, data_source=QMT_SELF_OWNED)
    cov = r.coverage()
    assert cov["data_source"] == QMT_SELF_OWNED
    assert cov["min_date"] == "2025-09-01"
    assert cov["max_date"] == "2025-09-05"
    assert cov["n_codes"] == 2
    # filter 生效后只剩 hfq+xtquant 行：2 codes × 5 days = 10
    assert cov["n_rows_after_dedup"] == 10
    r.close()


def test_qmt_self_owned_universe_coverage(tmp_path):
    p = _build_qmt_self_owned_db(tmp_path)
    r = DuckDBDailyReader(p, data_source=QMT_SELF_OWNED)
    cov = r.coverage(codes=["000001.SZ", "300750.SZ"],
                     start_date="2025-09-01", end_date="2025-09-05")
    uc = cov["universe_coverage"]
    assert uc["universe_size"] == 2
    assert uc["codes_with_data"] == 1
    assert "300750.SZ" in uc["codes_missing"]
    r.close()


def test_qmt_self_owned_trading_calendar(tmp_path):
    p = _build_qmt_self_owned_db(tmp_path)
    r = DuckDBDailyReader(p, data_source=QMT_SELF_OWNED)
    cal = r.trading_calendar("2025-09-01", "2025-09-05")
    assert cal == ["2025-09-01", "2025-09-02", "2025-09-03",
                   "2025-09-04", "2025-09-05"]
    r.close()


def test_qmt_self_owned_no_wal_check(tmp_path):
    """qmt_self_owned 不应该做金策智算的 WAL 警告。"""
    p = _build_qmt_self_owned_db(tmp_path)
    # 故意造一个 .wal 文件
    open(p + ".wal", "wb").close()
    r = DuckDBDailyReader(p, data_source=QMT_SELF_OWNED)
    assert r.wal_detected is False
    r.close()


def test_jince_path_unchanged(sample_db_path):
    """显式 jince_zhisuan 时使用旧 schema，不破坏 v0.2 行为。"""
    r = DuckDBDailyReader(sample_db_path, data_source=JINCE_ZHISUAN)
    cov = r.coverage()
    assert cov["data_source"] == JINCE_ZHISUAN
    r.close()


def test_default_data_source_is_jince(sample_db_path):
    """不传 data_source 时默认 jince_zhisuan，向后兼容。"""
    r = DuckDBDailyReader(sample_db_path)
    assert r.data_source == JINCE_ZHISUAN
    r.close()
