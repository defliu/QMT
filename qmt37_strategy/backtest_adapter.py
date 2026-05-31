# coding=utf-8
"""千问3.7版回测适配器 — 将信号函数适配为回测引擎接口"""
from qmt37_strategy.signal_qmt37 import check_buy_sell
from qmt37_strategy.params import N_PERIOD, INTENSITY


def check_buy(df) -> tuple:
    """
    适配回测引擎的信号接口。
    签名与 core/signal_main_rise.check_buy 一致。

    Returns:
        (bool, reason_str, buy_type)
        bool: 是否触发买入
        reason_str: 触发原因描述
        buy_type: 'buy1', 'buy2', or None
    """
    b1, b2, sell = check_buy_sell(df, n_period=N_PERIOD, intensity=INTENSITY)

    if not (b1 or b2):
        return False, "", None

    reasons = []
    if b1:
        reasons.append("买点1(千问3.7)")
    if b2:
        reasons.append("买点2(千问3.7)")

    buy_type = 'both' if (b1 and b2) else ('buy1' if b1 else 'buy2')
    return True, "+".join(reasons), buy_type
