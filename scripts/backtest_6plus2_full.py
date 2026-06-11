#!/usr/bin/env python3
# coding=utf-8
"""
Full backtest for 6+2 Scorer with Sell Risk Management (SellStrategyEngine).

Integrates ScoreCalculator6Plus2 for daily scoring + SellStrategyEngine
for multi-layer sell decisions (bottom line, warning, confirm, clear, trailing stop).

Usage:
    python scripts/backtest_6plus2_full.py
    python scripts/backtest_6plus2_full.py --days 60 --top 3 --capital 100000 --max-hold 5
    python scripts/backtest_6plus2_full.py --pool D:/QMT_POOL/selected.txt
"""

import os
import sys
import json
import math
import argparse
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import numpy as np
import pandas as pd
from core.scoring.dimension6plus2 import ScoreCalculator6Plus2
from core.risk_manager import SellStrategyEngine, Action

# ── Constants ──────────────────────────────────────────────────────────
REQ_BARS = 800
DEFAULT_POOL = "D:/QMT_POOL/selected.txt"
SECTOR_HEAT_PATH = "D:/QMT_POOL/sector_heat.json"
TRADING_DAYS_PER_YEAR = 252
ANNUAL_RISK_FREE_RATE = 0.03


# ── Helpers ────────────────────────────────────────────────────────────


def _strip_suffix(code: str) -> str:
    code = code.upper()
    for s in ['.SH', '.SZ', '.BJ']:
        if code.endswith(s):
            return code[:-3]
    return code


def _add_suffix(code6: str) -> str:
    code6 = code6.strip().zfill(6)
    return code6 + ('.SH' if code6.startswith(('6', '9')) else '.SZ')


def read_pool(path: str) -> list[str]:
    """Read stock pool, return list of 6-digit codes. Empty if not found."""
    if not os.path.isfile(path):
        print(f"  [WARN] Pool file not found: {path}")
        return []
    codes = []
    try:
        with open(path, encoding='gbk', errors='replace') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                raw = line.split('\t')[0].strip()
                raw = _strip_suffix(raw)
                if raw.isdigit() and len(raw) == 6:
                    codes.append(raw)
    except Exception as e:
        print(f"  [ERROR] Reading pool failed: {e}")
        return []
    return codes


def download_all(stock_codes: list[str], req_bars: int = 800):
    """Download daily OHLCV via mootdx. Returns {code6: DataFrame}."""
    from mootdx.quotes import Quotes
    client = Quotes.factory(market='std')
    all_data = {}
    total = len(stock_codes)
    for idx, code6 in enumerate(stock_codes):
        try:
            bars = client.bars(symbol=code6, category=4, offset=req_bars)
            if bars is None or bars.empty:
                continue
            if 'vol' in bars.columns and 'volume' not in bars.columns:
                bars = bars.rename(columns={'vol': 'volume'})
            elif 'vol' in bars.columns and 'volume' in bars.columns:
                bars = bars.drop(columns=['vol'])
            if 'datetime' in bars.columns:
                bars['_date'] = pd.to_datetime(bars['datetime'].str[:10], errors='coerce')
                bars.set_index('_date', inplace=True)
                bars.drop(columns=['datetime'], inplace=True)
            bars.sort_index(inplace=True)
            bars = bars[bars.index.notna()]
            bars = bars[bars['close'] > 0]
            needed = ['open', 'high', 'low', 'close', 'volume']
            if all(c in bars.columns for c in needed):
                all_data[code6] = bars[needed].dropna()
            if (idx + 1) % 20 == 0:
                print(f"  Download [{idx+1}/{total}] got {len(all_data)} stocks...", flush=True)
        except Exception:
            pass
    return all_data


# ── Position tracking ─────────────────────────────────────────────────


class Position:
    """Simple position tracker."""
    __slots__ = ('code', 'buy_date', 'buy_price', 'shares', 'highest_price', 'score')

    def __init__(self, code: str, buy_date: str, buy_price: float,
                 shares: int, score: float = 0.0):
        self.code = code
        self.buy_date = buy_date
        self.buy_price = buy_price
        self.shares = shares
        self.highest_price = buy_price
        self.score = score


# ── Metrics ───────────────────────────────────────────────────────────


def _calc_sharpe(daily_returns: list[float]) -> float:
    """Compute annualized Sharpe ratio from daily return list."""
    if len(daily_returns) < 2:
        return 0.0
    arr = np.array(daily_returns)
    excess = arr - ANNUAL_RISK_FREE_RATE / TRADING_DAYS_PER_YEAR
    if np.std(arr) == 0:
        return 0.0
    return float(np.mean(excess) / np.std(arr) * math.sqrt(TRADING_DAYS_PER_YEAR))


def _calc_max_drawdown(equity: list[float]) -> float:
    """Compute maximum drawdown as a positive decimal."""
    peak = equity[0]
    max_dd = 0.0
    for eq in equity:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _compute_metrics(trades: list[dict], equity_curve: list) -> dict:
    """Compute all performance metrics from trades and equity curve."""
    n_trades = len(trades)
    if n_trades == 0 or not equity_curve:
        return {
            'total_trades': 0, 'win_trades': 0, 'lose_trades': 0,
            'win_rate': 0.0, 'avg_return': 0.0, 'total_return': 0.0,
            'max_return': 0.0, 'min_return': 0.0, 'max_drawdown': 0.0,
            'sharpe_ratio': 0.0, 'total_pnl': 0.0,
        }

    returns = [t.get('return', 0) for t in trades]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]

    # Equity-based metrics
    equity_values = [e[1] for e in equity_curve]
    initial = equity_values[0] if equity_values else 100000
    final = equity_values[-1] if equity_values else initial
    total_ret_pct = (final - initial) / initial * 100

    daily_rets = []
    for i in range(1, len(equity_values)):
        if equity_values[i - 1] > 0:
            daily_rets.append((equity_values[i] - equity_values[i - 1]) / equity_values[i - 1])

    return {
        'total_trades': n_trades,
        'win_trades': len(wins),
        'lose_trades': len(losses),
        'win_rate': round(len(wins) / n_trades * 100, 2) if n_trades > 0 else 0.0,
        'avg_return': round(np.mean(returns), 2) if returns else 0.0,
        'total_return': round(total_ret_pct, 2),
        'max_return': round(max(returns), 2) if returns else 0.0,
        'min_return': round(min(returns), 2) if returns else 0.0,
        'max_drawdown': round(_calc_max_drawdown(equity_values) * 100, 2),
        'sharpe_ratio': round(_calc_sharpe(daily_rets), 4),
        'total_pnl': round(sum(t.get('pnl', 0) for t in trades), 2),
    }


# ── Report ────────────────────────────────────────────────────────────


def print_summary(metrics: dict, trades: list[dict]):
    """Print backtest summary table to console."""
    print("\n" + "=" * 70)
    print("  Backtest Results — 6+2 Full with Sell Risk Management")
    print("=" * 70)
    print(f"  Total trades:     {metrics['total_trades']}")
    print(f"  Win rate:         {metrics['win_rate']:.1f}%")
    print(f"  Avg return:       {metrics['avg_return']:+.2f}%")
    print(f"  Total return:     {metrics['total_return']:+.2f}%")
    print(f"  Max return:       {metrics['max_return']:+.2f}%")
    print(f"  Min return:       {metrics['min_return']:+.2f}%")
    print(f"  Max drawdown:     {metrics['max_drawdown']:.2f}%")
    print(f"  Sharpe ratio:     {metrics['sharpe_ratio']:.4f}")
    print(f"  Total P&L:        {metrics['total_pnl']:+.2f}")
    print(f"  Win/Loss:         {metrics['win_trades']}/{metrics['lose_trades']}")

    # Recent trades
    if trades:
        print("\n  Last 10 trades:")
        print(f"  {'Code':>8} | {'BuyDate':>10} | {'SellDate':>10} | {'Buy':>8} | {'Sell':>8} | {'Ret%':>7} | {'Reason'}")
        print("  " + "-" * 80)
        for t in trades[-10:]:
            reason = t.get('sell_reason', '')[:20]
            print(f"  {t['code']:>8} | {t['buy_date']:>10} | {t['sell_date']:>10} "
                  f"| {t['buy_price']:>8.2f} | {t['sell_price']:>8.2f} "
                  f"| {t['return']:>+6.2f}% | {reason}")

    print("=" * 70)


# ── Main Backtest ─────────────────────────────────────────────────────


def run_backtest(
    pool_path: str = DEFAULT_POOL,
    backtest_days: int = 60,
    top_n: int = 3,
    initial_capital: float = 100000.0,
    max_hold: int = 5,
) -> dict:
    """
    Execute 6+2 full backtest with SellStrategyEngine integration.

    Returns dict with keys:
        trades: list[dict]  — all completed trades
        metrics: dict       — performance metrics
        equity_curve: list  — [(date, nav), ...]
        trades_df: DataFrame — all trades as DataFrame
    """
    scorer = ScoreCalculator6Plus2(sector_heat_path=SECTOR_HEAT_PATH)

    print("=" * 70)
    print("  6+2 Score Full Backtest — with Sell Risk Management")
    print(f"  Pool: {pool_path}")
    print(f"  Period: last {backtest_days} trading days")
    print(f"  Top-N: {top_n},  Max Hold: {max_hold},  Capital: {initial_capital:,.0f}")
    print("=" * 70)

    # ── Read pool + download ──
    codes6 = read_pool(pool_path)
    if not codes6:
        codes6 = ["600519", "000858", "601318", "600036", "000333"]
        print(f"  Pool empty, using fallback: {codes6}")

    print(f"\nDownloading {len(codes6)} stocks via mootdx...")
    all_data = download_all(codes6, REQ_BARS)
    print(f"  Got {len(all_data)} stocks with data")

    if len(all_data) < 3:
        print("  Insufficient data, aborting")
        return {"trades": [], "metrics": {}, "equity_curve": [], "trades_df": pd.DataFrame()}

    # ── Build date list ──
    all_dates = set()
    for df in all_data.values():
        all_dates.update(df.index.strftime('%Y-%m-%d'))
    all_dates = sorted(all_dates)
    print(f"  Total trading days: {len(all_dates)}")

    test_dates = all_dates[-backtest_days:]
    print(f"  Backtest range: {test_dates[0]} ~ {test_dates[-1]}")

    # ── Create SellStrategyEngine ──
    state_dir = os.path.join(PROJECT_ROOT, 'data')
    os.makedirs(state_dir, exist_ok=True)
    state_file = os.path.join(state_dir, 'backtest_6plus2_sell_state.json')
    sell_engine = SellStrategyEngine(
        strategy_name="6+2_BACKTEST",
        account_id="BACKTEST",
        state_file=state_file,
        is_intraday=False,
    )

    # ── Backtest loop ──
    portfolio = {}  # {code6: Position}
    trades = []
    equity_curve = []
    cash = initial_capital
    position_target = initial_capital / max_hold

    for i, today_str in enumerate(test_dates):
        today_yyyymmdd = today_str.replace('-', '')

        # 1) Update highest prices for all positions
        for code6, pos in list(portfolio.items()):
            df_stock = all_data.get(code6)
            if df_stock is not None and today_str in df_stock.index:
                current_close = float(df_stock.loc[today_str, 'close'])
                pos.highest_price = max(pos.highest_price, current_close)

        # 2) Build sell engine inputs
        holdings_dict = {}   # {code6: highest_price}
        positions_data = {}  # {code6: {cost, can_use, volume}}
        for code6, pos in portfolio.items():
            holdings_dict[code6] = pos.highest_price
            positions_data[code6] = {
                'cost': pos.buy_price,
                'can_use': pos.shares,
                'volume': pos.shares,
            }

        # 3) Build truncated data for sell engine (avoid lookahead)
        sell_data = {}
        for code6 in portfolio:
            df = all_data.get(code6)
            if df is not None:
                hist = df[df.index <= today_str]
                if len(hist) >= 30:
                    sell_data[code6] = hist

        # 4) Evaluate sell decisions
        if holdings_dict:
            try:
                decisions = sell_engine.evaluate(
                    today_yyyymmdd, holdings_dict, sell_data, positions_data
                )
            except Exception as e:
                decisions = []

            for code6, decision, shares_to_sell in decisions:
                pos = portfolio.get(code6)
                if pos is None:
                    continue
                df_stock = all_data.get(code6)
                if df_stock is None or today_str not in df_stock.index:
                    continue

                sell_price = float(df_stock.loc[today_str, 'close'])

                if decision.action == Action.CLEAR:
                    ret = (sell_price - pos.buy_price) / pos.buy_price
                    trades.append({
                        'code': code6,
                        'buy_date': pos.buy_date,
                        'sell_date': today_str,
                        'buy_price': round(pos.buy_price, 2),
                        'sell_price': round(sell_price, 2),
                        'return': round(ret * 100, 2),
                        'shares': pos.shares,
                        'pnl': round((sell_price - pos.buy_price) * pos.shares, 2),
                        'sell_reason': f"CLEAR({decision.reason})",
                        'sell_layer': decision.triggered_layer,
                    })
                    cash += sell_price * pos.shares
                    sell_engine.confirm_clear(code6, today_yyyymmdd)
                    del portfolio[code6]

                elif decision.action == Action.REDUCE and shares_to_sell >= 100:
                    actual = min(shares_to_sell, pos.shares)
                    ret = (sell_price - pos.buy_price) / pos.buy_price
                    trades.append({
                        'code': code6,
                        'buy_date': pos.buy_date,
                        'sell_date': today_str,
                        'buy_price': round(pos.buy_price, 2),
                        'sell_price': round(sell_price, 2),
                        'return': round(ret * 100, 2),
                        'shares': actual,
                        'pnl': round((sell_price - pos.buy_price) * actual, 2),
                        'sell_reason': f"REDUCE({decision.reason})",
                        'sell_layer': decision.triggered_layer,
                    })
                    cash += sell_price * actual
                    pos.shares -= actual

                    # If remaining shares < 100, sell remainder too
                    if pos.shares < 100:
                        trades.append({
                            'code': code6,
                            'buy_date': pos.buy_date,
                            'sell_date': today_str,
                            'buy_price': round(pos.buy_price, 2),
                            'sell_price': round(sell_price, 2),
                            'return': round(ret * 100, 2),
                            'shares': pos.shares,
                            'pnl': round((sell_price - pos.buy_price) * pos.shares, 2),
                            'sell_reason': "REMAINDER",
                            'sell_layer': 'remnant',
                        })
                        cash += sell_price * pos.shares
                        del portfolio[code6]

        # 5) Score and buy if under max_hold
        if len(portfolio) < max_hold:
            today_scores = []
            for code6, df in all_data.items():
                hist = df[df.index <= today_str]
                if len(hist) < 30:
                    continue
                try:
                    code_sw = _add_suffix(code6)
                    rec = scorer.score_single(
                        code_sw, hist.reset_index(drop=True),
                        dynamic_pe=20.0, static_pe=25.0,
                    )
                    today_scores.append((code6, rec['score_total']))
                except Exception:
                    pass

            if today_scores:
                today_scores.sort(key=lambda x: -x[1])
                slots = max_hold - len(portfolio)
                picks = today_scores[:slots]

                for code6, score in picks:
                    if code6 in portfolio:
                        continue
                    df_stock = all_data.get(code6)
                    if df_stock is None or today_str not in df_stock.index:
                        continue

                    buy_price = float(df_stock.loc[today_str, 'close'])
                    shares = int(position_target / buy_price / 100) * 100
                    if shares < 100:
                        continue
                    cost = buy_price * shares
                    if cost > cash:
                        shares = int(cash / buy_price / 100) * 100
                        if shares < 100:
                            continue
                        cost = buy_price * shares

                    # Reset any old sell engine state for this stock
                    sell_engine._states.pop(code6, None)

                    portfolio[code6] = Position(
                        code=code6, buy_date=today_str,
                        buy_price=buy_price, shares=shares, score=score,
                    )
                    cash -= cost

        # 6) Record NAV
        total_value = cash
        for code6, pos in portfolio.items():
            df_stock = all_data.get(code6)
            if df_stock is not None and today_str in df_stock.index:
                price = float(df_stock.loc[today_str, 'close'])
                total_value += price * pos.shares
            else:
                total_value += pos.buy_price * pos.shares  # mark to cost

        equity_curve.append((today_str, round(total_value, 2)))

        if (i + 1) % 10 == 0 or i == len(test_dates) - 1:
            print(f"  [{i+1}/{len(test_dates)}]  "
                  f"Holdings={len(portfolio):2d}  "
                  f"Trades={len(trades):3d}  "
                  f"NAV={total_value:>10.2f}  "
                  f"Cash={cash:>10.2f}", flush=True)

    # ── Close any remaining positions ──
    for code6, pos in list(portfolio.items()):
        df_stock = all_data.get(code6)
        if df_stock is not None:
            last_date = df_stock.index[-1].strftime('%Y-%m-%d')
            sell_price = float(df_stock.iloc[-1]['close'])
            ret = (sell_price - pos.buy_price) / pos.buy_price
            trades.append({
                'code': code6,
                'buy_date': pos.buy_date,
                'sell_date': last_date,
                'buy_price': round(pos.buy_price, 2),
                'sell_price': round(sell_price, 2),
                'return': round(ret * 100, 2),
                'shares': pos.shares,
                'pnl': round((sell_price - pos.buy_price) * pos.shares, 2),
                'sell_reason': 'CLOSE(end)',
                'sell_layer': 'final',
            })
            cash += sell_price * pos.shares
        del portfolio[code6]

    # ── Build results ──
    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()
    if not trades_df.empty:
        trades_df['win'] = trades_df['return'] > 0

    metrics = _compute_metrics(trades, equity_curve)

    # Print summary
    print_summary(metrics, trades)

    # Save CSV
    csv_path = os.path.join(PROJECT_ROOT, 'data', 'backtest_6plus2_full_result.csv')
    if not trades_df.empty:
        trades_df.to_csv(csv_path, index=False, encoding='utf-8')
        print(f"\n  CSV: {csv_path}")

    # Save JSON report
    report_path = os.path.join(PROJECT_ROOT, 'data', 'backtest_6plus2_full_report.json')
    report = {
        'metrics': metrics,
        'trade_count': len(trades),
        'equity_curve': [(d, v) for d, v in equity_curve],
        'config': {
            'pool': pool_path,
            'backtest_days': backtest_days,
            'top_n': top_n,
            'initial_capital': initial_capital,
            'max_hold': max_hold,
        },
    }
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"  JSON: {report_path}")

    return {
        'trades': trades,
        'metrics': metrics,
        'equity_curve': equity_curve,
        'trades_df': trades_df,
    }


# ── CLI ───────────────────────────────────────────────────────────────


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="6+2 Full Backtest with Sell Risk Management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--days', type=int, default=60,
                        help='Backtest trading days (default: 60)')
    parser.add_argument('--top', type=int, default=3,
                        help='Top N stocks to buy daily (default: 3)')
    parser.add_argument('--pool', type=str, default=DEFAULT_POOL,
                        help=f'Pool file path (default: {DEFAULT_POOL})')
    parser.add_argument('--capital', type=float, default=100000.0,
                        help='Initial capital (default: 100000)')
    parser.add_argument('--max-hold', type=int, default=5,
                        help='Max concurrent holdings (default: 5)')
    return parser.parse_args(argv)


def main():
    args = parse_args()
    result = run_backtest(
        pool_path=args.pool,
        backtest_days=args.days,
        top_n=args.top,
        initial_capital=args.capital,
        max_hold=args.max_hold,
    )
    trades = result.get('trades', [])
    metrics = result.get('metrics', {})
    if not trades:
        print("\n  No trades generated.")
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
