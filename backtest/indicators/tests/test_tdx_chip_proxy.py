# coding: utf-8
"""tdx_chip_proxy 单元测试.

运行: py -3 -m pytest backtest/indicators/tests/test_tdx_chip_proxy.py -v
"""
import sys, os
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, 'D:/QMT_STRATEGIES')
from backtest.indicators.tdx_chip_proxy import (
    COST_proxy, WINNER_proxy, SCR_proxy, COST_ratio, MIN_LOOKBACK
)


def _make_df(tp_arr, vol_arr, closes=None):
    """用代表价 tp 构造 df: high=low=close=tp, 便于可控测试."""
    n = len(tp_arr)
    if closes is None:
        closes = tp_arr
    df = pd.DataFrame({
        'high': tp_arr, 'low': tp_arr, 'close': closes, 'volume': vol_arr,
    }, index=pd.date_range('2020-01-01', periods=n, freq='B'))
    return df


def test_single_sided_up_cost_ratio_near_one():
    # 单边上涨: COST95/COST5 应趋近 1 (价格分布窄, 但上涨使分布有范围; 用小范围测)
    n = 300
    tp = np.linspace(10.0, 10.5, n)  # 缓慢上涨, 窄幅
    vol = np.ones(n)
    df = _make_df(tp, vol)
    r = COST_ratio(df, lookback=250)
    val = r.dropna().iloc[-1]
    assert val < 1.10, "窄幅上涨 COST_ratio 应接近 1, got %s" % val


def test_wide_range_cost_ratio_large():
    # 宽幅震荡: COST_ratio 应明显 > 1
    n = 300
    tp = np.concatenate([np.linspace(10, 20, 150), np.linspace(20, 10, 150)])
    vol = np.ones(n)
    df = _make_df(tp, vol)
    r = COST_ratio(df, lookback=250)
    val = r.dropna().iloc[-1]
    assert val > 1.3, "宽幅 COST_ratio 应较大, got %s" % val


def test_insufficient_data_returns_nan():
    n = 15  # < MIN_LOOKBACK(20)
    tp = np.linspace(10, 11, n)
    vol = np.ones(n)
    df = _make_df(tp, vol)
    r = COST_proxy(df, 50, lookback=250)
    assert r.isna().all(), "数据不足应全 NaN"


def test_empty_df_returns_nan():
    df = pd.DataFrame({'high': [], 'low': [], 'close': [], 'volume': []})
    r = COST_proxy(df, 50, lookback=250)
    assert len(r) == 0


def test_zero_volume_returns_nan():
    n = 300
    tp = np.linspace(10, 11, n)
    vol = np.zeros(n)
    df = _make_df(tp, vol)
    r = COST_proxy(df, 50, lookback=250)
    # 全 0 vol -> total=0 -> NaN
    assert r.dropna().empty or r.isna().all(), "全0量应返回 NaN"


def test_winner_up_trend_near_one():
    # 单边上涨, 收盘在高位 -> WINNER(C) 趋近 1
    n = 300
    tp = np.linspace(10, 20, n)
    vol = np.ones(n)
    df = _make_df(tp, vol, closes=tp)
    w = WINNER_proxy(df, lookback=250)
    val = w.dropna().iloc[-1]
    assert val > 0.85, "单边上涨 WINNER 应趋近 1, got %s" % val


def test_winner_down_trend_near_zero():
    # 单边下跌, 收盘在低位 -> WINNER(C) 趋近 0
    n = 300
    tp = np.linspace(20, 10, n)
    vol = np.ones(n)
    df = _make_df(tp, vol, closes=tp)
    w = WINNER_proxy(df, lookback=250)
    val = w.dropna().iloc[-1]
    assert val < 0.15, "单边下跌 WINNER 应趋近 0, got %s" % val


def test_scr_concentrated_small():
    # 窄幅集中 -> SCR 较小
    n = 300
    tp = np.linspace(10, 10.3, n)
    vol = np.ones(n)
    df = _make_df(tp, vol)
    s = SCR_proxy(df, lookback=250)
    val = s.dropna().iloc[-1]
    assert val < 5, "窄幅集中 SCR 应小, got %s" % val


def test_scr_wide_large():
    # 宽幅 -> SCR 较大
    n = 300
    tp = np.concatenate([np.linspace(10, 20, 150), np.linspace(20, 10, 150)])
    vol = np.ones(n)
    df = _make_df(tp, vol)
    s = SCR_proxy(df, lookback=250)
    val = s.dropna().iloc[-1]
    assert val > 30, "宽幅 SCR 应大, got %s" % val


def test_idempotent():
    n = 300
    tp = np.linspace(10, 15, n) + np.sin(np.arange(n) * 0.1)
    vol = np.abs(np.random.RandomState(42).randn(n)) + 1
    df = _make_df(tp, vol)
    r1 = COST_proxy(df, 90, lookback=250)
    r2 = COST_proxy(df, 90, lookback=250)
    pd.testing.assert_series_equal(r1, r2)


def test_no_future_leak():
    # 补充未来数据不影响历史值
    n = 300
    tp = np.linspace(10, 15, n)
    vol = np.ones(n)
    df = _make_df(tp, vol)
    r1 = COST_proxy(df, 50, lookback=250).iloc[:200]
    # 加未来数据
    tp2 = np.concatenate([tp, np.linspace(15, 30, 100)])
    vol2 = np.concatenate([vol, np.ones(100)])
    df2 = _make_df(tp2, vol2)
    r2 = COST_proxy(df2, 50, lookback=250).iloc[:200]
    pd.testing.assert_series_equal(r1, r2)


def test_winner_range_0_1():
    n = 300
    tp = np.linspace(10, 15, n) + np.sin(np.arange(n) * 0.2)
    vol = np.abs(np.random.RandomState(1).randn(n)) + 1
    df = _make_df(tp, vol)
    w = WINNER_proxy(df, lookback=250).dropna()
    assert (w >= 0).all() and (w <= 1).all(), "WINNER 应在 [0,1]"


def test_cost_monotone_in_percent():
    # COST(95) >= COST(5)
    n = 300
    tp = np.linspace(10, 15, n) + np.sin(np.arange(n) * 0.1)
    vol = np.abs(np.random.RandomState(7).randn(n)) + 1
    df = _make_df(tp, vol)
    c95 = COST_proxy(df, 95, lookback=250).dropna()
    c5 = COST_proxy(df, 5, lookback=250).dropna()
    assert (c95 >= c5).all(), "COST(95) 应 >= COST(5)"
