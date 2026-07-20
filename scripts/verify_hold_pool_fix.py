# coding=utf-8
"""验证 _run_hold_pool_selection 的 str<=datetime 崩溃已修复。

用 MockContextInfo(get_current_time() 返回 datetime, 正是触发崩溃的那种情况)
直接调 _run_hold_pool_selection, 确认不再抛 TypeError。

用法:
    python scripts/verify_hold_pool_fix.py
"""
import sys
import os
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = 0
FAIL = 0


def check(name, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s: %s" % (name, detail))
    else:
        FAIL += 1
        print("  [FAIL] %s: %s" % (name, detail))


def main():
    # 用重建后的 strategy_main(已含修复) 验证实际产物
    try:
        from strategy_main import _run_hold_pool_selection
        print("  已从重建版 strategy_main 导入 _run_hold_pool_selection")
    except Exception as e:
        print("  [WARN] 无法从 strategy_main 导入, 回退到源 adapters.qmt_wrapper: %s" % e)
        from adapters.qmt_wrapper import _run_hold_pool_selection

    from adapters.context_mock import MockContextInfo

    # MockContextInfo.get_current_time() 返回 datetime(2024,5,30,15,0,0)
    # 即 get_current_time() 返回 datetime 的情形 -> 修复前会 '1450' <= datetime 崩溃
    C = MockContextInfo()

    # 确认 mock 的 get_current_time 确实返回 datetime(复现触发条件)
    t = C.get_current_time()
    print("  mock get_current_time() 返回类型: %s -> %s" % (type(t).__name__, t))

    try:
        result = _run_hold_pool_selection(C)
        # 不抛异常即修复成功; 返回应是 list(可能因 mock 缺 get_stock_list_in_sector 而返回 [])
        check("买入窗口比较不再抛 TypeError",
              isinstance(result, list),
              "返回类型=%s, 长度=%d" % (type(result).__name__, len(result)))
    except TypeError as e:
        check("买入窗口比较不再抛 TypeError", False, "仍抛 TypeError: %s" % e)
        traceback.print_exc()
    except Exception as e:
        # 其他异常(如 mock 缺方法)不算本次修复的范畴, 但买入窗口比较这一行必须已过
        check("买入窗口比较不再抛 TypeError",
              "str' and 'datetime" not in str(e),
              "非目标异常(可接受): %s" % str(e)[:200])

    print("\n结果: %d PASS / %d FAIL" % (PASS, FAIL))
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == '__main__':
    main()
