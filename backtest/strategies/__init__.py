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


def get_strategy_diag(decision, strategy_name, key, default=None):
    """v0.4 取数辅助：从 decision.diagnostics.strategy_specific.{strategy_name}.{key} 取值。

    strategy_name 形如 'production/ima_uptrend_v31'，内部用最后一段作为 namespace key。
    SPEC: specs/SPEC_BACKTEST_FACTORY_V0.4_GENERALIZATION_PHASE1.md §3.3
    """
    short = strategy_name.split("/")[-1] if strategy_name else ""
    return (decision.get("diagnostics", {})
                    .get("strategy_specific", {})
                    .get(short, {})
                    .get(key, default))


import contextlib


def register_test_spy(name, fn):
    """测试辅助：直接向 registry 注入临时 fn，返回前一版本供还原。"""
    old = _REGISTRY.get(name)
    _REGISTRY[name] = fn
    return old


@contextlib.contextmanager
def strategy_spy(name, fn=None):
    """测试辅助：上下文管理器，临时替换 registry 中 name 对应的 evaluate_day。
    退出时 try/finally 自动还原，不污染生产 registry。

    用法 1（替换已注册策略，spy 包装原 fn）:
        with strategy_spy("production/ima_uptrend_v31") as (real_fn, spy_fn): ...
    用法 2（注入新临时策略 fn，退出时删除）:
        with strategy_spy("test/my_spy", fn=my_evaluate_day) as (None, my_evaluate_day): ...
    """
    existed = name in _REGISTRY
    real = _REGISTRY.get(name)
    injected = fn if fn is not None else real
    if injected is None:
        raise KeyError("strategy_spy: name=%r not registered and fn not given" % name)
    captured = [None]

    def _spy(*args, **kwargs):
        captured[0] = args
        return injected(*args, **kwargs)

    _REGISTRY[name] = _spy
    try:
        yield real, _spy
    finally:
        if existed:
            _REGISTRY[name] = real
        else:
            _REGISTRY.pop(name, None)


# 触发注册：自动扫描 production/ 和 research/ 子包
import importlib
import pkgutil


def _autodiscover():
    for cat in ("production", "research"):
        pkg = importlib.import_module("backtest.strategies." + cat)
        for _, modname, ispkg in pkgutil.iter_modules(pkg.__path__):
            if ispkg:
                importlib.import_module(
                    "backtest.strategies.%s.%s.strategy" % (cat, modname))


_autodiscover()
