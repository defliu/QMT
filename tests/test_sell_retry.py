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


class _FakeOrderForLookup:
    """模拟 QMT 委托簿条目，供 _lookup_recent_order_id 反查"""
    def __init__(self, code, order_id, volume, direction='sell'):
        parts = code.split('.')
        self.m_strInstrumentID = parts[0]
        self.m_strExchangeID = parts[1] if len(parts) > 1 else 'SZ'
        self.m_nOrderID = order_id
        self.m_nOrderVolume = volume
        self.m_nOrderStatus = 0
        self.m_strOptName = direction
        self.m_strRemark = ''
        self.m_strInsertTime = '14:30:00'


class TestTraderSellMarketMode:
    """验证 Trader.sell use_market 参数"""

    def test_sell_with_use_market_true_skips_ask1(self, mock_context):
        """use_market=True 时应跳过获取卖一价，直接市价"""
        import adapters.qmt_wrapper as qmt

        old_safemode = qmt.SAFEMODE_ENABLED
        qmt.SAFEMODE_ENABLED = False
        try:
            trader = qmt.Trader(mock_context, '67014907', 'STOCK', 'Test')
            passorder_calls = []

            def fake_passorder(*args, **kwargs):
                passorder_calls.append((args, kwargs))
                return 'fake_id'

            trader._passorder = fake_passorder
            fake_order = _FakeOrderForLookup('000001.SZ', 'fake_id', 500)
            old_gtd = getattr(qmt, 'get_trade_detail_data', None)
            qmt.get_trade_detail_data = lambda *a, **kw: [fake_order]
            try:
                result = trader.sell('000001.SZ', 500, remark='test', use_market=True)
                assert result == 'fake_id'
                assert len(passorder_calls) == 1
                _, kwargs = passorder_calls[0]
                assert kwargs.get('price_type') == 5
            finally:
                if old_gtd is not None:
                    qmt.get_trade_detail_data = old_gtd
                else:
                    del qmt.get_trade_detail_data
        finally:
            qmt.SAFEMODE_ENABLED = old_safemode

    def test_sell_with_use_market_false_uses_limit(self, mock_context):
        """use_market=False(默认) 应使用限价卖一价"""
        import adapters.qmt_wrapper as qmt

        old_safemode = qmt.SAFEMODE_ENABLED
        qmt.SAFEMODE_ENABLED = False
        try:
            trader = qmt.Trader(mock_context, '67014907', 'STOCK', 'Test')
            trader._get_ask1_price = lambda code: 10.5

            passorder_calls = []

            def fake_passorder(*args, **kwargs):
                passorder_calls.append((args, kwargs))
                return 'fake_id'

            trader._passorder = fake_passorder
            fake_order = _FakeOrderForLookup('000001.SZ', 'fake_id', 500)
            old_gtd = getattr(qmt, 'get_trade_detail_data', None)
            qmt.get_trade_detail_data = lambda *a, **kw: [fake_order]
            try:
                result = trader.sell('000001.SZ', 500, remark='test', use_market=False)
                assert result == 'fake_id'
                assert len(passorder_calls) == 1
                _, kwargs = passorder_calls[0]
                assert kwargs.get('price_type') == 0
            finally:
                if old_gtd is not None:
                    qmt.get_trade_detail_data = old_gtd
                else:
                    del qmt.get_trade_detail_data
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


class TestIsStarMarketStock:
    """验证 _is_star_market_stock 兼容多种代码格式"""

    def test_sh688396(self):
        import adapters.qmt_wrapper as qmt
        assert qmt._is_star_market_stock('SH688396') is True

    def test_sh689009(self):
        import adapters.qmt_wrapper as qmt
        assert qmt._is_star_market_stock('SH689009') is True

    def test_688396_sh(self):
        import adapters.qmt_wrapper as qmt
        assert qmt._is_star_market_stock('688396.SH') is True

    def test_688396(self):
        import adapters.qmt_wrapper as qmt
        assert qmt._is_star_market_stock('688396') is True

    def test_regular_stock(self):
        import adapters.qmt_wrapper as qmt
        assert qmt._is_star_market_stock('600641.SH') is False

    def test_sz_code(self):
        import adapters.qmt_wrapper as qmt
        assert qmt._is_star_market_stock('000001.SZ') is False


class TestNormalizeSellVolumeForBoard:
    """验证 _normalize_sell_volume_for_board 科创板/普通股票最低委托量规则"""

    def test_star_market_desired_100_available_300(self):
        """科创板 desired=100, available=300 → 修正为 200"""
        import adapters.qmt_wrapper as qmt
        assert qmt._normalize_sell_volume_for_board('688396.SH', 100, 300, False) == 200

    def test_star_market_desired_300_available_300(self):
        """科创板 desired=300, available=300 → 保持 300"""
        import adapters.qmt_wrapper as qmt
        assert qmt._normalize_sell_volume_for_board('688396.SH', 300, 300, False) == 300

    def test_star_market_available_100(self):
        """科创板 available=100 (不足200) → 一次性卖剩余 100"""
        import adapters.qmt_wrapper as qmt
        assert qmt._normalize_sell_volume_for_board('688396.SH', 100, 100, False) == 100

    def test_star_market_clear(self):
        """科创板 is_clear=True → 卖全部 available"""
        import adapters.qmt_wrapper as qmt
        assert qmt._normalize_sell_volume_for_board('688396.SH', 0, 300, True) == 300

    def test_star_market_available_0(self):
        """科创板 available=0 → 0"""
        import adapters.qmt_wrapper as qmt
        assert qmt._normalize_sell_volume_for_board('688396.SH', 100, 0, False) == 0

    def test_star_market_689_prefix(self):
        """689 开头也按科创板处理"""
        import adapters.qmt_wrapper as qmt
        assert qmt._normalize_sell_volume_for_board('689009.SH', 100, 300, False) == 200

    def test_regular_stock_100_available_600(self):
        """普通股票 desired=100, available=600 → 保持 100"""
        import adapters.qmt_wrapper as qmt
        assert qmt._normalize_sell_volume_for_board('600641.SH', 100, 600, False) == 100

    def test_regular_stock_desired_150_available_600(self):
        """普通股票 desired=150 → 向下取整到 100"""
        import adapters.qmt_wrapper as qmt
        assert qmt._normalize_sell_volume_for_board('600641.SH', 150, 600, False) == 100

    def test_regular_stock_available_50(self):
        """普通股票 available=50 (<100) → 一次性卖 50"""
        import adapters.qmt_wrapper as qmt
        assert qmt._normalize_sell_volume_for_board('600641.SH', 50, 50, False) == 50

    def test_regular_stock_available_50_desired_100(self):
        """普通股票 desired=100, available=50 → 0 (available不足且不等于desired)"""
        import adapters.qmt_wrapper as qmt
        assert qmt._normalize_sell_volume_for_board('600641.SH', 100, 50, False) == 0

    def test_returns_int(self):
        """返回值必须是 int"""
        import adapters.qmt_wrapper as qmt
        result = qmt._normalize_sell_volume_for_board('688396.SH', 100, 300, False)
        assert isinstance(result, int)

    def test_never_exceeds_available(self):
        """返回值不能超过 available_vol"""
        import adapters.qmt_wrapper as qmt
        assert qmt._normalize_sell_volume_for_board('688396.SH', 500, 300, False) <= 300

    def test_sh688396_format_desired_100_available_300(self):
        """SH688396 格式 desired=100, available=300 → 修正为 200"""
        import adapters.qmt_wrapper as qmt
        assert qmt._normalize_sell_volume_for_board('SH688396', 100, 300, False) == 200

    def test_sh688396_format_available_100(self):
        """SH688396 格式 available=100 (不足200) → 一次性卖剩余 100"""
        import adapters.qmt_wrapper as qmt
        assert qmt._normalize_sell_volume_for_board('SH688396', 100, 100, False) == 100

    def test_sh689009_format(self):
        """SH689009 格式也按科创板处理"""
        import adapters.qmt_wrapper as qmt
        assert qmt._normalize_sell_volume_for_board('SH689009', 100, 300, False) == 200


class TestCheckAndExecuteSellStarMarket:
    """验证 _check_and_execute_sell 中科创板卖出数量修正"""

    def test_star_market_raw_100_becomes_200(self):
        """科创板 raw decision shares=100, position can_use=300 → 实际 sell 200"""
        import adapters.qmt_wrapper as qmt
        from core.risk_manager import Action, SellDecision, SellStrategyEngine, SellPositionState

        fake = FakeTrader()
        fake.set_position('688396.SH', 300, 300, 10.0)
        fake._fail_count = 0

        qmt._g_trader = fake
        qmt._g_pending_sells = {}
        qmt._g_my_codes = {'688396.SH': 10.0}
        qmt._g_all_data = {'688396.SH': _make_test_df(10.0)}
        qmt._g_failed_printed = set()
        qmt._g_sell_skip_printed = set()
        qmt._g_price_skip_printed = set()
        qmt._g_timegate_skip_printed = set()
        qmt._g_last_sell_fingerprint = ''

        mock_dec = SellDecision(
            action=Action.REDUCE,
            triggered_layer='L1',
            triggered_sublayer=None,
            reason='test',
            sell_pct=0.3,
        )
        raw_decisions = [('688396.SH', mock_dec, 100)]

        engine = SellStrategyEngine('test', '67014907', 'D:/QMT_POOL/test_state.json')
        engine._states['688396.SH'] = SellPositionState(
            code='688396.SH', cost_price=10.0, current_shares=300, original_shares=300,
        )
        old_evaluate = engine.evaluate
        engine.evaluate = lambda *a, **kw: raw_decisions
        qmt._g_sell_engine = engine
        try:
            sells = qmt._check_and_execute_sell(None, '20260629')
            assert len(fake.sell_calls) == 1
            _, vol, _, _ = fake.sell_calls[0]
            assert vol == 200, "科创板 shares=100 available=300 应修正为 200，实际: %d" % vol
        finally:
            engine.evaluate = old_evaluate
            qmt._g_sell_engine = None


class TestRetryPendingSellStarMarket:
    """验证 _retry_pending_sell 中科创板卖出数量修正"""

    def test_star_market_retry_volume_100_becomes_200(self):
        """科创板 info volume=100, can_use=300 → 重试 sell volume=200"""
        import adapters.qmt_wrapper as qmt

        fake = FakeTrader()
        fake.set_position('688396.SH', 300, 300, 10.0)
        fake._fail_count = 0

        qmt._g_trader = fake
        qmt._g_pending_sells = {}
        qmt._g_my_codes = {'688396.SH': 10.0}
        qmt._g_all_data = {'688396.SH': _make_test_df(10.0)}

        info = {
            'order_id': 'old_123',
            'volume': 100,
            'sell_price': 10.5,
            'cost': 10.0,
            'pct': 0.3,
            'checks': 0,
            'retries': 0,
            'is_clear': False,
            'code': '688396.SH',
            'today': '20260629',
        }
        qmt._g_pending_sells['688396.SH'] = dict(info)

        qmt._retry_pending_sell('688396.SH', info, None)

        assert len(fake.sell_calls) == 1
        _, vol, _, _ = fake.sell_calls[0]
        assert vol == 200, "科创板 volume=100 available=300 应修正为 200，实际: %d" % vol


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
