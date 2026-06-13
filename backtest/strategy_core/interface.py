# coding: utf-8
"""
strategy_core.interface -- frozen evaluate_day signature + decision factory.

Authoritative source: agent_hub/2026-06-13_backtest_mvp/03_interface_freeze.md
  - evaluate_day signature : section 1  (8 params, fixed order)
  - StrategyDecision shape : section 6  (6 top-level keys; diagnostics has 4 keys)
  - sell reasons / blocked : sections 7 / 8

This task (2.1) only ships the SKELETON; the real evaluate_day body lands in
Task 2.4 (integration). Until then evaluate_day returns make_empty_decision().

3.6-safe constraints (03 section 1 constraint 3):
  - no `dict[str, ...]` / `list[str]` annotations
  - no `str | None` unions
  - no walrus, no match/case, no dataclass
  - keep f-strings out of the hot path; this skeleton uses none

Purity constraints (03 section 1 constraints 1 & 2):
  - no IO / network / time-based randomness
  - no xtquant / passorder / get_trade_detail_data / ContextInfo imports
"""


def make_empty_decision():
    """Return a fresh StrategyDecision dict shaped exactly per 03 section 6.

    Every call returns a NEW dict (no shared mutable state) so callers may
    mutate the result in-place without polluting subsequent calls. The shape
    is the contract downstream engine / report code rely on; do not drop or
    rename keys without re-running Phase 2.0 GATE.
    """
    return {
        "sell_decisions":      [],
        "buy_candidates":      [],
        "target_positions":    [],   # MVP: empty list, reserved for v0.3+
        "blocked_candidates":  [],
        "diagnostics": {
            "scores": {},
            "filter_counts": {
                "blocked_min_score":            0,
                "blocked_min_core":             0,
                "blocked_max_bias5":            0,
                "blocked_max_daily_pct":        0,
                "blocked_already_held":         0,
                "blocked_limit_up":             0,
                "blocked_suspended":            0,
                "blocked_insufficient_history": 0,
                "candidate_total":              0,
                "candidate_passed":             0,
            },
            "warnings": [],
            "trigger_counts": {
                "early_stop":  0,
                "early_kick":  0,
                "stop_loss":   0,
                "score_drop":  0,
                "replace":     0,
                "warning":     0,
                "confirm":     0,
            },
        },
        "logs": [],
    }


def evaluate_day(
    current_date,        # str, "YYYY-MM-DD"
    market_window,       # dict, code -> DataFrame[date, open, high, low, close, vol, amount]
    positions,           # list of position dicts (03 section 2)
    cash,                # float, available cash (CNY)
    universe,            # list of code strings (already de-duped / disabled-stripped)
    account_state,       # dict (03 section 3)
    strategy_config,     # dict (03 section 4)
    aux_data,            # dict (03 section 5)
):
    """Decide T+1 (or T close) trading intentions for current_date.

    See 03 section 1 for the full contract. This skeleton intentionally returns
    make_empty_decision(); Task 2.4 fills in the real scoring/selection/risk
    pipeline. Keep the parameter order and names exactly as listed -- they are
    part of the frozen interface (03 section 1 constraint 4).
    """
    # Bind locals so static analysers don't flag them as unused; this is a
    # skeleton, not a TODO -- behaviour ships in Task 2.4.
    _ = (current_date, market_window, positions, cash, universe,
         account_state, strategy_config, aux_data)
    return make_empty_decision()
