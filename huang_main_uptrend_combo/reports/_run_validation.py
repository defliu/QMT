# coding=utf-8
"""黄氏主升浪 combo selector 最小样本验证.
生成 reports/validation_detail.csv 和回填 reports/validation_report.md.
独立运行: python huang_main_uptrend_combo/reports/_run_validation.py
"""
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

import numpy as np
import pandas as pd

from huang_main_uptrend_combo.huang_main_uptrend_combo_selector import (
    select_huang_main_uptrend_combo, DEFAULT_PARAMS,
)


def _make_index(n, start=3000.0, step=2.0):
    """大盘指数: 单调上升, 满足 大盘指数>MA20>MA60"""
    dates = pd.date_range('2026-01-01', periods=n)
    close = [start + i * step for i in range(n)]
    return pd.DataFrame({'close': close}, index=dates)


def _make_stock_A_combo_pass(n=150):
    """A 股: 130 天窄幅震荡 + 19 天温和上涨 + 最后一天 6% 跳涨, 满足 combo"""
    dates = pd.date_range('2026-01-01', periods=n)
    closes = []
    for i in range(n):
        if i < 130:
            c = 10.0 + (i % 5) * 0.01
        elif i < n - 1:
            c = 10.04 + (i - 130) * 0.06
        else:
            prev = 10.04 + (n - 2 - 130) * 0.06
            c = prev * 1.06
        closes.append(c)
    return pd.DataFrame({
        'open': closes, 'high': closes, 'low': [c - 0.1 for c in closes],
        'close': closes,
        'volume': [10000.0 if i == n - 1 else 1000.0 for i in range(n)],
    }, index=dates)


def _make_stock_B_box_only(n=150):
    """B 股: 满足箱体突破但不满足双中军 (例: MA60 平台, 无多头排列)"""
    dates = pd.date_range('2026-01-01', periods=n)
    closes = [10.0 + (i % 3) * 0.05 for i in range(n - 1)] + [10.7]
    return pd.DataFrame({
        'open': closes, 'high': closes, 'low': [c - 0.1 for c in closes],
        'close': closes,
        'volume': [10000.0 if i == n - 1 else 1000.0 for i in range(n)],
    }, index=dates)


def _make_stock_C_neither(n=150):
    """C 股: 缩量横盘, 既不满足箱体突破也不满足双中军"""
    dates = pd.date_range('2026-01-01', periods=n)
    closes = [10.0 + (i % 7) * 0.02 for i in range(n)]
    return pd.DataFrame({
        'open': closes, 'high': closes, 'low': [c - 0.05 for c in closes],
        'close': closes, 'volume': [1000.0] * n,
    }, index=dates)


def main():
    n = 150
    data = {
        'A_组合通过': _make_stock_A_combo_pass(n),
        'B_只过箱体': _make_stock_B_box_only(n),
        'C_全部不过': _make_stock_C_neither(n),
    }
    index_df = _make_index(n)
    result = select_huang_main_uptrend_combo(data, index_df)

    # 只看最后一日
    last_per_code = result.groupby('code').tail(1).reset_index(drop=True)

    cols = [
        'code', 'date',
        'box_breakout_XG',
        'box_箱体振幅_ok', 'box_均线黏连_ok', 'box_放量_ok',
        'box_突破_ok', 'box_涨幅_ok',
        'double_zhongjun_XG',
        'double_多头排列_ok', 'double_均线发散_ok', 'double_MACD_ok',
        'double_CCI_ok', 'double_突破压力_ok',
        'double_MA20向上_ok', 'double_MA60向上_ok', 'double_大盘_ok',
        'combo_XG',
    ]
    detail = last_per_code[cols]
    out_csv = os.path.join(os.path.dirname(__file__), 'validation_detail.csv')
    detail.to_csv(out_csv, index=False, encoding='utf-8')

    # 统计
    n_box = int(last_per_code['box_breakout_XG'].sum())
    n_zhongjun = int(last_per_code['double_zhongjun_XG'].sum())
    n_combo = int(last_per_code['combo_XG'].sum())

    print('=== 最小样本验证结果 ===')
    print('样本股数:', len(data))
    print('通过箱体突破初选:', n_box)
    print('通过双中军精筛:', n_zhongjun)
    print('最终通过 combo:', n_combo)
    print()
    print(detail.to_string(index=False))

    return detail, n_box, n_zhongjun, n_combo


if __name__ == '__main__':
    main()
