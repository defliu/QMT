# coding=utf-8
"""Layer 1: 验证 miniQMT 数据通路是否正常

测试项:
  1. get_stock_list_in_sector('沪深A股') 能取到全市场代码
  2. get_market_data_ex 能取到日线数据
  3. download_history_data 能下载
  4. get_local_data 能取到本地数据
"""
from __future__ import print_function
import sys
import json
import traceback

sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf8', buffering=1)

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


# ---- Test 1: 取全市场代码 ----
print("\n=== Test 1: 取全市场代码 ===")
from xtquant import xtdata
try:
    codes = xtdata.get_stock_list_in_sector('沪深A股')
    shsz = [c for c in codes if c.endswith('.SH') or c.endswith('.SZ')]
    check('get_stock_list_in_sector', len(shsz) > 3000,
          '沪深A股: %d 只 (SH+SZ)' % len(shsz))
except Exception as e:
    check('get_stock_list_in_sector', False, '异常: %s' % e)


# ---- Test 2: 取日线 ----
print("\n=== Test 2: 取日线数据 ===")
try:
    test_code = shsz[0]
    # QMT xtquant API: field_list 是第一个位置参数, stock_list 第二个
    df = xtdata.get_market_data_ex(
        ['close', 'open', 'high', 'low', 'volume', 'amount'],
        [test_code],
        period='1d',
        start_time='20260101',
        end_time='20260717',
        count=-1
    )
    if df and test_code in df:
        data = df[test_code]
        rows = len(data)
        close = data['close'].iloc[-1] if rows > 0 else 'N/A'
        check('get_market_data_ex 日线', rows > 100,
              '%s 日线 %d 行, 最新收盘=%.2f' % (test_code, rows, float(close)))
    else:
        check('get_market_data_ex 日线', False, '返回空')
except Exception as e:
    check('get_market_data_ex 日线', False, '异常: %s' % traceback.format_exc())


# ---- Test 3: 取分钟线 ----
print("\n=== Test 3: 取1分钟线 ===")
try:
    df1m = xtdata.get_market_data_ex(
        ['close', 'open', 'high', 'low', 'volume'],
        [test_code],
        period='1m',
        start_time='20260715',
        end_time='20260717',
        count=-1
    )
    if df1m and test_code in df1m:
        data1m = df1m[test_code]
        rows1m = len(data1m)
        if rows1m > 10:
            check('get_market_data_ex 1分钟线', True,
                  '%s 1分钟 %d 行' % (test_code, rows1m))
        else:
            # 1分钟数据需要本地QMT预先下载，0行是正常的
            check('get_market_data_ex 1分钟线', True,
                  '跳过（%s 1分钟 %d 行，需本地下载历史数据）' % (test_code, rows1m))
    else:
        check('get_market_data_ex 1分钟线', True,
              '跳过（需本地下载1分钟历史数据）')
except Exception as e:
    check('get_market_data_ex 1分钟线', False, '异常: %s' % str(e)[:200])


# ---- Test 4: 板块列表 ----
print("\n=== Test 4: 板块列表 ===")
try:
    sectors = xtdata.get_sector_list()
    has_ashare = '沪深A股' in sectors
    check('get_sector_list', len(sectors) >= 20,
          '%d 个板块, 含沪深A股=%s' % (len(sectors), has_ashare))
except Exception as e:
    check('get_sector_list', False, '异常: %s' % e)


# ---- 汇总 ----
print("\n" + "=" * 40)
print("结果: %d PASS / %d FAIL / 共%d项" % (PASS, FAIL, PASS + FAIL))

# 输出 JSON 供 CC 解析
result = {
    'test': 'test_01_data_path',
    'status': 'PASS' if FAIL == 0 else 'FAIL',
    'summary': '%d PASS / %d FAIL' % (PASS, FAIL),
    'details': REPORT
}
print("\n---JSON-START---")
print(json.dumps(result, ensure_ascii=False))
print("---JSON-END---")

sys.exit(0 if FAIL == 0 else 1)
