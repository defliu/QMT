# coding=utf-8
"""Tests for huice_loader."""
import sys
import unittest

sys.path.insert(0, 'D:/QMT_STRATEGIES')

from huang_main_uptrend_combo.backtest.huice_loader import (
    load_ohlcv_from_huicexitong,
    load_benchmark_index,
)


class TestHuiceLoader(unittest.TestCase):

    def test_load_ohlcv_small_window(self):
        codes = ['000001.SZ', '600000.SH', '000002.SZ']
        ohlcv = load_ohlcv_from_huicexitong(codes, '2025-01-01', '2025-01-31')
        self.assertIsInstance(ohlcv, dict)
        self.assertGreater(len(ohlcv), 0)
        for code, df in ohlcv.items():
            self.assertIn('open', df.columns)
            self.assertIn('high', df.columns)
            self.assertIn('low', df.columns)
            self.assertIn('close', df.columns)
            self.assertIn('volume', df.columns)
            self.assertGreater(len(df), 0)

    def test_load_ohlcv_filters_bad_prices(self):
        ohlcv = load_ohlcv_from_huicexitong(['600000.SH'], '2024-06-01', '2024-12-31')
        self.assertIn('600000.SH', ohlcv)
        df = ohlcv['600000.SH']
        self.assertTrue((df['open'] > 0).all())
        self.assertTrue((df['high'] > 0).all())
        self.assertTrue((df['low'] > 0).all())
        self.assertTrue((df['close'] > 0).all())
        self.assertFalse(df.isnull().any().any())

    def test_load_benchmark_returns_close_only(self):
        bench = load_benchmark_index('000001.SH', '2025-01-01', '2025-01-31')
        self.assertIsInstance(bench.index, type(bench.index))
        self.assertTrue(hasattr(bench.index, 'day'))
        self.assertIn('close', bench.columns)
        self.assertEqual(len(bench.columns), 1)
        self.assertGreater(len(bench), 0)

    def test_no_lookahead_ordering(self):
        ohlcv = load_ohlcv_from_huicexitong(['600000.SH'], '2025-01-01', '2025-03-31')
        df = ohlcv['600000.SH']
        dates = df.index.tolist()
        for i in range(1, len(dates)):
            self.assertGreater(dates[i], dates[i - 1])


if __name__ == '__main__':
    unittest.main()
