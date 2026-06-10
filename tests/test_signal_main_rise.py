# coding=utf-8
"""测试 signal_main_rise.py: MACD条件 + 评分体系 (V1.0 — check_buy 已移除)"""
import pytest
import pandas as pd
import numpy as np

from core.utils import calc_macd, ma
from core.signal_main_rise import ScoreCalculator8D


# ============================================================
#  通用数据构造工具
# ============================================================

def _make_ohlcv(close_prices, opens=None, highs=None, lows=None):
    """从价格序列构建 OHLCV DataFrame（确定性构造）。"""
    n = len(close_prices)
    if opens is None:
        opens = np.empty(n)
        for i in range(n):
            opens[i] = close_prices[i-1] if i > 0 else close_prices[0] * 0.99
    if highs is None:
        highs = np.empty(n)
        for i in range(n):
            body_top = max(opens[i], close_prices[i])
            highs[i] = body_top * 1.015
    if lows is None:
        lows = np.empty(n)
        for i in range(n):
            body_bot = min(opens[i], close_prices[i])
            lows[i] = body_bot * 0.985
    volumes = np.full(n, 2_000_000, dtype=float)
    return pd.DataFrame({
        'open': opens.astype(float),
        'close': close_prices.astype(float),
        'high': highs.astype(float),
        'low': lows.astype(float),
        'volume': volumes,
    })


def _uptrend_closes(n, start, end):
    """单调上升收盘价序列。"""
    return np.linspace(start, end, n)


# ============================================================
#  1. MACD 条件 — 直接逻辑正确性测试
#    验证的是布尔条件表达式本身，不依赖特定价格数据
# ============================================================

class TestMACDConditions:

    def test_macd_green_shortening_logic(self):
        """3.1 绿柱缩短方向: MACD<0 & 昨日<0 & 今日>昨日 → 末位True"""
        macd = pd.Series([-0.5, -0.4, -0.3, -0.2, -0.1])
        cond = (macd < 0) & (macd.shift(1) < 0) & (macd > macd.shift(1))
        assert cond.iloc[-1], "连续绿柱缩短末位应为True"

    def test_macd_green_shortening_old_bug(self):
        """3.1 旧代码方向反了: 今日<昨日 应返回 False"""
        macd = pd.Series([-0.5, -0.4, -0.3, -0.2, -0.1])
        old_bug = (macd < 0) & (macd.shift(1) < 0) & (macd < macd.shift(1))
        assert not old_bug.iloc[-1], "旧代码(macd<prev)末位应为False"

    def test_macd_first_green_to_red_logic(self):
        """3.1 首次绿转红: 昨日<0 & 今日>0 → 末位True"""
        macd = pd.Series([-0.3, -0.2, -0.1, 0.05])
        cond = (macd > 0) & (macd.shift(1) < 0)
        assert cond.iloc[-1], "首次绿转红末位应为True"

    def test_macd_red_ok_logic(self):
        """3.1 红柱递增: MACD>0 & 昨日>0 & 今日≥昨日 → 末位True"""
        macd = pd.Series([0.1, 0.2, 0.3, 0.4, 0.5])
        cond = (macd > 0) & (macd.shift(1) > 0) & (macd >= macd.shift(1))
        assert cond.iloc[-1], "红柱递增末位应为True"

    def test_macd_satisfied_includes_all_three(self):
        """3.1 macd_satisfied = 红柱递增|绿柱缩短|首次绿转红"""
        # 场景: 首次绿转红
        macd1 = pd.Series([-0.2, -0.1, 0.05, 0.15])
        r = (macd1 > 0) & (macd1.shift(1) > 0) & (macd1 >= macd1.shift(1))
        g = (macd1 < 0) & (macd1.shift(1) < 0) & (macd1 > macd1.shift(1))
        f = (macd1 > 0) & (macd1.shift(1) < 0)
        assert (r | g | f).iloc[-1], "首次绿转红应满足macd_satisfied"

        # 场景: 绿柱缩短
        macd2 = pd.Series([-0.5, -0.4, -0.3, -0.25])
        r2 = (macd2 > 0) & (macd2.shift(1) > 0) & (macd2 >= macd2.shift(1))
        g2 = (macd2 < 0) & (macd2.shift(1) < 0) & (macd2 > macd2.shift(1))
        f2 = (macd2 > 0) & (macd2.shift(1) < 0)
        assert (r2 | g2 | f2).iloc[-1], "绿柱缩短应满足macd_satisfied"

        # 场景: 红柱递增
        macd3 = pd.Series([0.1, 0.2, 0.3, 0.35])
        r3 = (macd3 > 0) & (macd3.shift(1) > 0) & (macd3 >= macd3.shift(1))
        g3 = (macd3 < 0) & (macd3.shift(1) < 0) & (macd3 > macd3.shift(1))
        f3 = (macd3 > 0) & (macd3.shift(1) < 0)
        assert (r3 | g3 | f3).iloc[-1], "红柱递增应满足macd_satisfied"

    def test_macd_none_satisfied(self):
        """当MACD不满足任一条件时返回False"""
        # MACD>0 but decreasing (红柱递增失败), 且 prev>0 (首次绿转红失败)
        macd = pd.Series([0.5, 0.4, 0.3, 0.2, 0.1])
        r = (macd > 0) & (macd.shift(1) > 0) & (macd >= macd.shift(1))
        g = (macd < 0) & (macd.shift(1) < 0) & (macd > macd.shift(1))
        f = (macd > 0) & (macd.shift(1) < 0)
        assert not (r | g | f).iloc[-1], "递减MACD不应满足任一条件"


# ============================================================
#  2. 8D 评分体系测试
# ============================================================

class TestBuySignalInScore:

    def test_technical_score_returns_float(self):
        """_technical_score 返回有效分值"""
        prices = _uptrend_closes(120, 10, 20)
        df = _make_ohlcv(prices)
        scorer = ScoreCalculator8D()
        score = scorer._technical_score(df)
        assert isinstance(score, float)
        assert 0 <= score <= 18

    def test_score_calculator_class_exists(self):
        """ScoreCalculator8D 有 _technical_score 方法"""
        assert hasattr(ScoreCalculator8D, '_technical_score')
        assert callable(ScoreCalculator8D._technical_score)
