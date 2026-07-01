# coding=utf-8
"""订单反查 _lookup_recent_order_id 专项测试

覆盖场景：
1. sell() 下单后 remark 为空但仍能反查到订单号
2. 多候选时优先返回 remark 匹配 strategy_name 的订单
3. buy() 下单后 passorder 返回 0 但订单簿有真实订单 → 返回真实订单号
4. buy() 反查不到订单 → 返回 None
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


# ============================================================
#  Mock helpers
# ============================================================

class FakeOrder:
    """模拟 QMT 委托簿条目"""
    def __init__(self, code, order_id, volume, direction='sell',
                 remark='', status=0, insert_time=None):
        parts = code.split('.')
        self.m_strInstrumentID = parts[0]
        self.m_strExchangeID = parts[1] if len(parts) > 1 else 'SZ'
        self.m_nOrderID = order_id
        self.m_nOrderVolume = volume
        self.m_nOrderStatus = status
        self.m_strOptName = direction
        self.m_strRemark = remark
        self.m_strInsertTime = insert_time or '14:30:00'


class FakeContext:
    def get_full_tick(self, codes):
        return {}
    def get_stock_name(self, code):
        return code
    def get_current_time(self):
        from datetime import datetime
        return datetime(2026, 6, 29, 14, 30, 0)
    def get_tick_timetag(self):
        from datetime import datetime
        return int(datetime(2026, 6, 29, 14, 30, 0).timestamp() * 1000)


# ============================================================
#  Tests
# ============================================================

class TestLookupRemarkRelaxed:
    """TASK-2: remark 空/不含策略名时仍应反查到订单"""

    def test_empty_remark_still_matches(self):
        """remark 为空但 code/vol/dir/time/status 全部匹配 → 应返回订单号"""
        import adapters.qmt_wrapper as qmt

        old_safemode = qmt.SAFEMODE_ENABLED
        qmt.SAFEMODE_ENABLED = False
        try:
            ctx = FakeContext()
            trader = qmt.Trader(ctx, '67014907', 'STOCK', qmt.STRATEGY_NAME)

            now = time.time()
            order = FakeOrder('000001.SZ', 99999, 500, direction='卖出',
                              remark='', insert_time='14:30:00')

            old_func = getattr(qmt, 'get_trade_detail_data', None)
            qmt.get_trade_detail_data = lambda *a, **kw: [order]
            try:
                result = trader._lookup_recent_order_id('000001.SZ', 500, 'sell', now)
                assert result == 99999, "remark 为空时也应返回匹配的订单号，实际: %s" % result
            finally:
                if old_func is not None:
                    qmt.get_trade_detail_data = old_func
                else:
                    del qmt.get_trade_detail_data
        finally:
            qmt.SAFEMODE_ENABLED = old_safemode

    def test_remark_without_strategy_name_still_matches(self):
        """remark 不含策略名但其他条件全匹配 → 应返回订单号"""
        import adapters.qmt_wrapper as qmt

        old_safemode = qmt.SAFEMODE_ENABLED
        qmt.SAFEMODE_ENABLED = False
        try:
            ctx = FakeContext()
            trader = qmt.Trader(ctx, '67014907', 'STOCK', qmt.STRATEGY_NAME)

            now = time.time()
            order = FakeOrder('000001.SZ', 88888, 500, direction='卖出',
                              remark='其他策略|备注', insert_time='14:30:00')

            old_func = getattr(qmt, 'get_trade_detail_data', None)
            qmt.get_trade_detail_data = lambda *a, **kw: [order]
            try:
                result = trader._lookup_recent_order_id('000001.SZ', 500, 'sell', now)
                assert result == 88888, "remark 不含策略名时也应返回匹配的订单号，实际: %s" % result
            finally:
                if old_func is not None:
                    qmt.get_trade_detail_data = old_func
                else:
                    del qmt.get_trade_detail_data
        finally:
            qmt.SAFEMODE_ENABLED = old_safemode


class TestLookupRemarkPriority:
    """TASK-2: 多候选时 remark 匹配策略名的订单优先"""

    def test_prioritize_remark_match(self):
        """两个候选，一个 remark 含策略名、一个不含 → 返回 remark 匹配的"""
        import adapters.qmt_wrapper as qmt

        old_safemode = qmt.SAFEMODE_ENABLED
        qmt.SAFEMODE_ENABLED = False
        try:
            ctx = FakeContext()
            strategy_name = qmt.STRATEGY_NAME
            trader = qmt.Trader(ctx, '67014907', 'STOCK', strategy_name)

            now = time.time()
            order_no_remark = FakeOrder('000001.SZ', 11111, 500, direction='卖出',
                                         remark='', insert_time='14:30:00')
            order_with_remark = FakeOrder('000001.SZ', 22222, 500, direction='卖出',
                                           remark='%s|测试' % strategy_name,
                                           insert_time='14:29:50')

            old_func = getattr(qmt, 'get_trade_detail_data', None)
            qmt.get_trade_detail_data = lambda *a, **kw: [order_no_remark, order_with_remark]
            try:
                result = trader._lookup_recent_order_id('000001.SZ', 500, 'sell', now)
                assert result == 22222, "应优先返回 remark 匹配策略名的订单 22222，实际: %s" % result
            finally:
                if old_func is not None:
                    qmt.get_trade_detail_data = old_func
                else:
                    del qmt.get_trade_detail_data
        finally:
            qmt.SAFEMODE_ENABLED = old_safemode

    def test_single_candidate_without_remark_still_returned(self):
        """唯一候选 remark 不含策略名 → 仍应返回该订单"""
        import adapters.qmt_wrapper as qmt

        old_safemode = qmt.SAFEMODE_ENABLED
        qmt.SAFEMODE_ENABLED = False
        try:
            ctx = FakeContext()
            trader = qmt.Trader(ctx, '67014907', 'STOCK', qmt.STRATEGY_NAME)

            now = time.time()
            order = FakeOrder('000001.SZ', 33333, 500, direction='卖出',
                              remark='unrelated', insert_time='14:30:00')

            old_func = getattr(qmt, 'get_trade_detail_data', None)
            qmt.get_trade_detail_data = lambda *a, **kw: [order]
            try:
                result = trader._lookup_recent_order_id('000001.SZ', 500, 'sell', now)
                assert result == 33333, "唯一候选应被返回，实际: %s" % result
            finally:
                if old_func is not None:
                    qmt.get_trade_detail_data = old_func
                else:
                    del qmt.get_trade_detail_data
        finally:
            qmt.SAFEMODE_ENABLED = old_safemode


class TestBuyOrderLookup:
    """TASK-3: buy() 接入订单反查"""

    def test_buy_passorder_zero_but_real_order_exists(self):
        """passorder 返回 0，但订单簿有真实买入订单 → 应返回真实订单号"""
        import adapters.qmt_wrapper as qmt

        old_safemode = qmt.SAFEMODE_ENABLED
        qmt.SAFEMODE_ENABLED = False
        try:
            ctx = FakeContext()
            trader = qmt.Trader(ctx, '67014907', 'STOCK', qmt.STRATEGY_NAME)

            order = FakeOrder('600110.SH', 55555, 300, direction='买入',
                              remark=qmt.STRATEGY_NAME, insert_time='14:30:00')

            old_func = getattr(qmt, 'get_trade_detail_data', None)
            qmt.get_trade_detail_data = lambda *a, **kw: [order]
            try:
                result = trader.buy('600110.SH', 300, remark='test')
                assert result == 55555, "应返回真实订单号 55555，而非 passorder 返回的 0，实际: %s" % result
            finally:
                if old_func is not None:
                    qmt.get_trade_detail_data = old_func
                else:
                    del qmt.get_trade_detail_data
        finally:
            qmt.SAFEMODE_ENABLED = old_safemode

    def test_buy_no_order_found_returns_none(self):
        """买后反查不到订单 → 应返回 None"""
        import adapters.qmt_wrapper as qmt

        old_safemode = qmt.SAFEMODE_ENABLED
        qmt.SAFEMODE_ENABLED = False
        try:
            ctx = FakeContext()
            trader = qmt.Trader(ctx, '67014907', 'STOCK', qmt.STRATEGY_NAME)

            old_func = getattr(qmt, 'get_trade_detail_data', None)
            qmt.get_trade_detail_data = lambda *a, **kw: []
            try:
                result = trader.buy('600110.SH', 300, remark='test')
                assert result is None, "反查不到订单时应返回 None，实际: %s" % result
            finally:
                if old_func is not None:
                    qmt.get_trade_detail_data = old_func
                else:
                    del qmt.get_trade_detail_data
        finally:
            qmt.SAFEMODE_ENABLED = old_safemode

    def test_buy_safemode_still_returns_safemode_prefix(self):
        """SAFEMODE 下 buy 仍返回 safemode_ 前缀，不进入反查"""
        import adapters.qmt_wrapper as qmt

        old_safemode = qmt.SAFEMODE_ENABLED
        qmt.SAFEMODE_ENABLED = True
        try:
            ctx = FakeContext()
            trader = qmt.Trader(ctx, '67014907', 'STOCK', 'Test')
            result = trader.buy('000001.SZ', 300, remark='test')
            assert result is not None and result.startswith('safemode_'), \
                "SAFEMODE 下应返回 safemode_ 前缀，实际: %s" % result
        finally:
            qmt.SAFEMODE_ENABLED = old_safemode


class TestLookupRejectStatus:
    """验证废单/失败状态被正确排除"""

    def test_rejected_status_not_returned(self):
        """status=54(废单) 的订单不应被返回"""
        import adapters.qmt_wrapper as qmt

        old_safemode = qmt.SAFEMODE_ENABLED
        qmt.SAFEMODE_ENABLED = False
        try:
            ctx = FakeContext()
            trader = qmt.Trader(ctx, '67014907', 'STOCK', 'Test')

            now = time.time()
            rejected = FakeOrder('000001.SZ', 11111, 500, direction='卖出',
                                 remark='', status=54, insert_time='14:30:00')

            old_func = getattr(qmt, 'get_trade_detail_data', None)
            qmt.get_trade_detail_data = lambda *a, **kw: [rejected]
            try:
                result = trader._lookup_recent_order_id('000001.SZ', 500, 'sell', now)
                assert result is None, "废单(status=54)不应被返回，实际: %s" % result
            finally:
                if old_func is not None:
                    qmt.get_trade_detail_data = old_func
                else:
                    del qmt.get_trade_detail_data
        finally:
            qmt.SAFEMODE_ENABLED = old_safemode


class TestLookupDirectionMismatch:
    """验证方向不匹配被排除"""

    def test_buy_order_not_returned_for_sell_lookup(self):
        """查找卖出订单时，买入方向的订单不应被返回"""
        import adapters.qmt_wrapper as qmt

        old_safemode = qmt.SAFEMODE_ENABLED
        qmt.SAFEMODE_ENABLED = False
        try:
            ctx = FakeContext()
            trader = qmt.Trader(ctx, '67014907', 'STOCK', 'Test')

            now = time.time()
            buy_order = FakeOrder('000001.SZ', 77777, 500, direction='买入',
                                  remark='', insert_time='14:30:00')

            old_func = getattr(qmt, 'get_trade_detail_data', None)
            qmt.get_trade_detail_data = lambda *a, **kw: [buy_order]
            try:
                result = trader._lookup_recent_order_id('000001.SZ', 500, 'sell', now)
                assert result is None, "买入方向订单不应在卖出反查中返回，实际: %s" % result
            finally:
                if old_func is not None:
                    qmt.get_trade_detail_data = old_func
                else:
                    del qmt.get_trade_detail_data
        finally:
            qmt.SAFEMODE_ENABLED = old_safemode


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
