# coding: utf-8
"""Milestone A 验证：Strategy Registry 基本功能。"""

import pytest

from backtest.strategies import register_strategy, get_strategy, list_strategies


def test_registry_lists_ima_uptrend_v31():
    """6+2 reference strategy 必须已注册。"""
    names = list_strategies()
    assert "production/ima_uptrend_v31" in names


def test_registry_get_returns_callable():
    fn = get_strategy("production/ima_uptrend_v31")
    assert callable(fn)


def test_registry_get_unknown_raises_keyerror():
    with pytest.raises(KeyError) as exc:
        get_strategy("no/such/strategy")
    assert "registered:" in str(exc.value)


def test_registry_duplicate_register_raises():
    with pytest.raises(ValueError):
        @register_strategy("production/ima_uptrend_v31")
        def _fake(*a, **k):
            return None
