# coding=utf-8
"""测试 pool_filter.py — 筹码密集突破选股核心逻辑"""
import numpy as np
import pandas as pd


def _make_trigger_data():
    """构造满足全部条件的模拟K线（确定性数据），返回 DataFrame。

    Price structure (80 rows):
      Phase 1 (0-40):  slow rise   10.0 -> 11.5  (forms 60-day ceiling)
      Phase 2 (41-55): pullback    11.5 -> 10.8  (dips below ceiling)
      Phase 3 (56-64): recovery    10.8 -> 11.2
      Phase 4 (65-74): consolidation 11.1-11.3   (small moves, accumulation)
      Phase 5 (75-79): breakout above ceiling
    """
    n = 80
    t = np.arange(n, dtype=float)
    close = np.zeros(n)

    # Phase 1: rise
    close[0:41] = np.linspace(10.0, 11.5, 41)
    # Phase 2: pullback
    close[41:56] = np.linspace(11.5, 10.8, 15)
    # Phase 3: recovery
    close[56:65] = np.linspace(10.8, 11.2, 9)
    # Phase 4: consolidation
    close[65:75] = np.linspace(11.2, 11.3, 10)

    # Phase 5: breakout — last 5 days
    close[75] = close[74] * 1.002   # +0.2%  (< 3% → accumulation)
    close[76] = close[75] * 1.003   # +0.3%  (< 3% → accumulation)
    close[77] = close[76] * 1.04    # +4.0%
    close[78] = close[77] * 1.003   # +0.3%  (< 3% → accumulation)
    close[79] = close[78] * 1.08    # +8.0%  → breakout signal day

    # Open: slightly below close (bullish bias), except during pullback
    open_ = close * 0.995
    open_[30:46] = close[30:46] * 1.005   # pullback: open > close

    # High / Low: deterministic spread
    high = np.maximum(close, open_) * 1.005
    low = np.minimum(close, open_) * 0.995

    # Volume well above 100k threshold
    volume = np.full(n, 500000, dtype=int)

    return pd.DataFrame({
        'close': close,
        'open': open_,
        'high': high,
        'low': low,
        'volume': volume,
    })


def _make_no_trigger_data():
    """构造不满足条件的模拟K线 — 低振幅但低成交量 + 下跌趋势."""
    n = 80
    close = np.linspace(12.0, 10.0, n)  # downward trend
    open_ = close * 1.005                # open > close (bearish)
    high = np.maximum(close, open_) * 1.01
    low = np.minimum(close, open_) * 0.99
    volume = np.full(n, 50000, dtype=int)  # volume < 100k → fails base_active

    return pd.DataFrame({
        'close': close,
        'open': open_,
        'high': high,
        'low': low,
        'volume': volume,
    })


def _make_short_data():
    """返回不足60根K线的DataFrame."""
    n = 50
    close = np.linspace(10.0, 11.0, n)
    open_ = close * 0.995
    high = np.maximum(close, open_) * 1.005
    low = np.minimum(close, open_) * 0.995
    volume = np.full(n, 500000, dtype=int)

    return pd.DataFrame({
        'close': close,
        'open': open_,
        'high': high,
        'low': low,
        'volume': volume,
    })


class TestPoolFilter(object):

    def test_select_breakout_trigger(self):
        """满足全部条件的模拟K线 → 返回 True"""
        from core.pool_filter import select_breakout_stocks
        df = _make_trigger_data()
        result = select_breakout_stocks(df)
        assert result is True, (
            f"Expected True but got {result}\n"
            f"close[-1]={df['close'].iloc[-1]:.4f}, "
            f"close[-2]={df['close'].iloc[-2]:.4f}"
        )

    def test_select_breakout_no_trigger(self):
        """不满足条件的模拟K线 → 返回 False"""
        from core.pool_filter import select_breakout_stocks
        df = _make_no_trigger_data()
        result = select_breakout_stocks(df)
        assert result is False, f"Expected False but got {result}"

    def test_select_breakout_insufficient_data(self):
        """不足60根K线 → 返回 False"""
        from core.pool_filter import select_breakout_stocks
        df = _make_short_data()
        result = select_breakout_stocks(df)
        assert result is False, f"Expected False but got {result}"
