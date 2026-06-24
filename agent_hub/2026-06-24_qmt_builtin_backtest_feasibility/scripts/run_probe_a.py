# coding=utf-8
"""PART-A 驱动 — 用 QMT 自带 Python 跑探针。

输出：
  stdout / stderr → run_probe_a_<state>.log
  探针自己写       → data/_probe_a_log.json
"""

import json
import os
import sys
import time
import traceback

PROBE = r'D:/QMT_STRATEGIES/agent_hub/2026-06-24_qmt_builtin_backtest_feasibility/scripts/_qmt_probe_strategy.py'

PARAM = {
    'stock_code': '000001.SZ',
    'period': '1d',
    'start_time': '20240101',
    'end_time': '20240331',
    'trade_mode': 'backtest',
    'quote_mode': 'history',
    'asset': 1000000,
    'dividend_type': 'front',
    'title': 'probe_a_minimal',
}

def main():
    print('[probe_a] python:', sys.executable)
    print('[probe_a] cwd   :', os.getcwd())
    print('[probe_a] probe :', PROBE)
    print('[probe_a] param :', json.dumps(PARAM, ensure_ascii=False))

    t0 = time.time()
    try:
        from xtquant.qmttools import stgentry
        print('[probe_a] stgentry imported:', stgentry.__file__)
    except Exception:
        print('[probe_a] FAIL: import stgentry')
        traceback.print_exc()
        return 10

    try:
        ret = stgentry.run_file(PROBE, PARAM)
        print('[probe_a] run_file returned:', repr(ret))
        print('[probe_a] elapsed (s)      :', round(time.time() - t0, 2))
    except Exception:
        print('[probe_a] FAIL: run_file raised')
        print('[probe_a] elapsed (s)      :', round(time.time() - t0, 2))
        traceback.print_exc()
        return 20

    return 0


if __name__ == '__main__':
    sys.exit(main())