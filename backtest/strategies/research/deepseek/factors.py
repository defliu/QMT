# coding: utf-8
"""DeepSeek 策略指标计算库。

两部分：
  1. compute_indicators(df): 单 code 全序列 vectorized 预算所有指标列（PIT 安全，
     rolling 只用过去）。由 DeepseekReader.load_window 调用，预算一次，engine 按日切片。
  2. extract_signal_row(df, cfg): 读 df.iloc[-1] 做布尔判断，返回 (passed, score, debug)。

依赖：只用 pandas/numpy。编码 UTF-8，Python 3.10+。
不依赖 tdx 专有函数（COST/SCR/WINNER 等均不用，筹码条件 L 跳过）。
"""

from typing import Any, Dict, Tuple

import numpy as np
import pandas as pd


# ---------- 默认参数（可被 cfg 覆盖） ----------
DEFAULTS = {
    "slope_thresh": 2.5,        # 条件 B：5日平均每天涨幅% >= 2.5
    "pullback_pct": 0.98,       # 条件 C：low >= ma5 * 0.98
    "yang_ratio_thresh": 0.6,   # 条件 D：10日阳线比例 >= 0.6
    "gain_limit": 30.0,         # 条件 E：距60日线涨幅% < 30
    "eff_thresh": 0.005,        # 条件 F：有效阳线 涨幅 > 0.5%
    "eff_ratio_thresh": 50.0,   # 条件 F：10日有效阳线比例% >= 50
    "turnover_low": 3.0,        # 条件 G：换手率 > 3
    "turnover_high": 10.0,      # 条件 G：换手率 < 10
    "volratio_low": 1.2,        # 条件 H：量比 > 1.2
    "volratio_high": 4.0,       # 条件 H：量比 < 4
    "mv_low": 50.0,             # 条件 I：流通市值亿 >= 50
    "mv_high": 500.0,           # 条件 I：流通市值亿 < 500
    "bench_ma": 20,             # 条件 J：大盘 MA20
    "min_listed_days": 60,      # 次新过滤
}


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """单 code 全序列预算指标列。原地追加列后返回 df。

    输入 df 列：date, open, high, low, close, vol, amount, turnover_rate,
                circ_mv, is_st, listed_days（由 DeepseekReader 带出）
    追加列：ma5, ma10, ma20, ma60, slope5, huicai_ok, yang_ratio_10,
            gain_from_ma60, eff_ratio_10, vol_ratio_spec, circ_mv_yi
    """
    out = df.copy()
    close = out["close"]
    vol = out["vol"]

    out["ma5"] = close.rolling(5, min_periods=5).mean()
    out["ma10"] = close.rolling(10, min_periods=10).mean()
    out["ma20"] = close.rolling(20, min_periods=20).mean()
    out["ma60"] = close.rolling(60, min_periods=60).mean()

    # 条件 B：5日平均每天涨幅% = (ma5 - ma5.shift5)/ma5.shift5 / 5 * 100
    ma5 = out["ma5"]
    ma5_prev = ma5.shift(5)
    out["slope5"] = np.where(
        (ma5_prev.notna()) & (ma5_prev > 0),
        (ma5 - ma5_prev) / ma5_prev / 5.0 * 100.0,
        np.nan,
    )

    # 条件 C：回踩 low >= ma5 * 0.98（逐行 bool）
    out["huicai_ok"] = (out["low"].notna()) & (out["ma5"].notna()) & (
        out["low"] >= out["ma5"] * DEFAULTS["pullback_pct"])

    # 条件 D：10日阳线比例
    yangxian = (close > out["open"]).astype(float)
    out["yang_ratio_10"] = yangxian.rolling(10, min_periods=10).sum() / 10.0

    # 条件 E：距60日线涨幅%
    out["gain_from_ma60"] = np.where(
        (out["ma60"].notna()) & (out["ma60"] > 0),
        (close - out["ma60"]) / out["ma60"] * 100.0,
        np.nan,
    )

    # 条件 F：有效阳线比例%
    eff_yang = (close > close.shift(1) * (1.0 + DEFAULTS["eff_thresh"])).astype(float)
    out["eff_ratio_10"] = eff_yang.rolling(10, min_periods=10).sum() / 10.0 * 100.0

    # 条件 H：量比 = VOL / MA(REF(VOL,1), 5) = vol[t] / mean(vol[t-1..t-5])
    prev_vol_ma5 = vol.shift(1).rolling(5, min_periods=5).mean()
    out["vol_ratio_spec"] = np.where(
        (prev_vol_ma5.notna()) & (prev_vol_ma5 > 0),
        vol / prev_vol_ma5,
        np.nan,
    )

    # 条件 I：流通市值（亿）= circ_mv(万元) / 10000
    out["circ_mv_yi"] = out["circ_mv"] / 10000.0

    return out


def _safe_last(df: pd.DataFrame, col: str) -> float:
    """取 df[col] 最后一个非 NaN 值，缺失返回 nan。（仅测试/兼容用）"""
    if col not in df.columns or len(df) == 0:
        return float("nan")
    s = df[col].dropna()
    if len(s) == 0:
        return float("nan")
    return float(s.iloc[-1])


def extract_signal_row(df: pd.DataFrame, cfg: Dict[str, Any]) -> Tuple[bool, float, Dict[str, Any]]:
    """读 df.iloc[-1]（即 current_date 行）做布尔判断。

    性能：取一次最后一行 Series，直接列访问，避免逐列 dropna 全扫描。
    返回 (passed, score, debug)。
    """
    if df is None or len(df) == 0:
        return (False, 0.0, {"reason": "empty_df"})

    g = {k: cfg.get(k, v) for k, v in DEFAULTS.items()}
    row = df.iloc[-1]

    # 次新 / ST 预筛（卫生条件，恒开）
    listed_days = row.get("listed_days", float("nan"))
    is_st = row.get("is_st", float("nan"))
    last_date = str(row["date"])
    debug = {
        "last_date": last_date,
        "listed_days": listed_days,
        "is_st": is_st,
    }

    def _num(v):
        try:
            f = float(v)
            return f
        except (TypeError, ValueError):
            return float("nan")

    if not np.isnan(listed_days) and listed_days < g["min_listed_days"]:
        return (False, 0.0, dict(debug, reason="new_stock"))
    if not np.isnan(is_st) and is_st > 0:
        return (False, 0.0, dict(debug, reason="st"))

    close = _num(row.get("close"))
    ma5 = _num(row.get("ma5"))
    ma10 = _num(row.get("ma10"))
    ma20 = _num(row.get("ma20"))
    ma60 = _num(row.get("ma60"))
    slope5 = _num(row.get("slope5"))
    huicai_ok = row.get("huicai_ok", False)
    yang_ratio_10 = _num(row.get("yang_ratio_10"))
    gain_from_ma60 = _num(row.get("gain_from_ma60"))
    eff_ratio_10 = _num(row.get("eff_ratio_10"))
    turnover_rate = _num(row.get("turnover_rate"))
    vol_ratio_spec = _num(row.get("vol_ratio_spec"))
    circ_mv_yi = _num(row.get("circ_mv_yi"))
    open_ = _num(row.get("open"))

    debug.update({
        "close": close, "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60,
        "slope5": slope5, "yang_ratio_10": yang_ratio_10,
        "gain_from_ma60": gain_from_ma60, "eff_ratio_10": eff_ratio_10,
        "turnover_rate": turnover_rate, "vol_ratio_spec": vol_ratio_spec,
        "circ_mv_yi": circ_mv_yi,
    })

    # 任一核心指标缺失 → 数据不足
    if any(np.isnan(x) for x in (close, ma5, ma10, ma20, ma60)):
        return (False, slope5 if not np.isnan(slope5) else 0.0,
                dict(debug, reason="insufficient_history"))

    ena = cfg.get("enable", {}) or {}
    cond = {}

    # A：MA 多头排列
    cond["A_ma_bull"] = (close > ma5) and (ma5 > ma10) and (ma10 > ma20) and (ma20 > ma60)
    # B：斜率
    cond["B_slope"] = (not ena.get("B", True)) or (
        not np.isnan(slope5) and slope5 >= g["slope_thresh"])
    # C：阳线 + 回踩不破
    cond["C_yang_huicai"] = (not ena.get("C", True)) or (
        (close > open_) and bool(huicai_ok))
    # D：阳线比例
    cond["D_yang_ratio"] = (not ena.get("D", True)) or (
        not np.isnan(yang_ratio_10) and yang_ratio_10 >= g["yang_ratio_thresh"])
    # E：涨幅限制
    cond["E_gain"] = (not ena.get("E", True)) or (
        not np.isnan(gain_from_ma60) and gain_from_ma60 < g["gain_limit"])
    # F：有效阳线
    cond["F_eff"] = (not ena.get("F", True)) or (
        not np.isnan(eff_ratio_10) and eff_ratio_10 >= g["eff_ratio_thresh"])
    # G：换手率
    cond["G_turnover"] = (not ena.get("G", True)) or (
        not np.isnan(turnover_rate) and turnover_rate > g["turnover_low"]
        and turnover_rate < g["turnover_high"])
    # H：量比
    cond["H_volratio"] = (not ena.get("H", True)) or (
        not np.isnan(vol_ratio_spec) and vol_ratio_spec > g["volratio_low"]
        and vol_ratio_spec < g["volratio_high"])
    # I：流通市值
    cond["I_mv"] = (not ena.get("I", True)) or (
        not np.isnan(circ_mv_yi) and circ_mv_yi >= g["mv_low"]
        and circ_mv_yi < g["mv_high"])
    # K：非ST（恒开，上面已筛）
    cond["K_not_st"] = True
    # J（大盘安全）由 decision 层注入
    cond["J_market"] = True

    debug["cond"] = {k: bool(v) for k, v in cond.items()}
    passed = all(cond.values())
    score = slope5 if not np.isnan(slope5) else 0.0
    return (passed, score, debug)
