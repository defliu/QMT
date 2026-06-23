# coding: utf-8
import pandas as pd
import numpy as np
import pytest
from backtest.strategy_core import enums
from backtest.strategies.production.ima_uptrend_v31.decision import make_decision
from backtest.strategies.production.ima_uptrend_v31.risk_adapter import (
    evaluate_position_triggers, pick_top_reason, priority_of,
)


# ---------- helpers ----------
def _mw_row(code, last_close, prev_close, bars=70, base=10.0,
            current_date="2025-09-30"):
    """Build a >=60-bar market window. Last bar's date == current_date."""
    n = bars
    idx = pd.date_range(end=current_date, periods=n)
    closes = np.linspace(base, last_close, n)
    closes[-2] = prev_close
    closes[-1] = last_close
    return pd.DataFrame({
        "date":  idx.strftime("%Y-%m-%d"),
        "open":  closes,
        "high":  closes + 0.1,
        "low":   closes - 0.1,
        "close": closes,
        "vol":   [1_000_000] * n,
        "amount": [1e7] * n,
    })


def _score_rec(code, total=70.0, breakout=18.0, trend=11.0, conso=15.0,
               vp=10.0, macd=9.0, val=4.0, sent=3.0, sector=0.0,
               bias5=5.0, signal="hold"):
    return {"code": code, "score_total": total,
            "score_breakout": breakout, "score_trend": trend,
            "score_consolidation": conso, "score_volumeprice": vp,
            "score_macd": macd, "score_valuation": val,
            "score_sentiment": sent, "score_sector": sector,
            "bias5": bias5, "signal": signal}


def _cfg(**overrides):
    base = {
        "max_positions": 5, "rebalance_policy": "daily",
        "min_score": 60.0, "min_core": 32.0,
        "max_bias5": 10.0, "max_daily_pct": 9.0,
        "sector_heat_mode": "zero", "score_gap_threshold": 15.0,
        "early_stop_days": 3, "early_stop_loss": -0.05,
        "stop_loss": -0.08, "warning_score_threshold": 50.0,
        "early_stop_holding_days": 5, "early_stop_min_return": 0.03,
    }
    base.update(overrides)
    return base


def _account(total=1000000.0, mv=0.0, max_pos=5):
    return {"current_date": "2025-09-30", "trading_day_index": 30,
            "total_asset": total, "market_value": mv,
            "is_last_trading_day": False, "max_positions": max_pos}


def _aux():
    return {"fundamentals": None, "sector_map": None, "sector_heat": {},
            "benchmark": None, "trading_calendar": [], "warnings": []}


# ---------- risk_adapter tests ----------
def test_stop_loss_triggers():
    pos = {"code": "A", "volume": 100, "available_volume": 100, "cost_price": 10.0,
           "entry_date": "2025-09-01", "holding_days": 1, "last_price": 9.0,
           "unrealized_pnl": -100}
    assert enums.SELL_REASON_STOP_LOSS in evaluate_position_triggers(pos, None, _cfg())


def test_early_stop_triggers_at_3_days():
    pos = {"code": "A", "volume": 100, "available_volume": 100, "cost_price": 10.0,
           "entry_date": "2025-09-01", "holding_days": 3, "last_price": 9.4,
           "unrealized_pnl": -60}
    triggered = evaluate_position_triggers(pos, None, _cfg())
    assert enums.SELL_REASON_EARLY_STOP in triggered
    assert enums.SELL_REASON_STOP_LOSS not in triggered


def test_early_kick_triggers_at_5_days():
    pos = {"code": "A", "volume": 100, "available_volume": 100, "cost_price": 10.0,
           "entry_date": "2025-09-01", "holding_days": 5, "last_price": 10.2,
           "unrealized_pnl": 20}
    triggered = evaluate_position_triggers(pos, None, _cfg())
    assert enums.SELL_REASON_EARLY_KICK in triggered


def test_score_drop_triggers_when_score_below_min():
    pos = {"code": "A", "volume": 100, "available_volume": 100, "cost_price": 10.0,
           "entry_date": "2025-09-01", "holding_days": 2, "last_price": 11.0,
           "unrealized_pnl": 100}
    triggered = evaluate_position_triggers(pos, _score_rec("A", total=55.0), _cfg())
    assert enums.SELL_REASON_SCORE_DROP in triggered


def test_warning_triggers_when_score_below_warning_threshold():
    pos = {"code": "A", "volume": 100, "available_volume": 100, "cost_price": 10.0,
           "entry_date": "2025-09-01", "holding_days": 2, "last_price": 11.0,
           "unrealized_pnl": 100}
    triggered = evaluate_position_triggers(pos, _score_rec("A", total=45.0), _cfg())
    assert enums.SELL_REASON_WARNING in triggered
    assert enums.SELL_REASON_SCORE_DROP in triggered


def test_priority_stop_loss_above_score_drop():
    p_sl, _ = priority_of(enums.SELL_REASON_STOP_LOSS)
    p_sd, _ = priority_of(enums.SELL_REASON_SCORE_DROP)
    assert p_sl < p_sd


def test_pick_top_reason_picks_highest_priority():
    triggered = [enums.SELL_REASON_SCORE_DROP, enums.SELL_REASON_STOP_LOSS,
                 enums.SELL_REASON_WARNING]
    assert pick_top_reason(triggered) == enums.SELL_REASON_STOP_LOSS


def test_pick_top_reason_empty():
    assert pick_top_reason([]) is None


def test_confirm_not_triggered_in_v02():
    """OQ-C: SELL_REASON_CONFIRM enum kept but never triggered in v0.2."""
    pos = {"code": "A", "volume": 100, "available_volume": 100, "cost_price": 10.0,
           "entry_date": "2025-09-01", "holding_days": 2, "last_price": 11.0,
           "unrealized_pnl": 100}
    triggered = evaluate_position_triggers(pos, _score_rec("A", total=70.0), _cfg())
    assert enums.SELL_REASON_CONFIRM not in triggered


# ---------- decision filters ----------
def test_blocked_already_held():
    mw = {"A": _mw_row("A", 10.5, 10.4)}
    pos = [{"code": "A", "volume": 100, "available_volume": 100, "cost_price": 10.0,
            "entry_date": "2025-09-01", "holding_days": 1, "last_price": 10.5,
            "unrealized_pnl": 50}]
    d = make_decision("2025-09-30", mw, pos, 0.0, ["A"], _account(), _cfg(),
                      _aux(), [_score_rec("A", total=80.0)])
    assert d["diagnostics"]["strategy_specific"]["ima_uptrend_v31"]["filter_counts"]["blocked_already_held"] == 1
    assert any(b["blocked_by"] == enums.BLOCKED_ALREADY_HELD
               for b in d["blocked_candidates"])


def test_blocked_min_score():
    mw = {"A": _mw_row("A", 10.5, 10.4)}
    d = make_decision("2025-09-30", mw, [], 1e6, ["A"], _account(), _cfg(),
                      _aux(), [_score_rec("A", total=55.0)])
    assert d["diagnostics"]["strategy_specific"]["ima_uptrend_v31"]["filter_counts"]["blocked_min_score"] == 1
    assert d["diagnostics"]["candidate_passed"] == 0


def test_blocked_limit_up():
    mw = {"A": _mw_row("A", 11.05, 10.0)}
    d = make_decision("2025-09-30", mw, [], 1e6, ["A"], _account(), _cfg(),
                      _aux(), [_score_rec("A", total=80.0)])
    assert d["diagnostics"]["strategy_specific"]["ima_uptrend_v31"]["filter_counts"]["blocked_limit_up"] == 1


def test_blocked_max_bias5():
    mw = {"A": _mw_row("A", 10.1, 10.0)}
    d = make_decision("2025-09-30", mw, [], 1e6, ["A"], _account(), _cfg(),
                      _aux(), [_score_rec("A", total=80.0, bias5=15.0)])
    assert d["diagnostics"]["strategy_specific"]["ima_uptrend_v31"]["filter_counts"]["blocked_max_bias5"] == 1


def test_blocked_min_core():
    mw = {"A": _mw_row("A", 10.1, 10.0)}
    rec = _score_rec("A", total=80.0, breakout=1, trend=1, conso=1, vp=1,
                     macd=1, val=1)
    d = make_decision("2025-09-30", mw, [], 1e6, ["A"], _account(), _cfg(),
                      _aux(), [rec])
    assert d["diagnostics"]["strategy_specific"]["ima_uptrend_v31"]["filter_counts"]["blocked_min_core"] == 1


def test_blocked_max_daily_pct():
    mw = {"A": _mw_row("A", 10.95, 10.0)}
    d = make_decision("2025-09-30", mw, [], 1e6, ["A"], _account(), _cfg(),
                      _aux(), [_score_rec("A", total=80.0)])
    assert d["diagnostics"]["strategy_specific"]["ima_uptrend_v31"]["filter_counts"]["blocked_max_daily_pct"] == 1


def test_blocked_suspended_no_data_today():
    df = _mw_row("A", 10.5, 10.4)
    df = df.iloc[:-1]
    mw = {"A": df}
    d = make_decision("2025-09-30", mw, [], 1e6, ["A"], _account(), _cfg(),
                      _aux(), [_score_rec("A", total=80.0)])
    assert d["diagnostics"]["strategy_specific"]["ima_uptrend_v31"]["filter_counts"]["blocked_suspended"] == 1


def test_blocked_insufficient_history():
    df = _mw_row("A", 10.5, 10.4, bars=30)
    mw = {"A": df}
    d = make_decision("2025-09-30", mw, [], 1e6, ["A"], _account(), _cfg(),
                      _aux(), [])
    assert d["diagnostics"]["strategy_specific"]["ima_uptrend_v31"]["filter_counts"]["blocked_insufficient_history"] == 1


# ---------- buy / replace ----------
def test_buy_top_candidates_when_slots_open():
    mw = {"A": _mw_row("A", 10.1, 10.0), "B": _mw_row("B", 11.1, 11.0)}
    d = make_decision("2025-09-30", mw, [], 1e6, ["A", "B"], _account(), _cfg(),
                      _aux(),
                      [_score_rec("A", total=70.0), _score_rec("B", total=80.0)])
    codes = [b["code"] for b in d["buy_candidates"]]
    assert codes == ["B", "A"]
    assert d["buy_candidates"][0]["rank"] == 1
    assert d["buy_candidates"][0]["target_volume"] == 0


def test_replace_when_score_gap_15():
    mw = {"P": _mw_row("P", 10.5, 10.4), "C": _mw_row("C", 11.0, 10.9)}
    pos = [{"code": "P", "volume": 100, "available_volume": 100, "cost_price": 10.0,
            "entry_date": "2025-09-01", "holding_days": 2, "last_price": 10.5,
            "unrealized_pnl": 50}]
    d = make_decision("2025-09-30", mw, pos, 0.0, ["P", "C"],
                      _account(max_pos=1), _cfg(),
                      _aux(),
                      [_score_rec("P", total=60.0), _score_rec("C", total=78.0)])
    sell_reasons = [s["reason"] for s in d["sell_decisions"]]
    buy_codes = [b["code"] for b in d["buy_candidates"]]
    assert enums.SELL_REASON_REPLACE in sell_reasons
    assert "C" in buy_codes
    assert d["diagnostics"]["strategy_specific"]["ima_uptrend_v31"]["trigger_counts"]["replace"] == 1


def test_no_replace_when_gap_below_threshold():
    mw = {"P": _mw_row("P", 10.5, 10.4), "C": _mw_row("C", 11.0, 10.9)}
    pos = [{"code": "P", "volume": 100, "available_volume": 100, "cost_price": 10.0,
            "entry_date": "2025-09-01", "holding_days": 2, "last_price": 10.5,
            "unrealized_pnl": 50}]
    d = make_decision("2025-09-30", mw, pos, 0.0, ["P", "C"],
                      _account(max_pos=1), _cfg(),
                      _aux(),
                      [_score_rec("P", total=65.0), _score_rec("C", total=70.0)])
    assert d["diagnostics"]["strategy_specific"]["ima_uptrend_v31"]["trigger_counts"]["replace"] == 0


# ---------- structural ----------
def test_decision_has_6_top_keys():
    d = make_decision("2025-09-30", {}, [], 1e6, [], _account(), _cfg(),
                      _aux(), [])
    for k in ["sell_decisions", "buy_candidates", "target_positions",
              "blocked_candidates", "diagnostics", "logs"]:
        assert k in d


def test_diagnostics_scores_includes_all_scored():
    """03 section 6 constraint 5: scores covers ALL scored codes."""
    mw = {"A": _mw_row("A", 10.1, 10.0), "B": _mw_row("B", 11.1, 11.0)}
    d = make_decision("2025-09-30", mw, [], 1e6, ["A", "B"], _account(), _cfg(),
                      _aux(),
                      [_score_rec("A", total=80.0), _score_rec("B", total=50.0)])
    assert "A" in d["diagnostics"]["strategy_specific"]["ima_uptrend_v31"]["scores"]
    assert "B" in d["diagnostics"]["strategy_specific"]["ima_uptrend_v31"]["scores"]


def test_target_positions_empty_in_v02():
    d = make_decision("2025-09-30", {}, [], 1e6, [], _account(), _cfg(),
                      _aux(), [])
    assert d["target_positions"] == []


def test_sell_priority_ordering():
    mw = {"A": _mw_row("A", 9.0, 9.1), "B": _mw_row("B", 11.0, 10.9)}
    pos = [
        {"code": "A", "volume": 100, "available_volume": 100, "cost_price": 10.0,
         "entry_date": "2025-09-01", "holding_days": 1, "last_price": 9.0,
         "unrealized_pnl": -100},
        {"code": "B", "volume": 100, "available_volume": 100, "cost_price": 10.0,
         "entry_date": "2025-09-01", "holding_days": 2, "last_price": 11.0,
         "unrealized_pnl": 100},
    ]
    d = make_decision("2025-09-30", mw, pos, 0.0, [], _account(), _cfg(),
                      _aux(),
                      [_score_rec("A", total=30.0), _score_rec("B", total=55.0)])
    priorities = [s["priority"] for s in d["sell_decisions"]]
    assert priorities == sorted(priorities)


def test_sell_decision_target_volume_zero():
    """OQ-F: strategy_core does not size sells; target_volume = 0."""
    mw = {"A": _mw_row("A", 9.0, 9.1)}
    pos = [{"code": "A", "volume": 100, "available_volume": 100, "cost_price": 10.0,
            "entry_date": "2025-09-01", "holding_days": 1, "last_price": 9.0,
            "unrealized_pnl": -100}]
    d = make_decision("2025-09-30", mw, pos, 0.0, [], _account(), _cfg(),
                      _aux(), [_score_rec("A", total=30.0)])
    assert d["sell_decisions"][0]["target_volume"] == 0


def test_logs_emitted():
    d = make_decision("2025-09-30", {}, [], 1e6, [], _account(), _cfg(),
                      _aux(), [])
    assert len(d["logs"]) >= 1
    assert "evaluate_day" in d["logs"][0]
