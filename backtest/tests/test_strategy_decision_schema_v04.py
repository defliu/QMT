# coding: utf-8
"""Milestone B 验证：v0.4 diagnostics schema 形状 + get_strategy_diag 取数。

SPEC: specs/SPEC_BACKTEST_FACTORY_V0.4_GENERALIZATION_PHASE1.md §3.3
"""

from backtest.strategy_core.interface import make_empty_decision
from backtest.strategies import get_strategy_diag


def test_empty_decision_top_keys():
    d = make_empty_decision()
    assert set(d.keys()) == {
        "sell_decisions", "buy_candidates", "target_positions",
        "blocked_candidates", "diagnostics", "logs",
    }


def test_empty_decision_diagnostics_common_keys():
    """通用字段在 diagnostics 顶层。"""
    diag = make_empty_decision()["diagnostics"]
    assert set(diag.keys()) == {
        "warnings", "candidate_total", "candidate_passed", "strategy_specific",
    }
    assert diag["warnings"] == []
    assert diag["candidate_total"]  == 0
    assert diag["candidate_passed"] == 0


def test_empty_decision_strategy_specific_namespace():
    """私有字段挂在 strategy_specific.{name}。"""
    ss = make_empty_decision()["diagnostics"]["strategy_specific"]
    assert set(ss.keys()) == {"ima_uptrend_v31"}
    ima = ss["ima_uptrend_v31"]
    assert set(ima.keys()) == {"scores", "filter_counts", "trigger_counts"}
    assert ima["scores"] == {}


def test_empty_decision_filter_counts_8_keys():
    fc = (make_empty_decision()["diagnostics"]
                                ["strategy_specific"]
                                ["ima_uptrend_v31"]
                                ["filter_counts"])
    expected = {
        "blocked_min_score", "blocked_min_core", "blocked_max_bias5",
        "blocked_max_daily_pct", "blocked_already_held", "blocked_limit_up",
        "blocked_suspended", "blocked_insufficient_history",
    }
    assert set(fc.keys()) == expected
    assert all(v == 0 for v in fc.values())


def test_empty_decision_trigger_counts_7_keys():
    tc = (make_empty_decision()["diagnostics"]
                                ["strategy_specific"]
                                ["ima_uptrend_v31"]
                                ["trigger_counts"])
    expected = {"early_stop", "early_kick", "stop_loss",
                "score_drop", "replace", "warning", "confirm"}
    assert set(tc.keys()) == expected
    assert all(v == 0 for v in tc.values())


def test_get_strategy_diag_basic():
    d = make_empty_decision()
    fc = get_strategy_diag(d, "production/ima_uptrend_v31", "filter_counts")
    assert isinstance(fc, dict)
    assert "blocked_min_score" in fc


def test_get_strategy_diag_default_on_unknown_key():
    d = make_empty_decision()
    assert get_strategy_diag(d, "production/ima_uptrend_v31", "no_such", 42) == 42


def test_get_strategy_diag_default_on_unknown_strategy():
    d = make_empty_decision()
    assert get_strategy_diag(d, "no/such/strategy", "filter_counts", "X") == "X"
