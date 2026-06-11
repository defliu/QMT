# coding=utf-8
"""测试 utils.py 的完整实现"""
import pytest
import pandas as pd
import numpy as np
from core.utils import calc_ma_angle, calc_bias, calc_up_ratio


class TestCalcMaAngle(object):

    def test_calc_ma_angle_45deg(self):
        """MA5角度应接近45度"""
        ma_values = [10, 10.1, 10.2, 10.3, 10.4]
        angle = calc_ma_angle(ma_values, window=5)
        assert angle == pytest.approx(45.0, abs=1.0)

    def test_calc_ma_angle_flat(self):
        """均线走平时角度接近0"""
        ma_values = [10, 10, 10, 10, 10]
        angle = calc_ma_angle(ma_values, window=5)
        assert angle == pytest.approx(0.0, abs=0.1)


class TestCalcBias(object):

    def test_calc_bias_positive(self):
        """价格在均线上方 -> 正乖离"""
        bias = calc_bias(11.0, 10.0)
        assert bias == pytest.approx(10.0)

    def test_calc_bias_zero(self):
        """价格等于均线 -> 乖离0"""
        bias = calc_bias(10.0, 10.0)
        assert bias == pytest.approx(0.0)


class TestCalcUpRatio(object):

    def test_calc_up_ratio_all_up(self):
        """全部阳线 -> 比例1.0"""
        closes = [10, 11, 12, 13, 14]
        ratio = calc_up_ratio(closes, period=5)
        assert ratio == pytest.approx(1.0)

    def test_calc_up_ratio_half(self):
        """一半阳线 -> 比例0.5"""
        closes = [10, 12, 11, 13, 12]
        ratio = calc_up_ratio(closes, period=5)
        assert ratio == pytest.approx(0.5)


class TestCalcKdj(object):

    def test_calc_kdj_returns_tuple(self, mock_klines):
        """calc_kdj 返回 (k, d, j) 三元组"""
        from core.utils import calc_kdj
        k, d, j = calc_kdj(mock_klines['close'], mock_klines['high'], mock_klines['low'])
        assert isinstance(k, pd.Series)
        assert isinstance(d, pd.Series)
        assert isinstance(j, pd.Series)
        assert len(k) == len(mock_klines)

    def test_calc_kdj_range(self, mock_klines):
        """KDJ 值应在合理范围 0-100 内"""
        from core.utils import calc_kdj
        k, d, j = calc_kdj(mock_klines['close'], mock_klines['high'], mock_klines['low'])
        assert k.iloc[-1] >= 0
        assert d.iloc[-1] >= 0
        assert k.iloc[-1] <= 100
        assert d.iloc[-1] <= 100


class TestCalcAtr(object):

    def test_calc_atr_returns_series(self, mock_klines):
        """calc_atr 返回 pandas Series"""
        from core.utils import calc_atr
        atr = calc_atr(mock_klines['close'], mock_klines['high'], mock_klines['low'])
        assert isinstance(atr, pd.Series)
        assert len(atr) == len(mock_klines)

    def test_calc_atr_positive(self, mock_klines):
        """ATR 值必须为正"""
        from core.utils import calc_atr
        atr = calc_atr(mock_klines['close'], mock_klines['high'], mock_klines['low'])
        assert atr.iloc[-1] > 0


class TestCalcMacd(object):

    def test_calc_macd_returns_tuple(self, mock_klines):
        """calc_macd 返回 (diff, dea, macd) 三元组"""
        from core.utils import calc_macd
        diff, dea, macd = calc_macd(mock_klines['close'])
        assert isinstance(diff, pd.Series)
        assert isinstance(dea, pd.Series)
        assert isinstance(macd, pd.Series)
        assert len(diff) == len(mock_klines)

    def test_calc_macd_length(self, mock_klines):
        """足够的数据量下 MACD 不应全为 NaN"""
        from core.utils import calc_macd
        _, _, macd = calc_macd(mock_klines['close'])
        assert macd.notna().sum() > 20


class TestCalcRsi(object):

    def test_calc_rsi_returns_series(self, mock_klines):
        """calc_rsi 返回 pandas Series"""
        from core.utils import calc_rsi
        rsi = calc_rsi(mock_klines['close'])
        assert isinstance(rsi, pd.Series)
        assert len(rsi) == len(mock_klines)

    def test_calc_rsi_range(self, mock_klines):
        """RSI 值应在 0-100 范围内"""
        from core.utils import calc_rsi
        rsi = calc_rsi(mock_klines['close'])
        assert 0 <= rsi.iloc[-1] <= 100
