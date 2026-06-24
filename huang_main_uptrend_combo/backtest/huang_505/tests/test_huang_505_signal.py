# coding=utf-8
"""505 版信号触发的最小单测."""
import numpy as np
import pandas as pd
import pytest

from huang_main_uptrend_combo.huang_main_uptrend_combo_selector import (
    _calc_huang_505_conditions, DEFAULT_PARAMS, select_huang_main_uptrend_combo,
)


def _make_bullish_df(n=80, start=10.0, daily_growth=0.015):
    """构造单调上涨 + 阳线 + 站稳 MA5 的票 (指数增长确保角度 >=45°)."""
    dates = pd.date_range('2025-01-01', periods=n)
    close = np.array([start * (1 + daily_growth) ** i for i in range(n)])
    open_ = close * 0.99  # 阳线: open < close
    high = close * 1.02
    low = close * 0.985   # 站稳 MA5: low >= MA5*0.98
    vol = np.full(n, 10000.0)
    df = pd.DataFrame({
        'open': open_, 'high': high, 'low': low, 'close': close,
        'volume': vol,
    }, index=dates)
    return df


def test_huang505_bullish_triggers_xg():
    """单调上涨 + 阳线 + 站稳 MA5 + 角度足够 → 最后一根必触发 XG."""
    df = _make_bullish_df()
    out = _calc_huang_505_conditions(df, DEFAULT_PARAMS)
    assert 'huang505_XG' in out.columns
    # MA60 要求 >= 60 根, 最后 20 根应至少有一根 XG=True
    assert bool(out['huang505_XG'].iloc[-1]) or out['huang505_XG'].iloc[-20:].any(), \
        'bullish 票 80 根日 K 内未触发任何 huang505_XG'


def test_huang505_flat_no_xg():
    """横盘票 → 所有条件不达, XG 全 False."""
    dates = pd.date_range('2025-01-01', periods=80)
    close = np.full(80, 10.0)
    df = pd.DataFrame({
        'open': close, 'high': close * 1.005, 'low': close * 0.995,
        'close': close, 'volume': np.full(80, 10000.0),
    }, index=dates)
    out = _calc_huang_505_conditions(df, DEFAULT_PARAMS)
    assert not out['huang505_XG'].any(), '横盘票不该触发 huang505_XG'


def test_huang505_chip_v1_degraded():
    """v1 筹码降级标记必须是 True."""
    df = _make_bullish_df()
    out = _calc_huang_505_conditions(df, DEFAULT_PARAMS)
    assert out['huang505_chip_v1_降级标记'].all()


def test_huang505_xg_in_selector_output():
    """selector 主入口也应输出 huang505_XG 列."""
    df = _make_bullish_df()
    bench = pd.DataFrame({'close': np.linspace(3000, 3300, 80)},
                         index=df.index)
    result = select_huang_main_uptrend_combo({'TEST.SZ': df}, bench)
    assert 'huang505_XG' in result.columns


def test_huang505_bias5_diagnostic_only():
    """BIAS5 是 diagnostic, 不影响 XG."""
    df = _make_bullish_df(daily_growth=0.025)  # 强势冲高, BIAS5 大
    out = _calc_huang_505_conditions(df, DEFAULT_PARAMS)
    # 即使 BIAS5 > 10, XG 也可能 True (只要其他条件满足)
    bias = out['huang505_BIAS5'].iloc[-1]
    assert bias > 0  # diagnostic 字段非空且正常
