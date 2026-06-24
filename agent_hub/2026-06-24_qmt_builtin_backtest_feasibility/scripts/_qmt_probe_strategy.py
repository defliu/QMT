# coding=utf-8
"""QMT 内置回测探针策略 — PART-A 用，最小可执行版。

只做三件事：
1. init 打印生命周期标记
2. handlebar 累计 bar 数
3. stop 把 bar 数写入文件，让外部知道 handlebar 跑过几次

不下单、不调 passorder、不写 D:/QMT_POOL。
"""

import json
import os
import time

PROBE_LOG = r'D:/QMT_STRATEGIES/agent_hub/2026-06-24_qmt_builtin_backtest_feasibility/data/_probe_a_log.json'

_state = {
    'init_called': False,
    'after_init_called': False,
    'handlebar_count': 0,
    'stop_called': False,
    'first_bar_time': None,
    'last_bar_time': None,
    'error': None,
}


def init(C):
    _state['init_called'] = True
    _state['init_ts'] = time.time()
    # 注意：start_time/end_time 在 _param 里，stgframe 没自动赋值到 C
    C.start_time = C._param.get('start_time', '')
    C.end_time = C._param.get('end_time', '')


def after_init(C):
    _state['after_init_called'] = True


def handlebar(C):
    try:
        _state['handlebar_count'] += 1
        bar_time = C.timelist[C.barpos] if C.barpos >= 0 and C.barpos < len(C.timelist) else None
        if _state['first_bar_time'] is None:
            _state['first_bar_time'] = bar_time
        _state['last_bar_time'] = bar_time
    except Exception as e:
        _state['error'] = repr(e)


def stop(C):
    _state['stop_called'] = True
    _state['stop_ts'] = time.time()
    try:
        os.makedirs(os.path.dirname(PROBE_LOG), exist_ok=True)
        with open(PROBE_LOG, 'w', encoding='utf-8') as f:
            json.dump(_state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        # stop 阶段写不进去就静默，外层会用 stderr 兜底
        pass