# coding: utf-8
"""research/deepseek — DeepSeek 主升浪选股策略（黄氏 AI 优化版）。

薄壳：register + evaluate_day。指标由 DeepseekReader 一次性预算（vectorized），
本文件只做布尔判断 + 大盘条件 J + 仓位/卖出决策组装。

SPEC: specs/SPEC_DeepSeek选股策略回测.md
数据：astock parquet（hfq 后复权，PIT 安全）；日线基本面字段由 reader 带出。
"""

from backtest.strategies import register_strategy
from backtest.strategies.research.deepseek.decision import assemble_decision


ALLOWED_TRADING_MODELS = ["next_open"]


@register_strategy("research/deepseek")
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
    """DeepSeek 策略主入口。

    market_window[code] 已含预算好的指标列（ma5/ma10/ma20/ma60/slope5/
    yang_ratio_10/gain_from_ma60/eff_ratio_10/turnover_rate/vol_ratio_spec/
    circ_mv_yi/is_st/listed_days）。本函数读 iloc[-1] 做布尔判断。
    """
    cfg = strategy_config or {}
    decision = assemble_decision(
        current_date=current_date,
        market_window=market_window or {},
        positions=positions or [],
        account_state=account_state or {},
        strategy_config=cfg,
        aux_data=aux_data or {},
    )
    return decision
