# coding=utf-8
"""strategy_mfic.py 模拟运行日志演示（不使用QMT ContextInfo）"""
import sys, os
sys.path.insert(0, 'D:/QMT_STRATEGIES')
os.chdir('D:/QMT_STRATEGIES')
import warnings; warnings.filterwarnings('ignore')

from strategy_mfic import _normalize, _compute_scores, _get_market_time, _is_rebalance_day, _read_positions
import numpy as np, pandas as pd

print("=" * 55)
print("  strategy_mfic.py 模拟运行日志")
print("  本演示模拟QMT handlebar内的完整流程")
print("  实际QMT运行时，C.get_market_data_ex() 返回真实数据")
print("=" * 55)
print()

# ===== 1. 策略初始化 =====
print("[MF] ========== 策略初始化 ==========")
print("[MF] 多因子IC策略 初始化完成")
print("[MF] 本金: 100000元 | 单票上限: 2% | 止损: -12%")
print("[MF] 调仓: 双月 | TOP80 | 市值: 0-30亿 | 成交额>2000万")
print("[MF] 持仓文件: D:/QMT_POOL/mfic_positions.json")
print("[MF] =============================================")
print()

# ===== 2. 读取当前持仓 =====
positions = _read_positions()
print("[MF] 当前持仓: %d只" % len(positions))
if positions:
    for code in list(positions.keys())[:3]:
        p = positions[code]
        print("    %s: %d股, 入场%.2f, 日期%s" % (code, p["shares"], p["entry_price"], p["buy_date"]))
print()

# ===== 3. 模拟调仓日数据获取和评分 =====
print("[MF] ========== 调仓日流程模拟 ==========")
print("[MF] 调仓日: 2026-08-31 (偶数月最后一个交易日)")
print("[MF] 时间: 14:50 (尾盘交易窗口)")

# 模拟评分：用随机数据演示正常化 + 评分逻辑
np.random.seed(42)
n = 100
mock_data = pd.DataFrame({
    "pb": np.random.uniform(2, 100, n),
    "momentum_1m": np.random.uniform(-0.3, 0.3, n),
    "volatility_60d": np.random.uniform(0.1, 0.5, n),
    "ROE": np.random.uniform(-10, 30, n),
}, index=["%06d.SZ" % i for i in range(n)])

scores = _compute_scores(mock_data)
valid = scores.dropna()
print("[MF] 候选股: %d只有效评分" % len(valid))
print("[MF] 选中TOP 80只:")
print("[MF]   第1名: 000001.SZ 总分=%.1f" % valid.max())
print("[MF]   第2名: 000002.SZ 总分=%.1f" % valid.sort_values(ascending=False).iloc[1])
print("[MF]   第3名: 000003.SZ 总分=%.1f" % valid.sort_values(ascending=False).iloc[2])
print("[MF]   ...(共80只)")
print("[MF]   第80名: 总分=%.1f" % valid.sort_values(ascending=False).iloc[79])
print()

# ===== 4. 模拟止损检查 =====
print("[MF] ========== 止损检查模拟 ==========")
print("[MF] 假设当前持仓:")
print("    000001.SZ: 入场13.50 -> 现价11.80 (跌幅-12.6% -> 触发止损!)")
print("    000002.SZ: 入场8.20 -> 现价8.50 (涨幅+3.7% -> 正常)")
print("    600519.SH: 入场1800.00 -> 现价1950.00 (涨幅+8.3% -> 正常)")
print("[MF] 止损触发 000001.SZ: 入场13.50 现价11.80 跌幅-12.6%")
print("[MF] 止损卖出 000001.SZ 100股")
print("[MF] 找替代票: 000010.SZ (评分排名第81, 不在持仓)")
print("[MF] 买入 000010.SZ 50股 替代止损票")
print("[MF] 持仓更新: 80只 (1替换)")
print()

# ===== 5. 模拟下单 =====
print("[MF] ========== 调仓下单模拟 ==========")
print("[MF] 持仓文件: D:/QMT_POOL/mfic_positions.json")
print("[MF] 单票上限: 2000元/只 (10万x2%%)")
print("[MF] 预留现金: 2% (2000元)")
print("[MF] 可用资金: 98000元, 分80只 = 1225元/只(均价)")

print("[MF] 卖出操作:")
print("    [下单] 卖出 000005.SZ 100股 (不在新池)")
print("    [下单] 卖出 000007.SZ 200股 (不在新池)")
print("    (共卖出10只, 回收约18000元)")

print("[MF] 买入操作:")
print("    [下单] 买入 000001.SZ 13.50x100股=1350元")
print("    [下单] 买入 000002.SZ 8.20x200股=1640元")
print("    [下单] 买入 000003.SZ 15.80x100股=1580元")
print("    ...(共买入80只, 总金额约97800元)")
print()

# ===== 6. 模拟正常日（非调仓日） =====
print("[MF] ========== 非调仓日 (2026-09-01) ==========")
print("[MF] is_last_bar: True")
print("[MF] 当前时间: 2026-09-01 14:45:00")
print("[MF] 是否调仓日: False (9月非偶数月)")
print("[MF] 止损检查: 所有持仓>止损线, 无操作")
print("[MF] handlebar 完成")
print()

# ===== 7. 验证正常化函数 =====
print("[MF] ========== 核心函数验证 ==========")
s = pd.Series(np.random.randn(1000))
ns = _normalize(s)
print("[MF] _normalize: 均值=%.6f, 标准差=%.2f (期望: 均值≈0, 标准差≈1)" % (ns.mean(), ns.std()))
ns_r = _normalize(s, reverse=True)
print("[MF] _normalize(reverse): 均值=%.6f (期望: 与正向值相反)" % (ns_r.mean() + ns.mean()))

print()
print("=" * 55)
print("  模拟运行完成")
print("  说明: 实际QMT运行时, C.get_market_data_ex()")
print("  返回真实行情数据, 所有日志前缀为 [MF]")
print("  持仓文件自动创建在 D:/QMT_POOL/mfic_positions.json")
print("  下单使用 passorder(strRemark='mfic')")
print("=" * 55)
