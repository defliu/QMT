# coding=utf-8
"""持仓强制同步 + 卖出反查失败兜底测试。"""
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from adapters import qmt_wrapper as qmt


class _StateStub(object):
    def __init__(self, cleared=False, cleared_date='', current_shares=0):
        self.cleared = cleared
        self.cleared_date = cleared_date
        self.current_shares = current_shares


class _EngineStub(object):
    def __init__(self, states=None):
        self._states = states or {}

    def save_state(self):
        pass


def _set_trader(positions):
    """positions: {code: volume}"""
    trader = MagicMock()
    trader.get_position.side_effect = lambda code: {'volume': positions.get(code, 0),
                                                     'can_use': positions.get(code, 0)}
    return trader


class TestSyncHoldingsFromAccount(unittest.TestCase):
    def setUp(self):
        self._saved_trader = qmt._g_trader
        self._saved_codes = qmt._g_my_codes
        self._saved_engine = qmt._g_sell_engine
        qmt._g_my_codes = {}

    def tearDown(self):
        qmt._g_trader = self._saved_trader
        qmt._g_my_codes = self._saved_codes
        qmt._g_sell_engine = self._saved_engine

    def test_pops_cleared_code_and_marks_engine(self):
        qmt._g_trader = _set_trader({'600001.SH': 0, '600002.SH': 500})
        qmt._g_my_codes = {'600001.SH': 10.0, '600002.SH': 5.0}
        state = _StateStub(cleared=False, current_shares=500)
        qmt._g_sell_engine = _EngineStub({'600001.SH': state})
        with patch.object(qmt, 'write_holdings_file') as wf:
            held = qmt._sync_holdings_from_account(None, '20260626')
        self.assertNotIn('600001.SH', qmt._g_my_codes)
        self.assertIn('600002.SH', qmt._g_my_codes)
        self.assertTrue(state.cleared)
        self.assertEqual(state.cleared_date, '20260626')
        self.assertEqual(state.current_shares, 0)
        self.assertIn('600002.SH', held)
        self.assertNotIn('600001.SH', held)
        self.assertTrue(wf.called)

    def test_keeps_holding_code(self):
        qmt._g_trader = _set_trader({'600002.SH': 500})
        qmt._g_my_codes = {'600002.SH': 5.0}
        qmt._g_sell_engine = None
        with patch.object(qmt, 'write_holdings_file'):
            held = qmt._sync_holdings_from_account(None, '20260626')
        self.assertEqual(set(held), {'600002.SH'})

    def test_trader_none_returns_empty(self):
        qmt._g_trader = None
        self.assertEqual(qmt._sync_holdings_from_account(None, '20260626'), set())


class TestCheckPendingSellsLookupFallback(unittest.TestCase):
    def setUp(self):
        self._saved_trader = qmt._g_trader
        self._saved_codes = qmt._g_my_codes
        self._saved_pending = dict(qmt._g_pending_sells)
        self._saved_pnl = qmt._g_cumulative_pnl
        self._saved_engine = qmt._g_sell_engine
        qmt._g_pending_sells.clear()
        qmt._g_my_codes = {}
        qmt._g_cumulative_pnl = 0.0

    def tearDown(self):
        qmt._g_trader = self._saved_trader
        qmt._g_my_codes = self._saved_codes
        qmt._g_pending_sells.clear()
        qmt._g_pending_sells.update(self._saved_pending)
        qmt._g_cumulative_pnl = self._saved_pnl
        qmt._g_sell_engine = self._saved_engine

    def _no_order_found(self, *a, **kw):
        return []

    def test_lookup_fail_but_position_zero_treats_as_filled(self):
        """反查失败 + 持仓归零 → 全部成交，不撤单不重试"""
        trader = _set_trader({'600001.SH': 0})
        qmt._g_trader = trader
        qmt._g_my_codes = {'600001.SH': 10.0}
        info = {'order_id': 12345, 'volume': 100, 'sell_price': 11.0,
                'cost': 10.0, 'pct': 1.0, 'is_clear': True,
                'code': '600001.SH', 'today': '20260626'}
        qmt._g_pending_sells['600001.SH'] = info
        with patch.object(qmt, 'get_trade_detail_data', side_effect=self._no_order_found, create=True), \
             patch.object(qmt, '_is_trading_time', return_value=True), \
             patch.object(qmt, '_get_qmt_time', return_value=None), \
             patch.object(qmt, '_finish_pending_sell') as fin, \
             patch.object(qmt, '_confirm_engine_clear'), \
             patch.object(qmt, '_append_trade_record'), \
             patch.object(qmt, 'write_nav_file'), \
             patch.object(qmt, '_retry_pending_sell') as retry:
            qmt._check_pending_sells(MagicMock(), '20260626')
        self.assertTrue(fin.called, '应调用 _finish_pending_sell 全部成交')
        trader.cancel_order.assert_not_called()
        self.assertFalse(retry.called, '全部成交不应走重试')

    def test_lookup_fail_but_partial_fill_keeps_remaining(self):
        """反查失败 + 持仓减少 → 部分成交确认，剩余继续等，不撤单"""
        # 委托 300 股，已成交 0（already_traded=0），实际剩 100（说明已成交 200）
        trader = _set_trader({'600001.SH': 100})
        qmt._g_trader = trader
        qmt._g_my_codes = {'600001.SH': 10.0}
        info = {'order_id': 12345, 'volume': 300, 'sell_price': 11.0,
                'cost': 10.0, 'pct': 1.0, 'already_traded': 0,
                'code': '600001.SH', 'today': '20260626'}
        qmt._g_pending_sells['600001.SH'] = info
        with patch.object(qmt, 'get_trade_detail_data', side_effect=self._no_order_found, create=True), \
             patch.object(qmt, '_is_trading_time', return_value=True), \
             patch.object(qmt, '_get_qmt_time', return_value=None), \
             patch.object(qmt, '_append_trade_record') as rec, \
             patch.object(qmt, 'write_nav_file'), \
             patch.object(qmt, '_finish_pending_sell') as fin:
            qmt._check_pending_sells(MagicMock(), '20260626')
        # 没全部成交
        self.assertFalse(fin.called)
        # 没撤单
        trader.cancel_order.assert_not_called()
        # 剩余保留
        self.assertIn('600001.SH', qmt._g_pending_sells)
        self.assertEqual(qmt._g_pending_sells['600001.SH']['volume'], 100)
        self.assertEqual(qmt._g_pending_sells['600001.SH']['already_traded'], 200)
        # 记了一笔成交
        self.assertTrue(rec.called)

    def test_lookup_fail_no_fill_cancels_and_retries(self):
        """反查失败 + 持仓未减 → 走原撤单重试"""
        # 委托 200，实际还有 200（prev_vol=200，actual=200，没成交）
        trader = _set_trader({'600001.SH': 200})
        qmt._g_trader = trader
        qmt._g_my_codes = {'600001.SH': 10.0}
        info = {'order_id': 12345, 'volume': 200, 'sell_price': 11.0,
                'cost': 10.0, 'pct': 1.0, 'already_traded': 0,
                'code': '600001.SH', 'today': '20260626'}
        qmt._g_pending_sells['600001.SH'] = info
        with patch.object(qmt, 'get_trade_detail_data', side_effect=self._no_order_found, create=True), \
             patch.object(qmt, '_is_trading_time', return_value=True), \
             patch.object(qmt, '_get_qmt_time', return_value=None), \
             patch.object(qmt, '_retry_pending_sell') as retry, \
             patch.object(qmt, '_finish_pending_sell') as fin, \
             patch.object(qmt, '_append_trade_record'), \
             patch.object(qmt, 'write_nav_file'):
            qmt._g_retry_skip_printed.clear()
            qmt._check_pending_sells(MagicMock(), '20260626')
        self.assertFalse(fin.called, '没成交不该调 _finish_pending_sell')
        self.assertTrue(trader.cancel_order.called, '没成交应撤单')
        self.assertTrue(retry.called, '应走重试')


if __name__ == '__main__':
    import unittest
    unittest.main()
