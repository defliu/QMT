# coding=utf-8
"""生产买入窗口测试。"""
from adapters import qmt_wrapper as qmt


def test_buy_window_boundaries():
    assert not qmt._is_buy_window('0959')
    assert qmt._is_buy_window('1000')
    assert qmt._is_buy_window('1005')
    assert qmt._is_buy_window('1010')
    assert not qmt._is_buy_window('1011')


def test_buy_window_constants():
    assert qmt.BUY_WINDOW_START == '1000'
    assert qmt.BUY_WINDOW_END == '1010'
    assert qmt.BUY_WINDOW_LABEL == '10:00-10:10'


def test_tdx_pool_path_unchanged():
    assert qmt.POOL_PATH.replace('\\', '/') == 'D:/QMT_POOL/selected.txt'
