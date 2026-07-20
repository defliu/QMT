# coding=utf-8
"""strategy_mfic.py miniQMT本地测试脚本
用法（在miniQMT运行的机器上）：
  cd D:/QMT_STRATEGIES
  bin.x64/pythonw.exe scripts/qmt_test_mfic.py

测试分层：
  Layer 1: xtquant数据通路
  Layer 2: 策略核心组件（过滤/评分/选股）
  Layer 3: 完整调仓流程模拟（不下单）
"""
import sys
import os

TEST_RESULTS = {"layer1": [], "layer2": [], "layer3": []}

def log(msg):
    print("[mfic-test] %s" % msg)
    with open(r"D:\QMT_POOL\mfic_test.log", "a") as f:
        f.write("%s\n" % msg)

# ============================================================
# Layer 1: 数据通路测试
# ============================================================
def test_layer1():
    log("===== Layer 1: 数据通路 =====")
    try:
        from xtquant import xtdata
        log("  xtdata 导入: PASS")

        # 测试获取全市场股票
        codes = xtdata.get_stock_list_in_sector("沪深A股")
        log("  沪深A股股票数: %d" % len(codes))
        TEST_RESULTS["layer1"].append(("get_stock_list", len(codes) > 3000))

        # 测试获取行情数据
        if len(codes) > 0:
            test_codes = codes[:50]
            md = xtdata.get_market_data_ex(
                fields=["close", "pb", "pe_ttm", "circ_mv", "amount"],
                stock_code=test_codes,
                period="1d",
                count=60
            )
            if md:
                first_code = test_codes[0]
                if first_code in md:
                    data = md[first_code]
                    if data is not None and len(data.get("close", [])) > 0:
                        log("  行情数据获取: PASS (%d天数据)" % len(data.get("close", [])))
                        TEST_RESULTS["layer1"].append(("get_market_data", True))
                    else:
                        log("  行情数据获取: FAIL (数据为空)")
                        TEST_RESULTS["layer1"].append(("get_market_data", False))
                else:
                    log("  行情数据获取: FAIL (无此代码)")
                    TEST_RESULTS["layer1"].append(("get_market_data", False))
            else:
                log("  行情数据获取: FAIL")
                TEST_RESULTS["layer1"].append(("get_market_data", False))

        # 测试财务数据
        try:
            fin = xtdata.get_financial_data(
                ["PERSHAREINDEX.du_return_on_equity"],
                [test_codes[0]] if codes else [],
                "20260101", "20260701", "announce_time"
            )
            log("  财务数据获取: %s" % ("PASS" if fin is not None else "返回None"))
            TEST_RESULTS["layer1"].append(("get_financial_data", fin is not None))
        except Exception as e:
            log("  财务数据获取: FAIL (%s)" % str(e)[:60])
            TEST_RESULTS["layer1"].append(("get_financial_data", False))

    except Exception as e:
        log("  Layer 1 异常: %s" % str(e))
        TEST_RESULTS["layer1"].append(("xtdata_import", False))
        return False

    passed = all(p[1] for p in TEST_RESULTS["layer1"])
    log("  Layer 1 总体: %s (%d/%d)" % ("PASS" if passed else "FAIL",
         sum(1 for p in TEST_RESULTS["layer1"] if p[1]), len(TEST_RESULTS["layer1"])))
    return passed

# ============================================================
# Layer 2: 策略核心组件
# ============================================================
def test_layer2():
    log("")
    log("===== Layer 2: 策略核心 =====")
    try:
        # 测试过滤 + 评分逻辑（使用模拟数据）
        sys.path.insert(0, 'D:/QMT_STRATEGIES')
        from strategy_mfic import _normalize, _compute_scores

        # 创建模拟DataFrame（字段名模拟QMT原始数据）
        np.random.seed(42)
        n_stocks = 100
        codes = ["%06d.SZ" % i for i in range(n_stocks)]
        mock_data = pd.DataFrame({
            "pb": np.random.uniform(2, 100, n_stocks),  # 用于计算BP
            "momentum_1m": np.random.uniform(-0.3, 0.3, n_stocks),
            "volatility_60d": np.random.uniform(0.1, 0.5, n_stocks),
            "ROE": np.random.uniform(-10, 30, n_stocks),
        }, index=codes)

        scores = _compute_scores(mock_data)
        valid_count = len(scores.dropna())
        log("  模拟评分: %d/100只有效" % valid_count)
        TEST_RESULTS["layer2"].append(("compute_scores", valid_count > 50))

        # 验证排序
        sorted_scores = scores.dropna().sort_values(ascending=False)
        log("  最高分: %.1f, 最低分: %.1f" % (sorted_scores.iloc[0], sorted_scores.iloc[-1]))
        TEST_RESULTS["layer2"].append(("score_ordering", sorted_scores.iloc[0] > sorted_scores.iloc[-1]))

        # 测试正常化函数
        s = pd.Series(np.random.randn(100))
        ns = _normalize(s, reverse=False)
        TEST_RESULTS["layer2"].append(("normalize", abs(ns.mean()) < 0.1))

        ns_r = _normalize(s, reverse=True)
        TEST_RESULTS["layer2"].append(("normalize_reverse", abs(ns_r.mean() + ns.mean()) < 0.2))

    except Exception as e:
        import traceback
        log("  Layer 2 异常: %s" % str(e))
        log("  %s" % traceback.format_exc())
        return False

    passed = all(p[1] for p in TEST_RESULTS["layer2"])
    log("  Layer 2 总体: %s (%d/%d)" % ("PASS" if passed else "FAIL",
         sum(1 for p in TEST_RESULTS["layer2"] if p[1]), len(TEST_RESULTS["layer2"])))
    return passed

# ============================================================
# 执行
# ============================================================
if __name__ == "__main__":
    log("========== MFIC Strategy Test Start ==========")

    l1 = test_layer1()
    l2 = test_layer2()

    log("")
    log("========================================")
    log("  Layer 1 (数据通路): %s" % ("PASS" if l1 else "FAIL"))
    log("  Layer 2 (策略核心): %s" % ("PASS" if l2 else "FAIL"))
    log("========================================")

    if l1 and l2:
        log("  结论: 策略可加载至miniQMT运行")
    else:
        log("  结论: 策略需修复后重新测试")

    log("========== MFIC Strategy Test End ==========")
