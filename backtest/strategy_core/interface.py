# coding: utf-8
"""DEPRECATED: strategy_core.interface

v0.3 frozen contract 入口；v0.4 起 6+2 物理迁出，本模块降级为 shim，
转调 backtest.strategies.production.ima_uptrend_v31。

新代码请使用：
    from backtest.strategies import get_strategy
    evaluate_day = get_strategy("production/ima_uptrend_v31")

SPEC: specs/SPEC_BACKTEST_FACTORY_V0.4_GENERALIZATION_PHASE1.md §4.1 / §五 Step 3
"""

import warnings

# 触发注册（import side effect）
from backtest.strategies import get_strategy  # noqa: F401
from backtest.strategies.production.ima_uptrend_v31.strategy import (
    evaluate_day as _evaluate_day_impl,
)


def make_empty_decision():
    """v0.4 空 decision schema —— SPEC §3.3：通用字段提顶 + 私有字段 namespace 化。"""
    return {
        "sell_decisions":      [],
        "buy_candidates":      [],
        "target_positions":    [],
        "blocked_candidates":  [],
        "diagnostics": {
            "warnings":         [],
            "candidate_total":  0,
            "candidate_passed": 0,
            "strategy_specific": {
                "ima_uptrend_v31": {
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
                    },
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
            },
        },
        "logs": [],
    }


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
    """DEPRECATED shim → production/ima_uptrend_v31.

    保留 8 参签名以兼容现有调用方；新代码请通过 get_strategy() 获取。
    """
    warnings.warn(
        "backtest.strategy_core.interface.evaluate_day is deprecated; "
        "use backtest.strategies.get_strategy('production/ima_uptrend_v31') instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return _evaluate_day_impl(
        current_date,
        market_window,
        positions,
        cash,
        universe,
        account_state,
        strategy_config,
        aux_data,
    )
