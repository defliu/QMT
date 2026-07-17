# coding=utf-8
"""Layer 3: 完整交易流程模拟（不下单）

模拟 handlebar 在 14:50 买入窗口的完整流程:
  1. 加载全市场数据（取前200只）
  2. 生成候选池（从加载的股票中选）
  3. check_buy 信号过滤
  4. bias过滤
  5. 评分排序
  6. 生成买入候选列表

不依赖 QMT Context 对象，直接用 xtdata 取真实数据 + 策略函数计算。
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
from strategy_main import (
    _passes_buy_bias_filter, _load_config, _g_all_data, _g_scorer,
    _run_scoring, _append_log, _score_display, _fetch_pe_data
)
import pandas as pd

# ---- Step 1: 加载数据 ----
print("\n=== Step 1: 加载全市场数据（前200只） ===")
try:
    codes = xtdata.get_stock_list_in_sector('沪深A股')
    shsz = [c for c in codes if c.endswith('.SH') or c.endswith('.SZ')]
    test_codes = shsz[:200]

    loaded = 0
    for code in test_codes:
        df = xtdata.get_market_data_ex(
            ['close', 'open', 'high', 'low', 'volume', 'amount'],
            [code], period='1d', start_time='20260101', end_time='20260717', count=-1
        )
        if df and code in df and len(df[code]) >= 60:
            _g_all_data[code] = df[code]
            loaded += 1

    check('全市场数据加载', loaded >= 100,
          '%d/200 只加载成功（需>=60根日线）' % loaded)
except Exception as e:
    check('全市场数据加载', False, '异常: %s' % str(e)[:300])


# ---- Step 2: 生成候选池（模拟S010筛选） ----
print("\n=== Step 2: 生成候选池 ===")
try:
    cfg = _load_config()
    strategy_cfg = cfg.get('strategy', {})
    max_hold = strategy_cfg.get('max_hold', 3)

    candidates = []
    for code, df in _g_all_data.items():
        buy, signal, buy_type = check_buy(df)
        if not buy:
            continue
        if not _passes_buy_bias_filter(code, df, label='全流程测试'):
            continue
        # 跳过ST（用代码前缀判断，因为没有C对象取名字）
        if code.startswith('ST') or code.startswith('*ST'):
            continue
        candidates.append({'code': code, 'signal': signal, 'buy_type': buy_type})

    check('候选池生成', len(candidates) >= 3,
          '%d 只通过check_buy+bias过滤（至少需3只才能填满仓位）' % len(candidates))
except Exception as e:
    check('候选池生成', False, '异常: %s' % str(e)[:300])


# ---- Step 3: 评分排序 ----
print("\n=== Step 3: 评分排序 ===")
try:
    if candidates:
        # 初始化 scorer（需要先创建）
        from strategy_main import _g_scorer as scorer_check
        if _g_scorer is None:
            from strategy_main import SwitchScorer
            _g_scorer = SwitchScorer(mode='6plus2')

        # 构建5日收益率数据（_run_scoring需要）
        ret_series_data = {}
        for s in candidates:
            code = s['code']
            df = _g_all_data.get(code)
            if df is not None and len(df) >= 7:
                try:
                    ret = float(df['close'].iloc[-1] / df['close'].iloc[-6] - 1)
                    ret_series_data[code] = ret
                except:
                    pass
        pool_5d_returns = pd.Series(ret_series_data).dropna()

        scored = []
        for s in candidates:
            code = s['code']
            df = _g_all_data.get(code)
            if df is None:
                continue
            try:
                pe_ttm, pe_static, pb, _ = _fetch_pe_data(code)
                pe_info = {'dynamic_pe': pe_ttm, 'static_pe': pe_static}
            except:
                pe_info = None
            try:
                result = _g_scorer.score_single(
                    stock_code=code, df=df,
                    dynamic_pe=pe_info['dynamic_pe'] if pe_info else None,
                    static_pe=pe_info['static_pe'] if pe_info else None,
                    pool_5d_returns=pool_5d_returns,
                )
                scored.append({
                    'code': code,
                    'score': result['score_total'],
                    'signal': s['signal'],
                    'buy_type': s['buy_type'],
                    'details': result,
                })
            except Exception as e:
                print("    [评分跳过] %s: %s" % (code, str(e)[:100]))
                continue

        scored.sort(key=lambda x: x['score'], reverse=True)

        if scored:
            print("  Top 5 评分结果:")
            for i, s in enumerate(scored[:5]):
                d = s['details']
                print("    %d. %s 总分=%.2f 突破=%.2f 趋势=%.2f 回踩=%.2f 量价=%.2f MACD=%.2f 估值=%.2f" % (
                    i + 1, s['code'], s['score'],
                    d.get('score_breakout', 0), d.get('score_trend', 0),
                    d.get('score_consolidation', 0), d.get('score_volumeprice', 0),
                    d.get('score_macd', 0), d.get('score_valuation', 0)))

        check('评分排序', len(scored) >= 3,
              '%d 只评分成功（至少3只才能买入）' % len(scored))
        if scored:
            check('最高分>50', scored[0]['score'] > 50,
                  '最高分=%.2f' % scored[0]['score'])
    else:
        check('评分排序', False, '无候选股可评分')
        check('最高分>50', False, '无候选股')
except Exception as e:
    import traceback
    check('评分排序', False, '异常: %s' % traceback.format_exc()[:300])


# ---- Step 4: 买入候选列表 ----
print("\n=== Step 4: 买入候选列表 ===")
try:
    if candidates:
        current_nav = 91204  # 模拟净值
        per_stock_amount = int(current_nav * 0.30 / 100) * 100
        buyable = scored[:max_hold] if scored else []
        check('买入候选列表', len(buyable) >= 1,
              '%d 只可买入, 每只约%.0f元' % (len(buyable), per_stock_amount))
    else:
        check('买入候选列表', False, '无候选股')
except Exception as e:
    check('买入候选列表', False, '异常: %s' % str(e)[:200])


# ---- 汇总 ----
print("\n" + "=" * 40)
print("结果: %d PASS / %d FAIL / 共%d项" % (PASS, FAIL, PASS + FAIL))

result = {
    'test': 'test_03_full_flow',
    'status': 'PASS' if FAIL == 0 else 'FAIL',
    'summary': '%d PASS / %d FAIL' % (PASS, FAIL),
    'details': REPORT
}
print("\n---JSON-START---")
print(json.dumps(result, ensure_ascii=False))
print("---JSON-END---")

sys.exit(0 if FAIL == 0 else 1)
