# coding: utf-8
"""Risk adapter - per-position sell-signal evaluator.

Pure function over position + price + score. No imports of QMT/xtquant.
Returns the single HIGHEST-priority sell reason (per 03 section 7 priority
mapping). Engine/decision layer also collects ALL triggered reasons for
trigger_counts.

3.6-safe: no dict[str,...] / unions / walrus / match-case / dataclass.
"""
from backtest.strategy_core import enums


# Priority mapping per 03 section 7 (lower number = higher priority).
PRIORITY_MAP = {
    enums.SELL_REASON_STOP_LOSS:   (enums.PRIORITY_BOTTOM_LINE, enums.LAYER_BOTTOM_LINE),
    enums.SELL_REASON_EARLY_STOP:  (enums.PRIORITY_BOTTOM_LINE, enums.LAYER_BOTTOM_LINE),
    enums.SELL_REASON_EARLY_KICK:  (enums.PRIORITY_CONFIRM,     enums.LAYER_CONFIRM),
    enums.SELL_REASON_REPLACE:     (enums.PRIORITY_CONFIRM,     enums.LAYER_CONFIRM),
    enums.SELL_REASON_CONFIRM:     (enums.PRIORITY_CONFIRM,     enums.LAYER_CONFIRM),
    enums.SELL_REASON_SCORE_DROP:  (enums.PRIORITY_WARNING,     enums.LAYER_WARNING),
    enums.SELL_REASON_WARNING:     (enums.PRIORITY_WARNING,     enums.LAYER_WARNING),
}


def evaluate_position_triggers(position, score_record, strategy_config):
    """Return a list of triggered sell reasons (str enum values), unsorted.

    Args:
        position: dict per 03 section 2 (code, volume, available_volume,
                  cost_price, entry_date, holding_days, last_price,
                  unrealized_pnl).
        score_record: dict per 03 section 6 diagnostics.scores, or None when
                      no score is available (e.g. suspended).
        strategy_config: dict per 03 section 4.

    The caller picks the single highest-priority via pick_top_reason() for
    sell_decisions, but uses the full list for trigger_counts.
    """
    triggered = []

    cost = float(position["cost_price"])
    last = float(position["last_price"])
    if cost > 0:
        ret = (last - cost) / cost
    else:
        ret = 0.0
    holding_days = int(position.get("holding_days", 1))

    # Bottom line: stop_loss
    stop_loss = float(strategy_config.get("stop_loss", -0.08))
    if ret <= stop_loss:
        triggered.append(enums.SELL_REASON_STOP_LOSS)

    # Bottom line: early_stop (short-horizon stop, OQ-A rule 1).
    early_stop_days = int(strategy_config.get("early_stop_days", 3))
    early_stop_loss = float(strategy_config.get("early_stop_loss", -0.05))
    if holding_days >= early_stop_days and ret <= early_stop_loss:
        triggered.append(enums.SELL_REASON_EARLY_STOP)

    # Confirm: early_kick (long-horizon kickout, OQ-A rule 2).
    early_kick_days = int(strategy_config.get("early_stop_holding_days", 5))
    early_kick_min = float(strategy_config.get("early_stop_min_return", 0.03))
    if holding_days >= early_kick_days and ret < early_kick_min:
        triggered.append(enums.SELL_REASON_EARLY_KICK)

    # Warning: score_drop / warning (held-position score erosion).
    if score_record is not None:
        score = float(score_record.get("score_total", 0.0))
        min_score = float(strategy_config.get("min_score", 60.0))
        warning_threshold = float(strategy_config.get("warning_score_threshold", 50.0))
        if score < min_score:
            triggered.append(enums.SELL_REASON_SCORE_DROP)
        if score < warning_threshold:
            triggered.append(enums.SELL_REASON_WARNING)

    # SELL_REASON_CONFIRM intentionally not triggered in v0.2 per OQ-C.

    return triggered


def priority_of(reason):
    """Return (priority_int, layer_str) for a sell reason.

    Lower priority number = higher precedence. Unknown reasons fall back to
    warning layer.
    """
    return PRIORITY_MAP.get(reason, (enums.PRIORITY_WARNING, enums.LAYER_WARNING))


def pick_top_reason(triggered):
    """Among the triggered list, return the reason with highest precedence.

    Tie-breaking is left to Python's stable min(); for v0.2 the priority map
    is unique enough at each layer that ties only happen within a layer where
    either choice is acceptable. Returns None for an empty list.
    """
    if not triggered:
        return None
    return min(triggered, key=lambda r: priority_of(r)[0])
