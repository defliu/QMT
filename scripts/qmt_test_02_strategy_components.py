# coding=utf-8
"""Layer 2: 验证策略组件（选股池+信号+评分）在真实数据上是否正常

测试项:
  1. check_buy 信号计算
  2. _passes_buy_bias_filter 过滤
  3. 综合选股流程（模拟S010筛选后的完整买入候选列表）
"""
from __future__ import print_function
import sys
import json

sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf8', buffering=1)
sys.path.insert(0, 'D:/QMT_STRATEGIES')

PASS = 0
FAIL = 0
REPORT = []

def check(name, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        REPORT.append({'name': name, 'status': 'PASS', 'detail': detail})
    else:
        FAIL += 1
        REPORT.append({'name': name, 'status': 'FAIL', 'detail': detail})
    print("  [%s] %s: %s" % ('PASS' if cond else 'FAIL', name, detail))


from xtquant import xtdata
from core.signal_main_rise import check_buy
from strategy_main import _passes_buy_bias_filter, _g_all_data


# ---- Test 1: check_buy 信号计算 ----
print("\n=== Test 1: check_buy 信号计算 ===")
try:
    codes = xtdata.get_stock_list_in_sector('沪深A股')
    shsz = [c for c in codes if c.endswith('.SH') or c.endswith('.SZ')]
    test_codes = shsz[:100]

    pass_check = 0
    pass_all = 0
    for code in test_codes:
        df = xtdata.get_market_data_ex(
            ['close', 'open', 'high', 'low', 'volume', 'amount'],
            [code], period='1d', start_time='20260101', end_time='20260717', count=-1
        )
        if not df or code not in df:
            continue
        d = df[code]
        if len(d) < 60:
            continue

        buy, signal, buy_type = check_buy(d)
        if buy:
            pass_check += 1
            if _passes_buy_bias_filter(code, d, label='test'):
                pass_all += 1

    print("  check_buy通过: %d/%d, bias也通过: %d" % (pass_check, len(test_codes), pass_all))
    check('check_buy 信号计算', pass_check >= 5,
          '%d/100 只通过信号（行情正常时通常>10只）' % pass_check)
    check('bias过滤', pass_all >= 1,
          '%d/100 只通过全部过滤' % pass_all)
except Exception as e:
    check('check_buy 信号计算', False, '异常: %s' % str(e)[:300])
    check('bias过滤', False, '异常: %s' % str(e)[:300])


# ---- Test 2: 大盘感知 ----
print("\n=== Test 2: 大盘感知 ===")
try:
    index_df = xtdata.get_market_data_ex(
        ['close', 'open', 'high', 'low', 'volume'],
        ['000001.SH'], period='1d', start_time='20260101', end_time='20260717', count=-1
    )
    if index_df and '000001.SH' in index_df:
        idf = index_df['000001.SH']
        rows = len(idf)
        close = float(idf['close'].iloc[-1])
        check('大盘数据可用', rows > 100,
              '上证指数 %d 行, 最新收盘=%.2f' % (rows, close))
    else:
        check('大盘数据可用', False, '返回空')
except Exception as e:
    check('大盘数据可用', False, '异常: %s' % str(e)[:200])


# ---- Test 3: 配置加载 ----
print("\n=== Test 3: 配置加载 ===")
try:
    from strategy_main import _load_config
    cfg = _load_config()
    strategy_cfg = cfg.get('strategy', {})
    has_capital = strategy_cfg.get('capital_base', 0) > 0
    has_max_hold = strategy_cfg.get('max_hold', 0) > 0
    check('配置加载', has_capital and has_max_hold,
          'capital_base=%.0f, max_hold=%d' % (strategy_cfg.get('capital_base', 0), strategy_cfg.get('max_hold', 0)))
except Exception as e:
    check('配置加载', False, '异常: %s' % str(e)[:300])


# ---- 汇总 ----
print("\n" + "=" * 40)
print("结果: %d PASS / %d FAIL / 共%d项" % (PASS, FAIL, PASS + FAIL))

result = {
    'test': 'test_02_strategy_components',
    'status': 'PASS' if FAIL == 0 else 'FAIL',
    'summary': '%d PASS / %d FAIL' % (PASS, FAIL),
    'details': REPORT
}
print("\n---JSON-START---")
print(json.dumps(result, ensure_ascii=False))
print("---JSON-END---")

sys.exit(0 if FAIL == 0 else 1)
