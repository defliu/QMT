# coding=utf-8
"""Smoke test for run_backtest_huang_combo."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, 'D:/QMT_STRATEGIES')

from huang_main_uptrend_combo.backtest.run_backtest_huang_combo import run_backtest
from argparse import Namespace


class TestRunBacktestMinimum(unittest.TestCase):

    def test_run_backtest_smoke(self):
        out_root = tempfile.mkdtemp(prefix='huang_smoke_')
        try:
            args = Namespace(
                start='2025-06-01',
                end='2025-08-31',
                universe='D:/QMT_STRATEGIES/backtest/data/universe/core_100.csv',
                benchmark='000001.SH',
                out_root=out_root,
                hold_periods='5,10,20',
                signal_source='combo_XG',
            )
            summary = run_backtest(args)
            self.assertIn('run_id', summary)
            self.assertIn('signal_rows', summary)
            self.assertIn('stats', summary)
            self.assertIn('bench_compare', summary)
            self.assertGreaterEqual(len(summary['stats']), 3)
            out_dir = os.path.join(out_root, summary['run_id'])
            self.assertTrue(os.path.isdir(out_dir))
            sj_path = os.path.join(out_dir, 'summary.json')
            self.assertTrue(os.path.isfile(sj_path))
            with open(sj_path, 'r', encoding='utf-8') as f:
                sj = json.load(f)
            self.assertIn('stats', sj)
            self.assertIn('bench_compare', sj)
        finally:
            shutil.rmtree(out_root, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
