# coding: utf-8
"""
strategy_core.interface -- frozen evaluate_day signature + decision factory.

Authoritative source: agent_hub/2026-06-13_backtest_mvp/03_interface_freeze.md
  - evaluate_day signature : section 1  (8 params, fixed order)
  - StrategyDecision shape : section 6  (6 top-level keys; diagnostics has 4 keys)
  - sell reasons / blocked : sections 7 / 8

Task 2.4 integrated: evaluate_day now drives the full pipeline
  score_universe -> make_decision and merges scoring warnings into
  decision.diagnostics.warnings. make_empty_decision() is preserved for
  callers/tests that need a zeroed shape.

3.6-safe constraints (03 section 1 constraint 3):
  - no `dict[str, ...]` / `list[str]` annotations
  - no `str | None` unions
  - no walrus, no match/case, no dataclass
  - keep f-strings out of the hot path; this module uses none

Purity constraints (03 section 1 constraints 1 & 2):
  - no IO / network / time-based randomness
  - no xtquant / passorder / get_trade_detail_data / ContextInfo imports
  - inputs are not mutated (None aux_data is rebuilt as a fresh empty dict)
"""

from backtest.strategy_core.scoring_adapter import score_universe
from backtest.strategy_core.decision import make_decision


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

    Integration pipeline (Task 2.4):
      1. score_universe(market_window) -> records (per 03 section 6
         diagnostics.scores schema) + warnings.
      2. make_decision(...) -> full StrategyDecision dict.
      3. Append scoring warnings into decision.diagnostics.warnings.

    See 03 section 1 for the full contract. Keep parameter order/names as
    listed -- they are part of the frozen interface (03 section 1
    constraint 4).

    Notes on purity / None handling:
      - aux_data may be None; we substitute a fresh empty dict locally so
        downstream code (decision layer reads aux_data.get("warnings", []))
        does not crash. The caller's None is never written to.
      - sector_heat_mode != "zero" intentionally raises NotImplementedError
        out of score_universe (03 section 4 constraint 2).
    """
    cfg = strategy_config or {}
    sector_heat_mode = cfg.get("sector_heat_mode", "zero")
    aux_for_pipeline = aux_data if aux_data is not None else {}

    score_records, score_warnings = score_universe(
        market_window or {},
        sector_heat_mode=sector_heat_mode,
        aux_data=aux_for_pipeline,
        return_warnings=True,
    )

    decision = make_decision(
        current_date=current_date,
        market_window=market_window,
        positions=positions,
        cash=cash,
        universe=universe,
        account_state=account_state,
        strategy_config=strategy_config,
        aux_data=aux_for_pipeline,
        score_records=score_records,
    )

    # Merge scoring warnings into decision diagnostics (03 section 6 key 3).
    if score_warnings:
        decision["diagnostics"]["warnings"].extend(score_warnings)

    return decision
