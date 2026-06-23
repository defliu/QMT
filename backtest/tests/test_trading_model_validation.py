# coding: utf-8
"""Milestone A 验证：trading_model 启动校验。

resolve_strategy() 校验策略 ALLOWED_TRADING_MODELS，不通过即 raise ValueError；
本测试直接调 resolve_strategy()，不依赖 run_backtest 全链路。
"""

import pytest

from backtest.engine.daily_engine import resolve_strategy


def test_resolve_strategy_next_open_passes():
    fn, tm = resolve_strategy("production/ima_uptrend_v31", "next_open")
    assert callable(fn)
    assert tm == "next_open"


def test_resolve_strategy_default_args_passes():
    """传 None 走默认（production/ima_uptrend_v31 + next_open）。"""
    fn, tm = resolve_strategy(None, None)
    assert callable(fn)
    assert tm == "next_open"


def test_resolve_strategy_unknown_trading_model_raises():
    """trading_model=fantasy_close 不在 ALLOWED → ValueError，错误信息须含关键 token。"""
    with pytest.raises(ValueError) as exc:
        resolve_strategy("production/ima_uptrend_v31", "fantasy_close")
    msg = str(exc.value)
    assert "trading_model" in msg
    assert "fantasy_close" in msg
    assert "production/ima_uptrend_v31" in msg


def test_resolve_strategy_unknown_strategy_raises_keyerror():
    """策略未注册 → KeyError（来自 registry）。"""
    with pytest.raises(KeyError):
        resolve_strategy("no/such/strategy", "next_open")
