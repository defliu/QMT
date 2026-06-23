# coding=utf-8
"""单元测试: huang_main_uptrend_combo_selector"""
import sys
sys.path.insert(0, 'D:/QMT_STRATEGIES')

import unittest
import numpy as np
import pandas as pd

from huang_main_uptrend_combo.huang_main_uptrend_combo_selector import (
    tdx_ma, tdx_ema, tdx_ref, tdx_hhv, tdx_llv,
    tdx_cross, tdx_count, tdx_avedev,
    _calc_box_breakout_conditions,
    _calc_double_zhongjun_conditions,
    select_huang_main_uptrend_combo,
    DEFAULT_PARAMS,
)


class TestTdxMappingFunctions(unittest.TestCase):
    """A组: TDX 映射工具函数"""

    def test_tdx_ma_basic(self):
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = tdx_ma(s, 3)
        self.assertTrue(np.isnan(result.iloc[0]))
        self.assertTrue(np.isnan(result.iloc[1]))
        self.assertAlmostEqual(result.iloc[2], 2.0)
        self.assertAlmostEqual(result.iloc[3], 3.0)
        self.assertAlmostEqual(result.iloc[4], 4.0)

    def test_tdx_ema_basic(self):
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = tdx_ema(s, 3)
        alpha = 2.0 / (3 + 1)
        e0 = 1.0
        e1 = alpha * 2.0 + (1 - alpha) * e0
        e2 = alpha * 3.0 + (1 - alpha) * e1
        e3 = alpha * 4.0 + (1 - alpha) * e2
        e4 = alpha * 5.0 + (1 - alpha) * e3
        self.assertAlmostEqual(result.iloc[0], e0, places=10)
        self.assertAlmostEqual(result.iloc[1], e1, places=10)
        self.assertAlmostEqual(result.iloc[2], e2, places=10)
        self.assertAlmostEqual(result.iloc[3], e3, places=10)
        self.assertAlmostEqual(result.iloc[4], e4, places=10)

    def test_tdx_ref_basic(self):
        s = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0])
        r1 = tdx_ref(s, 1)
        r2 = tdx_ref(s, 2)
        self.assertTrue(np.isnan(r1.iloc[0]))
        self.assertAlmostEqual(r1.iloc[1], 10.0)
        self.assertAlmostEqual(r1.iloc[4], 40.0)
        self.assertTrue(np.isnan(r2.iloc[0]))
        self.assertTrue(np.isnan(r2.iloc[1]))
        self.assertAlmostEqual(r2.iloc[2], 10.0)

    def test_tdx_hhv_basic(self):
        s = pd.Series([1.0, 3.0, 2.0, 5.0, 4.0])
        result = tdx_hhv(s, 3)
        self.assertTrue(np.isnan(result.iloc[0]))
        self.assertTrue(np.isnan(result.iloc[1]))
        self.assertAlmostEqual(result.iloc[2], 3.0)
        self.assertAlmostEqual(result.iloc[3], 5.0)
        self.assertAlmostEqual(result.iloc[4], 5.0)

    def test_tdx_llv_basic(self):
        s = pd.Series([5.0, 3.0, 4.0, 1.0, 2.0])
        result = tdx_llv(s, 3)
        self.assertTrue(np.isnan(result.iloc[0]))
        self.assertTrue(np.isnan(result.iloc[1]))
        self.assertAlmostEqual(result.iloc[2], 3.0)
        self.assertAlmostEqual(result.iloc[3], 1.0)
        self.assertAlmostEqual(result.iloc[4], 1.0)

    def test_tdx_cross_basic(self):
        a = pd.Series([1.0, 2.0, 3.0, 2.0, 4.0])
        b = pd.Series([2.0, 2.0, 2.0, 3.0, 3.0])
        result = tdx_cross(a, b)
        self.assertFalse(result.iloc[0])
        self.assertFalse(result.iloc[1])
        self.assertTrue(result.iloc[2])
        self.assertFalse(result.iloc[3])
        self.assertTrue(result.iloc[4])

    def test_tdx_count_basic(self):
        cond = pd.Series([True, False, True, True, False, True, True, True])
        result = tdx_count(cond, 5)
        self.assertAlmostEqual(result.iloc[4], 3.0)
        self.assertAlmostEqual(result.iloc[5], 3.0)
        self.assertAlmostEqual(result.iloc[6], 4.0)
        self.assertAlmostEqual(result.iloc[7], 4.0)

    def test_tdx_avedev_basic(self):
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = tdx_avedev(s, 3)
        self.assertTrue(np.isnan(result.iloc[0]))
        self.assertTrue(np.isnan(result.iloc[1]))
        mean234 = (2.0 + 3.0 + 4.0) / 3.0
        expected = (abs(2.0 - mean234) + abs(3.0 - mean234) + abs(4.0 - mean234)) / 3.0
        self.assertAlmostEqual(result.iloc[3], expected, places=10)


def _make_box_breakout_data(n=100):
    """构造满足箱体突破全部5个子条件的数据.
    前N-1天: 窄幅震荡(振幅<20%), 均线黏连, 量平稳
    最后一天: close=HHV(high,60)(high=close), 放量, 涨幅>5%
    """
    dates = pd.date_range('2026-01-01', periods=n)
    close_list = []
    high_list = []
    low_list = []
    vol_list = []
    base_price = 10.0
    for i in range(n):
        if i < n - 1:
            c = base_price + (i % 5) * 0.1
            h = c + 0.2
            l = c - 0.2
            v = 1000.0
        else:
            prev_c = base_price + ((n - 2) % 5) * 0.1
            c = prev_c * 1.08
            h = c
            l = c - 0.2
            v = 10000.0
        close_list.append(c)
        high_list.append(h)
        low_list.append(l)
        vol_list.append(v)
    df = pd.DataFrame({
        'open': close_list, 'high': high_list, 'low': low_list,
        'close': close_list, 'volume': vol_list,
    }, index=dates)
    return df


def _make_zhongjun_data(n=150):
    """构造满足双中军全部8个子条件的数据.
    前N-1天: 线性上涨
    最后一天: 大幅跳涨, 使MA5角度>30, CCI>100且递增, 突破近期高点但<1.08倍
    """
    dates = pd.date_range('2026-01-01', periods=n)
    close_list = []
    high_list = []
    low_list = []
    vol_list = []
    for i in range(n):
        if i < n - 1:
            c = 10.0 + i * 0.3
        else:
            c = 10.0 + (n - 1) * 0.3 + 3.0
        h = c * 1.02
        l = c * 0.98
        v = 1000.0 + i * 50.0
        close_list.append(c)
        high_list.append(h)
        low_list.append(l)
        vol_list.append(v)
    df = pd.DataFrame({
        'open': close_list, 'high': high_list, 'low': low_list,
        'close': close_list, 'volume': vol_list,
    }, index=dates)
    return df


def _make_index_df(n, start=3000.0, step=2.0):
    dates = pd.date_range('2026-01-01', periods=n)
    close = [start + i * step for i in range(n)]
    return pd.DataFrame({'close': close}, index=dates)


class TestBoxBreakoutConditions(unittest.TestCase):
    """B组: 箱体突破子条件"""

    def test_box_breakout_positive_case(self):
        df = _make_box_breakout_data(100)
        p = dict(DEFAULT_PARAMS)
        result = _calc_box_breakout_conditions(df, p)
        last = result.iloc[-1]
        self.assertTrue(last['box_箱体振幅_ok'])
        self.assertTrue(last['box_均线黏连_ok'])
        self.assertTrue(last['box_放量_ok'])
        self.assertTrue(last['box_突破_ok'])
        self.assertTrue(last['box_涨幅_ok'])
        self.assertTrue(last['box_breakout_XG'])

    def test_box_breakout_negative_case(self):
        n = 100
        dates = pd.date_range('2026-01-01', periods=n)
        df = pd.DataFrame({
            'open': [10.0] * n,
            'high': [10.0] * n,
            'low': [10.0] * n,
            'close': [10.0] * n,
            'volume': [100.0] * n,
        }, index=dates)
        p = dict(DEFAULT_PARAMS)
        result = _calc_box_breakout_conditions(df, p)
        last = result.iloc[-1]
        self.assertFalse(last['box_breakout_XG'])
        false_count = sum([
            not last['box_放量_ok'],
            not last['box_突破_ok'],
            not last['box_涨幅_ok'],
        ])
        self.assertGreaterEqual(false_count, 2)


class TestDoubleZhongjunConditions(unittest.TestCase):
    """C组: 双中军子条件"""

    def test_double_zhongjun_positive_case(self):
        n = 150
        df = _make_zhongjun_data(n)
        index_df = _make_index_df(n, start=3000.0, step=2.0)
        p = dict(DEFAULT_PARAMS)
        result = _calc_double_zhongjun_conditions(df, index_df, p)
        last = result.iloc[-1]
        self.assertTrue(last['double_多头排列_ok'])
        self.assertTrue(last['double_均线发散_ok'])
        self.assertTrue(last['double_MACD_ok'])
        self.assertTrue(last['double_CCI_ok'])
        self.assertTrue(last['double_突破压力_ok'])
        self.assertTrue(last['double_MA20向上_ok'])
        self.assertTrue(last['double_MA60向上_ok'])
        self.assertTrue(last['double_大盘_ok'])
        self.assertTrue(last['double_zhongjun_XG'])

    def test_double_zhongjun_negative_case_no_index(self):
        n = 150
        df = _make_zhongjun_data(n)
        p = dict(DEFAULT_PARAMS)
        result = _calc_double_zhongjun_conditions(df, None, p)
        last = result.iloc[-1]
        self.assertFalse(last['double_大盘_ok'])
        self.assertFalse(last['double_zhongjun_XG'])


def _make_combo_data(n=150):
    """构造同时满足箱体突破 + 双中军全部子条件的数据.
    130天窄幅震荡, 19天温和上涨(rate=0.06), 最后一天6%跳涨.
    60日振幅 <20%, MA5/MA20 >1.05, 满足所有条件.
    """
    dates = pd.date_range('2026-01-01', periods=n)
    close_list = []
    high_list = []
    low_list = []
    vol_list = []
    for i in range(n):
        if i < 130:
            c = 10.0 + (i % 5) * 0.01
        elif i < n - 1:
            c = 10.04 + (i - 130) * 0.06
        else:
            prev_c = 10.04 + (n - 2 - 130) * 0.06
            c = prev_c * 1.06
        h = c
        l = c - 0.1
        v = 10000.0 if i == n - 1 else 1000.0
        close_list.append(c)
        high_list.append(h)
        low_list.append(l)
        vol_list.append(v)
    df = pd.DataFrame({
        'open': close_list, 'high': high_list, 'low': low_list,
        'close': close_list, 'volume': vol_list,
    }, index=dates)
    return df


class TestComboXG(unittest.TestCase):
    """D组: combo_XG 组合"""

    def test_combo_box_pass_zhongjun_fail(self):
        df = _make_box_breakout_data(100)
        p = dict(DEFAULT_PARAMS)
        box = _calc_box_breakout_conditions(df, p)
        dbl = _calc_double_zhongjun_conditions(df, None, p)
        self.assertTrue(box.iloc[-1]['box_breakout_XG'])
        self.assertFalse(dbl.iloc[-1]['double_zhongjun_XG'])
        merged = pd.concat([box, dbl], axis=1)
        merged['combo_XG'] = merged['box_breakout_XG'] & merged['double_zhongjun_XG']
        self.assertFalse(merged.iloc[-1]['combo_XG'])

    def test_combo_both_pass(self):
        df = _make_combo_data(150)
        index_df = _make_index_df(150, start=3000.0, step=2.0)
        p = dict(DEFAULT_PARAMS)
        box = _calc_box_breakout_conditions(df, p)
        dbl = _calc_double_zhongjun_conditions(df, index_df, p)
        merged = pd.concat([box, dbl], axis=1)
        merged['combo_XG'] = merged['box_breakout_XG'] & merged['double_zhongjun_XG']
        self.assertTrue(merged.iloc[-1]['combo_XG'])


class TestCompletenessEdgeCases(unittest.TestCase):
    """E组: 完整性/边界"""

    def test_no_lookahead_hhv(self):
        """无未来数据: 篡改第 30 行的数据, 第 0..29 行的指标输出必须保持不变.
        若发现某行输出受到未来数据影响, 说明 HHV/LLV/REF 等含 lookahead 漏洞.
        """
        n = 100
        dates = pd.date_range('2026-01-01', periods=n)
        close_list = [10.0 + i * 0.1 for i in range(n)]
        high_list = [c + 0.5 for c in close_list]
        low_list = [c - 0.5 for c in close_list]
        vol_list = [1000.0 + i * 10.0 for i in range(n)]

        df1 = pd.DataFrame({
            'open': close_list, 'high': high_list, 'low': low_list,
            'close': close_list, 'volume': vol_list,
        }, index=dates)

        p = dict(DEFAULT_PARAMS)
        result1 = _calc_box_breakout_conditions(df1, p)

        # 篡改第 30 行 high 到一个极端值
        TAMPER_IDX = 30
        high_list2 = list(high_list)
        high_list2[TAMPER_IDX] = 999.0
        df2 = pd.DataFrame({
            'open': close_list, 'high': high_list2, 'low': low_list,
            'close': close_list, 'volume': vol_list,
        }, index=dates)

        result2 = _calc_box_breakout_conditions(df2, p)

        # 第 0..29 行的所有 box_* 指标必须不受第 30 行篡改影响
        for i in range(0, TAMPER_IDX):
            for col in result1.columns:
                v1 = result1.iloc[i][col]
                v2 = result2.iloc[i][col]
                if isinstance(v1, float) and np.isnan(v1):
                    self.assertTrue(np.isnan(v2),
                        '行 %d 列 %s: 篡改后变为 %s, 应仍为 NaN (lookahead!)' % (i, col, v2))
                else:
                    self.assertEqual(v1, v2,
                        '行 %d 列 %s: 篡改前 %s, 篡改后 %s (lookahead!)' % (i, col, v1, v2))

    def test_no_lookahead_near_high(self):
        """近期高点 = REF(HHV(HIGH,20),1) 必须不含当日 high.
        构造: 倒数第二天前的 HIGH 都是 10, 最后一天 HIGH=100.
        近期高点 在最后一日应是 REF(HHV([10,...,10,100],20),1) = HHV([10,...,10],20)
        = 10, 而不是 100. 严格 < 当日 high.
        """
        n = 100
        dates = pd.date_range('2026-01-01', periods=n)
        high = [10.0] * (n - 1) + [100.0]
        close = high
        df = pd.DataFrame({
            'open': close, 'high': high, 'low': [c - 0.5 for c in close],
            'close': close, 'volume': [1000.0] * n,
        }, index=dates)
        index_df = pd.DataFrame({'close': [3000.0 + i for i in range(n)]}, index=dates)
        p = dict(DEFAULT_PARAMS)
        result = _calc_double_zhongjun_conditions(df, index_df, p)
        # 最后一行 近期高点 必须 = 10 (不是 100, 不含当日)
        last_near_high = result.iloc[-1]['double_近期高点']
        self.assertAlmostEqual(last_near_high, 10.0, places=4,
            msg='近期高点 取到了当日 high=100, 含 lookahead!')

    def test_output_columns_complete(self):
        n = 150
        df = _make_zhongjun_data(n)
        index_df = _make_index_df(n, start=3000.0, step=2.0)
        result = select_huang_main_uptrend_combo({'TEST': df}, index_df)

        required_xg = ['box_breakout_XG', 'double_zhongjun_XG', 'combo_XG']
        for col in required_xg:
            self.assertIn(col, result.columns)

        box_ok_cols = ['box_箱体振幅_ok', 'box_均线黏连_ok', 'box_放量_ok', 'box_突破_ok', 'box_涨幅_ok']
        for col in box_ok_cols:
            self.assertIn(col, result.columns)

        double_ok_cols = ['double_多头排列_ok', 'double_均线发散_ok', 'double_MACD_ok',
                          'double_CCI_ok', 'double_突破压力_ok', 'double_MA20向上_ok',
                          'double_MA60向上_ok', 'double_大盘_ok']
        for col in double_ok_cols:
            self.assertIn(col, result.columns)

    def test_short_series_no_crash(self):
        n = 10
        dates = pd.date_range('2026-01-01', periods=n)
        df = pd.DataFrame({
            'open': [10.0 + i * 0.1 for i in range(n)],
            'high': [10.5 + i * 0.1 for i in range(n)],
            'low': [9.5 + i * 0.1 for i in range(n)],
            'close': [10.0 + i * 0.1 for i in range(n)],
            'volume': [1000.0] * n,
        }, index=dates)
        result = select_huang_main_uptrend_combo({'SHORT': df}, None)
        self.assertFalse(result.empty)
        self.assertTrue((result['combo_XG'] == False).all())


if __name__ == '__main__':
    unittest.main()
