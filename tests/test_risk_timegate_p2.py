# coding=gbk
"""P2 接通主循环：cooling-off + 时段路由 + 防刷屏 log"""
import unittest
import time
import io
import contextlib
from unittest.mock import patch, MagicMock

from core.risk_manager import SellDecision, Action
from adapters import qmt_wrapper


def _make_decision(code, layer, reason='test', sublayer=None):
    """构造一个 CLEAR 决策（清仓层用）或 REDUCE 决策（其它层用）"""
    if layer == '底线层' or layer == '清仓层':
        return SellDecision.clear(code, reason, layer, [reason], sublayer=sublayer)
    return SellDecision.reduce(code, 0.3, reason, layer, [reason])


class TestAllowedLayersFiltering(unittest.TestCase):
    """验证 _check_and_execute_sell 的 allowed_layers 过滤逻辑"""

    def setUp(self):
        qmt_wrapper._g_timegate_skip_printed.clear()
        self._saved_engine = qmt_wrapper._g_sell_engine
        self._saved_trader = qmt_wrapper._g_trader
        self._saved_codes = qmt_wrapper._g_my_codes
        self._saved_all_data = qmt_wrapper._g_all_data
        self._saved_fp = qmt_wrapper._g_last_sell_fingerprint
        # 隔离卖出链路的全局状态
        self._saved_pending = dict(qmt_wrapper._g_pending_sells)
        self._saved_skip = set(qmt_wrapper._g_sell_skip_printed)
        self._saved_price_skip = set(qmt_wrapper._g_price_skip_printed)
        self._saved_failed_printed = set(qmt_wrapper._g_failed_printed)
        self._saved_fail_cool = dict(qmt_wrapper._g_sell_fail_cooldown)
        qmt_wrapper._g_pending_sells.clear()
        qmt_wrapper._g_sell_skip_printed.clear()
        qmt_wrapper._g_price_skip_printed.clear()
        qmt_wrapper._g_failed_printed.clear()
        qmt_wrapper._g_sell_fail_cooldown.clear()

    def tearDown(self):
        qmt_wrapper._g_sell_engine = self._saved_engine
        qmt_wrapper._g_trader = self._saved_trader
        qmt_wrapper._g_my_codes = self._saved_codes
        qmt_wrapper._g_all_data = self._saved_all_data
        qmt_wrapper._g_last_sell_fingerprint = self._saved_fp
        qmt_wrapper._g_pending_sells.clear()
        qmt_wrapper._g_pending_sells.update(self._saved_pending)
        qmt_wrapper._g_sell_skip_printed.clear()
        qmt_wrapper._g_sell_skip_printed.update(self._saved_skip)
        qmt_wrapper._g_price_skip_printed.clear()
        qmt_wrapper._g_price_skip_printed.update(self._saved_price_skip)
        qmt_wrapper._g_failed_printed.clear()
        qmt_wrapper._g_failed_printed.update(self._saved_failed_printed)
        qmt_wrapper._g_sell_fail_cooldown.clear()
        qmt_wrapper._g_sell_fail_cooldown.update(self._saved_fail_cool)
        qmt_wrapper._g_timegate_skip_printed.clear()

    def _run_with_mock_engine(self, decisions, allowed_layers):
        """跑 _check_and_execute_sell + 返回 (sells, captured_stdout)。
        实际下单链路：_g_trader.sell(code, shares, remark=...) 返回 order_id（数字）或 None。
        这里 mock 返回 None 让函数走"失败"分支，避免触碰 _g_pending_sells / _g_sell_engine._states。
        """
        engine = MagicMock()
        engine.evaluate.return_value = [(code, dec, 100) for code, dec in decisions]
        engine._states = {}
        trader = MagicMock()
        trader.get_position.return_value = {'code': '000001.SZ', 'available': 100, 'volume': 100}
        trader.sell.return_value = None   # 让 sell 路径走"失败"分支，避免污染状态机
        qmt_wrapper._g_sell_engine = engine
        qmt_wrapper._g_trader = trader
        qmt_wrapper._g_my_codes = {code: {} for code, _ in decisions}
        qmt_wrapper._g_all_data = {code: MagicMock() for code, _ in decisions}

        buf = io.StringIO()
        with patch.object(qmt_wrapper, '_get_current_prices', return_value={code: 10.0 for code, _ in decisions}):
            with patch.object(qmt_wrapper, '_get_current_price', return_value=10.0):
                with patch.object(qmt_wrapper, 'print_sell_diagnostics'):
                    with contextlib.redirect_stdout(buf):
                        sells = qmt_wrapper._check_and_execute_sell(MagicMock(), '20260623', allowed_layers=allowed_layers)
        return sells, buf.getvalue()

    def test_whitelist_pass(self):
        """底线层决策 + 允许底线层 → 通过（无拦截 log）"""
        dec = _make_decision('000001.SZ', '底线层')
        allowed = {'layers': {'底线层'}, 'exclude_sublayers': set()}
        sells, out = self._run_with_mock_engine([('000001.SZ', dec)], allowed)
        self.assertNotIn('[时段拦截]', out)

    def test_whitelist_block(self):
        """预警层决策 + 只允许底线层 → 拦截"""
        dec = _make_decision('000002.SZ', '预警层')
        allowed = {'layers': {'底线层'}, 'exclude_sublayers': set()}
        sells, out = self._run_with_mock_engine([('000002.SZ', dec)], allowed)
        self.assertIn('[时段拦截]', out)
        self.assertIn('预警层', out)

    def test_sublayer_block_trailing(self):
        """清仓层 trailing 决策 + exclude_sublayers={trailing} → 拦截"""
        dec = _make_decision('000003.SZ', '清仓层', reason='移动止盈', sublayer='trailing')
        allowed = {'layers': {'底线层', '清仓层'}, 'exclude_sublayers': {'trailing'}}
        sells, out = self._run_with_mock_engine([('000003.SZ', dec)], allowed)
        self.assertIn('[时段拦截|sublayer]', out)
        self.assertIn('trailing', out)

    def test_sublayer_no_block_non_trailing(self):
        """清仓层非 trailing 决策 + exclude_sublayers={trailing} → 通过"""
        dec = _make_decision('000004.SZ', '清仓层', reason='A3:破20日线', sublayer=None)
        allowed = {'layers': {'底线层', '清仓层'}, 'exclude_sublayers': {'trailing'}}
        sells, out = self._run_with_mock_engine([('000004.SZ', dec)], allowed)
        self.assertNotIn('[时段拦截]', out)

    def test_backward_compat_no_allowed_layers(self):
        """不传 allowed_layers → 不过滤（保留旧行为）"""
        dec = _make_decision('000005.SZ', '预警层')
        sells, out = self._run_with_mock_engine([('000005.SZ', dec)], None)
        self.assertNotIn('[时段拦截]', out)

    def test_log_dedup(self):
        """同一(code,layer)拦截 3 次 → log 只出现 1 次"""
        dec = _make_decision('000006.SZ', '预警层')
        allowed = {'layers': {'底线层'}, 'exclude_sublayers': set()}
        out_total = ''
        for _ in range(3):
            sells, out = self._run_with_mock_engine([('000006.SZ', dec)], allowed)
            out_total += out
        self.assertEqual(out_total.count('[时段拦截]'), 1)


class TestCoolingOffGlobalState(unittest.TestCase):

    def test_cooling_active_after_init(self):
        saved = qmt_wrapper._g_strategy_start_ts
        try:
            qmt_wrapper._g_strategy_start_ts = time.time() - 10
            self.assertTrue(qmt_wrapper._is_in_cooling_off())
        finally:
            qmt_wrapper._g_strategy_start_ts = saved

    def test_cooling_expired(self):
        saved = qmt_wrapper._g_strategy_start_ts
        try:
            qmt_wrapper._g_strategy_start_ts = time.time() - 120
            self.assertFalse(qmt_wrapper._is_in_cooling_off())
        finally:
            qmt_wrapper._g_strategy_start_ts = saved


class TestTimegateSkipDedup(unittest.TestCase):

    def test_dedup_set_grows(self):
        qmt_wrapper._g_timegate_skip_printed.clear()
        qmt_wrapper._g_timegate_skip_printed.add(('layer', '000001.SZ', '预警层'))
        qmt_wrapper._g_timegate_skip_printed.add(('layer', '000001.SZ', '预警层'))
        self.assertEqual(len(qmt_wrapper._g_timegate_skip_printed), 1)

        qmt_wrapper._g_timegate_skip_printed.add(('layer', '000002.SZ', '预警层'))
        self.assertEqual(len(qmt_wrapper._g_timegate_skip_printed), 2)

        qmt_wrapper._g_timegate_skip_printed.add(('sublayer', '000001.SZ', 'trailing'))
        self.assertEqual(len(qmt_wrapper._g_timegate_skip_printed), 3)

    def test_dedup_clear_on_day_change(self):
        """模拟日切清空（不真跑 handlebar，验证 set.clear 行为）"""
        qmt_wrapper._g_timegate_skip_printed.add(('layer', '000001.SZ', '预警层'))
        self.assertGreater(len(qmt_wrapper._g_timegate_skip_printed), 0)
        qmt_wrapper._g_timegate_skip_printed.clear()
        self.assertEqual(len(qmt_wrapper._g_timegate_skip_printed), 0)


if __name__ == '__main__':
    unittest.main()
