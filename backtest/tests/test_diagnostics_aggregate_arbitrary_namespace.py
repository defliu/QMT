# coding: utf-8
"""TASK-5: 证明任意 namespace 自动进 summary。

注册临时 spy 策略，返回自定义 namespace，断言 summary 里
strategy_specific.{name}.{key}_avg_per_day 存在。
"""
import pandas as pd
from backtest.engine.daily_engine import run_backtest
from backtest.strategies import strategy_spy


class FakeReader(object):
    def __init__(self, market, calendar, db_path="fake.duckdb",
                 db_mtime="2026-06-14T00:00:00", wal=False):
        self.market = market
        self.calendar = calendar
        self.db_path = db_path
        self._db_mtime = db_mtime
        self.wal_detected = wal
        self.wal_warning_message = ""

    def coverage(self, codes=None, start_date=None, end_date=None):
        cov = {
            "min_date":           self.calendar[0],
            "max_date":           self.calendar[-1],
            "n_codes":            len(self.market),
            "n_rows_after_dedup": sum(len(df) for df in self.market.values()),
            "dedup_count":        0,
            "db_mtime":           self._db_mtime,
        }
        if codes is not None:
            present = [c for c in codes if c in self.market]
            missing = [c for c in codes if c not in self.market]
            cov["universe_coverage"] = {
                "universe_size":   len(codes),
                "codes_with_data": len(present),
                "codes_missing":   missing,
                "missing_count":   len(missing),
            }
        return cov

    def trading_calendar(self, start_date, end_date):
        return [d for d in self.calendar if start_date <= d <= end_date]

    def load_window(self, codes, start_date, end_date):
        out = {}
        for code in codes:
            if code not in self.market:
                continue
            df = self.market[code]
            sub = df[(df["date"].astype(str) >= start_date)
                     & (df["date"].astype(str) <= end_date)]
            if len(sub) > 0:
                out[code] = sub.reset_index(drop=True)
        return out


def _build_market(n_days=10, start="2025-09-01"):
    dates = pd.bdate_range(start=start, periods=n_days).strftime("%Y-%m-%d").tolist()
    df = pd.DataFrame({
        "date":  dates,
        "open":  [10.0] * n_days,
        "high":  [10.5] * n_days,
        "low":   [9.5]  * n_days,
        "close": [10.0] * n_days,
        "vol":   [1000] * n_days,
        "amount": [10000.0] * n_days,
    })
    return {"000001.SZ": df}, dates


_SPY_NAME = "test/arbitrary_namespace_spy"


def _evaluate_day(current_date, market_window, positions, cash,
                  universe, account_state, strategy_config, aux_data):
    return {
        "sell_decisions":     [],
        "buy_candidates":     [],
        "target_positions":   [],
        "blocked_candidates": [],
        "diagnostics": {
            "warnings":         [],
            "candidate_total":  1,
            "candidate_passed": 0,
            "strategy_specific": {
                "my_test_strat": {
                    "custom_counts": {"a": 1, "b": 2},
                },
            },
        },
        "logs": [],
    }


def test_arbitrary_namespace_enters_summary():
    """任意 namespace 自动进 summary.diagnostics_aggregate.strategy_specific。"""
    with strategy_spy(_SPY_NAME, fn=_evaluate_day):
        market, dates = _build_market()
        reader = FakeReader(market, dates)
        result = run_backtest(
            reader=reader, universe=["000001.SZ"],
            start_date=dates[0], end_date=dates[-1],
            strategy_config={"max_positions": 5},
            execution_cfg={"price": "next_open", "slippage": 0.001,
                           "commission_rate": 0.00025, "tax_rate": 0.0001},
            initial_cash=1_000_000.0, universe_hash="u", config_hash="c",
            strategy_name=_SPY_NAME,
            trading_model="next_open",
        )
        da = result["summary"]["diagnostics_aggregate"]
        ss = da["strategy_specific"]
        assert "my_test_strat" in ss, (
            "my_test_strat namespace 应被自动聚合，实际 keys=" + str(list(ss.keys()))
        )
        mts = ss["my_test_strat"]
        assert "custom_counts_avg_per_day" in mts, (
            "custom_counts 应走 avg_per_day 聚合，实际 keys=" + str(list(mts.keys()))
        )
        agg = mts["custom_counts_avg_per_day"]
        assert agg["a"] > 0
        assert agg["b"] > 0


def test_arbitrary_namespace_present_marker():
    """非 number dict 的字段应标 _present=True。"""
    spy2_name = "test/arbitrary_present_spy"

    def _evaluate_day2(current_date, market_window, positions, cash,
                       universe, account_state, strategy_config, aux_data):
        return {
            "sell_decisions":     [],
            "buy_candidates":     [],
            "target_positions":   [],
            "blocked_candidates": [],
            "diagnostics": {
                "warnings":         [],
                "candidate_total":  0,
                "candidate_passed": 0,
                "strategy_specific": {
                    "my_test_strat": {
                        "custom_counts": {"a": 1, "b": 2},
                        "custom_meta":   {"nested": "value"},
                    },
                },
            },
            "logs": [],
        }
    with strategy_spy(spy2_name, fn=_evaluate_day2):
        market, dates = _build_market()
        reader = FakeReader(market, dates)
        result = run_backtest(
            reader=reader, universe=["000001.SZ"],
            start_date=dates[0], end_date=dates[-1],
            strategy_config={"max_positions": 5},
            execution_cfg={"price": "next_open", "slippage": 0.001,
                           "commission_rate": 0.00025, "tax_rate": 0.0001},
            initial_cash=1_000_000.0, universe_hash="u", config_hash="c",
            strategy_name=spy2_name,
            trading_model="next_open",
        )
        da = result["summary"]["diagnostics_aggregate"]
        ss = da["strategy_specific"]["my_test_strat"]
        assert "custom_counts_avg_per_day" in ss
        assert ss.get("custom_meta_present") is True
