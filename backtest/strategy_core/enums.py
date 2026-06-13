# coding: utf-8
"""
Strategy enums for backtest factory v0.2.

Authoritative source: agent_hub/2026-06-13_backtest_mvp/03_interface_freeze.md
  - sell reasons:       see 03 section 7 (7 reasons; OQ-A: EARLY_STOP + EARLY_KICK
                        coexist; OQ-C: CONFIRM kept as enum, no trigger in v0.2;
                        bottom_line is a layer, NOT a reason -> not exposed here)
  - blocked reasons:    see 03 section 8 (8 reasons; INSUFFICIENT_HISTORY new in
                        signed version)
  - layer / priority:   see 03 section 6 / section 7 mapping

3.6-safe constraints (03 section 1 constraint 3):
  - no `dict[str, ...]` / `list[str]` annotations
  - no `str | None`
  - no walrus `:=`, no match/case, no dataclass

This module must NOT import xtquant / passorder / get_trade_detail_data /
ContextInfo (03 section 1 constraint 2). Pure constants only.
"""

# ---------------------------------------------------------------------------
# Sell reasons (03 section 7) -- 7 enums.
# ---------------------------------------------------------------------------
SELL_REASON_STOP_LOSS    = "stop_loss"
SELL_REASON_EARLY_STOP   = "early_stop"
SELL_REASON_EARLY_KICK   = "early_kick"   # OQ-A: long-horizon kickout (5d < 3%)
SELL_REASON_REPLACE      = "replace"
SELL_REASON_SCORE_DROP   = "score_drop"
SELL_REASON_WARNING      = "warning"
SELL_REASON_CONFIRM      = "confirm"      # OQ-C: enum kept, trigger deferred

# ---------------------------------------------------------------------------
# Blocked reasons (03 section 8) -- 8 enums.
# ---------------------------------------------------------------------------
BLOCKED_MIN_SCORE             = "min_score"
BLOCKED_MIN_CORE              = "min_core"
BLOCKED_MAX_BIAS5             = "max_bias5"
BLOCKED_MAX_DAILY_PCT         = "max_daily_pct"
BLOCKED_ALREADY_HELD          = "already_held"
BLOCKED_LIMIT_UP              = "limit_up"
BLOCKED_SUSPENDED             = "suspended"
BLOCKED_INSUFFICIENT_HISTORY  = "insufficient_history"  # 03 section 8 #8

# ---------------------------------------------------------------------------
# Layer / priority constants (03 section 6 / section 7 mapping; optional helpers).
# ---------------------------------------------------------------------------
LAYER_BOTTOM_LINE = "bottom_line"
LAYER_CONFIRM     = "confirm"
LAYER_WARNING     = "warning"

PRIORITY_BOTTOM_LINE = 1
PRIORITY_CONFIRM     = 2
PRIORITY_WARNING     = 3
