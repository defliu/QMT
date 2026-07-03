# coding: utf-8
"""DeepSeek 决策组装：买入信号筛选 + 卖出规则 + 仓位管理 → decision dict。

遵循 6 顶层键 schema：
  sell_decisions / buy_candidates / target_positions / blocked_candidates /
  diagnostics / logs

卖出规则（SPEC §3.3，engine 不支持部分止盈，20% 全卖）：
  - 止损 -8%（硬止损）
  - 止盈 +20%（全卖，非分批）
  - 趋势破坏：close < ma10 AND ma10 < ma20
  - 大盘风险：上证/基准 < MA20 连续 3 日
  - 持仓上限：holding_days >= 60
"""

from typing import Any, Dict, List

import numpy as np
import pandas as pd

from backtest.strategies.research.deepseek.factors import extract_signal_row


_DEFAULT_MAX_POSITIONS = 5
_DEFAULT_STOP_LOSS = -0.08
_DEFAULT_TAKE_PROFIT = 0.20
_DEFAULT_MAX_HOLD = 60
_DEFAULT_MARKET_RISK_DAYS = 3
_LIMIT_UP_PCT = 0.0995

# benchmark 序列预排序缓存：engine 每天传同一 aux_data，避免每日重排 O(D²)。
# key = id(aux_data dict)；value = (sorted_date_str_list, sorted_close_array)。
_BENCH_CACHE = {}


def _get_bench_sorted(aux_data):
    """返回 (dates_sorted, closes_sorted)，缓存。"""
    bc = (aux_data or {}).get("benchmark_closes")
    if not bc:
        return (None, None)
    key = id(aux_data)
    cached = _BENCH_CACHE.get(key)
    if cached is not None:
        return cached
    items = [(str(d), float(v)) for d, v in bc.items()
             if v is not None and not (isinstance(v, float) and np.isnan(v))]
    items.sort(key=lambda x: x[0])
    if not items:
        _BENCH_CACHE[key] = (None, None)
        return (None, None)
    dates = [d for d, _ in items]
    closes = np.array([v for _, v in items], dtype=float)
    _BENCH_CACHE[key] = (dates, closes)
    return (dates, closes)


def _bench_series_up_to(aux_data, current_date, n_days):
    """截至 current_date 的基准收盘序列（升序），最多取最近 n_days 条。

    用二分定位截止索引，O(log D)。
    """
    dates, closes = _get_bench_sorted(aux_data)
    if dates is None:
        return []
    fd = str(current_date)
    # 二分找 <= fd 的右边界
    import bisect
    idx = bisect.bisect_right(dates, fd)
    if idx == 0:
        return []
    # 取最近 n_days 条
    start = max(0, idx - n_days)
    return closes[start:idx].tolist()


def _market_ok_and_risk(aux_data, current_date, cfg):
    """返回 (market_ok, market_risk_trigger)。

    market_ok: 基准 close > MA20（条件 J）。
    market_risk_trigger: 基准 close < MA20 连续 N 日（卖出离场）。
    """
    ma_n = int(cfg.get("bench_ma", 20))
    risk_days = int(cfg.get("market_risk_days", _DEFAULT_MARKET_RISK_DAYS))
    ena_j = (cfg.get("enable", {}) or {}).get("J", True)

    series = _bench_series_up_to(aux_data, current_date, ma_n + risk_days + 5)
    if len(series) < ma_n + 1:
        # 数据不足：启用 J 时保守判 False，不触发 risk
        return (not ena_j, False)

    closes = np.array(series, dtype=float)
    ma_today = closes[-ma_n:].mean()
    market_ok = (not ena_j) or (closes[-1] > ma_today)

    # 连续 N 日 close < MA20（用正向索引避免负索引切片为空）
    risk_trigger = False
    n = len(closes)
    if n >= ma_n + risk_days:
        streak = 0
        for i in range(risk_days):
            pos = n - 1 - i          # 今日、昨日、前日 ...
            ma_i = closes[pos - ma_n + 1: pos + 1].mean()
            if closes[pos] < ma_i:
                streak += 1
            else:
                break
        risk_trigger = streak >= risk_days
    return (market_ok, risk_trigger)


def _daily_pct(df):
    """df 最后一日涨跌幅（close/prev_close - 1）。"""
    if df is None or len(df) < 2:
        return 0.0
    c0 = float(df["close"].iloc[-2])
    c1 = float(df["close"].iloc[-1])
    if c0 <= 0:
        return 0.0
    return c1 / c0 - 1.0


def assemble_decision(
    current_date,
    market_window,
    positions,
    account_state,
    strategy_config,
    aux_data,
):
    """主决策组装。"""
    cfg = strategy_config or {}
    max_positions = int(cfg.get("max_positions", _DEFAULT_MAX_POSITIONS))
    stop_loss = float(cfg.get("stop_loss", _DEFAULT_STOP_LOSS))
    take_profit = float(cfg.get("take_profit", _DEFAULT_TAKE_PROFIT))
    max_hold = int(cfg.get("max_hold", _DEFAULT_MAX_HOLD))

    total_asset = float((account_state or {}).get("total_asset", 0))

    decision = {
        "sell_decisions": [],
        "buy_candidates": [],
        "target_positions": [],
        "blocked_candidates": [],
        "diagnostics": {
            "warnings": [],
            "candidate_total": 0,
            "candidate_passed": 0,
            "strategy_specific": {
                "deepseek": {
                    "market_ok": None,
                    "market_risk": False,
                    "signal_pass_codes": [],
                    "blocked_counts": {},
                    "top_candidates": [],
                },
            },
        },
        "logs": [],
    }
    _ss = decision["diagnostics"]["strategy_specific"]["deepseek"]

    held_codes = set(p["code"] for p in (positions or []))

    # ---------- 1. 大盘条件 J + 风险 ----------
    market_ok, market_risk = _market_ok_and_risk(aux_data, current_date, cfg)
    _ss["market_ok"] = market_ok
    _ss["market_risk"] = market_risk

    # ---------- 2. 卖出决策 ----------
    for pos in (positions or []):
        code = pos["code"]
        cost = float(pos.get("cost_price", 0))
        last_price = float(pos.get("last_price", 0))
        hold = int(pos.get("holding_days", 0))
        volume = int(pos.get("volume", 0))
        if cost <= 0 or volume <= 0:
            continue
        ret = last_price / cost - 1.0

        sell_reason = None
        if ret <= stop_loss:
            sell_reason = "stop_loss"
        elif ret >= take_profit:
            sell_reason = "take_profit"
        elif market_risk:
            sell_reason = "market_risk"
        elif hold >= max_hold:
            sell_reason = "max_hold"
        else:
            # 趋势破坏：close < ma10 AND ma10 < ma20
            df = market_window.get(code)
            if df is not None and len(df) > 0:
                ma10 = df["ma10"].iloc[-1] if "ma10" in df.columns else np.nan
                ma20 = df["ma20"].iloc[-1] if "ma20" in df.columns else np.nan
                close = float(df["close"].iloc[-1])
                if (not np.isnan(ma10)) and (not np.isnan(ma20)):
                    if close < ma10 and ma10 < ma20:
                        sell_reason = "trend_break"

        if sell_reason:
            decision["sell_decisions"].append({
                "code": code,
                "action": "sell",
                "target_volume": 0,
                "reason": sell_reason,
                "layer": "risk" if sell_reason in ("stop_loss", "market_risk") else "signal",
                "priority": 1,
                "diagnostics_ref": code,
            })

    # ---------- 3. 买入信号筛选 ----------
    candidates = []
    block_counts = {}
    for code in (market_window.keys()):
        df = market_window[code]
        decision["diagnostics"]["candidate_total"] += 1

        if code in held_codes:
            block_counts["already_held"] = block_counts.get("already_held", 0) + 1
            continue

        # 涨停不买（次日大概率无法成交）
        if _daily_pct(df) >= _LIMIT_UP_PCT:
            block_counts["limit_up"] = block_counts.get("limit_up", 0) + 1
            decision["blocked_candidates"].append({
                "code": code, "blocked_by": "limit_up", "reason": "limit up today"})
            continue

        passed, score, debug = extract_signal_row(df, cfg)
        if not passed:
            reason = debug.get("reason", "cond_fail")
            block_counts[reason] = block_counts.get(reason, 0) + 1
            continue

        # 条件 J：大盘安全
        if not market_ok:
            block_counts["market_unsafe"] = block_counts.get("market_unsafe", 0) + 1
            continue

        candidates.append((code, score))

    _ss["blocked_counts"] = block_counts
    _ss["signal_pass_codes"] = [c for c, _ in candidates]
    decision["diagnostics"]["candidate_passed"] = len(candidates)

    # ---------- 4. 排序 + 仓位 ----------
    candidates.sort(key=lambda x: x[1], reverse=True)
    open_slots = max(0, max_positions - len(held_codes))
    n_buy = min(open_slots, len(candidates))

    per_weight = 1.0 / max_positions if max_positions > 0 else 0.0
    per_cash = total_asset * per_weight

    for rank_idx, (code, score) in enumerate(candidates[:n_buy], start=1):
        decision["buy_candidates"].append({
            "code": code,
            "score_total": float(score),
            "rank": rank_idx,
            "target_weight": per_weight,
            "target_cash": per_cash,
            "target_volume": 0,
            "reason": "deepseek_signal",
        })
    _ss["top_candidates"] = [{"code": c, "score": float(s)} for c, s in candidates[:n_buy]]

    decision["logs"].append(
        "deepseek %s market_ok=%s risk=%s cand=%d pass=%d sell=%d buy=%d"
        % (current_date, market_ok, market_risk,
           decision["diagnostics"]["candidate_total"],
           decision["diagnostics"]["candidate_passed"],
           len(decision["sell_decisions"]), len(decision["buy_candidates"])))

    return decision
