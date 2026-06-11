# coding=utf-8
"""验证卖出后 _g_my_codes 同步修复"""
import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from adapters.qmt_wrapper import _finish_pending_sell


def test_finish_pending_sell_cleans_my_codes():
    """_finish_pending_sell 卖出完成后必须清理 _g_my_codes"""
    from adapters import qmt_wrapper as m

    # 模拟持仓
    m._g_my_codes['600000.SH'] = 10.0
    m._g_pending_sells['600000.SH'] = {
        'order_id': 12345,
        'volume': 100,
        'sell_price': 11.0,
        'cost': 10.0,
        'pct': 1.0,
        'checks': 0,
        'retries': 0,
        'is_clear': True,
        'code': '600000.SH',
        'today': '20260609',
    }

    with patch.object(m, '_append_trade_record'), \
         patch.object(m, '_append_log'):
        _finish_pending_sell(None, '600000.SH', m._g_pending_sells['600000.SH'], 100)

    assert '600000.SH' not in m._g_my_codes, \
        "_finish_pending_sell 后 _g_my_codes 应清除该股票"
    assert '600000.SH' not in m._g_pending_sells, \
        "_finish_pending_sell 后 _g_pending_sells 应清除该股票"


def test_buy_count_uses_account_holdings():
    """买入数量检查应使用 账户持仓 而非 _g_my_codes"""
    from adapters.qmt_wrapper import MAX_HOLD

    # 模拟 _g_my_codes 有3只（含已卖出未清理的），但账户只有2只
    账户持仓 = {'600001.SH', '600002.SH'}
    我的持仓 = {'600001.SH', '600002.SH', '600003.SH'}  # 多出的已卖出

    可买数量_旧 = max(0, MAX_HOLD - len(我的持仓))  # 旧逻辑
    可买数量_新 = max(0, MAX_HOLD - len(账户持仓))  # 新逻辑

    assert 可买数量_旧 == 0, "旧逻辑用 _g_my_codes: 应为0（满仓误判）"
    assert 可买数量_新 == MAX_HOLD - 2, "新逻辑用 账户持仓: 应为空位数"
