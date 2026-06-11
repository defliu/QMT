# -*- coding: utf-8 -*-
"""Fix formatting in risk_only_strategy.py: add _print_holdings_report, enhance sell logs"""
import sys

path = 'D:/QMT_STRATEGIES/risk_only_strategy.py'

with open(path, 'r', encoding='gbk') as f:
    content = f.read()

# === 1. Insert _print_holdings_report function ===
# Current order: ... _reset_risk_log() ... blank ... _write_risk_log()
# We want:       ... _reset_risk_log() ... blank ... _print_holdings_report() ... blank ... _write_risk_log()

insert_func = """def _print_holdings_report(today, codes, pd, diagnosis_list):
    \"\"\"持仓报告：盘前持仓+账户持仓+对比表 (匹配qmt_wrapper格式)\"\"\"
    tracked_codes = list(_g_sell_engine._states.keys()) if _g_sell_engine and _g_sell_engine._states else []
    print()
    print('=' * 55)
    print('  持仓收盘报告 %s' % today)
    print('=' * 55)
    print()
    print('  【盘前持仓】%d 只' % len(tracked_codes))
    if tracked_codes:
        for idx, c in enumerate(sorted(tracked_codes), 1):
            state = _g_sell_engine._states.get(c) if _g_sell_engine else None
            reason = get_trade_state_reason(state)
            print('  %d. %s  %s' % (idx, c, reason))
    else:
        print('  (空)')
    print()
    print('  【账户持仓】%d 只' % len(codes))
    if codes:
        diag_map = {}
        for d in diagnosis_list:
            diag_map[d['code']] = d
        for idx, c in enumerate(sorted(codes), 1):
            p = pd.get(c, {})
            vol = p.get('volume', 0)
            cost = p.get('cost', 0)
            diag = diag_map.get(c, {})
            curr = diag.get('current_price', 0) or cost
            profit = diag.get('profit_pct', 0)
            in_strategy = '★策略' if c in tracked_codes else '其他'
            print('  %d. %s  %d股  成本=%.2f  现价=%.2f  盈亏=%+.1f%%  %s' % (idx, c, vol, cost, curr, profit, in_strategy))
    else:
        print('  (空)')
    print()
    print('  策略跟踪: %d 只 | 账户持有: %d 只' % (len(tracked_codes), len(codes)))
    print('=' * 55)


"""

# Find "_reset_risk_log function end" marker: the last '    _g_risk_log_written = False'
idx = content.rfind('    _g_risk_log_written = False')
if idx < 0:
    print('ERROR: cannot find insertion point')
    sys.exit(1)

# Move past the end of the line
idx = content.find('\n', idx) + 1  # past the newline
# Skip blank lines following
while idx < len(content) and content[idx] in '\r\n':
    idx += 1
# Now idx points to 'def _write_risk_log('

content = content[:idx] + insert_func + content[idx:]
print('1. _print_holdings_report function inserted')

# === 2. Modify sell log section ===
# Find the evaluate() line and the _write_risk_log call to replace the block
sell_start = 'decisions = _g_sell_engine.evaluate(today, hd, all_data, pd)'
sell_end = '_write_risk_log(today, codes, pd, hd, dt, diagnosis_list, decisions)'

i0 = content.find(sell_start)
i1 = content.find(sell_end, i0)
if i0 < 0 or i1 < 0:
    print('ERROR: sell section markers not found')
    sys.exit(1)

i1 += len(sell_end)  # include the end marker
old_sell_block = content[i0:i1]

new_sell_block = """decisions = _g_sell_engine.evaluate(today, hd, all_data, pd)
    for code, decision, shares in decisions:
        if shares < 100: continue
        # 计算现价和盈亏用于日志
        cost_price = pd.get(code, {}).get('cost', 0)
        current_price = 0.0
        if code in all_data:
            df = all_data[code]
            current_price = float(df['close'].astype(float).iloc[-1])
        pnl_str = \"%+.1f%%\" % ((current_price - cost_price) / cost_price * 100) if cost_price > 0 else \"--\"
        signal_str = \"|\".join(decision.triggered_signals) if decision.triggered_signals else \"\"

        oid = _sell_with_limit(C, code, shares, decision.reason)
        if oid:
            _g_pending_sells[code] = {
                \"order_id\": oid,
                \"volume\": shares,
                \"retries\": 0,
                \"checks\": 0,
            }
            print(\"  [风控] %s  现价=%.2f  盈亏=%s  卖出%d股  原因=%s  层=%s  委托=%s\" % (code, current_price, pnl_str, shares, decision.reason, decision.triggered_layer, oid))
            _append_risk_log(\"sell_order: %s price=%.2f pnl=%s %dshares reason=%s layer=%s signals=%s oid=%s\" % (code, current_price, pnl_str, shares, decision.reason, decision.triggered_layer, signal_str, oid))
        else:
            print(\"  [风控] %s  现价=%.2f  盈亏=%s  卖出%d股  原因=%s  层=%s  失败\" % (code, current_price, pnl_str, shares, decision.reason, decision.triggered_layer))
            _append_risk_log(\"sell_failed: %s price=%.2f pnl=%s %dshares reason=%s layer=%s signals=%s\" % (code, current_price, pnl_str, shares, decision.reason, decision.triggered_layer, signal_str))
    if not decisions: print(\"  [风控] 未检测到卖出信号\")
    tv = sum(p[\"volume\"] for p in pd.values())
    tc = sum(p[\"cost\"]*p[\"volume\"] for p in pd.values())
    print(\"  [风控] 总计 %d 只持仓  股数=%d  总成本=%.2f\" % (len(codes), tv, tc))
    _print_holdings_report(today, codes, pd, diagnosis_list)
    _write_risk_log(today, codes, pd, hd, dt, diagnosis_list, decisions)"""

content = content.replace(old_sell_block, new_sell_block, 1)
print('2. Sell log section updated')

# === Write back in GBK ===
with open(path, 'w', encoding='gbk') as f:
    f.write(content)

# === Verify GBK ===
with open(path, 'rb') as f:
    raw = f.read()
try:
    raw.decode('gbk')
    print('3. GBK encoding: OK')
except Exception as e:
    print('3. GBK encoding: FAILED -', e)
    sys.exit(1)

# === Verify key elements ===
with open(path, 'r', encoding='gbk') as f:
    v = f.read()
print('   Has _print_holdings_report function:', 'def _print_holdings_report' in v)
print('   Has _print_holdings_report call:    ', '_print_holdings_report(today' in v)
print('   Has 现价=:', '现价=' in v)
print('   Has 层=:', '层=' in v)
print('   Has 信号 detail:', 'signal_str' in v)
print('DONE')
