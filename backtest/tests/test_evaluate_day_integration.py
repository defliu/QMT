# coding: utf-8
"""End-to-end integration tests for evaluate_day after Task 2.4."""
import numpy as np
import pandas as pd
import pytest
from backtest.strategy_core import enums
from backtest.strategy_core.interface import evaluate_day, make_empty_decision


def _mw(code, last_close=10.5, prev_close=10.4, bars=70, base=10.0,
        current_date="2025-09-30"):
    n = bars
    idx = pd.date_range(end=current_date, periods=n)
    closes = np.linspace(base, last_close, n)
    closes[-2] = prev_close
    closes[-1] = last_close
    rng = np.random.default_rng(seed=hash(code) & 0xFFFF)
    return pd.DataFrame({
        "date":  idx.strftime("%Y-%m-%d"),
        "open":  closes,
        "high":  closes + 0.1,
        "low":   closes - 0.1,
        "close": closes,
        "vol":   rng.integers(800_000, 1_200_000, n),
        "amount":closes * rng.integers(800_000, 1_200_000, n),
    })


def _cfg(**ovr):
    base = {
        "max_positions": 5, "rebalance_policy": "daily",
        "min_score": 0.0, "min_core": 0.0,  # loose so most pass
        "max_bias5": 100.0, "max_daily_pct": 9.0,
        "sector_heat_mode": "zero", "score_gap_threshold": 15.0,
        "early_stop_days": 3, "early_stop_loss": -0.05,
        "stop_loss": -0.08, "warning_score_threshold": 50.0,
        "early_stop_holding_days": 5, "early_stop_min_return": 0.03,
    }
    base.update(ovr)
    return base


def _account(total=1_000_000.0, max_pos=5):
    return {"current_date": "2025-09-30", "trading_day_index": 30,
            "total_asset": total, "market_value": 0.0,
            "is_last_trading_day": False, "max_positions": max_pos}


def _aux():
    return {"fundamentals": None, "sector_map": None, "sector_heat": {},
            "benchmark": None, "trading_calendar": [], "warnings": []}


# ---------- shape ----------
def test_evaluate_day_returns_full_decision_shape():
    d = evaluate_day(
        current_date="2025-09-30",
        market_window={},
        positions=[],
        cash=1e6,
        universe=[],
        account_state=_account(),
        strategy_config=_cfg(),
        aux_data=_aux(),
    )
    expected = make_empty_decision()
    assert set(d.keys()) == set(expected.keys())
    assert set(d["diagnostics"].keys()) == set(expected["diagnostics"].keys())


def test_empty_universe_empty_market_runs_clean():
    d = evaluate_day("2025-09-30", {}, [], 1e6, [], _account(), _cfg(), _aux())
    assert d["sell_decisions"] == []
    assert d["buy_candidates"] == []
    assert d["blocked_candidates"] == []
    assert d["diagnostics"]["filter_counts"]["candidate_total"] == 0


# ---------- end-to-end basic ----------
def test_evaluate_day_picks_top_candidate():
    mw = {"A": _mw("A"), "B": _mw("B")}
    d = evaluate_day("2025-09-30", mw, [], 1e6, ["A","B"],
                     _account(), _cfg(), _aux())
    # diagnostics.scores must contain both
    assert "A" in d["diagnostics"]["scores"]
    assert "B" in d["diagnostics"]["scores"]
    # candidate_total = 2
    assert d["diagnostics"]["filter_counts"]["candidate_total"] == 2


def test_evaluate_day_logs_present():
    d = evaluate_day("2025-09-30", {}, [], 1e6, [], _account(), _cfg(), _aux())
    assert len(d["logs"]) >= 1


def test_evaluate_day_warnings_merged():
    """score_universe 的 warnings 应合并到 decision.diagnostics.warnings."""
    short_df = _mw("X", bars=30)  # < 60 -> warn
    mw = {"X": short_df, "A": _mw("A")}
    d = evaluate_day("2025-09-30", mw, [], 1e6, ["X","A"],
                     _account(), _cfg(), _aux())
    warns = d["diagnostics"]["warnings"]
    assert any("insufficient" in w.lower() for w in warns)


# ---------- purity / determinism ----------
def test_evaluate_day_is_deterministic():
    """同一输入两次调用必须返回相同结果（03 section 1 约束 1: 纯函数语义）."""
    mw = {"A": _mw("A"), "B": _mw("B")}
    d1 = evaluate_day("2025-09-30", mw, [], 1e6, ["A","B"],
                      _account(), _cfg(), _aux())
    d2 = evaluate_day("2025-09-30", mw, [], 1e6, ["A","B"],
                      _account(), _cfg(), _aux())
    # buy_candidates ordering / scores must be byte-identical (modulo float repr)
    assert [b["code"] for b in d1["buy_candidates"]] == [b["code"] for b in d2["buy_candidates"]]
    assert d1["diagnostics"]["filter_counts"] == d2["diagnostics"]["filter_counts"]


def test_evaluate_day_no_input_mutation():
    """evaluate_day 不得修改入参（aux_data.warnings 等）."""
    aux = _aux()
    aux["warnings"].append("preexisting")
    aux_snapshot = dict(aux)
    aux_warnings_snapshot = list(aux["warnings"])

    mw = {"A": _mw("A")}
    evaluate_day("2025-09-30", mw, [], 1e6, ["A"],
                 _account(), _cfg(), _aux())  # 用新 _aux 避免污染上面 snapshot
    assert aux == aux_snapshot
    assert aux["warnings"] == aux_warnings_snapshot


# ---------- sell + buy combined ----------
def test_sell_stop_loss_then_buy_other():
    """持仓 P 跌停 -> sell stop_loss; 候选 C 高分 -> buy."""
    mw = {"P": _mw("P", last_close=8.5, prev_close=8.6, base=10.0),
          "C": _mw("C", last_close=11.0, prev_close=10.9, base=10.0)}
    pos = [{"code":"P","volume":1000,"available_volume":1000,"cost_price":10.0,
            "entry_date":"2025-09-01","holding_days":5,"last_price":8.5,
            "unrealized_pnl":-1500}]
    d = evaluate_day("2025-09-30", mw, pos, 0.0, ["P","C"],
                     _account(max_pos=2), _cfg(), _aux())
    sell_codes = [s["code"] for s in d["sell_decisions"]]
    sell_reasons = [s["reason"] for s in d["sell_decisions"]]
    assert "P" in sell_codes
    assert enums.SELL_REASON_STOP_LOSS in sell_reasons
    # trigger count
    assert d["diagnostics"]["trigger_counts"]["stop_loss"] >= 1


def test_sector_heat_mode_static_raises():
    """v0.2 仅支持 zero（OQ-D / 03 section 4 约束 2）."""
    with pytest.raises(NotImplementedError):
        evaluate_day("2025-09-30", {"A": _mw("A")}, [], 1e6, ["A"],
                     _account(), _cfg(sector_heat_mode="static"), _aux())


# ---------- defensive ----------
def test_evaluate_day_handles_none_universe():
    d = evaluate_day("2025-09-30", {}, [], 1e6, None, _account(), _cfg(), _aux())
    assert d["buy_candidates"] == []


def test_evaluate_day_handles_none_positions():
    d = evaluate_day("2025-09-30", {"A": _mw("A")}, None, 1e6, ["A"],
                     _account(), _cfg(), _aux())
    # Should not crash on None positions
    assert isinstance(d["sell_decisions"], list)


def test_evaluate_day_handles_none_aux_data():
    """aux_data=None 也不该崩."""
    d = evaluate_day("2025-09-30", {}, [], 1e6, [], _account(), _cfg(), None)
    assert isinstance(d, dict)
