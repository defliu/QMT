# coding: utf-8
"""DeepSeek 策略单测：信号逻辑 + PIT 安全 + 卖出规则 + 决策 schema。

不依赖 DuckDB / 真实行情，全部用合成 DataFrame，确定性可复现。
"""

import numpy as np
import pandas as pd
import pytest

from backtest.strategies import get_strategy, list_strategies
from backtest.strategies.research.deepseek.factors import (
    compute_indicators, extract_signal_row,
)
from backtest.strategies.research.deepseek.decision import assemble_decision


# ---------------- 合成行情 ----------------

def _bullish_df(n=120, seed=1):
    """构造满足 V4 全条件的合成行情：平底 + 末段 5 日急拉。

    V4 条件互斥约束：slope5>=2.5（MA5 五日涨>=12.5%）与 gain_from_ma60<30
    （close 不离 MA60 太远）互相拉扯。解法：前段真·平底（ma5_prev≈base，
    slope5 易达标；ma60≈base，gain 不超），末 5 日 +4.5%/日急拉。
    """
    rng = np.random.RandomState(seed)
    closes = np.empty(n)
    closes[:n - 5] = 10.0                      # 前 n-5 日平底
    for i in range(n - 5, n):
        closes[i] = closes[i - 1] * 1.045      # 末 5 日 +4.5%/日
    # 平底段做阳线（open 微低于 close）保证阳线比例；末段自然阳线
    opens = closes * (1.0 - rng.uniform(0, 0.002, n))
    highs = np.maximum(closes, opens) * (1.0 + rng.uniform(0.001, 0.003, n))
    lows = opens * (1.0 - rng.uniform(0, 0.003, n))      # 回踩不破 MA5*0.98
    vols = np.full(n, 1e6)
    vols[-1] = 2.5e6                                     # 仅末日放量 → 量比 2.5
    dates = pd.date_range("2024-01-01", periods=n, freq="B").strftime("%Y-%m-%d")
    df = pd.DataFrame({
        "date": dates, "open": opens, "high": highs, "low": lows,
        "close": closes, "vol": vols, "amount": closes * vols,
        "turnover_rate": np.full(n, 5.0),    # 落在 3-10
        "circ_mv": np.full(n, 100.0 * 1e4),  # 100 亿
        "is_st": np.zeros(n),
        "listed_days": np.full(n, 365),
        "adj_factor": np.ones(n),
    })
    return df


def _bearish_df(n=120):
    """构造一个下行行情（不满足多头）。"""
    closes = 10.0 * np.exp(-np.linspace(0, 0.5, n))
    df = _bullish_df(n)
    df["close"] = closes
    df["open"] = closes * 1.005
    df["high"] = df["open"] * 1.005
    df["low"] = closes * 0.995
    return df


# ---------------- 指标 ----------------

def test_compute_indicators_columns():
    df = compute_indicators(_bullish_df())
    for col in ("ma5", "ma10", "ma20", "ma60", "slope5", "yang_ratio_10",
                "gain_from_ma60", "eff_ratio_10", "vol_ratio_spec", "circ_mv_yi"):
        assert col in df.columns
    # ma60 前 59 行 NaN
    assert df["ma60"].isna().sum() == 59


def test_circ_mv_yi_unit():
    """circ_mv 单位万元 → 亿 = /10000。100 亿 = 1e6 万。"""
    df = compute_indicators(_bullish_df())
    assert abs(df["circ_mv_yi"].iloc[-1] - 100.0) < 1e-6


# ---------------- 信号 ----------------

def test_bullish_signal_passes_v4():
    df = compute_indicators(_bullish_df())
    cfg = {"enable": {}}  # V4 全开
    passed, score, debug = extract_signal_row(df, cfg)
    assert passed is True
    assert score > 0


def test_bearish_signal_fails():
    df = compute_indicators(_bearish_df())
    cfg = {"enable": {}}
    passed, score, debug = extract_signal_row(df, cfg)
    assert passed is False


def test_v0_relaxes_slope():
    """V0 不启用 B(斜率)：把 slope 拉低，V4 失败但 V0 仍可能通过。"""
    df = compute_indicators(_bullish_df())
    # 篡改 slope5 为 0（模拟斜率不达标）
    df["slope5"] = 0.0
    passed_v4, _, _ = extract_signal_row(df, {"enable": {}})
    assert passed_v4 is False
    passed_v0, _, _ = extract_signal_row(
        df, {"enable": {"B": False, "C": False, "E": False, "F": False,
                        "G": False, "H": False, "I": False, "J": False}})
    assert passed_v0 is True


def test_st_filter():
    df = compute_indicators(_bullish_df())
    df.loc[df.index[-1], "is_st"] = 1
    passed, _, debug = extract_signal_row(df, {"enable": {}})
    assert passed is False
    assert debug["reason"] == "st"


def test_new_stock_filter():
    df = compute_indicators(_bullish_df())
    df.loc[df.index[-1], "listed_days"] = 30
    passed, _, debug = extract_signal_row(df, {"enable": {}})
    assert passed is False
    assert debug["reason"] == "new_stock"


# ---------------- PIT 安全 ----------------

def test_pit_no_lookahead():
    """信号在 T 日不应被 T+1 之后的数据影响。

    构造 T 日满足信号的行情，然后在 T+1 之后插入暴涨/暴跌，
    T 日的信号结果应保持不变。
    """
    df = compute_indicators(_bullish_df(n=120))
    cfg = {"enable": {}}
    passed_t, score_t, _ = extract_signal_row(df, cfg)

    # 在末尾追加 20 行极端行情
    extra = _bullish_df(n=20, seed=99)
    extra["close"] = df["close"].iloc[-1] * np.array([5.0] * 20)  # 暴涨 5 倍
    df2 = pd.concat([df, extra], ignore_index=True)
    df2 = compute_indicators(df2)
    # T 日 = df2 倒数第 21 行
    df_t = df2.iloc[:120].copy()
    passed_t2, score_t2, _ = extract_signal_row(df_t, cfg)

    assert passed_t == passed_t2
    # T 日指标值不变（PIT：不受未来暴涨影响）
    assert abs(score_t - score_t2) < 1e-9


# ---------------- 卖出规则 ----------------

def _make_position(code, cost, last_price, hold=0):
    return {"code": code, "volume": 1000, "available_volume": 1000,
            "cost_price": cost, "last_price": last_price,
            "holding_days": hold}


def test_stop_loss_sell():
    pos = _make_position("C1", cost=10.0, last_price=9.1)  # -9% <= -8%
    df = compute_indicators(_bullish_df())
    win = {"C1": df}
    d = assemble_decision("2025-01-01", win, [pos],
                          {"total_asset": 1e6}, {"max_positions": 5, "enable": {}}, {})
    reasons = [s["reason"] for s in d["sell_decisions"]]
    assert "stop_loss" in reasons


def test_take_profit_sell():
    pos = _make_position("C1", cost=10.0, last_price=12.1)  # +21% >= 20%
    df = compute_indicators(_bullish_df())
    d = assemble_decision("2025-01-01", {"C1": df}, [pos],
                          {"total_asset": 1e6}, {"max_positions": 5, "enable": {}}, {})
    reasons = [s["reason"] for s in d["sell_decisions"]]
    assert "take_profit" in reasons


def test_max_hold_sell():
    pos = _make_position("C1", cost=10.0, last_price=10.5, hold=61)
    df = compute_indicators(_bullish_df())
    d = assemble_decision("2025-01-01", {"C1": df}, [pos],
                          {"total_asset": 1e6}, {"max_positions": 5, "max_hold": 60, "enable": {}}, {})
    reasons = [s["reason"] for s in d["sell_decisions"]]
    assert "max_hold" in reasons


def test_market_risk_sell_all():
    """大盘连续 3 日 < MA20 → 全仓离场。"""
    pos = _make_position("C1", cost=10.0, last_price=10.5, hold=5)
    df = compute_indicators(_bullish_df())
    # 构造下行 benchmark：连续 3 日低于 MA20
    bench = {}
    prices = list(np.linspace(4000, 3000, 40))  # 持续下跌
    for i, p in enumerate(prices):
        bench["2025-01-%02d" % (i + 1)] = float(p)
    d = assemble_decision("2025-01-40", {"C1": df}, [pos],
                          {"total_asset": 1e6},
                          {"max_positions": 5, "enable": {}},
                          {"benchmark_closes": bench})
    reasons = [s["reason"] for s in d["sell_decisions"]]
    assert "market_risk" in reasons


def test_buy_cap_at_max_positions():
    """超过 max_positions 的候选不买入。"""
    df = compute_indicators(_bullish_df())
    win = {"C%d" % i: df.copy() for i in range(10)}
    d = assemble_decision("2025-01-01", win, [],
                          {"total_asset": 1e6}, {"max_positions": 5, "enable": {}},
                          {"benchmark_closes": {"2025-01-01": 1.0}})
    # 至多 5 个 buy 候选
    assert len(d["buy_candidates"]) <= 5
    # 每个 target_weight = 0.2
    for b in d["buy_candidates"]:
        assert abs(b["target_weight"] - 0.2) < 1e-9


# ---------------- 决策 schema ----------------

def test_strategy_registered():
    assert "research/deepseek" in list_strategies()


def test_evaluate_day_returns_v04_schema():
    fn = get_strategy("research/deepseek")
    df = compute_indicators(_bullish_df())
    d = fn(
        current_date="2025-01-01",
        market_window={"C1": df},
        positions=[],
        cash=1_000_000.0,
        universe=["C1"],
        account_state={"total_asset": 1_000_000.0, "max_positions": 5},
        strategy_config={"max_positions": 5, "enable": {}},
        aux_data={"benchmark_closes": {"2025-01-01": 1.0}},
    )
    for key in ("sell_decisions", "buy_candidates", "target_positions",
                "blocked_candidates", "diagnostics", "logs"):
        assert key in d
    assert "deepseek" in d["diagnostics"]["strategy_specific"]
