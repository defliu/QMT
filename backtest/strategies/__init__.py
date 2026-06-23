# coding: utf-8
"""Strategy Registry —— 最简装饰器实现，不引入插件框架。

Phase 1: 解除 engine 与 6+2 的硬绑定。
策略名空间：'<category>/<strategy_id>'，category in {production, research}。

SPEC: specs/SPEC_BACKTEST_FACTORY_V0.4_GENERALIZATION_PHASE1.md §3.2
"""

_REGISTRY = {}


def register_strategy(name):
    """装饰器：在策略模块顶层注册 evaluate_day。"""
    def _wrap(evaluate_fn):
        if name in _REGISTRY:
            raise ValueError("strategy already registered: " + name)
        _REGISTRY[name] = evaluate_fn
        return evaluate_fn
    return _wrap


def get_strategy(name):
    if name not in _REGISTRY:
        raise KeyError(
            "strategy not found: " + name +
            "; registered: " + ",".join(sorted(_REGISTRY.keys()))
        )
    return _REGISTRY[name]


def list_strategies():
    return sorted(_REGISTRY.keys())


# 触发注册：import 子包即可
from backtest.strategies.production import ima_uptrend_v31  # noqa: F401
