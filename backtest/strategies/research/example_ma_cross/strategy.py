# coding: utf-8
"""research/example_ma_cross —— 5/10 均线金叉 minimal example。

⚠️ 这不是有效策略。存在意义：给别人接入工厂时有一个非 6+2 的骨架可抄。
不要把它当"已知能赚钱的代码"，不要照搬这套打分逻辑。

接入参考：
- v0.4 接入流程详见 agent_hub/回测工厂使用说明书.md "如何接入新策略" 章节
- StrategyDecision schema 见 agent_hub/2026-06-23_backtest_generalization/05_interface_freeze_v04.md
"""

from backtest.strategies import register_strategy


ALLOWED_TRADING_MODELS = ["next_open"]


def _ma(df_rows, n):
    """计算最后 n 行的 close 简单均线。df_rows 已按 date 升序。"""
    if len(df_rows) < n:
        return None
    s = 0.0
    for r in df_rows[-n:]:
        s += float(r["close"])
    return s / n


def _make_empty_decision(warnings):
    return {
        "sell_decisions":     [],
        "buy_candidates":     [],
        "target_positions":   [],
        "blocked_candidates": [],
        "diagnostics": {
            "warnings":         list(warnings or []),
            "candidate_total":  0,
            "candidate_passed": 0,
            "strategy_specific": {
                "example_ma_cross": {
                    "signal_counts":  {"golden_cross": 0, "death_cross": 0},
                    "blocked_counts": {"insufficient_history": 0,
                                       "already_held":         0},
                },
            },
        },
        "logs": [],
    }


@register_strategy("research/example_ma_cross")
def evaluate_day(
    current_date,
    market_window,
    positions,
    cash,
    universe,
    account_state,
    strategy_config,
    aux_data,
):
    """5/10 均线金叉示例。

    业务逻辑（极简）：
      - 买：金叉（ma5_t > ma10_t AND ma5_t-1 <= ma10_t-1），不在持仓且非已死叉
      - 卖：死叉（ma5_t < ma10_t AND ma5_t-1 >= ma10_t-1）
    """
    cfg = strategy_config or {}
    max_positions = int(cfg.get("max_positions",
                                account_state.get("max_positions", 5)))

    aux = aux_data or {}
    decision = _make_empty_decision(aux.get("warnings", []))
    ss = decision["diagnostics"]["strategy_specific"]["example_ma_cross"]
    sig = ss["signal_counts"]
    blk = ss["blocked_counts"]

    held_codes = set()
    for p in (positions or []):
        held_codes.add(p["code"])

    universe_list = list(universe or [])
    decision["diagnostics"]["candidate_total"] = len(universe_list)

    # ===== 1. 卖出判断（先于买，腾出仓位） =====
    sell_codes = set()
    for pos in (positions or []):
        code = pos["code"]
        df = (market_window or {}).get(code)
        if df is None or len(df) < 11:
            continue
        rows = df.to_dict("records") if hasattr(df, "to_dict") else list(df)
        ma5_t  = _ma(rows[:],  5)
        ma10_t = _ma(rows[:], 10)
        ma5_y  = _ma(rows[:-1], 5)
        ma10_y = _ma(rows[:-1], 10)
        if None in (ma5_t, ma10_t, ma5_y, ma10_y):
            continue
        if ma5_t < ma10_t and ma5_y >= ma10_y:
            sig["death_cross"] += 1
            sell_codes.add(code)
            decision["sell_decisions"].append({
                "code":            code,
                "action":          "sell",
                "target_volume":   0,
                "reason":          "death_cross",
                "layer":           "signal",
                "priority":        5,
                "diagnostics_ref": code,
            })

    # ===== 2. 买入候选 =====
    candidates = []
    for code in universe_list:
        df = (market_window or {}).get(code)
        if df is None or len(df) < 11:
            blk["insufficient_history"] += 1
            decision["blocked_candidates"].append({
                "code": code, "blocked_by": "insufficient_history",
                "raw_score": 0.0, "reason": "history < 11 bars",
            })
            continue
        if code in held_codes and code not in sell_codes:
            blk["already_held"] += 1
            decision["blocked_candidates"].append({
                "code": code, "blocked_by": "already_held",
                "raw_score": 0.0, "reason": "in positions",
            })
            continue
        rows = df.to_dict("records") if hasattr(df, "to_dict") else list(df)
        ma5_t  = _ma(rows[:],  5)
        ma10_t = _ma(rows[:], 10)
        ma5_y  = _ma(rows[:-1], 5)
        ma10_y = _ma(rows[:-1], 10)
        if None in (ma5_t, ma10_t, ma5_y, ma10_y):
            continue
        if ma5_t > ma10_t and ma5_y <= ma10_y:
            sig["golden_cross"] += 1
            candidates.append((code, ma5_t - ma10_t))

    decision["diagnostics"]["candidate_passed"] = len(candidates)

    candidates.sort(key=lambda t: t[1], reverse=True)

    n_held_after_sell = len(positions or []) - len(sell_codes)
    open_slots = max(0, max_positions - n_held_after_sell)
    take = candidates[:open_slots]

    if take:
        per_weight = 1.0 / max_positions if max_positions > 0 else 0.0
        total_asset = float(account_state.get("total_asset", cash))
        per_cash = total_asset * per_weight
        rank = 0
        for code, gap in take:
            rank += 1
            decision["buy_candidates"].append({
                "code":          code,
                "score_total":   float(gap),
                "rank":          rank,
                "target_weight": per_weight,
                "target_cash":   per_cash,
                "target_volume": 0,
                "reason":        "golden_cross_top",
            })

    decision["logs"].append(
        "[example_ma_cross] %s scanned=%d gc=%d dc=%d buy=%d sell=%d"
        % (current_date, len(universe_list),
           sig["golden_cross"], sig["death_cross"],
           len(decision["buy_candidates"]), len(decision["sell_decisions"]))
    )
    return decision
