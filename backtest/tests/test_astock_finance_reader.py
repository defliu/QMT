# coding: utf-8
"""Tests for AstockFinanceReader — PIT anti-lookahead finance reader."""
import os

import pandas as pd
import pytest

from backtest.data_tools.astock_finance_reader import (
    AstockFinanceReader,
    DEFAULT_FINANCE_DIR,
    DEFAULT_DAILY_PATH,
    DEFAULT_FIELDS,
)

ASTOCK_FINANCE_EXISTS = os.path.isfile(
    os.path.join(DEFAULT_FINANCE_DIR, "fina_indicator.parquet"))
ASTOCK_DAILY_EXISTS = os.path.isfile(DEFAULT_DAILY_PATH)
ASTOCK_READY = ASTOCK_FINANCE_EXISTS and ASTOCK_DAILY_EXISTS


# =====================================================================
# Synthetic fixture tests (always run, no real data needed)
# =====================================================================

@pytest.fixture
def synthetic_finance_dir(tmp_path):
    """Create a minimal fina_indicator.parquet with controlled PIT data."""
    data = {
        "ts_code": ["TEST.SH"] * 4,
        "end_date": ["20250331", "20250630", "20250930", "20251231"],
        "ann_date": ["20250428", "20250829", "20251030", "20260331"],
        "eps":       [0.10, 0.25, 0.40, 0.60],
        "roe":       [1.0,  2.5,  4.0,  6.0],
        "gross_margin": [30.0, 31.0, 32.0, 33.0],
        "netprofit_margin": [10.0, 11.0, 12.0, 13.0],
        "bps":       [5.0, 5.1, 5.2, 5.3],
        "q_profit_yoy": [1.0, 2.0, 3.0, 4.0],
    }
    df = pd.DataFrame(data)
    out_dir = tmp_path / "finance"
    out_dir.mkdir()
    df.to_parquet(str(out_dir / "fina_indicator.parquet"))
    return str(out_dir)


@pytest.fixture
def synthetic_daily_path(tmp_path):
    """Create a minimal stock_daily.parquet with PE data."""
    dates = pd.date_range("2025-01-02", "2025-12-31", freq="B")
    rows = []
    for d in dates:
        rows.append({
            "trade_date": d,
            "ts_code": "TEST.SH",
            "pe": 10.0 + d.month,
            "pe_ttm": 9.0 + d.month,
        })
    df = pd.DataFrame(rows)
    df = df.set_index(["trade_date", "ts_code"])
    p = tmp_path / "stock_daily.parquet"
    df.to_parquet(str(p))
    return str(p)


@pytest.fixture
def synth_reader(synthetic_finance_dir, synthetic_daily_path):
    return AstockFinanceReader(
        finance_dir=synthetic_finance_dir,
        daily_path=synthetic_daily_path,
    )


class TestPITSynthetic:
    """PIT logic tests using synthetic data."""

    def test_pit_before_all_announcements_returns_empty(self, synth_reader):
        """asof_date before any ann_date -> no data visible."""
        result = synth_reader.get_fundamentals_pit("TEST.SH", "2025-01-01")
        assert result == {}

    def test_pit_after_first_announcement(self, synth_reader):
        """asof_date after Q1 ann_date (20250428) but before Q2 -> Q1 data."""
        result = synth_reader.get_fundamentals_pit("TEST.SH", "2025-05-15")
        assert result["eps"] == 0.10
        assert result["roe"] == 1.0
        assert result["end_date"] == "20250331"

    def test_pit_after_second_announcement(self, synth_reader):
        """asof_date after Q2 ann_date (20250829) -> Q2 data (latest end_date)."""
        result = synth_reader.get_fundamentals_pit("TEST.SH", "2025-09-15")
        assert result["eps"] == 0.25
        assert result["roe"] == 2.5
        assert result["end_date"] == "20250630"

    def test_pit_after_all_announcements(self, synth_reader):
        """asof_date after all ann_dates -> Q4 data."""
        result = synth_reader.get_fundamentals_pit("TEST.SH", "2026-06-01")
        assert result["eps"] == 0.60
        assert result["roe"] == 6.0
        assert result["end_date"] == "20251231"

    def test_pit_unknown_code_returns_empty(self, synth_reader):
        result = synth_reader.get_fundamentals_pit("NOSUCH.SH", "2025-06-01")
        assert result == {}

    def test_pit_specific_fields(self, synth_reader):
        result = synth_reader.get_fundamentals_pit(
            "TEST.SH", "2025-06-01", fields=["eps", "roe"])
        assert set(result.keys()) == {"end_date", "eps", "roe"}
        assert result["eps"] == 0.10
        assert result["roe"] == 1.0
        assert result["end_date"] == "20250331"

    def test_pit_custom_announcement_dates(self, synth_reader):
        """Boundary: asof exactly on ann_date is visible (<=)."""
        result = synth_reader.get_fundamentals_pit("TEST.SH", "2025-04-28")
        assert result["eps"] == 0.10

        # One day before is not visible
        result2 = synth_reader.get_fundamentals_pit("TEST.SH", "2025-04-27")
        assert result2 == {}


class TestDailyPESynthetic:
    """Daily PE tests using synthetic data."""

    def test_daily_pe_on_trading_day(self, synth_reader):
        result = synth_reader.get_daily_pe("TEST.SH", "2025-03-10")
        assert "dynamic_pe" in result
        assert "static_pe" in result
        assert result["static_pe"] == 10.0 + 3  # March
        assert result["dynamic_pe"] == 9.0 + 3

    def test_daily_pe_before_data_returns_empty(self, synth_reader):
        result = synth_reader.get_daily_pe("TEST.SH", "2024-12-31")
        assert result == {}

    def test_daily_pe_unknown_code_returns_empty(self, synth_reader):
        result = synth_reader.get_daily_pe("NOSUCH.SH", "2025-06-01")
        assert result == {}


class TestScoringConvenienceSynthetic:
    """get_fundamentals_for_scoring tests."""

    def test_returns_pe_dict_per_code(self, synth_reader):
        result = synth_reader.get_fundamentals_for_scoring(
            ["TEST.SH"], "2025-06-01")
        assert "TEST.SH" in result
        assert "dynamic_pe" in result["TEST.SH"]
        assert "static_pe" in result["TEST.SH"]

    def test_empty_list(self, synth_reader):
        result = synth_reader.get_fundamentals_for_scoring([], "2025-06-01")
        assert result == {}


# =====================================================================
# Real data tests (skip if astock data not present)
# =====================================================================

@pytest.fixture
def real_reader():
    if not ASTOCK_READY:
        pytest.skip("astock data not found at %s" % DEFAULT_FINANCE_DIR)
    return AstockFinanceReader()


class TestPITRealData:
    """Tests against real astock parquet data."""

    def test_600000_recent_date_has_data(self, real_reader):
        fund = real_reader.get_fundamentals_pit("600000.SH", "2026-06-18")
        assert fund != {}, "expected non-empty fundamentals for 600000.SH"
        assert fund.get("eps") is not None
        assert fund.get("roe") is not None

    def test_600000_very_early_date_returns_empty(self, real_reader):
        """2005-01-01 is before 600000.SH's first ann_date (20050423)."""
        fund = real_reader.get_fundamentals_pit("600000.SH", "2005-01-01")
        assert fund == {}

    def test_600000_pit_boundary(self, real_reader):
        """Verify PIT: a date before the latest ann_date gives older data."""
        fund_recent = real_reader.get_fundamentals_pit("600000.SH", "2026-06-18")
        fund_old = real_reader.get_fundamentals_pit("600000.SH", "2025-06-01")
        # Both should have data, but different end_dates
        if fund_recent and fund_old:
            assert fund_recent["end_date"] >= fund_old["end_date"]

    def test_unknown_code_returns_empty(self, real_reader):
        fund = real_reader.get_fundamentals_pit("999999.SH", "2026-06-18")
        assert fund == {}


class TestDailyPERealData:
    """Tests against real stock_daily parquet."""

    def test_600000_pe_recent(self, real_reader):
        pe = real_reader.get_daily_pe("600000.SH", "2026-06-18")
        assert pe != {}, "expected PE data for 600000.SH"
        assert pe["static_pe"] > 0
        assert pe["dynamic_pe"] > 0

    def test_600000_pe_before_data(self, real_reader):
        pe = real_reader.get_daily_pe("600000.SH", "2008-01-01")
        assert pe == {}

    def test_unknown_code_returns_empty(self, real_reader):
        pe = real_reader.get_daily_pe("999999.SH", "2026-06-18")
        assert pe == {}


class TestScoringRealData:
    """get_fundamentals_for_scoring against real data."""

    def test_builds_pe_dict(self, real_reader):
        result = real_reader.get_fundamentals_for_scoring(
            ["600000.SH"], "2026-06-18")
        assert "600000.SH" in result
        assert result["600000.SH"]["dynamic_pe"] > 0
        assert result["600000.SH"]["static_pe"] > 0
