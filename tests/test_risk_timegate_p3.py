# coding=utf-8
"""P3 锟斤拷锟斤拷: 锟斤拷锟较撅拷锟斤拷 09:25-09:30 预锟斤拷硬止锟斤拷"""
import unittest
import io
import contextlib
from unittest.mock import MagicMock, patch
import sys
sys.path.insert(0, 'D:/QMT_STRATEGIES')

import pandas as pd
from adapters import qmt_wrapper
from core.risk_manager import SellStrategyEngine, SellPositionState


def _make_mock_C(close_series_map):
    """close_series_map: {code: [prev_close, ref_price]}"""
    C = MagicMock()

    def _get_md(fields, codes, period='1d', count=2):
        result = {}
        for code in codes:
            if code not in close_series_map:
                continue
            arr = close_series_map[code]
            result[code] = pd.DataFrame({'close': arr})
        return result

    C.get_market_data_ex.side_effect = _get_md
    return C


class TestPremarketHardStop(unittest.TestCase):

    def setUp(self):
        self._saved = {
            'mode': qmt_wrapper.PREMARKET_HARD_STOP_MODE,
            'check_done': qmt_wrapper._g_premarket_check_done,
            'orders': dict(qmt_wrapper._g_premarket_orders),
            'my_codes': dict(qmt_wrapper._g_my_codes),
            'sell_engine': qmt_wrapper._g_sell_engine,
            'trader': qmt_wrapper._g_trader,
        }
        qmt_wrapper._g_premarket_check_done = False
        qmt_wrapper._g_premarket_orders = {}
        qmt_wrapper._g_my_codes = {'000001.SZ': 10.0}

        engine = MagicMock(spec=SellStrategyEngine)
        engine._states = {
            '000001.SZ': SellPositionState(code='000001.SZ', cost_price=10.0)
        }
        qmt_wrapper._g_sell_engine = engine

        trader = MagicMock()
        trader.sell_limit_price = MagicMock(return_value='ORD123')
        trader.SELL_CODE = 24
        trader.get_position = MagicMock(return_value={'volume': 200, 'cost': 10.0})
        qmt_wrapper._g_trader = trader

    def tearDown(self):
        qmt_wrapper.PREMARKET_HARD_STOP_MODE = self._saved['mode']
        qmt_wrapper._g_premarket_check_done = self._saved['check_done']
        qmt_wrapper._g_premarket_orders = self._saved['orders']
        qmt_wrapper._g_my_codes = self._saved['my_codes']
        qmt_wrapper._g_sell_engine = self._saved['sell_engine']
        qmt_wrapper._g_trader = self._saved['trader']

    def test_off_mode_no_order(self):
        qmt_wrapper.PREMARKET_HARD_STOP_MODE = 'OFF'
        C = _make_mock_C({'000001.SZ': [10.0, 8.5]})
        with contextlib.redirect_stdout(io.StringIO()):
            qmt_wrapper._check_pre_market_hard_stop(C, '20260623', '0925')
        self.assertEqual(qmt_wrapper._g_trader.sell_limit_price.call_count, 0)
        self.assertTrue(qmt_wrapper._g_premarket_check_done)

    def test_g3_triggers_in_g3_only(self):
        qmt_wrapper.PREMARKET_HARD_STOP_MODE = 'G3_ONLY'
        # cost=10, ref=8.5 -> cum_pnl=-15% -> G3
        C = _make_mock_C({'000001.SZ': [10.0, 8.5]})
        with contextlib.redirect_stdout(io.StringIO()):
            qmt_wrapper._check_pre_market_hard_stop(C, '20260623', '0925')
        self.assertEqual(qmt_wrapper._g_trader.sell_limit_price.call_count, 1)
        args, kwargs = qmt_wrapper._g_trader.sell_limit_price.call_args
        # price = prev_close * 0.91 = 10 * 0.91 = 9.10
        self.assertAlmostEqual(args[2], 9.10, places=2)
        self.assertEqual(qmt_wrapper._g_premarket_orders['000001.SZ']['grade'], 'G3')

    def test_g2_not_trigger_in_g3_only(self):
        qmt_wrapper.PREMARKET_HARD_STOP_MODE = 'G3_ONLY'
        # cost=10, prev=10, ref=9.4 -> daily_drop=-6%, cum_pnl=-6% -> G3 实锟斤拷
        # 锟侥筹拷 cost=9.7, prev=10, ref=9.4 -> daily_drop=-6%, cum_pnl=-3.09% -> G2
        qmt_wrapper._g_sell_engine._states['000001.SZ'].cost_price = 9.7
        C = _make_mock_C({'000001.SZ': [10.0, 9.4]})
        with contextlib.redirect_stdout(io.StringIO()):
            qmt_wrapper._check_pre_market_hard_stop(C, '20260623', '0925')
        self.assertEqual(qmt_wrapper._g_trader.sell_limit_price.call_count, 0)

    def test_g2_triggers_in_g2_and_g3(self):
        qmt_wrapper.PREMARKET_HARD_STOP_MODE = 'G2_AND_G3'
        qmt_wrapper._g_sell_engine._states['000001.SZ'].cost_price = 9.7
        C = _make_mock_C({'000001.SZ': [10.0, 9.4]})
        with contextlib.redirect_stdout(io.StringIO()):
            qmt_wrapper._check_pre_market_hard_stop(C, '20260623', '0925')
        self.assertEqual(qmt_wrapper._g_trader.sell_limit_price.call_count, 1)
        args, kwargs = qmt_wrapper._g_trader.sell_limit_price.call_args
        # price = ref_price * 0.99 = 9.4 * 0.99 = 9.306 -> round 9.31
        self.assertAlmostEqual(args[2], 9.31, places=2)
        self.assertEqual(qmt_wrapper._g_premarket_orders['000001.SZ']['grade'], 'G2')

    def test_g1_no_order(self):
        qmt_wrapper.PREMARKET_HARD_STOP_MODE = 'G3_ONLY'
        # cost=10, prev=10, ref=9.6 -> daily_drop=-4%, cum_pnl=-4% -> G1
        C = _make_mock_C({'000001.SZ': [10.0, 9.6]})
        with contextlib.redirect_stdout(io.StringIO()):
            qmt_wrapper._check_pre_market_hard_stop(C, '20260623', '0925')
        self.assertEqual(qmt_wrapper._g_trader.sell_limit_price.call_count, 0)

    def test_g0_no_order(self):
        qmt_wrapper.PREMARKET_HARD_STOP_MODE = 'G3_ONLY'
        # cost=10, prev=10, ref=10.5 -> daily_drop=+5%, cum_pnl=+5% -> G0
        C = _make_mock_C({'000001.SZ': [10.0, 10.5]})
        with contextlib.redirect_stdout(io.StringIO()):
            qmt_wrapper._check_pre_market_hard_stop(C, '20260623', '0925')
        self.assertEqual(qmt_wrapper._g_trader.sell_limit_price.call_count, 0)

    def test_reentrancy_guard(self):
        qmt_wrapper.PREMARKET_HARD_STOP_MODE = 'G3_ONLY'
        C = _make_mock_C({'000001.SZ': [10.0, 8.5]})
        with contextlib.redirect_stdout(io.StringIO()):
            qmt_wrapper._check_pre_market_hard_stop(C, '20260623', '0925')
            qmt_wrapper._check_pre_market_hard_stop(C, '20260623', '0926')
            qmt_wrapper._check_pre_market_hard_stop(C, '20260623', '0929')
        self.assertEqual(qmt_wrapper._g_trader.sell_limit_price.call_count, 1)

    def test_shares_less_than_100_skip(self):
        qmt_wrapper.PREMARKET_HARD_STOP_MODE = 'G3_ONLY'
        qmt_wrapper._g_trader.get_position.return_value = {'volume': 50, 'cost': 10.0}
        C = _make_mock_C({'000001.SZ': [10.0, 8.5]})
        with contextlib.redirect_stdout(io.StringIO()):
            qmt_wrapper._check_pre_market_hard_stop(C, '20260623', '0925')
        self.assertEqual(qmt_wrapper._g_trader.sell_limit_price.call_count, 0)

    def test_cost_price_fallback_to_my_codes(self):
        qmt_wrapper.PREMARKET_HARD_STOP_MODE = 'G3_ONLY'
        qmt_wrapper._g_sell_engine._states['000001.SZ'].cost_price = 0.0  # 锟竭讹拷锟斤拷
        qmt_wrapper._g_my_codes['000001.SZ'] = 10.0
        C = _make_mock_C({'000001.SZ': [10.0, 8.5]})
        with contextlib.redirect_stdout(io.StringIO()):
            qmt_wrapper._check_pre_market_hard_stop(C, '20260623', '0925')
        # 锟斤拷锟斤拷 cost=10, ref=8.5 -> cum_pnl=-15% -> G3 锟斤拷锟斤拷
        self.assertEqual(qmt_wrapper._g_trader.sell_limit_price.call_count, 1)

    def test_ref_price_unavailable_skip(self):
        qmt_wrapper.PREMARKET_HARD_STOP_MODE = 'G3_ONLY'
        C = MagicMock()
        C.get_market_data_ex.return_value = {}  # 取锟斤拷锟斤拷
        with contextlib.redirect_stdout(io.StringIO()):
            qmt_wrapper._check_pre_market_hard_stop(C, '20260623', '0925')
        self.assertEqual(qmt_wrapper._g_trader.sell_limit_price.call_count, 0)

    def test_daily_reset_allows_rerun(self):
        qmt_wrapper.PREMARKET_HARD_STOP_MODE = 'G3_ONLY'
        C = _make_mock_C({'000001.SZ': [10.0, 8.5]})
        with contextlib.redirect_stdout(io.StringIO()):
            qmt_wrapper._check_pre_market_hard_stop(C, '20260623', '0925')
        self.assertEqual(qmt_wrapper._g_trader.sell_limit_price.call_count, 1)
        # 模锟斤拷锟斤拷锟斤拷
        qmt_wrapper._g_premarket_check_done = False
        qmt_wrapper._g_premarket_orders = {}
        with contextlib.redirect_stdout(io.StringIO()):
            qmt_wrapper._check_pre_market_hard_stop(C, '20260624', '0925')
        self.assertEqual(qmt_wrapper._g_trader.sell_limit_price.call_count, 2)


class TestPremarketDiagnostic(unittest.TestCase):
    """P3 观察期诊断 CSV 测试"""

    def setUp(self):
        import tempfile, os
        self._tmpdir = tempfile.mkdtemp(prefix='p3diag_')
        self._saved_my_codes = dict(qmt_wrapper._g_my_codes)
        qmt_wrapper._g_my_codes = {'000001.SZ': 10.0, '600000.SH': 5.0}

    def tearDown(self):
        import shutil
        qmt_wrapper._g_my_codes = self._saved_my_codes
        try:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
        except Exception:
            pass

    def test_diag_writes_csv_with_both_fields(self):
        """验证诊断函数同时记录 md close[-1]/[-2] 和 tick lastPrice/preClose"""
        import os
        _real_open = open
        C = MagicMock()
        # md: 000001 close=[10.0, 8.5], 600000 close=[5.0, 4.8]
        def _get_md(fields, codes, period='1d', count=2):
            return {
                '000001.SZ': pd.DataFrame({'close': [10.0, 8.5]}),
                '600000.SH': pd.DataFrame({'close': [5.0, 4.8]}),
            }
        C.get_market_data_ex.side_effect = _get_md
        # tick
        C.get_full_tick.return_value = {
            '000001.SZ': {'lastPrice': 8.6, 'preClose': 10.0, 'open': 9.0, 'high': 9.1, 'low': 8.4},
            '600000.SH': {'lastPrice': 4.85, 'preClose': 5.0, 'open': 4.9, 'high': 4.95, 'low': 4.78},
        }

        # 把 D:/QMT_POOL 重定向到 tmpdir（patch os.path.exists + open）
        diag_path = os.path.join(self._tmpdir, 'premarket_diag_20260624.csv')
        with patch.object(qmt_wrapper, 'os') as mock_os:
            mock_os.path.exists.side_effect = lambda p: os.path.exists(diag_path) if 'premarket_diag' in p else os.path.exists(p)
            with patch('builtins.open', wraps=_real_open) as mock_open:
                def _redirect_open(path, *args, **kwargs):
                    if isinstance(path, str) and 'premarket_diag' in path:
                        return _real_open(diag_path, *args, **kwargs)
                    return _real_open(path, *args, **kwargs)
                mock_open.side_effect = _redirect_open
                with contextlib.redirect_stdout(io.StringIO()):
                    qmt_wrapper._log_premarket_diagnostic(C, '20260624', '0925')

        self.assertTrue(os.path.exists(diag_path), '诊断 CSV 应已写入')
        with _real_open(diag_path, 'r') as f:
            content = f.read()
        # 表头
        self.assertIn('md_close_minus_1', content)
        self.assertIn('tick_lastPrice', content)
        # 两个 code 都写了
        self.assertIn('000001.SZ', content)
        self.assertIn('600000.SH', content)
        # md 字段值
        self.assertIn('8.5000', content)  # close[-1]
        self.assertIn('10.0000', content)  # close[-2]
        # tick 字段值
        self.assertIn('8.6', content)
        self.assertIn('4.85', content)

    def test_diag_handles_missing_data(self):
        """C 取不到数据时不抛异常"""
        import os
        _real_open = open
        C = MagicMock()
        C.get_market_data_ex.side_effect = Exception('mock fail')
        C.get_full_tick.side_effect = Exception('mock fail')
        diag_path = os.path.join(self._tmpdir, 'premarket_diag_20260624.csv')
        with patch('builtins.open', wraps=_real_open) as mock_open:
            def _redirect_open(path, *args, **kwargs):
                if isinstance(path, str) and 'premarket_diag' in path:
                    return _real_open(diag_path, *args, **kwargs)
                return _real_open(path, *args, **kwargs)
            mock_open.side_effect = _redirect_open
            with contextlib.redirect_stdout(io.StringIO()):
                # 不应抛异常
                qmt_wrapper._log_premarket_diagnostic(C, '20260624', '0925')


if __name__ == '__main__':
    unittest.main()
