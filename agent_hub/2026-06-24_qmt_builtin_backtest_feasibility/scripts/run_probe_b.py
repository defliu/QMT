# coding=utf-8
"""PART-B 驱动 — 单标的回测 + callback 落盘。"""

import json
import os
import sys
import time
import traceback

PROBE = r'D:/QMT_STRATEGIES/agent_hub/2026-06-24_qmt_builtin_backtest_feasibility/scripts/_qmt_probe_b_strategy.py'

PARAM = {
    'stock_code': '000001.SZ',
    'period': '1d',
    'start_time': '20240901',
    'end_time': '20241231',
    'trade_mode': 'backtest',
    'quote_mode': 'history',
    'asset': 1000000,
    'dividend_type': 'front',
    'title': 'probe_b_single_stock',
}


def main():
    print('[probe_b] python:', sys.executable)
    print('[probe_b] probe :', PROBE)
    print('[probe_b] param :', json.dumps(PARAM, ensure_ascii=False))

    t0 = time.time()
    try:
        from xtquant.qmttools import stgentry
        print('[probe_b] stgentry imported:', stgentry.__file__)
    except Exception:
        print('[probe_b] FAIL import stgentry')
        traceback.print_exc()
        return 10

    try:
        ret = stgentry.run_file(PROBE, PARAM)
        print('[probe_b] run_file returned:', repr(ret))
        print('[probe_b] elapsed (s)      :', round(time.time() - t0, 2))
    except Exception:
        print('[probe_b] FAIL run_file')
        print('[probe_b] elapsed (s)      :', round(time.time() - t0, 2))
        traceback.print_exc()
        return 20

    return 0


if __name__ == '__main__':
    sys.exit(main())
