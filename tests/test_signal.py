# coding=utf-8
"""测试 signal_main_rise.py 的 ScoreCalculator8D（check_buy 已移除）"""
import pytest
import pandas as pd
import numpy as np


class TestScoreCalculator8D(object):

    def test_total_score_returns_dict(self, mock_klines):
        """total_score 返回包含所有维度的字典"""
        from core.signal_main_rise import ScoreCalculator8D
        scorer = ScoreCalculator8D()
        result = scorer.total_score(mock_klines)
        assert isinstance(result, dict)
        assert 'final_total' in result
        assert 'rating' in result

    def test_technical_score(self, mock_klines):
        """技术面打分应为正数"""
        from core.signal_main_rise import ScoreCalculator8D
        scorer = ScoreCalculator8D()
        df = mock_klines
        score = scorer._technical_score(df)
        assert isinstance(score, float)
        assert score > 0
