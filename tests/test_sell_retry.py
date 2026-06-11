# coding=utf-8
"""卖出撤单重试逻辑专项测试"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


class FakeTrader:
    """Mock Trader for testing sell retry logic."""
    def __init__(self):
        self.sell_calls = []
        self.cancel_calls = []
        self._positions = {}
        self._fail_count = 0

    def sell(self, code, volume, remark='', use_market=False):
        self.sell_calls.append((code, volume, remark, use_market))
        self._fail_count += 1
        if self._fail_count <= 2:
            return None
        return 'order_%s_%d' % (code, len(self.sell_calls))

    def cancel_order(self, order_id, code):
        self.cancel_calls.append((order_id, code))
        return True

    def get_position(self, code):
        return self._positions.get(code)

    def set_position(self, code, volume, can_use, cost):
        self._positions[code] = {
            'volume': volume, 'can_use': can_use, 'cost': cost, 'profit': 0
        }


class TestSellRetryState:
    """验证 _retry_pending_sell 状态维护"""

    def test_retry_increments_retries_on_success(self):
        """成功重试时 retries 应递增"""
        import adapters.qmt_wrapper as qmt

        fake = FakeTrader()
        fake.set_position('000001.SZ', 1000, 1000, 10.0)
        # 设置 _fail_count=1 后第三次调用会成功
        fake._fail_count = 0

        qmt._g_trader = fake
        qmt._g_pending_sells = {}
        qmt._g_my_codes = {'000001.SZ': 10.5}
        qmt._g_all_data = {}
        qmt._g_all_data['000001.SZ'] = _make_test_df(10.5)

        info = {
            'order_id': 'old_123',
            'volume': 500,
            'sell_price': 10.5,
            'cost': 10.0,
            'pct': 0.3,
            'checks': 1,
            'retries': 0,
            'is_clear': False,
            'code': '000001.SZ',
            'today': '20260610',
        }
        qmt._g_pending_sells['000001.SZ'] = dict(info)

        qmt._retry_pending_sell('000001.SZ', info, None)

        updated = qmt._g_pending_sells.get('000001.SZ')
        assert updated is not None, "retry后应保留在 _g_pending_sells 中"
        assert updated['retries'] == 1, "retries 应从0递增到1"

    def test_retry_preserves_state_on_sell_failure(self):
        """sell失败时也应保留状态并递增 retries"""
        import adapters.qmt_wrapper as qmt

        fake = FakeTrader()
        fake.set_position('000001.SZ', 1000, 1000, 10.0)

        qmt._g_trader = fake
        qmt._g_pending_sells = {}
        qmt._g_my_codes = {'000001.SZ': 10.5}
        qmt._g_all_data = {}
        qmt._g_all_data['000001.SZ'] = _make_test_df(10.5)

        info = {
            'order_id': 'old_123',
            'volume': 500,
            'sell_price': 10.5,
            'cost': 10.0,
            'pct': 0.3,
            'checks': 0,
            'retries': 1,
            'is_clear': False,
            'code': '000001.SZ',
            'today': '20260610',
        }
        qmt._g_pending_sells['000001.SZ'] = dict(info)

        qmt._retry_pending_sell('000001.SZ', info, None)

        updated = qmt._g_pending_sells.get('000001.SZ')
        assert updated is not None, "sell失败后也应保留在 _g_pending_sells 中"
        assert updated['retries'] == 2, "retries 应从1递增到2"

    def test_retry_uses_market_order_on_second_retry(self):
        """第二次重试(retries>=1)应使用市价单"""
        import adapters.qmt_wrapper as qmt

        fake = FakeTrader()
        fake.set_position('000001.SZ', 1000, 1000, 10.0)
        fake._fail_count = 0  # 直接成功

        qmt._g_trader = fake
        qmt._g_pending_sells = {}
        qmt._g_my_codes = {'000001.SZ': 10.5}
        qmt._g_all_data = {}
        qmt._g_all_data['000001.SZ'] = _make_test_df(10.5)

        info = {
            'order_id': 'old_123',
            'volume': 500,
            'sell_price': 10.5,
            'cost': 10.0,
            'pct': 0.3,
            'checks': 0,
            'retries': 1,
            'is_clear': False,
            'code': '000001.SZ',
            'today': '20260610',
        }
        qmt._g_pending_sells['000001.SZ'] = dict(info)

        qmt._retry_pending_sell('000001.SZ', info, None)

        assert len(fake.sell_calls) >= 1
        _, _, _, use_market = fake.sell_calls[-1]
        assert use_market is True, "retries>=1 时应使用市价单(use_market=True)"

    def test_retry_uses_limit_order_on_first_retry(self):
        """首次重试(retries=0)应使用限价单"""
        import adapters.qmt_wrapper as qmt

        fake = FakeTrader()
        fake.set_position('000001.SZ', 1000, 1000, 10.0)
        fake._fail_count = 0

        qmt._g_trader = fake
        qmt._g_pending_sells = {}
        qmt._g_my_codes = {'000001.SZ': 10.5}
        qmt._g_all_data = {}
        qmt._g_all_data['000001.SZ'] = _make_test_df(10.5)

        info = {
            'order_id': 'old_123',
            'volume': 500,
            'sell_price': 10.5,
            'cost': 10.0,
            'pct': 0.3,
            'checks': 0,
            'retries': 0,
            'is_clear': False,
            'code': '000001.SZ',
            'today': '20260610',
        }
        qmt._g_pending_sells['000001.SZ'] = dict(info)

        qmt._retry_pending_sell('000001.SZ', info, None)

        assert len(fake.sell_calls) >= 1
        _, _, _, use_market = fake.sell_calls[-1]
        assert use_market is False, "retries=0 时应使用限价单(use_market=False)"


class TestPendingSellRetryLimit:
    """验证 _check_pending_sells 中订单丢失时持续重试"""

    def test_order_not_found_always_retries(self, monkeypatch):
        """订单找不到但仍有持仓时应持续重试，不放弃"""
        import adapters.qmt_wrapper as qmt
        import builtins

        fake = FakeTrader()
        fake.set_position('000001.SZ', 1000, 1000, 10.0)
        qmt._g_trader = fake
        qmt._g_pending_sells = {
            '000001.SZ': {
                'order_id': 'lost_123',
                'volume': 500,
                'sell_price': 10.5,
                'cost': 10.0,
                'pct': 0.3,
                'checks': 3,
                'retries': 3,
                'is_clear': False,
                'code': '000001.SZ',
                'today': '20260610',
            }
        }
        qmt._g_my_codes = {'000001.SZ': 10.5}
        qmt._g_all_data = {}
        qmt._g_all_data['000001.SZ'] = _make_test_df(10.5)

        old_func = getattr(qmt, 'get_trade_detail_data', None)
        qmt.get_trade_detail_data = lambda *a, **kw: []
        try:
            qmt._check_pending_sells(None, '20260610')
            # 只要有持仓就应该继续重试，不清理
            assert '000001.SZ' in qmt._g_pending_sells, "有持仓时应保留pending继续重试"
        finally:
            if old_func is not None:
                qmt.get_trade_detail_data = old_func
            else:
                del qmt.get_trade_detail_data


class TestTraderSellMarketMode:
    """验证 Trader.sell use_market 参数"""

    def test_sell_with_use_market_true_skips_ask1(self, mock_context):
        """use_market=True 时应跳过获取卖一价，直接市价"""
        import adapters.qmt_wrapper as qmt

        # 临时关闭 SAFEMODE 以测试实际委托逻辑
        old_safemode = qmt.SAFEMODE_ENABLED
        qmt.SAFEMODE_ENABLED = False
        try:
            trader = qmt.Trader(mock_context, '67014907', 'STOCK', 'Test')
            passorder_calls = []

            def fake_passorder(*args, **kwargs):
                passorder_calls.append((args, kwargs))
                return 'fake_id'

            trader._passorder = fake_passorder

            result = trader.sell('000001.SZ', 500, remark='test', use_market=True)
            assert result == 'fake_id'
            assert len(passorder_calls) == 1
            # price_type=5 表示市价单
            _, kwargs = passorder_calls[0]
            assert kwargs.get('price_type') == 5
        finally:
            qmt.SAFEMODE_ENABLED = old_safemode

    def test_sell_with_use_market_false_uses_limit(self, mock_context):
        """use_market=False(默认) 应使用限价卖一价"""
        import adapters.qmt_wrapper as qmt

        old_safemode = qmt.SAFEMODE_ENABLED
        qmt.SAFEMODE_ENABLED = False
        try:
            trader = qmt.Trader(mock_context, '67014907', 'STOCK', 'Test')
            # Mock _get_ask1_price 返回有效卖一价，避免回退到市价单
            trader._get_ask1_price = lambda code: 10.5

            passorder_calls = []

            def fake_passorder(*args, **kwargs):
                passorder_calls.append((args, kwargs))
                return 'fake_id'

            trader._passorder = fake_passorder

            result = trader.sell('000001.SZ', 500, remark='test', use_market=False)
            assert result == 'fake_id'
            assert len(passorder_calls) == 1
            # price_type=0 表示限价单
            _, kwargs = passorder_calls[0]
            assert kwargs.get('price_type') == 0
        finally:
            qmt.SAFEMODE_ENABLED = old_safemode


def _make_test_df(price=10.5, days=60):
    """构造测试用K线DataFrame"""
    import numpy as np
    import pandas as pd
    closes = np.full(days, price, dtype=float)
    opens = np.full(days, price, dtype=float)
    highs = np.full(days, price * 1.01, dtype=float)
    lows = np.full(days, price * 0.99, dtype=float)
    volumes = np.full(days, 1000000.0, dtype=float)
    return pd.DataFrame({
        'open': opens, 'close': closes, 'high': highs,
        'low': lows, 'volume': volumes,
    })


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
