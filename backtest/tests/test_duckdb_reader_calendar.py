# coding: utf-8
from backtest.data_tools.duckdb_reader import DuckDBDailyReader


def test_calendar_distinct_trade_dates(sample_db_path):
    r = DuckDBDailyReader(sample_db_path)
    cal = r.trading_calendar("2025-09-01", "2025-09-30")
    assert len(cal) > 15
    assert all(isinstance(d, str) and len(d) == 10 for d in cal)
    r.close()


def test_calendar_includes_suspension_day(sample_db_path):
    # 300059.SZ 停牌的 5 天，只要别的股票有数据日历仍包含
    r = DuckDBDailyReader(sample_db_path)
    cal = r.trading_calendar("2025-09-15", "2025-09-19")
    assert len(cal) >= 1
    r.close()
