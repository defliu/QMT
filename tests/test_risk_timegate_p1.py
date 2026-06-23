# coding=gbk
"""P1 基础设施：SellDecision.triggered_sublayer + 时段辅助函数"""
import unittest
import time
try:
    from core.risk_manager import SellDecision
except ImportError:
    import sys
    sys.path.insert(0, 'D:/QMT_STRATEGIES')
    from core.risk_manager import SellDecision
from adapters import qmt_wrapper


class TestSellDecisionSublayer(unittest.TestCase):

    def test_clear_no_sublayer_default(self):
        d = SellDecision.clear('000001', '硬止损', '底线层', ['累计亏损'])
        self.assertIsNone(d.triggered_sublayer)

    def test_clear_with_trailing_sublayer(self):
        d = SellDecision.clear('000001', '移动止盈', '清仓层', ['移动止盈'], sublayer='trailing')
        self.assertEqual(d.triggered_sublayer, 'trailing')

    def test_hold_no_sublayer(self):
        d = SellDecision.hold()
        self.assertIsNone(d.triggered_sublayer)

    def test_reduce_no_sublayer(self):
        d = SellDecision.reduce('000001', 0.3, '预警信号', '预警层', ['B1'])
        self.assertIsNone(d.triggered_sublayer)


class TestGetAllowedLayers(unittest.TestCase):

    def test_pre_open(self):
        r = qmt_wrapper._get_allowed_sell_layers('0900')
        self.assertEqual(r['layers'], set())

    def test_open_impact(self):
        r = qmt_wrapper._get_allowed_sell_layers('0930')
        self.assertEqual(r['layers'], {'底线层'})

    def test_early_buffer(self):
        r = qmt_wrapper._get_allowed_sell_layers('0937')
        self.assertIn('清仓层', r['layers'])
        self.assertIn('trailing', r['exclude_sublayers'])

    def test_mid_session(self):
        r = qmt_wrapper._get_allowed_sell_layers('0945')
        for layer in ('底线层', '清仓层', '预警层', '确认层', 'warning_add'):
            self.assertIn(layer, r['layers'])
        self.assertEqual(r['exclude_sublayers'], set())

    def test_tail_session(self):
        r = qmt_wrapper._get_allowed_sell_layers('1445')
        for layer in ('底线层', '清仓层', '预警层', '确认层', 'warning_add'):
            self.assertIn(layer, r['layers'])

    def test_close_cancel(self):
        r = qmt_wrapper._get_allowed_sell_layers('1458')
        self.assertEqual(r['layers'], set())

    def test_exclude_sublayers_structure(self):
        """所有时段返回值都包含 layers 和 exclude_sublayers 两个 key"""
        for t in ('0800', '0925', '0930', '0937', '0945', '1200', '1445', '1458', '1600'):
            r = qmt_wrapper._get_allowed_sell_layers(t)
            self.assertIn('layers', r)
            self.assertIn('exclude_sublayers', r)


class TestCoolingOff(unittest.TestCase):

    def test_cooling_off_active(self):
        """mock 启动时间在 30 秒前 → cooling-off 应返回 True"""
        saved = qmt_wrapper._g_strategy_start_ts
        qmt_wrapper._g_strategy_start_ts = time.time() - 30
        try:
            self.assertTrue(qmt_wrapper._is_in_cooling_off())
        finally:
            qmt_wrapper._g_strategy_start_ts = saved

    def test_cooling_off_expired(self):
        """mock 启动时间在 120 秒前 → cooling-off 应返回 False"""
        saved = qmt_wrapper._g_strategy_start_ts
        qmt_wrapper._g_strategy_start_ts = time.time() - 120
        try:
            self.assertFalse(qmt_wrapper._is_in_cooling_off())
        finally:
            qmt_wrapper._g_strategy_start_ts = saved

    def test_cooling_off_none(self):
        """_g_strategy_start_ts 为 None → 安全返回 False"""
        saved = qmt_wrapper._g_strategy_start_ts
        qmt_wrapper._g_strategy_start_ts = None
        try:
            self.assertFalse(qmt_wrapper._is_in_cooling_off())
        finally:
            qmt_wrapper._g_strategy_start_ts = saved


if __name__ == '__main__':
    unittest.main()
