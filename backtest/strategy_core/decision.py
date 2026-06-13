# coding: utf-8
"""Decision layer - assembles StrategyDecision per 03 section 6.

Orchestrates:
  - sell_decisions (loop positions, call risk_adapter)
  - buy_candidates (filter scored records by thresholds, rank by score_total)
  - blocked_candidates (short-circuit filter chain)
  - replace logic (CLAUDE.md: score_gap >= 15 -> sell weakest + buy candidate)
  - diagnostics: scores (all scored), filter_counts, trigger_counts, warnings
  - logs

strategy_core constraints (03 section 1):
  - Pure function. No IO/network. No QMT/xtquant.
  - Python 3.6-safe.
"""
from backtest.strategy_core import enums
from backtest.strategy_core.risk_adapter import (
    evaluate_position_triggers, pick_top_reason, priority_of,
)


# OQ-D: single limit-up approximation threshold for v0.2.
_LIMIT_UP_PCT = 9.95


def _is_suspended(market_window, code, current_date):
    """code missing from window or last bar's date != current_date -> suspended."""
    df = (market_window or {}).get(code)
    if df is None or len(df) == 0:
        return True
    if "date" not in df.columns:
        return True
    last_date = df["date"].iloc[-1]
    return str(last_date) != str(current_date)


def _has_insufficient_history(market_window, code):
    df = (market_window or {}).get(code)
    return df is None or len(df) < 60


def _daily_pct(market_window, code):
    """Same-day percent change using close vs prev close. 0.0 if unknown."""
    df = (market_window or {}).get(code)
    if df is None or len(df) < 2:
        return 0.0
    last = float(df["close"].iloc[-1])
    prev = float(df["close"].iloc[-2])
    if prev == 0:
        return 0.0
    return (last - prev) / prev * 100.0


def _core_sum(rec):
    """6-dim core sum: breakout + trend + consolidation + volumeprice + macd + valuation."""
    return (float(rec["score_breakout"]) + float(rec["score_trend"])
            + float(rec["score_consolidation"]) + float(rec["score_volumeprice"])
            + float(rec["score_macd"]) + float(rec["score_valuation"]))


def make_decision(
    current_date,
    market_window,
    positions,
    cash,
    universe,
    account_state,
    strategy_config,
    aux_data,
    score_records,
):
    """Build a complete StrategyDecision from already-scored records.

    score_records is the output of score_universe() (Task 2.2).
    """
    decision = {
        "sell_decisions":     [],
        "buy_candidates":     [],
        "target_positions":   [],
        "blocked_candidates": [],
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
            "warnings": list((aux_data or {}).get("warnings", []) or []),
            "trigger_counts": {
                "early_stop": 0, "early_kick": 0, "stop_loss": 0,
                "score_drop": 0, "replace":    0, "warning":    0, "confirm": 0,
            },
        },
        "logs": [],
    }

    fc = decision["diagnostics"]["filter_counts"]
    tc = decision["diagnostics"]["trigger_counts"]

    # Index score records by code.
    scores_by_code = {}
    for rec in (score_records or []):
        scores_by_code[rec["code"]] = rec

    # 03 section 6 constraint 5: scores covers ALL scored codes.
    for code, rec in scores_by_code.items():
        decision["diagnostics"]["scores"][code] = dict(rec)

    held_codes = set()
    for p in (positions or []):
        held_codes.add(p["code"])

    # ===== 1. Sell decisions: loop positions =====
    sell_by_code = {}  # code -> sell_decision dict
    for pos in (positions or []):
        code = pos["code"]
        score_rec = scores_by_code.get(code)
        triggered = evaluate_position_triggers(pos, score_rec, strategy_config)
        for r in triggered:
            if r in tc:
                tc[r] += 1
        top = pick_top_reason(triggered)
        if top is not None:
            prio, layer = priority_of(top)
            sell_by_code[code] = {
                "code":            code,
                "action":          "sell",
                "target_volume":   0,           # OQ-F: engine converts.
                "reason":          top,
                "layer":           layer,
                "priority":        prio,
                "diagnostics_ref": code if score_rec is not None else "",
            }
            if code in decision["diagnostics"]["scores"]:
                decision["diagnostics"]["scores"][code]["signal"] = "sell"

    # ===== 2. Buy candidate filter chain =====
    min_score = float(strategy_config.get("min_score", 60.0))
    min_core = float(strategy_config.get("min_core", 32.0))
    max_bias5 = float(strategy_config.get("max_bias5", 10.0))
    max_daily = float(strategy_config.get("max_daily_pct", 9.0))

    universe_list = list(universe or [])
    fc["candidate_total"] = len(universe_list)

    candidate_records = []
    for code in universe_list:
        # Short-circuit chain (03 section 8 constraint 1).
        if _has_insufficient_history(market_window, code):
            decision["blocked_candidates"].append({
                "code": code, "blocked_by": enums.BLOCKED_INSUFFICIENT_HISTORY,
                "raw_score": 0.0,
                "reason": "history < 60 bars",
            })
            fc["blocked_insufficient_history"] += 1
            continue
        if _is_suspended(market_window, code, current_date):
            decision["blocked_candidates"].append({
                "code": code, "blocked_by": enums.BLOCKED_SUSPENDED,
                "raw_score": 0.0,
                "reason": "no data on " + str(current_date),
            })
            fc["blocked_suspended"] += 1
            continue
        if code in held_codes:
            raw = scores_by_code.get(code, {}).get("score_total", 0.0)
            decision["blocked_candidates"].append({
                "code": code, "blocked_by": enums.BLOCKED_ALREADY_HELD,
                "raw_score": float(raw),
                "reason": "already in positions",
            })
            fc["blocked_already_held"] += 1
            continue
        dp = _daily_pct(market_window, code)
        if dp >= _LIMIT_UP_PCT:
            raw = scores_by_code.get(code, {}).get("score_total", 0.0)
            decision["blocked_candidates"].append({
                "code": code, "blocked_by": enums.BLOCKED_LIMIT_UP,
                "raw_score": float(raw),
                "reason": "daily_pct >= 9.95 (limit-up approx)",
            })
            fc["blocked_limit_up"] += 1
            continue
        if dp > max_daily:
            raw = scores_by_code.get(code, {}).get("score_total", 0.0)
            decision["blocked_candidates"].append({
                "code": code, "blocked_by": enums.BLOCKED_MAX_DAILY_PCT,
                "raw_score": float(raw),
                "reason": "daily_pct exceeds max_daily_pct",
            })
            fc["blocked_max_daily_pct"] += 1
            continue
        score_rec = scores_by_code.get(code)
        if score_rec is None:
            decision["blocked_candidates"].append({
                "code": code, "blocked_by": enums.BLOCKED_INSUFFICIENT_HISTORY,
                "raw_score": 0.0,
                "reason": "no score record",
            })
            fc["blocked_insufficient_history"] += 1
            continue
        if float(score_rec["bias5"]) > max_bias5:
            decision["blocked_candidates"].append({
                "code": code, "blocked_by": enums.BLOCKED_MAX_BIAS5,
                "raw_score": float(score_rec["score_total"]),
                "reason": "bias5 exceeds max_bias5",
            })
            fc["blocked_max_bias5"] += 1
            continue
        core = _core_sum(score_rec)
        if core < min_core:
            decision["blocked_candidates"].append({
                "code": code, "blocked_by": enums.BLOCKED_MIN_CORE,
                "raw_score": float(score_rec["score_total"]),
                "reason": "core sum below min_core",
            })
            fc["blocked_min_core"] += 1
            continue
        if float(score_rec["score_total"]) < min_score:
            decision["blocked_candidates"].append({
                "code": code, "blocked_by": enums.BLOCKED_MIN_SCORE,
                "raw_score": float(score_rec["score_total"]),
                "reason": "score_total below min_score",
            })
            fc["blocked_min_score"] += 1
            continue
        candidate_records.append(score_rec)

    fc["candidate_passed"] = len(candidate_records)

    # ===== 3. Sort candidates by score_total desc =====
    candidate_records.sort(key=lambda r: float(r["score_total"]), reverse=True)

    # ===== 4. Replace logic (CLAUDE.md: score_gap >= 15) =====
    score_gap = float(strategy_config.get("score_gap_threshold", 15.0))
    max_positions = int(account_state.get("max_positions",
                                          strategy_config.get("max_positions", 5)))

    held_scores = []
    for pos in (positions or []):
        if pos["code"] in sell_by_code:
            continue  # already being sold
        rec = scores_by_code.get(pos["code"])
        held_scores.append((pos["code"], float(rec["score_total"]) if rec else 0.0))
    held_scores.sort(key=lambda t: t[1])  # weakest first
    weakest = held_scores[0] if held_scores else None

    open_slots = max_positions - len(positions or []) + len(sell_by_code)

    buy_records = []
    if open_slots > 0:
        n_take = min(open_slots, len(candidate_records))
        for rec in candidate_records[:n_take]:
            buy_records.append((rec, "top_candidate"))

    if weakest is not None and len(candidate_records) > 0:
        consumed = len(buy_records)
        if consumed < len(candidate_records):
            cand = candidate_records[consumed]
            if float(cand["score_total"]) - weakest[1] >= score_gap:
                w_code = weakest[0]
                if w_code not in sell_by_code:
                    prio, layer = priority_of(enums.SELL_REASON_REPLACE)
                    sell_by_code[w_code] = {
                        "code":            w_code,
                        "action":          "sell",
                        "target_volume":   0,
                        "reason":          enums.SELL_REASON_REPLACE,
                        "layer":           layer,
                        "priority":        prio,
                        "diagnostics_ref": w_code if w_code in scores_by_code else "",
                    }
                    tc["replace"] += 1
                    if w_code in decision["diagnostics"]["scores"]:
                        decision["diagnostics"]["scores"][w_code]["signal"] = "sell"
                buy_records.append((cand, "replace_target"))

    # ===== 5. Assemble buy_candidates =====
    if buy_records:
        per_weight = 1.0 / max_positions if max_positions > 0 else 0.0
        total_asset = float(account_state.get("total_asset", cash))
        per_cash = total_asset * per_weight
        rank = 0
        for rec, reason in buy_records:
            rank += 1
            decision["buy_candidates"].append({
                "code":          rec["code"],
                "score_total":   float(rec["score_total"]),
                "score_core":    _core_sum(rec),
                "bias5":         float(rec["bias5"]),
                "daily_pct":     _daily_pct(market_window, rec["code"]),
                "rank":          rank,
                "target_weight": per_weight,
                "target_cash":   per_cash,
                "target_volume": 0,            # OQ-F
                "reason":        reason,
            })
            if rec["code"] in decision["diagnostics"]["scores"]:
                decision["diagnostics"]["scores"][rec["code"]]["signal"] = "buy"

    # ===== 6. Sell decisions ordered by priority =====
    sells = list(sell_by_code.values())
    sells.sort(key=lambda d: d["priority"])
    decision["sell_decisions"] = sells

    # ===== 7. Log a one-liner per call =====
    decision["logs"].append(
        "evaluate_day %s candidates=%d passed=%d sell=%d buy=%d"
        % (current_date, fc["candidate_total"], fc["candidate_passed"],
           len(sells), len(decision["buy_candidates"]))
    )

    return decision
