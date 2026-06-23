# coding: utf-8
"""production/ima_uptrend_v31 — 6+2 主升浪策略注册入口（v0.4 reference strategy）。

本文件是薄壳，复用原 strategy_core/interface.py 的 evaluate_day 实现。
6+2 逻辑沿用 ima_uptrend_v31.py / decision.py / risk_adapter.py / scoring_adapter.py，
搬位置不改实现（SPEC §4.1 / §8.3）。

ALLOWED_TRADING_MODELS: 声明本策略支持的撮合模型，由 engine 启动时校验。
"""

from backtest.strategies import register_strategy
from backtest.strategies.production.ima_uptrend_v31.scoring_adapter import score_universe
from backtest.strategies.production.ima_uptrend_v31.decision import make_decision


ALLOWED_TRADING_MODELS = ["next_open"]


@register_strategy("production/ima_uptrend_v31")
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
    """v0.4 reference impl —— 与原 strategy_core/interface.py 行为完全等价。"""
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

    if score_warnings:
        decision["diagnostics"]["warnings"].extend(score_warnings)

    return decision
