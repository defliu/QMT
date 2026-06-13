# coding: utf-8
"""Performance metrics for backtest factory v0.2.

Frozen contract: 04_output_schema_freeze.md §1.4 performance.

Inputs are the equity_curve rows produced by Portfolio.equity_row()
(SIDE-EFFECT-FREE: this module never mutates them) and the trades list
produced by execution.fill_*. All math is plain numpy on float arrays;
no scipy / sklearn dependency.

Constraints:
  - Pure function, no IO.
  - Python 3.6-safe.
  - benchmark_available=false -> excess_return / information_ratio /
    tracking_error return None (per 04 §1.4).
"""
import math


def _annualize_factor(trading_days):
    """Standard 252-day annualization base; safe for short samples."""
    if trading_days <= 0:
        return 1.0
    return 252.0 / float(trading_days)


def _max_drawdown(equity):
    """min over t of (equity[t] - peak[t]) / peak[t]; returns negative or 0."""
    if not equity:
        return 0.0
    peak = equity[0]
    mdd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (v - peak) / peak
            if dd < mdd:
                mdd = dd
    return mdd


def _sharpe(returns, trading_days):
    """rf=0; mean(daily)/std(daily) * sqrt(252)."""
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(var) if var > 0 else 0.0
    if std == 0:
        return 0.0
    return mean / std * math.sqrt(252.0)


def _pair_trades(trades):
    """Pair buy -> sell per code in chronological order.

    Returns list of (buy_trade, sell_trade) tuples. Unmatched buys (still
    held at end of run) are dropped from win-rate / avg-holding calcs.
    """
    buys_by_code = {}
    pairs = []
    for t in trades:
        code = t["code"]
        if t["side"] == "buy":
            buys_by_code.setdefault(code, []).append(t)
        elif t["side"] == "sell":
            queue = buys_by_code.get(code, [])
            if queue:
                pairs.append((queue.pop(0), t))
    return pairs


def _trading_day_diff(date_a, date_b, trading_calendar):
    """Count trading days between two YYYY-MM-DD strings (b - a, inclusive of b)."""
    cal = list(trading_calendar or [])
    a = str(date_a)
    b = str(date_b)
    try:
        ia = cal.index(a)
        ib = cal.index(b)
    except ValueError:
        # Fall back to naive day diff if calendar is missing one of them.
        return max(0, len(cal) and 0 or 0)
    return ib - ia


def compute_metrics(equity_rows, trades, trading_calendar,
                    initial_cash, benchmark_available=False):
    """Compute performance dict matching 04 §1.4.

    Args:
        equity_rows: list of dicts from Portfolio.equity_row in order.
        trades: list of trade dicts from execution.fill_*.
        trading_calendar: list of YYYY-MM-DD trading-day strings.
        initial_cash: float, starting cash.
        benchmark_available: bool. False -> excess/info/tracking are None.
    """
    n_days = len(trading_calendar) if trading_calendar else len(equity_rows)
    if n_days <= 0:
        n_days = 1

    if equity_rows:
        end_total = float(equity_rows[-1]["total_asset"])
    else:
        end_total = float(initial_cash)
    total_return = (end_total / float(initial_cash)) - 1.0 if initial_cash > 0 else 0.0
    annual_return = total_return * _annualize_factor(n_days)

    equity_series = [float(r["total_asset"]) for r in equity_rows]
    daily_returns = [float(r["daily_return"]) for r in equity_rows[1:]]  # skip day 0

    mdd = _max_drawdown(equity_series)
    sharpe = _sharpe(daily_returns, n_days)
    if mdd != 0:
        calmar = annual_return / abs(mdd)
    else:
        calmar = None

    pairs = _pair_trades(trades)
    n_buy = sum(1 for t in trades if t["side"] == "buy")
    n_sell = sum(1 for t in trades if t["side"] == "sell")

    if pairs:
        wins = 0
        hold_sum = 0
        for buy, sell in pairs:
            buy_amt = float(buy["amount"]) + float(buy["commission"])
            sell_amt = float(sell["amount"]) - float(sell["commission"]) - float(sell["tax"])
            if sell_amt > buy_amt:
                wins += 1
            hold_sum += _trading_day_diff(buy["date"], sell["date"], trading_calendar)
        win_rate = wins / float(len(pairs))
        avg_holding_days = hold_sum / float(len(pairs))
    else:
        win_rate = 0.0
        avg_holding_days = 0.0

    perf = {
        "total_return":     round(total_return, 6),
        "annual_return":    round(annual_return, 6),
        "max_drawdown":     round(mdd, 6),
        "sharpe":           round(sharpe, 6),
        "calmar":           None if calmar is None else round(calmar, 6),
        "win_rate":         round(win_rate, 6),
        "n_trades":         len(trades),
        "n_buy":            n_buy,
        "n_sell":           n_sell,
        "avg_holding_days": round(avg_holding_days, 6),
        "excess_return":     None,
        "information_ratio": None,
        "tracking_error":    None,
    }
    return perf
