# coding=utf-8
"""因子计算函数。"""

import numpy as np
import pandas as pd


def winsorize(series, lower=0.01, upper=0.99):
    lo = series.quantile(lower)
    hi = series.quantile(upper)
    return series.clip(lo, hi)


def standardize(series):
    return (series - series.mean()) / series.std(ddof=0)


FACTOR_CONFIG = {
    "EP": {"category": "价值", "params": {}},
    "BP": {"category": "价值", "params": {}},
    "dividend_yield": {"category": "价值", "params": {}},
    "ROE": {"category": "质量", "params": {}},
    "grossprofit_margin": {"category": "质量", "params": {}},
    "momentum_1m": {"category": "动量", "params": {"window": 20}},
    "momentum_3m": {"category": "动量", "params": {"window": 60}},
    "momentum_6m": {"category": "动量", "params": {"window": 120}},
    "turnover_change": {"category": "情绪", "params": {}},
    "volatility_60d": {"category": "情绪", "params": {"window": 60}},
    "liquidity_avg": {"category": "情绪", "params": {"window": 20}},
}


def compute_all_factors(panel, fin_ffill, date):
    """计算 date 日所有因子的截面值。返回 {factor_name: Series}"""
    result = {}
    trade_dates = sorted(panel.index.get_level_values("trade_date").unique())
    date_series = panel.loc[date]

    # EP
    ep = 1.0 / date_series["pe_ttm"].replace(0, np.nan)
    result["EP"] = ep

    # BP
    bp = 1.0 / date_series["pb"].replace(0, np.nan)
    result["BP"] = bp

    # dividend_yield
    result["dividend_yield"] = date_series["dv_ratio"]

    # ROE (从财务表取最近季度)
    fin_dates = fin_ffill.index
    valid = fin_dates[fin_dates <= pd.Timestamp(date)]
    if len(valid) > 0:
        roe = fin_ffill.loc[valid[-1], "roe"]
        gpm = fin_ffill.loc[valid[-1], "grossprofit_margin"]
    else:
        roe = pd.Series(np.nan, index=date_series.index)
        gpm = pd.Series(np.nan, index=date_series.index)
    result["ROE"] = roe.reindex(date_series.index)
    result["grossprofit_margin"] = gpm.reindex(date_series.index)

    # 动量
    date_idx = trade_dates.index(date)
    for name, w in [("momentum_1m", 20), ("momentum_3m", 60), ("momentum_6m", 120)]:
        if date_idx >= w:
            start = trade_dates[date_idx - w]
            start_close = panel.loc[start, "close"]
            end_close = date_series["close"]
            common = start_close.index.intersection(end_close.index)
            ret = end_close[common] / start_close[common] - 1.0
            result[name] = ret.reindex(date_series.index)
        else:
            result[name] = pd.Series(0.0, index=date_series.index)

    # 换手率变化 (20d / 60d)
    if date_idx >= 60:
        s20 = panel.loc[trade_dates[date_idx - 20]:date, "turnover_rate"].groupby("ts_code").mean()
        s60 = panel.loc[trade_dates[date_idx - 60]:date, "turnover_rate"].groupby("ts_code").mean()
        tc = s20 / s60.replace(0, np.nan) - 1.0
        result["turnover_change"] = tc.reindex(date_series.index)
    else:
        result["turnover_change"] = pd.Series(0.0, index=date_series.index)

    # 波动率 (60d)
    if date_idx >= 60:
        pct = panel.loc[trade_dates[date_idx - 60]:date, "pct_chg"]
        vol = pct.groupby("ts_code").std()
        result["volatility_60d"] = vol.reindex(date_series.index)
    else:
        result["volatility_60d"] = pd.Series(0.0, index=date_series.index)

    # 流动性 (20d avg log amount)
    if date_idx >= 20:
        amt = panel.loc[trade_dates[date_idx - 20]:date, "amount"]
        la = np.log(amt.groupby("ts_code").mean().replace(0, np.nan))
        result["liquidity_avg"] = la.reindex(date_series.index)
    else:
        result["liquidity_avg"] = pd.Series(0.0, index=date_series.index)

    return result
