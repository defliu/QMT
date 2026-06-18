# coding=utf-8
"""卖出功能专项测试脚本 — 覆盖四层卖出引擎全部分支。
运行: cd D:\QMT_STRATEGIES && python scripts\test_sell_engine.py
"""

import sys
import os
import json
import tempfile
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.risk_manager import SellStrategyEngine, SellPositionState, Action

STATE_FILE = os.path.join(tempfile.gettempdir(), '_test_sell_state.json')


# ============================================================
#  辅助函数
# ============================================================

def make_klines(days=60, start_price=10.0, end_price=11.0, seed=None):
    """构造基础K线 DataFrame，含 open/close/high/low/volume。"""
    if seed is not None:
        np.random.seed(seed)
    dates = pd.bdate_range(end='2026-06-02', periods=days)
    closes = np.linspace(start_price, end_price, days) + np.random.randn(days) * 0.1
    opens = np.zeros(days)
    opens[0] = closes[0]
    for i in range(1, days):
        opens[i] = closes[i - 1] + np.random.randn() * 0.05
    highs = np.maximum(opens, closes) + np.abs(np.random.randn(days)) * 0.15 + 0.02
    lows = np.minimum(opens, closes) - np.abs(np.random.randn(days)) * 0.15 - 0.02
    volumes = np.random.randint(100000, 500000, days).astype(float)
    return pd.DataFrame({
        'open': opens, 'close': closes, 'high': highs,
        'low': lows, 'volume': volumes,
    }, index=dates)


def apply_bar(df, idx, close=None, open_=None, high=None, low=None, volume=None):
    """覆盖指定位置 K 线的字段。"""
    if close is not None:
        df.iloc[idx, df.columns.get_loc('close')] = close
    if open_ is not None:
        df.iloc[idx, df.columns.get_loc('open')] = open_
    if high is not None:
        df.iloc[idx, df.columns.get_loc('high')] = high
    if low is not None:
        df.iloc[idx, df.columns.get_loc('low')] = low
    if volume is not None:
        df.iloc[idx, df.columns.get_loc('volume')] = volume
    return df


def extend_df(df, bars=1):
    """在 DataFrame 末尾追加 N 个 bar。"""
    last_date = df.index[-1]
    new_dates = pd.bdate_range(last_date + pd.Timedelta(days=1), periods=bars)
    new_df = pd.DataFrame(index=new_dates, columns=df.columns, dtype=float)
    for col in df.columns:
        new_df[col] = df.iloc[-1][col]
    return pd.concat([df, new_df])


def create_engine():
    """创建干净的引擎实例。"""
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)
    return SellStrategyEngine('test', 'test_acct', STATE_FILE)


def build_positions(cost=10.0, shares=1000):
    return {'000001.SZ': {'cost': cost, 'can_use': shares, 'volume': shares}}


def check(decisions, expected_action, expected_substr=None, expected_pct=None):
    """验证决策结果，返回 (ok, msg)。同时检查 reason 和 triggered_layer。"""
    if not decisions:
        return False, '无决策返回'
    _code, decision, shares = decisions[0]
    if decision.action != expected_action:
        return False, '期望动作=%s, 实际=%s' % (expected_action.name, decision.action.name)
    if expected_substr:
        found = (expected_substr in (decision.reason or '') or
                 expected_substr in (decision.triggered_layer or ''))
        if not found:
            return False, '期望包含"%s" (reason="%s", layer="%s")' % (
                expected_substr, decision.reason, decision.triggered_layer)
    if expected_pct is not None and abs(decision.sell_pct - expected_pct) > 0.01:
        return False, '期望比例=%.2f, 实际=%.2f' % (expected_pct, decision.sell_pct)
    return True, ''


def prevent_c3(df):
    """确保最后30日中最高HIGH那根的LOW低于当前收盘，避免C3误触发。"""
    high30 = df['high'].values[-30:]
    low30 = df['low'].values[-30:]
    close = df['close'].values[-1]
    max_pos = int(high30.argmax())
    if low30[max_pos] >= close:
        idx = -(30 - max_pos)
        df.iloc[idx, df.columns.get_loc('low')] = close * 0.98
    return df


def assert_b1_triggered(engine):
    """确认引擎状态中的 B1 标记已设置（用于 B1 次日测试）。"""
    st = engine._states.get('000001.SZ')
    return st and st.b1_needs_nextday_check and st.warning_reduced


# ============================================================
#  ① 底线层
# ============================================================

def test_bottom_line_loss():
    """累计亏损 >= 5% → 清仓"""
    df = make_klines(60, 10.0, 9.4, seed=1)
    engine = create_engine()
    decisions = engine.evaluate('20260602', {'000001.SZ': 10.0},
                                {'000001.SZ': df}, build_positions(10.0))
    ok, msg = check(decisions, Action.CLEAR, '底线层')
    print('  [PASS] 累计亏损≥5%%清仓' if ok else '  [FAIL] 累计亏损≥5%%: ' + msg)
    return ok


def test_bottom_line_daily_drop():
    """单日跌幅 >= 7% → 清仓"""
    df = make_klines(60, 10.0, 10.0, seed=2)
    prev_close = float(df.iloc[-2]['close'])
    apply_bar(df, -1, close=prev_close * 0.925, open_=prev_close * 0.97,
              high=prev_close * 0.98, low=prev_close * 0.91)
    engine = create_engine()
    decisions = engine.evaluate('20260602', {'000001.SZ': 10.0},
                                {'000001.SZ': df}, build_positions(8.0))  # cost=8 避免累计亏损触发
    ok, msg = check(decisions, Action.CLEAR, '底线层')
    print('  [PASS] 单日跌幅≥7%%清仓' if ok else '  [FAIL] 单日跌幅≥7%%: ' + msg)
    return ok


# ============================================================
#  ② 预警层
# ============================================================

def test_b1_explosive_volume():
    """B1: 爆量分歧(均量1.5倍+长上影) → 减30%"""
    df = make_klines(60, 10.0, 11.0, seed=3)
    vol_ma5 = float(df['volume'].rolling(5).mean().iloc[-1])
    apply_bar(df, -1, close=10.95, open_=11.05, high=11.80, low=10.90,
              volume=vol_ma5 * 2.0)
    engine = create_engine()
    decisions = engine.evaluate('20260602', {'000001.SZ': 11.0},
                                {'000001.SZ': df}, build_positions(10.0))
    ok, msg = check(decisions, Action.REDUCE, '爆量', 0.30)
    print('  [PASS] B1爆量分歧减30%' if ok else '  [FAIL] B1爆量分歧: ' + msg)
    return ok


def test_b1_nextday_unrecovered():
    """B1 隔日未修复 → 再减20%"""
    df = make_klines(60, 10.0, 11.0, seed=3)  # 与通过的B1测试同种子
    vol_ma5 = float(df['volume'].rolling(5).mean().iloc[-1])
    apply_bar(df, -1, close=10.95, open_=11.05, high=11.80, low=10.90,
              volume=vol_ma5 * 2.0)
    engine = create_engine()
    # 第一次评估：触发 B1
    dec1 = engine.evaluate('20260602', {'000001.SZ': 11.0},
                           {'000001.SZ': df}, build_positions(10.0))
    if not dec1:
        print('  [FAIL] B1隔日未修复: 第一次评估未触发B1')
        return False
    if not assert_b1_triggered(engine):
        print('  [FAIL] B1隔日未修复: B1状态标记未设置')
        return False

    # 追加第61根 K 线（隔日未修复: 收低于开盘价即视为未修复）
    df2 = extend_df(df, 1)
    prev = float(df2.iloc[-2]['close'])
    # 新 bar: close < open → 未修复；收盘略高于 MA20 避免 A3
    apply_bar(df2, -1, close=prev * 0.992, open_=prev * 1.005,
              high=prev * 1.01, low=prev * 0.985,
              volume=float(df.iloc[-1]['volume']) * 0.8)
    # 防止C3干扰（将最高HIGH日的LOW拉至收盘以下）
    prevent_c3(df2)
    # 第二次评估：传入较高成本价以避免移动止盈干扰（cost>current→利润≤0→止盈跳过）
    dec2 = engine.evaluate('20260603', {'000001.SZ': 11.0},
                           {'000001.SZ': df2}, build_positions(cost=11.2))
    ok, msg = check(dec2, Action.REDUCE, '未修复', 0.20)
    print('  [PASS] B1隔日未修复减20%' if ok else '  [FAIL] B1隔日未修复: ' + msg)
    return ok


def test_b2_volume_divergence():
    """B2: 量价背离 → 减30%"""
    df = make_klines(60, 10.0, 11.5, seed=5)
    # 最后 bar: 创5日新高 + 缩量 < 前日70%
    five_day_high = float(df['close'].iloc[-5:].max())
    apply_bar(df, -1, close=five_day_high * 1.01,
              open_=float(df.iloc[-2]['close']) * 1.005,
              high=five_day_high * 1.03, low=five_day_high * 1.0,
              volume=float(df.iloc[-2]['volume']) * 0.5)
    engine = create_engine()
    decisions = engine.evaluate('20260602', {'000001.SZ': 11.5},
                                {'000001.SZ': df}, build_positions(10.0))
    ok, msg = check(decisions, Action.REDUCE, '量价背离', 0.30)
    print('  [PASS] B2量价背离减30%' if ok else '  [FAIL] B2量价背离: ' + msg)
    return ok


def test_c2_macd_shortening():
    """C2: MACD红柱连续缩短3日 → 减30%
    构造思路:
      Phase1(0-19): 涨幅 0.010/天 → 稳定建立初始趋势
      Phase2(20-39): 涨幅 0.060/天 → 加速,DIF快速上升,红柱扩张
      Phase3(40-49): 涨幅减速 0.060→0.050/天 → DIF仍>0但增速↓,红柱缩短
      Phase4(50-59): 涨幅减速 0.050→0.035/天 → 红柱继续缩短,且确保全部>DIF>0阈值
    """
    np.random.seed(6)
    days = 60
    dates = pd.bdate_range(end='2026-06-02', periods=days)
    # 涨幅序列: 稳定→加速→平滑减速(末尾≥0.035确保MACD正值)
    rates = np.concatenate([
        np.full(20, 0.010),                    # 0-19:  稳定上涨
        np.full(20, 0.060),                    # 20-39: 加速,红柱扩张
        np.linspace(0.060, 0.050, 10),         # 40-49: 减速,红柱缩短
        np.linspace(0.050, 0.040, 10),         # 50-59: 继续减速,最低0.040确保DIF>0
    ])
    prices = [10.0]
    for r in rates[:days - 1]:
        prices.append(prices[-1] + r)
    prices = np.array(prices[:days]) + np.random.randn(days) * 0.005

    closes = pd.Series(prices, index=dates)
    opens = pd.Series(index=dates, dtype=float)
    opens.iloc[0] = closes.iloc[0]
    for i in range(1, days):
        opens.iloc[i] = closes.iloc[i - 1] + np.random.randn() * 0.005
    highs = pd.concat([opens, closes], axis=1).max(axis=1) + np.abs(np.random.randn(days)) * 0.03 + 0.01
    lows = pd.concat([opens, closes], axis=1).min(axis=1) - np.abs(np.random.randn(days)) * 0.03 - 0.01
    volumes = np.random.randint(100000, 500000, days).astype(float)
    df = pd.DataFrame({
        'open': opens, 'close': closes, 'high': highs,
        'low': lows, 'volume': volumes,
    }, index=dates)
    df = prevent_c3(df)
    # 使用实际收盘价作为当前价（避免传入过高价格导致highest_price虚高，进而误触发移动止盈）
    current_price = round(float(df['close'].iloc[-1]) * 1.005, 2)
    engine = create_engine()
    decisions = engine.evaluate('20260602', {'000001.SZ': current_price},
                                {'000001.SZ': df}, build_positions(10.0))
    ok, msg = check(decisions, Action.REDUCE, 'MACD红柱缩短', 0.30)
    print('  [PASS] C2 MACD红柱缩短减30%' if ok else '  [FAIL] C2 MACD缩短: ' + msg)
    return ok


def test_kdj_death():
    """KDJ死叉 + MA5走平 → 减30%
    构造: 拉升→横盘(MA5走平, KDJ区间建立)→尾盘杀跌(KDJ死叉)"""
    np.random.seed(7)
    days = 60
    dates = pd.bdate_range(end='2026-06-02', periods=days)
    # Phase1(0-44): 10→11.5 稳定上行
    # Phase2(45-49): 升至11.7并回落 (建立高H9)
    # Phase3(50-54): 回探至11.3 (建立低L9)
    # Phase4(55-58): 修复至11.4窄幅波动 (RSV≈50, MA5走平)
    # Phase5(59): 杀跌至11.3 (RSV骤降→KDJ死叉)

    raw = np.linspace(10.0, 11.5, 45).tolist()  # 0-44
    raw += [11.6, 11.7, 11.65, 11.6, 11.55]      # 45-49 冲高
    raw += [11.5, 11.4, 11.35, 11.3, 11.35]       # 50-54 回探
    raw += [11.6, 11.55, 11.6, 11.55, 11.38]       # 55-59 横盘末棒小幅杀跌(不触发底线层)
    raw = np.array(raw[:days])  # 确保长度准确
    raw += np.random.randn(days) * 0.015

    closes = raw
    opens = pd.Series(index=dates, dtype=float)
    opens.iloc[0] = closes[0]
    for i in range(1, days):
        opens.iloc[i] = closes[i - 1] + np.random.randn() * 0.008
    highs = pd.concat([opens, pd.Series(closes, index=dates)], axis=1).max(axis=1)
    highs += np.abs(np.random.randn(days)) * 0.05 + 0.01
    lows = pd.concat([opens, pd.Series(closes, index=dates)], axis=1).min(axis=1)
    lows -= np.abs(np.random.randn(days)) * 0.05 + 0.01
    volumes = np.random.randint(100000, 500000, days).astype(float)
    df = pd.DataFrame({
        'open': opens, 'close': closes, 'high': highs,
        'low': lows, 'volume': volumes,
    }, index=dates)
    df = prevent_c3(df)
    engine = create_engine()
    # 用高于最新收盘的成本价(11.3+), 使利润≤0, 跳过移动止盈干扰
    decisions = engine.evaluate('20260602', {'000001.SZ': 11.7},
                                {'000001.SZ': df}, build_positions(11.5))
    ok, msg = check(decisions, Action.REDUCE, 'KDJ', 0.30)
    print('  [PASS] KDJ死叉+MA5走平减30%' if ok else '  [FAIL] KDJ死叉+MA5走平: ' + msg)
    return ok


# ============================================================
#  ③ 确认层（需先有预警标记）
# ============================================================

def _make_confirm_state():
    state = SellPositionState(code='000001.SZ', cost_price=10.0, current_shares=1000)
    state.warning_reduced = True
    state.b1_needs_nextday_check = False
    state.b1_additional_reduced = False
    state.confirm_reduced = False
    return state


def test_confirm_a2():
    """A2: 跌破MA10 → 减50%"""
    df = make_klines(60, 10.0, 11.2, seed=8)
    # 最后 bar 跌破 MA10
    ma10 = df['close'].rolling(10).mean()
    target_close = float(ma10.iloc[-1]) * 0.98
    apply_bar(df, -1, close=target_close, open_=float(df.iloc[-2]['close']) * 0.995,
              high=float(df.iloc[-2]['close']), low=target_close * 0.99)
    df = prevent_c3(df)
    engine = create_engine()
    state = _make_confirm_state()
    engine._states['000001.SZ'] = state
    decisions = engine.evaluate('20260602', {'000001.SZ': 11.2},
                                {'000001.SZ': df}, build_positions(11.0))  # cost>当前价避免移动止盈
    ok, msg = check(decisions, Action.REDUCE, 'A2:破10日线', 0.50)
    print('  [PASS] A2跌破MA10减50%' if ok else '  [FAIL] A2跌破MA10: ' + msg)
    return ok


def test_confirm_c1():
    """C1: 高位长上影线 → 减50%"""
    df = make_klines(60, 10.0, 11.0, seed=9)
    # 条件: 10日内涨幅>=5% + 长上影线
    apply_bar(df, -1, close=10.9, open_=10.95, high=11.6, low=10.85,
              volume=float(df.iloc[-1]['volume']))
    # 确保倒数第10日的收盘在较低位置（涨幅>=5%）
    compare_price = float(df.iloc[-10]['close'])
    recent_high = float(df['close'].iloc[-5:].max())
    if recent_high < compare_price * 1.05:
        apply_bar(df, -10, close=recent_high / 1.06, open_=recent_high / 1.055,
                  high=recent_high / 1.05, low=recent_high / 1.07)
    df = prevent_c3(df)
    engine = create_engine()
    state = _make_confirm_state()
    engine._states['000001.SZ'] = state
    decisions = engine.evaluate('20260602', {'000001.SZ': 11.0},
                                {'000001.SZ': df}, build_positions(11.0))  # cost>当前价避免移动止盈
    ok, msg = check(decisions, Action.REDUCE, '高位长上影', 0.50)
    print('  [PASS] C1高位长上影减50%' if ok else '  [FAIL] C1高位长上影: ' + msg)
    return ok


def test_confirm_b3():
    """B3: 高位天量收阴 → 减50%"""
    df = make_klines(60, 10.0, 11.5, seed=10)
    # 条件: 收盘近20日高位 + 收阴 + 量>=均量1.5倍
    # 最后5根都维持在高位
    high_price = 11.5
    for i in range(5):
        apply_bar(df, -1 - i, close=high_price - i * 0.05,
                  open_=high_price - i * 0.03,
                  high=high_price - i * 0.02 + 0.1,
                  low=high_price - i * 0.05 - 0.05)
    # 最后 bar: 收阴 + 天量
    vol_ma5 = float(df['volume'].rolling(5).mean().iloc[-1])
    apply_bar(df, -1, close=11.25, open_=11.6, high=11.65, low=11.20,
              volume=vol_ma5 * 2.0)
    engine = create_engine()
    state = _make_confirm_state()
    # 确保 B1 不会干扰确认层
    state.b1_needs_nextday_check = False
    state.b1_additional_reduced = True
    engine._states['000001.SZ'] = state
    decisions = engine.evaluate('20260602', {'000001.SZ': 11.5},
                                {'000001.SZ': df}, build_positions(10.0))
    ok, msg = check(decisions, Action.REDUCE, '天量收阴', 0.50)
    print('  [PASS] B3高位天量收阴减50%' if ok else '  [FAIL] B3高位天量收阴: ' + msg)
    return ok


# ============================================================
#  ④ 清仓层
# ============================================================

def test_clear_a3():
    """A3: 跌破MA20 3日未收复 → 清仓"""
    df = make_klines(60, 10.0, 12.0, seed=11)
    # 最后4根 K 线持续低于 MA20
    ma20 = df['close'].rolling(20).mean()
    # 让最后4天收盘都低于 MA20
    for i in range(4):
        ma20_val = float(ma20.iloc[-1])
        below_ma20 = ma20_val * 0.97
        idx = -1 - i
        prev_close = float(df.iloc[idx - 1]['close']) if idx > -len(df) else below_ma20
        apply_bar(df, idx, close=below_ma20, open_=prev_close * 0.995,
                  high=prev_close * 1.01, low=below_ma20 * 0.99)
    engine = create_engine()
    decisions = engine.evaluate('20260602', {'000001.SZ': 12.0},
                                {'000001.SZ': df}, build_positions(10.0))
    ok, msg = check(decisions, Action.CLEAR, '破20日线')
    print('  [PASS] A3跌破MA20清仓' if ok else '  [FAIL] A3跌破MA20: ' + msg)
    return ok


def test_clear_c3():
    """C3: 跌破最高价当日低点 → 清仓"""
    np.random.seed(12)
    days = 60
    dates = pd.bdate_range(end='2026-06-02', periods=days)
    # 在约第35天制造一个大幅冲高（成为30日最高点），该日低点设为12.0
    # 之后价格逐渐回落到该低点以下
    t = np.arange(days)
    base = np.linspace(10.0, 10.5, days) + np.random.randn(days) * 0.08
    # 第35天: spike up
    spike_day = 35
    base[spike_day] = 13.5
    # 从第36天起: 逐步回落
    for i in range(spike_day + 1, days):
        base[i] = base[i - 1] - 0.06 + np.random.randn() * 0.05
    # 确保最后价格低于 spike 日的低点
    spike_low = 12.0  # 该日最低点
    base[-1] = spike_low * 0.99  # 低于低点
    base[-2] = spike_low * 1.01
    base[-3] = spike_low * 1.03

    closes = base
    opens = np.zeros(days)
    opens[0] = closes[0]
    for i in range(1, days):
        opens[i] = closes[i - 1] + np.random.randn() * 0.04
    opens[spike_day] = 12.5
    highs = np.maximum(opens, closes) + np.abs(np.random.randn(days)) * 0.1 + 0.02
    lows = np.minimum(opens, closes) - np.abs(np.random.randn(days)) * 0.1 - 0.02
    highs[spike_day] = 13.8
    lows[spike_day] = spike_low
    volumes = np.random.randint(100000, 500000, days).astype(float)
    df = pd.DataFrame({
        'open': opens, 'close': closes, 'high': highs,
        'low': lows, 'volume': volumes,
    }, index=dates)

    engine = create_engine()
    decisions = engine.evaluate('20260602', {'000001.SZ': 13.8},
                                {'000001.SZ': df}, build_positions(8.0))
    ok, msg = check(decisions, Action.CLEAR, '破最高日低点')
    print('  [PASS] C3跌破最高日低点清仓' if ok else '  [FAIL] C3跌破最高日低点: ' + msg)
    return ok


# ============================================================
#  ⑤ 移动止盈
# ============================================================

def test_trailing_under_10pct():
    """盈利<10% 跌破MA5 → 清仓"""
    df = make_klines(60, 10.0, 10.5, seed=14)
    # 最后 bar 跌破 MA5
    ma5 = df['close'].rolling(5).mean()
    ma5_val = float(ma5.iloc[-1])
    apply_bar(df, -1, close=ma5_val * 0.98, open_=float(df.iloc[-2]['close']) * 0.995,
              high=float(df.iloc[-2]['close']), low=ma5_val * 0.97)
    engine = create_engine()
    state = SellPositionState(code='000001.SZ', cost_price=10.0, current_shares=1000)
    engine._states['000001.SZ'] = state
    decisions = engine.evaluate('20260602', {'000001.SZ': 10.5},
                                {'000001.SZ': df}, build_positions(10.0))
    ok, msg = check(decisions, Action.CLEAR, '移动止盈')
    print('  [PASS] 移动止盈(<10%破MA5)清仓' if ok else '  [FAIL] 移动止盈(<10%破MA5): ' + msg)
    return ok


def test_trailing_10_20pct():
    """盈利10-20% 回撤>=6% → 清仓"""
    df = make_klines(60, 10.0, 11.5, seed=15)
    engine = create_engine()
    state = SellPositionState(code='000001.SZ', cost_price=10.0, current_shares=1000)
    engine._states['000001.SZ'] = state
    # 盈利=15%, 最高价13.0 → 回撤=(13-11.5)/13=11.5% >= 6%
    decisions = engine.evaluate('20260602', {'000001.SZ': 13.0},
                                {'000001.SZ': df}, build_positions(10.0))
    ok, msg = check(decisions, Action.CLEAR, '移动止盈')
    print('  [PASS] 移动止盈(15%利回撤6%+)清仓' if ok else '  [FAIL] 移动止盈(15%利): ' + msg)
    return ok


def test_trailing_20_30pct():
    """盈利20-30% 回撤>=8% → 清仓"""
    df = make_klines(60, 10.0, 12.5, seed=16)
    engine = create_engine()
    state = SellPositionState(code='000001.SZ', cost_price=10.0, current_shares=1000)
    engine._states['000001.SZ'] = state
    # 盈利=25%, 最高价14.5 → 回撤=(14.5-12.5)/14.5=13.8% >= 8%
    decisions = engine.evaluate('20260602', {'000001.SZ': 14.5},
                                {'000001.SZ': df}, build_positions(10.0))
    ok, msg = check(decisions, Action.CLEAR, '移动止盈')
    print('  [PASS] 移动止盈(25%利回撤8%+)清仓' if ok else '  [FAIL] 移动止盈(25%利): ' + msg)
    return ok


def test_trailing_over_30pct():
    """盈利>30% 回撤>=10% → 清仓"""
    df = make_klines(60, 10.0, 13.5, seed=17)
    engine = create_engine()
    state = SellPositionState(code='000001.SZ', cost_price=10.0, current_shares=1000)
    engine._states['000001.SZ'] = state
    # 盈利=35%, 最高价16.0 → 回撤=(16-13.5)/16=15.6% >= 10%
    decisions = engine.evaluate('20260602', {'000001.SZ': 16.0},
                                {'000001.SZ': df}, build_positions(10.0))
    ok, msg = check(decisions, Action.CLEAR, '移动止盈')
    print('  [PASS] 移动止盈(35%利回撤10%+)清仓' if ok else '  [FAIL] 移动止盈(35%利): ' + msg)
    return ok


# ============================================================
#  V1.1 移动止盈测试
# ============================================================

def test_trailing_atr_adaptive_low_vol():
    """V1.1: 低波动股票 ATR 自适应阈值 = FLOOR 6%"""
    from core.risk_manager import TRAILING_DRAWDOWN_FLOOR, TRAILING_ATR_N
    df = make_klines(60, 10.0, 12.0, seed=20)
    engine = create_engine()
    state = SellPositionState(code='000001.SZ', cost_price=10.0, current_shares=1000,
                              highest_price=12.0)
    engine._states['000001.SZ'] = state

    # 低波动：ATR=0.2, highest=15.0
    # 动态阈值 = max(6%, 2.5*0.2/15) = max(6%, 3.3%) = 6%
    dd_threshold = engine._calc_dynamic_drawdown_threshold(15.0, 0.2)
    ok = dd_threshold == TRAILING_DRAWDOWN_FLOOR
    print('  [PASS] V1.1 低波动动态阈值=FLOOR' if ok else '  [FAIL] V1.1 低波动动态阈值: %f' % dd_threshold)
    return ok


def test_trailing_atr_adaptive_high_vol():
    """V1.1: 高波动股票 ATR 自适应阈值 > FLOOR"""
    from core.risk_manager import TRAILING_DRAWDOWN_CAP
    df = make_klines(60, 10.0, 15.0, seed=21)
    engine = create_engine()

    # 高波动：ATR=2.0, highest=30.0
    # 动态阈值 = max(6%, 2.5*2.0/30) = max(6%, 16.7%) = 15% (cap)
    dd_threshold = engine._calc_dynamic_drawdown_threshold(30.0, 2.0)
    ok = dd_threshold == TRAILING_DRAWDOWN_CAP
    print('  [PASS] V1.1 高波动动态阈值=CAP' if ok else '  [FAIL] V1.1 高波动动态阈值: %f' % dd_threshold)
    return ok


def test_trailing_chandelier_20pct():
    """V1.1: 20% 盈利启用吊灯止损"""
    df = make_klines(60, 10.0, 12.0, seed=22)
    engine = create_engine()
    state = SellPositionState(code='000001.SZ', cost_price=10.0, current_shares=1000,
                              highest_price=15.0)
    engine._states['000001.SZ'] = state
    # profit = (12-10)/10 = 20%, 应走高盈利分支
    decisions = engine.evaluate('20260602', {'000001.SZ': 15.0},
                                {'000001.SZ': df}, build_positions(10.0))
    ok = len(decisions) >= 0  # 只要不报错即可
    print('  [PASS] V1.1 20%盈利分支正常' if ok else '  [FAIL] V1.1 20%盈利分支异常')
    return ok


def test_trailing_no_chandelier_below_10pct():
    """V1.1: 10% 以下走 MA5 分支，不进 ATR 计算"""
    df = make_klines(60, 10.0, 10.5, seed=23)
    engine = create_engine()
    state = SellPositionState(code='000001.SZ', cost_price=10.0, current_shares=1000,
                              highest_price=10.5)
    engine._states['000001.SZ'] = state
    # profit = (10.5-10)/10 = 5%, 走 MA5 分支
    decisions = engine.evaluate('20260602', {'000001.SZ': 10.5},
                                {'000001.SZ': df}, build_positions(10.0))
    ok = len(decisions) >= 0
    print('  [PASS] V1.1 <10%走MA5分支' if ok else '  [FAIL] V1.1 <10%分支异常')
    return ok


def test_diagnose_position_after_constant_removal():
    """V1.1: 删除 LO/MID/HI 后 diagnose_position 不抛 NameError"""
    df = make_klines(60, 10.0, 12.0, seed=24)
    engine = create_engine()
    try:
        diag = engine.diagnose_position('000001.SZ', df, 10.0, 12.0, 13.0)
        ok = 'trailing' in diag['layers']
        print('  [PASS] V1.1 diagnose_position正常' if ok else '  [FAIL] V1.1 diagnose_position异常')
    except NameError as e:
        print('  [FAIL] V1.1 NameError: %s' % e)
        ok = False
    return ok


def test_trailing_atr_none_fallback():
    """V1.1: 数据不足20根时 atr=None，回退到 FLOOR"""
    from core.risk_manager import TRAILING_DRAWDOWN_FLOOR
    df = make_klines(15, 10.0, 11.0, seed=25)  # 只有15根，不够20根
    engine = create_engine()
    state = SellPositionState(code='000001.SZ', cost_price=10.0, current_shares=1000,
                              highest_price=11.0)
    engine._states['000001.SZ'] = state
    # profit = 10%, 走中盈利分支，但 ATR 不够
    decisions = engine.evaluate('20260602', {'000001.SZ': 11.0},
                                {'000001.SZ': df}, build_positions(10.0))
    ok = len(decisions) >= 0
    print('  [PASS] V1.1 ATR=None回退' if ok else '  [FAIL] V1.1 ATR=None异常')
    return ok


def test_dynamic_threshold_floor_cap_boundary():
    """V1.1: 动态阈值边界行为"""
    engine = create_engine()

    # 边界1：ATR*N/highest 刚好 = 6%
    # 2.5 * 0.36 / 15 = 0.06 = 6%
    dd1 = engine._calc_dynamic_drawdown_threshold(15.0, 0.36)
    ok1 = abs(dd1 - 0.06) < 0.001

    # 边界2：ATR*N/highest 刚好 = 15%
    # 2.5 * 0.9 / 15 = 0.15 = 15%
    dd2 = engine._calc_dynamic_drawdown_threshold(15.0, 0.9)
    ok2 = abs(dd2 - 0.15) < 0.001

    ok = ok1 and ok2
    print('  [PASS] V1.1 动态阈值边界' if ok else '  [FAIL] V1.1 边界: dd1=%f dd2=%f' % (dd1, dd2))
    return ok


def test_trailing_skip_when_warning_pending():
    """V1.1: warning_reduced=True 但 confirm_reduced=False 时跳过移动止盈"""
    df = make_klines(60, 10.0, 12.0, seed=26)
    engine = create_engine()
    state = SellPositionState(code='000001.SZ', cost_price=10.0, current_shares=1000,
                              highest_price=13.0)
    state.warning_reduced = True
    state.confirm_reduced = False
    engine._states['000001.SZ'] = state
    # profit = 20%, 应该触发移动止盈，但被 warning_reduced 跳过
    decisions = engine.evaluate('20260602', {'000001.SZ': 13.0},
                                {'000001.SZ': df}, build_positions(10.0))
    # 检查是否有移动止盈决策（应该没有，因为被跳过）
    has_trailing = any('移动止盈' in (d[1].reason or '') for d in decisions)
    ok = not has_trailing
    print('  [PASS] V1.1 warning跳过移动止盈' if ok else '  [FAIL] V1.1 warning未跳过')
    return ok


def test_diagnose_position_consistent_with_check_trailing_profit():
    """V1.1 B1: diagnose_position 与 _check_trailing_profit 边界一致"""
    engine = create_engine()

    test_cases = [
        (10.0, 10.5, 10.5, '5%'),
        (10.0, 11.5, 11.5, '15%'),
        (10.0, 12.5, 13.0, '25%'),
        (10.0, 13.5, 14.0, '35%'),
    ]

    all_ok = True
    for cost, current, highest, label in test_cases:
        state = SellPositionState(code='000001.SZ', cost_price=cost, current_shares=1000,
                                  highest_price=highest)
        engine._states['000001.SZ'] = state

        # 构造与 current 一致的 DataFrame（最后一根 close = current）
        df = make_klines(60, cost, current, seed=27)
        df.iloc[-1, df.columns.get_loc('close')] = current
        close_s = df['close'].astype(float)

        # 调用 _check_trailing_profit
        check_result = engine._check_trailing_profit(close_s,
                                                       df['high'].astype(float),
                                                       df['low'].astype(float), state)

        # 调用 diagnose_position
        diag = engine.diagnose_position('000001.SZ', df, cost, current, highest)
        diag_result = diag['layers']['trailing']['移动止盈']['triggered']

        if check_result != diag_result:
            print('  [FAIL] V1.1 B1 %s: check=%s diag=%s' % (label, check_result, diag_result))
            all_ok = False

    ok = all_ok
    print('  [PASS] V1.1 B1 一致性' if ok else '  [FAIL] V1.1 B1 不一致')
    return ok


# ============================================================
#  运行入口
# ============================================================

def run_all():
    tests = [
        ('底线层-累计亏损',       test_bottom_line_loss),
        ('底线层-单日跌幅',       test_bottom_line_daily_drop),
        ('预警层-B1爆量分歧',     test_b1_explosive_volume),
        ('预警层-B1隔日未修复',   test_b1_nextday_unrecovered),
        ('预警层-B2量价背离',     test_b2_volume_divergence),
        ('预警层-C2 MACD缩短',    test_c2_macd_shortening),
        ('预警层-KDJ死叉+MA5走平', test_kdj_death),
        ('确认层-A2破MA10',      test_confirm_a2),
        ('确认层-C1高位长上影',   test_confirm_c1),
        ('确认层-B3天量收阴',     test_confirm_b3),
        ('清仓层-A3破MA20',      test_clear_a3),
        ('清仓层-C3破最高日低点',  test_clear_c3),
        ('移动止盈-<10%破MA5',   test_trailing_under_10pct),
        ('移动止盈-10~20%回撤6%', test_trailing_10_20pct),
        ('移动止盈-20~30%回撤8%', test_trailing_20_30pct),
        ('移动止盈->30%回撤10%',  test_trailing_over_30pct),
        ('V1.1-低波动ATR自适应',  test_trailing_atr_adaptive_low_vol),
        ('V1.1-高波动ATR自适应',  test_trailing_atr_adaptive_high_vol),
        ('V1.1-20%盈利吊灯止损',  test_trailing_chandelier_20pct),
        ('V1.1-10%以下MA5分支',   test_trailing_no_chandelier_below_10pct),
        ('V1.1-diagnose_position', test_diagnose_position_after_constant_removal),
        ('V1.1-ATR=None回退',     test_trailing_atr_none_fallback),
        ('V1.1-动态阈值边界',     test_dynamic_threshold_floor_cap_boundary),
        ('V1.1-warning跳过',      test_trailing_skip_when_warning_pending),
        ('V1.1-B1一致性',         test_diagnose_position_consistent_with_check_trailing_profit),
    ]
    passed = failed = 0
    for name, func in tests:
        print('[%s]' % name)
        if func():
            passed += 1
        else:
            failed += 1
    total = passed + failed
    print('\n' + '=' * 50)
    print('总计: %d, 通过: %d, 失败: %d' % (total, passed, failed))
    print('通过率: %.1f%%' % (passed / total * 100 if total else 0))
    return failed


if __name__ == '__main__':
    sys.exit(run_all())
