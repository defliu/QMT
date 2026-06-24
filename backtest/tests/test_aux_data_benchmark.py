# coding: utf-8
"""验证 MS-I: daily_engine 注入 benchmark_closes / benchmark_code 到 aux_data。"""
import pandas as pd
import pytest

from backtest.strategies import register_strategy
from backtest.engine.daily_engine import run_backtest


# spy strategy: 抓 aux_data 到模块级变量
_CAPTURED = {}


@register_strategy("_spy/benchmark_test")
def _spy_evaluate_day(current_date, market_window, positions, cash, universe,
                     account_state, strategy_config, aux_data):
    _CAPTURED["last_aux"] = aux_data
    return {
        "sell_decisions": [],
        "buy_candidates": [],
        "target_positions": [],
        "blocked_candidates": [],
        "diagnostics": {
            "warnings": [],
            "candidate_total": 0,
            "candidate_passed": 0,
            "strategy_specific": {"benchmark_test": {}},
        },
        "logs": [],
    }


# spy 的 ALLOWED_TRADING_MODELS:
# resolve_strategy 按 strategy_name 反推 module path
# backtest.strategies._spy.benchmark_test.strategy → ImportError →
# fallback 到 ["next_open"] (daily_engine.py:241-243), 正好满足。
# 因此 spy 不需要显式设置 ALLOWED_TRADING_MODELS。


class _FakeReader(object):
    """最小 FakeReader, 抄自 test_daily_engine.py。"""
    def __init__(self, market, calendar):
        self.market = market
        self.calendar = calendar
        self.db_path = "fake.duckdb"
        self._db_mtime = "2026-06-24T00:00:00"
        self.wal_detected = False
        self.wal_warning_message = ""

    def coverage(self, codes=None, start_date=None, end_date=None):
        return {
            "min_date":           self.calendar[0],
            "max_date":           self.calendar[-1],
            "n_codes":            len(self.market),
            "n_rows_after_dedup": sum(len(df) for df in self.market.values()),
            "dedup_count":        0,
            "db_mtime":           self._db_mtime,
            "universe_coverage": {
                "universe_size":   len(codes or []),
                "codes_with_data": len(self.market),
                "codes_missing":   [],
                "missing_count":   0,
            },
        }

    def trading_calendar(self, start_date, end_date):
        return list(self.calendar)

    def load_window(self, codes, start_date, end_date):
        return {c: self.market[c] for c in codes if c in self.market}


def _build_simple_market():
    dates = ["2025-09-02", "2025-09-03", "2025-09-04", "2025-09-05"]
    df = pd.DataFrame({
        "date":   dates,
        "open":   [10.0, 10.1, 10.2, 10.3],
        "high":   [10.1, 10.2, 10.3, 10.4],
        "low":    [9.9, 10.0, 10.1, 10.2],
        "close":  [10.05, 10.15, 10.25, 10.35],
        "vol":    [10000, 11000, 12000, 13000],
        "amount": [100500.0, 111650.0, 123000.0, 134550.0],
    })
    return {"000001.SZ": df}, dates


_EXEC = {"price": "next_open", "slippage": 0.001,
         "commission_rate": 0.00025, "tax_rate": 0.0001}

_CFG = {"max_positions": 3, "rebalance_policy": "daily",
        "min_score": 0.0, "min_core": 0.0, "max_bias5": 100.0,
        "max_daily_pct": 9.0, "sector_heat_mode": "zero",
        "score_gap_threshold": 15.0,
        "early_stop_days": 3, "early_stop_loss": -0.05,
        "stop_loss": -0.08, "warning_score_threshold": 50.0,
        "early_stop_holding_days": 5, "early_stop_min_return": 0.03}


@pytest.fixture(autouse=True)
def _reset():
    _CAPTURED.clear()
    yield
    _CAPTURED.clear()


def test_aux_data_has_benchmark_keys_when_disabled():
    """benchmark_code=None 时 benchmark_closes 必须存在且为 None。"""
    market, dates = _build_simple_market()
    reader = _FakeReader(market, dates)
    run_backtest(
        reader=reader, universe=["000001.SZ"],
        start_date=dates[0], end_date=dates[-1],
        strategy_config=_CFG, execution_cfg=_EXEC,
        initial_cash=1_000_000.0, config_name="ms_i_test",
        universe_hash="ufake", config_hash="cfake",
        strategy_name="_spy/benchmark_test",
        trading_model="next_open",
        benchmark_code=None,
    )
    aux = _CAPTURED.get("last_aux", {})
    assert "benchmark_closes" in aux, "MS-I 未注入 benchmark_closes key"
    assert "benchmark_code" in aux, "MS-I 未注入 benchmark_code key"
    assert aux["benchmark_closes"] is None
    assert aux["benchmark_code"] is None


def test_trading_calendar_still_present_regression():
    """回归：trading_calendar 注入逻辑没被破坏。"""
    market, dates = _build_simple_market()
    reader = _FakeReader(market, dates)
    run_backtest(
        reader=reader, universe=["000001.SZ"],
        start_date=dates[0], end_date=dates[-1],
        strategy_config=_CFG, execution_cfg=_EXEC,
        initial_cash=1_000_000.0, config_name="ms_i_test",
        universe_hash="ufake", config_hash="cfake",
        strategy_name="_spy/benchmark_test",
        trading_model="next_open",
    )
    aux = _CAPTURED.get("last_aux", {})
    assert "trading_calendar" in aux
    assert aux["trading_calendar"] == dates
