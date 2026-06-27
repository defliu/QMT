# coding: utf-8
"""Tests for minute_signal and astock_minute_reader."""
import os
import shutil
import tempfile

import numpy as np
import pandas as pd
import pytest

from backtest.data_tools.astock_minute_reader import (
    AstockMinuteReader,
    ASTOCK_MINUTE_DIR,
)
from backtest.indicators.minute_signal import (
    breakout_signal_at_time,
    fake_breakout_rate_by_time,
    gen_chip_signal_from_db,
)


ASTOCK_1MIN_EXISTS = os.path.isdir(ASTOCK_MINUTE_DIR)


# ---------------------------------------------------------------------------
# Fixtures: synthetic 1min data
# ---------------------------------------------------------------------------

def _make_1min_df(n_days=30, base_price=10.0, breakout_day=None, breakout_time="10:00"):
    """Build a synthetic 1min DataFrame for testing.

    breakout_day: if set (0-indexed), on that day the 10:00 bar will be above
    all previous days' highs, creating a breakout signal.
    Prices are flat (no trend) so no accidental breakouts occur.
    """
    records = []
    dates = pd.bdate_range("2026-01-01", periods=n_days)
    times = ["09:%02d:00" % m for m in range(30, 60)] + [
        "10:%02d:00" % m for m in range(0, 30)
    ]
    times = times[:60]

    for d_idx, day in enumerate(dates):
        day_high = base_price + 0.1
        day_close = base_price + 0.05
        if breakout_day is not None and d_idx == breakout_day:
            day_high = base_price + n_days * 0.1 + 5.0
            day_close = day_high - 0.1
        for t_str in times:
            h = day_high
            c = day_close
            records.append({
                "trade_date": day,
                "trade_time": pd.Timestamp("%s %s" % (day.strftime("%Y-%m-%d"), t_str)),
                "ts_code": "TEST.SZ",
                "open": c - 0.05,
                "high": h,
                "low": c - 0.1,
                "close": c,
                "vol": 1000.0,
                "amount": 10000.0,
                "adj_factor": 1.0,
            })

    df = pd.DataFrame(records)
    df = df.set_index(["trade_date", "trade_time"])
    return df


@pytest.fixture
def synth_1min():
    return _make_1min_df(n_days=30, breakout_day=25, breakout_time="10:00")


@pytest.fixture
def synth_1min_no_breakout():
    return _make_1min_df(n_days=30, breakout_day=None)


# ---------------------------------------------------------------------------
# TASK-1: AstockMinuteReader tests
# ---------------------------------------------------------------------------

class TestAstockMinuteReader(object):

    @pytest.fixture
    def tmp_minute_dir(self, tmp_path):
        return str(tmp_path / "minute")

    def test_load_returns_none_when_file_missing(self, tmp_minute_dir):
        reader = AstockMinuteReader(minute_dir=tmp_minute_dir, adjustment="raw")
        result = reader.load_minute_window("NOCODE.SZ", "2026-01-01", "2026-06-01")
        assert result is None

    def test_load_with_real_parquet(self, tmp_minute_dir):
        if not ASTOCK_1MIN_EXISTS:
            pytest.skip("astock 1min not found at %s" % ASTOCK_MINUTE_DIR)
        src = os.path.join(ASTOCK_MINUTE_DIR, "600000.SH.parquet")
        if not os.path.isfile(src):
            pytest.skip("600000.SH.parquet not found")
        os.makedirs(tmp_minute_dir, exist_ok=True)
        dst = os.path.join(tmp_minute_dir, "600000.SH.parquet")
        shutil.copy2(src, dst)

        reader = AstockMinuteReader(minute_dir=tmp_minute_dir, adjustment="raw")
        df = reader.load_minute_window("600000.SH", "2026-06-01", "2026-06-18")
        assert df is not None
        assert len(df) > 0
        assert "close" in df.columns
        assert "trade_time" in df.columns

    def test_adjustment_invalid_raises(self, tmp_minute_dir):
        with pytest.raises(ValueError):
            AstockMinuteReader(minute_dir=tmp_minute_dir, adjustment="bad")

    def test_available_codes_empty_dir(self, tmp_minute_dir):
        reader = AstockMinuteReader(minute_dir=tmp_minute_dir)
        assert reader.available_codes() == []

    def test_available_codes_with_files(self, tmp_minute_dir):
        os.makedirs(tmp_minute_dir, exist_ok=True)
        for code in ["000001.SZ", "600000.SH"]:
            pd.DataFrame({"x": [1]}).to_parquet(
                os.path.join(tmp_minute_dir, code + ".parquet")
            )
        reader = AstockMinuteReader(minute_dir=tmp_minute_dir)
        codes = reader.available_codes()
        assert "000001.SZ" in codes
        assert "600000.SH" in codes

    def test_qfq_adjustment(self, tmp_minute_dir):
        os.makedirs(tmp_minute_dir, exist_ok=True)
        dates = pd.bdate_range("2026-01-01", periods=3)
        records = []
        for d in dates:
            for m in [0, 30]:
                records.append({
                    "trade_date": d,
                    "trade_time": pd.Timestamp("%s 10:%02d:00" % (d.strftime("%Y-%m-%d"), m)),
                    "ts_code": "TEST.SZ",
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.0,
                    "close": 10.5,
                    "vol": 1000.0,
                    "amount": 10000.0,
                    "adj_factor": 1.0 if m == 0 else 2.0,
                })
        df = pd.DataFrame(records).set_index(["trade_date", "trade_time"])
        df.to_parquet(os.path.join(tmp_minute_dir, "TEST.SZ.parquet"))

        reader = AstockMinuteReader(minute_dir=tmp_minute_dir, adjustment="hfq")
        result = reader.load_minute_window("TEST.SZ", "2026-01-01", "2026-01-05")
        assert result is not None
        assert len(result) == 6


# ---------------------------------------------------------------------------
# TASK-2: breakout_signal_at_time tests
# ---------------------------------------------------------------------------

class TestBreakoutSignalAtTime(object):

    def test_breakout_detected(self, synth_1min):
        result = breakout_signal_at_time(synth_1min, time_str="10:00", lookback_days=20)
        assert isinstance(result, pd.Series)
        assert len(result) == 30
        assert result.iloc[25] is True or result.iloc[25] == True

    def test_no_breakout_all_false(self, synth_1min_no_breakout):
        result = breakout_signal_at_time(synth_1min_no_breakout, time_str="10:00", lookback_days=20)
        assert result.sum() == 0

    def test_empty_input(self):
        result = breakout_signal_at_time(pd.DataFrame(), time_str="10:00")
        assert len(result) == 0

    def test_none_input(self):
        result = breakout_signal_at_time(None, time_str="10:00")
        assert len(result) == 0

    def test_result_index_is_date_strings(self, synth_1min):
        result = breakout_signal_at_time(synth_1min, time_str="10:00", lookback_days=20)
        for idx in result.index:
            assert len(idx) == 10
            assert idx[4] == "-"
            assert idx[7] == "-"


# ---------------------------------------------------------------------------
# TASK-2: fake_breakout_rate_by_time tests
# ---------------------------------------------------------------------------

class TestFakeBreakoutRateByTime(object):

    def test_returns_dict_with_all_times(self, synth_1min):
        times = ["09:30", "10:00", "13:30"]
        result = fake_breakout_rate_by_time(synth_1min, times=times, lookback_days=20)
        assert isinstance(result, dict)
        assert set(result.keys()) == set(times)
        for k, v in result.items():
            assert len(v) == 3
            fake, total, rate = v
            assert isinstance(fake, int)
            assert isinstance(total, int)
            assert isinstance(rate, float)

    def test_empty_input(self):
        result = fake_breakout_rate_by_time(pd.DataFrame())
        assert result == {"09:30": (0, 0, 0.0), "10:00": (0, 0, 0.0),
                          "13:30": (0, 0, 0.0), "14:30": (0, 0, 0.0)}

    def test_rate_between_0_and_1(self, synth_1min):
        result = fake_breakout_rate_by_time(synth_1min, lookback_days=20)
        for fake, total, rate in result.values():
            assert 0.0 <= rate <= 1.0
            if total > 0:
                assert fake <= total


# ---------------------------------------------------------------------------
# TASK-2: gen_chip_signal_from_db tests
# ---------------------------------------------------------------------------

class TestGenChipSignalFromDb(object):

    def test_missing_db_returns_empty(self):
        result = gen_chip_signal_from_db(
            "600000.SH", ["2026-06-18"], "/nonexistent/path.duckdb"
        )
        assert isinstance(result, pd.Series)
        assert len(result) == 0

    def test_with_real_db(self):
        chip_path = None
        for p in [
            "D:/QMT_STRATEGIES/chip_1min_529.duckdb",
            "E:/QMT_STRATEGIES/chip_1min_529.duckdb",
            "D:/QMT_POOL/chip_1min_529.duckdb",
        ]:
            if os.path.isfile(p):
                chip_path = p
                break
        if chip_path is None:
            pytest.skip("chip_1min_529.duckdb not found")
        result = gen_chip_signal_from_db(
            "600000.SH", ["2026-06-18"], chip_path
        )
        assert isinstance(result, pd.Series)


# ---------------------------------------------------------------------------
# TASK-4: Real data integration tests
# ---------------------------------------------------------------------------

class TestRealDataIntegration(object):

    def test_real_1min_breakout(self):
        if not ASTOCK_1MIN_EXISTS:
            pytest.skip("astock 1min dir not found")
        reader = AstockMinuteReader(adjustment="raw")
        df = reader.load_minute_window("600000.SH", "2026-05-01", "2026-06-18")
        if df is None or df.empty:
            pytest.skip("no 1min data for 600000.SH in range")
        result = breakout_signal_at_time(df, time_str="10:00", lookback_days=20)
        assert isinstance(result, pd.Series)
        assert len(result) > 0
        assert result.dtype == bool

    def test_real_1min_available_codes(self):
        if not ASTOCK_1MIN_EXISTS:
            pytest.skip("astock 1min dir not found")
        reader = AstockMinuteReader()
        codes = reader.available_codes()
        assert len(codes) > 100
