# coding: utf-8
"""MS-E 验证：research/example_ma_cross minimal example 策略接入。"""

import pytest

from backtest.strategies import get_strategy, list_strategies


def test_example_ma_cross_registered():
    """example 策略必须在 registry 中。"""
    assert "research/example_ma_cross" in list_strategies()


def test_example_ma_cross_returns_v04_schema():
    """evaluate_day 返回的 decision 符合 v0.4 schema。"""
    fn = get_strategy("research/example_ma_cross")
    d = fn(
        current_date="2025-09-15",
        market_window={},
        positions=[],
        cash=1_000_000.0,
        universe=["000001.SZ", "000002.SZ"],
        account_state={"total_asset": 1_000_000.0, "max_positions": 5},
        strategy_config={"max_positions": 5},
        aux_data=None,
    )

    # 顶层 6 keys
    assert set(d.keys()) == {"sell_decisions", "buy_candidates",
                              "target_positions", "blocked_candidates",
                              "diagnostics", "logs"}

    # diagnostics 通用字段提顶
    diag = d["diagnostics"]
    assert set(diag.keys()) == {"warnings", "candidate_total",
                                  "candidate_passed", "strategy_specific"}
    assert diag["candidate_total"] == 2
    assert diag["candidate_passed"] == 0

    # 私有字段用自己的 namespace
    ss = diag["strategy_specific"]
    assert set(ss.keys()) == {"example_ma_cross"}
    assert set(ss["example_ma_cross"].keys()) == {
        "signal_counts", "blocked_counts",
    }
    assert set(ss["example_ma_cross"]["signal_counts"].keys()) == {
        "golden_cross", "death_cross",
    }
    assert set(ss["example_ma_cross"]["blocked_counts"].keys()) == {
        "insufficient_history", "already_held",
    }


def test_example_ma_cross_golden_cross_triggers_buy():
    """构造能金叉的 market_window，验证 buy_candidates 产出。"""
    import pandas as pd

    closes = [10.0] * 10 + [20.0]
    dates  = ["2025-09-%02d" % (i + 1) for i in range(11)]
    df = pd.DataFrame({
        "date":   dates,
        "open":   closes,
        "high":   closes,
        "low":    closes,
        "close":  closes,
        "vol":    [100] * 11,
        "amount": [1000.0] * 11,
    })

    fn = get_strategy("research/example_ma_cross")
    d = fn(
        current_date="2025-09-11",
        market_window={"000001.SZ": df},
        positions=[],
        cash=1_000_000.0,
        universe=["000001.SZ"],
        account_state={"total_asset": 1_000_000.0, "max_positions": 5},
        strategy_config={"max_positions": 5},
        aux_data=None,
    )
    assert len(d["buy_candidates"]) == 1
    assert d["buy_candidates"][0]["code"] == "000001.SZ"
    assert (d["diagnostics"]["strategy_specific"]
                 ["example_ma_cross"]["signal_counts"]["golden_cross"]) == 1
