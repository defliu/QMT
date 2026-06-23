# coding: utf-8
"""Tests for strategy_core interface skeleton (Task 2.1).

Validates the frozen contract from agent_hub/2026-06-13_backtest_mvp/
03_interface_freeze.md. evaluate_day's real body lands in Task 2.4; here we
only assert signature, return shape, and enum completeness.
"""
import inspect


def test_evaluate_day_signature():
    from backtest.strategy_core.interface import evaluate_day
    sig = inspect.signature(evaluate_day)
    assert list(sig.parameters) == [
        "current_date", "market_window", "positions", "cash", "universe",
        "account_state", "strategy_config", "aux_data",
    ]


def test_make_empty_decision_keys():
    from backtest.strategy_core.interface import make_empty_decision
    d = make_empty_decision()
    for k in ["sell_decisions", "buy_candidates", "target_positions",
              "blocked_candidates", "diagnostics", "logs"]:
        assert k in d
    diag = d["diagnostics"]
    # 通用字段
    assert set(diag.keys()) == {"warnings", "candidate_total", "candidate_passed",
                                "strategy_specific"}
    assert diag["warnings"] == []
    assert diag["candidate_total"]  == 0
    assert diag["candidate_passed"] == 0

    # 策略私有字段
    ss = diag["strategy_specific"]
    assert set(ss.keys()) == {"ima_uptrend_v31"}
    ima = ss["ima_uptrend_v31"]
    assert set(ima.keys()) == {"scores", "filter_counts", "trigger_counts"}
    assert ima["scores"] == {}
    fc = ima["filter_counts"]
    assert set(fc.keys()) == {
        "blocked_min_score", "blocked_min_core", "blocked_max_bias5",
        "blocked_max_daily_pct", "blocked_already_held", "blocked_limit_up",
        "blocked_suspended", "blocked_insufficient_history",
    }
    for v in fc.values():
        assert v == 0
    tc = ima["trigger_counts"]
    assert set(tc.keys()) == {
        "early_stop", "early_kick", "stop_loss", "score_drop",
        "replace", "warning", "confirm",
    }
    for v in tc.values():
        assert v == 0


def test_evaluate_day_returns_empty_decision_skeleton():
    """Task 2.1 stage: evaluate_day returns an empty decision; Task 2.4 fills the body."""
    from backtest.strategy_core.interface import evaluate_day, make_empty_decision
    out = evaluate_day(
        current_date="2025-09-01",
        market_window={},
        positions=[],
        cash=1000000.0,
        universe=[],
        account_state={
            "current_date": "2025-09-01", "trading_day_index": 1,
            "total_asset": 1000000.0, "market_value": 0.0,
            "is_last_trading_day": False, "max_positions": 5,
        },
        strategy_config={},
        aux_data={
            "fundamentals": None, "sector_map": None,
            "sector_heat": {}, "benchmark": None,
            "trading_calendar": [], "warnings": [],
        },
    )
    expected = make_empty_decision()
    assert set(out.keys()) == set(expected.keys())


def test_enums_complete():
    """Verify the signed enum set (OQ-A: EARLY_KICK present; bottom_line is a layer, not a reason)."""
    from backtest.strategy_core import enums
    # 7 sell reasons
    assert enums.SELL_REASON_STOP_LOSS == "stop_loss"
    assert enums.SELL_REASON_EARLY_STOP == "early_stop"
    assert enums.SELL_REASON_EARLY_KICK == "early_kick"      # OQ-A
    assert enums.SELL_REASON_REPLACE == "replace"
    assert enums.SELL_REASON_SCORE_DROP == "score_drop"
    assert enums.SELL_REASON_WARNING == "warning"
    assert enums.SELL_REASON_CONFIRM == "confirm"
    # 03 section 7 dropped BOTTOM_LINE as a reason (it's a layer)
    assert not hasattr(enums, "SELL_REASON_BOTTOM_LINE")
    # 8 blocked reasons
    for name in ["BLOCKED_MIN_SCORE", "BLOCKED_MIN_CORE", "BLOCKED_MAX_BIAS5",
                 "BLOCKED_MAX_DAILY_PCT", "BLOCKED_ALREADY_HELD",
                 "BLOCKED_LIMIT_UP", "BLOCKED_SUSPENDED",
                 "BLOCKED_INSUFFICIENT_HISTORY"]:
        assert hasattr(enums, name)
