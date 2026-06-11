# coding=utf-8
"""pytest fixtures：Mock K线数据 + MockContextInfo + SAFEMODE 状态重置"""
import pytest
import pandas as pd
import numpy as np


@pytest.fixture(autouse=True)
def safemode_reset():
    """每个测试前重置 SAFEMODE 全局状态，消除跨测试污染。

    BacktestRunner._patch_qmt_wrapper() 会设置 SAFEMODE_ENABLED = False，
    若未重置将导致后续 safemode 测试失败（order-dependent）。
    同时重置 _g_init_done 使 StrategyRunner.init() 可重复执行。
    """
    import adapters.qmt_wrapper as qmt
    qmt.SAFEMODE_ENABLED = True
    qmt._g_init_done = False


@pytest.fixture
def mock_klines():
    """返回模拟 K 线 DataFrame，包含 open/close/high/low/volume，至少60行"""
    n = 60
    base_close = 10.0
    closes = []
    opens = []
    highs = []
    lows = []
    volumes = []

    price = base_close
    for i in range(n):
        daily_change = np.random.uniform(-0.03, 0.03)
        op = price * (1 + np.random.uniform(-0.01, 0.01))
        close = price * (1 + daily_change)
        high = max(op, close) * (1 + abs(np.random.uniform(0, 0.02)))
        low = min(op, close) * (1 - abs(np.random.uniform(0, 0.02)))
        vol = int(np.random.uniform(1000000, 5000000))

        opens.append(round(op, 2))
        closes.append(round(close, 2))
        highs.append(round(high, 2))
        lows.append(round(low, 2))
        volumes.append(vol)
        price = close

    df = pd.DataFrame({
        'open': opens,
        'close': closes,
        'high': highs,
        'low': lows,
        'volume': volumes,
    })
    return df


@pytest.fixture
def mock_context(mock_klines):
    """返回已注入 mock_klines 的 MockContextInfo 实例"""
    from adapters.context_mock import MockContextInfo
    ctx = MockContextInfo()
    ctx.set_klines(mock_klines)
    return ctx
