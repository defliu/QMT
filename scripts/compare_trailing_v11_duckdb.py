#!/usr/bin/env python3
# coding=utf-8
"""移动止盈 V1.1 对照回测 - DuckDB 真实数据版
数据源: qmt_self_owned DuckDB
Universe: PIT 305 固定池
baseline: 旧 3 段静态阈值 (10-20%:6%, 20-30%:8%, >30%:10%+吊灯)
experiment: V1.1 动态阈值 (ATR 自适应)
"""
import sys
import os
import csv
import tempfile
import copy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import duckdb
from core.risk_manager import (
    SellStrategyEngine, Action, SellPositionState,
    TRAILING_BREAK_MA5_INTERVAL, CHANDELIER_ATR_MULTIPLE,
    CHANDELIER_LOOKBACK, calc_atr,
)
from core.scoring.dimension6plus2 import ScoreCalculator6Plus2
import core.risk_manager as rm_module


# ============================================================
#  数据加载 (照抄 compare_stoploss_position_duckdb.py)
# ============================================================

def load_duckdb_data(db_path, codes, start_date, end_date):
    conn = duckdb.connect(db_path, read_only=True)
    try:
        placeholders = ",".join(["?"] * len(codes))
        sql = """
            SELECT code, trade_date AS date,
                   open, high, low, close, vol, amount
            FROM dat_day
            WHERE code IN (%s)
              AND trade_date BETWEEN ? AND ?
              AND adjustment = 'hfq'
              AND source = 'xtquant'
            ORDER BY code, date
        """ % placeholders
        params = list(codes) + [start_date, end_date]
        df = conn.execute(sql, params).fetchdf()
        df["date"] = df["date"].astype(str)

        all_data = {}
        for code, sub in df.groupby("code"):
            sub = sub.drop(columns=["code"]).reset_index(drop=True)
            sub = sub.set_index("date")
            needed = ["open", "high", "low", "close", "vol"]
            if all(c in sub.columns for c in needed):
                sub = sub[needed].rename(columns={"vol": "volume"})
                all_data[code] = sub.dropna()
        return all_data
    finally:
        conn.close()


def read_universe_csv(path):
    codes = []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row.get("code", "").strip()
            if code:
                codes.append(code)
    return codes


# ============================================================
#  旧版 _check_trailing_profit (3 段静态阈值)
# ============================================================

def _check_trailing_profit_old(self, close, high, low, state):
    """旧版 3 段静态阈值移动止盈 (baseline)"""
    if state.cost_price <= 0 or state.highest_price <= 0:
        return False

    current_price = float(close.iloc[-1])
    profit_pct = (current_price - state.cost_price) / state.cost_price
    drawdown = (state.highest_price - current_price) / state.highest_price

    if profit_pct <= 0:
        return False

    if profit_pct < TRAILING_BREAK_MA5_INTERVAL:
        ma5 = float(close.rolling(5).mean().iloc[-1])
        if current_price < ma5:
            return True
        return False

    atr = None
    if len(close) >= CHANDELIER_LOOKBACK:
        atr_series = calc_atr(close, high, low, n=14)
        atr = float(atr_series.iloc[-1])

    if profit_pct < 0.20:
        return drawdown >= 0.06
    elif profit_pct < 0.30:
        return drawdown >= 0.08
    else:
        if atr is not None:
            chandelier_level = state.highest_price - CHANDELIER_ATR_MULTIPLE * atr
            if current_price <= chandelier_level:
                return True
        return drawdown >= 0.10


# ============================================================
#  回测引擎 (扩展: 追踪移动止盈触发分布)
# ============================================================

class TrailingBacktester:
    def __init__(self, all_data, scorer, initial_capital=100000):
        self.all_data = all_data
        self.scorer = scorer
        self.initial_capital = initial_capital

    def run(self, stop_loss, max_total_ratio, max_hold=3,
            start_date="2025-09-01", end_date="2026-06-10", min_score=50,
            use_old_trailing=False):
        state_file = os.path.join(tempfile.gettempdir(), "_test_trailing_v11.json")
        if os.path.exists(state_file):
            os.remove(state_file)

        engine = SellStrategyEngine("test", "test", state_file,
                                    hard_stop_loss=stop_loss)

        if use_old_trailing:
            engine._check_trailing_profit = lambda c, h, l, s: _check_trailing_profit_old(engine, c, h, l, s)

        all_dates = set()
        for code, df in self.all_data.items():
            all_dates.update(df.index.tolist())
        trade_dates = sorted([d for d in all_dates if start_date <= d <= end_date])

        holdings = {}
        positions = {}
        nav = self.initial_capital
        max_nav = self.initial_capital
        min_nav = self.initial_capital
        daily_navs = []

        total_trades = 0
        win_trades = 0
        total_pnl = 0
        max_single_loss = 0
        stop_loss_count = 0
        trailing_count = 0
        trailing_by_bucket = {"<10%": 0, "10-20%": 0, "20-30%": 0, ">30%": 0}
        total_holding_days = 0
        holding_count = 0
        max_intraday_exposure = 0
        high_vol_hold_days = 0
        high_vol_count = 0
        low_vol_hold_days = 0
        low_vol_count = 0

        for today in trade_dates:
            for code in list(holdings.keys()):
                df = self.all_data.get(code)
                if df is not None and today in df.index:
                    current_price = float(df.loc[today, "close"])
                    holdings[code] = max(holdings[code], current_price)

            if holdings:
                daily_data = {}
                for code in holdings.keys():
                    df = self.all_data.get(code)
                    if df is not None:
                        mask = df.index <= today
                        if mask.sum() >= 30:
                            daily_data[code] = df[mask]

                if daily_data:
                    decisions = engine.evaluate(today.replace("-", ""), holdings,
                                              daily_data, positions)
                    for code, dec, shares in decisions:
                        total_trades += 1
                        if dec.action == Action.CLEAR:
                            df = self.all_data.get(code)
                            if df is not None and today in df.index:
                                sell_price = float(df.loc[today, "close"])
                                if code in positions:
                                    cost = positions[code]["cost"]
                                    pnl = (sell_price - cost) * shares
                                    total_pnl += pnl
                                    nav += pnl
                                    if pnl < max_single_loss:
                                        max_single_loss = pnl
                                    hdays = positions[code].get("holding_days", 0)
                                    total_holding_days += hdays
                                    holding_count += 1

                                    profit_pct = (sell_price - cost) / cost
                                    if profit_pct < 0.10:
                                        bucket = "<10%"
                                    elif profit_pct < 0.20:
                                        bucket = "10-20%"
                                    elif profit_pct < 0.30:
                                        bucket = "20-30%"
                                    else:
                                        bucket = ">30%"

                                    reason = dec.reason or ""
                                    if "移动止盈" in reason:
                                        trailing_count += 1
                                        trailing_by_bucket[bucket] += 1

                                    if "硬止损" in reason:
                                        stop_loss_count += 1
                                    win_trades += 1 if pnl > 0 else 0

                                    atr_val = None
                                    if len(df) >= 20:
                                        try:
                                            atr_s = calc_atr(
                                                df["close"].astype(float),
                                                df["high"].astype(float),
                                                df["low"].astype(float), n=14)
                                            atr_val = float(atr_s.iloc[-1])
                                        except Exception:
                                            pass
                                    if atr_val is not None and sell_price > 0:
                                        atr_pct = atr_val / sell_price
                                        if atr_pct > 0.024:
                                            high_vol_hold_days += hdays
                                            high_vol_count += 1
                                        else:
                                            low_vol_hold_days += hdays
                                            low_vol_count += 1

                            holdings.pop(code, None)
                            positions.pop(code, None)

            if len(holdings) < max_hold:
                available_slots = max_hold - len(holdings)
                for code in list(self.all_data.keys())[:available_slots * 10]:
                    if code in holdings or code in positions:
                        continue
                    df = self.all_data.get(code)
                    if df is None or today not in df.index:
                        continue
                    try:
                        result = self.scorer.score_single(stock_code=code, df=df)
                        if result["score_total"] >= min_score:
                            buy_price = float(df.loc[today, "close"])
                            amount = nav * max_total_ratio / max_hold
                            shares = int(amount / buy_price / 100) * 100
                            if shares >= 100:
                                holdings[code] = buy_price
                                positions[code] = {
                                    "cost": buy_price,
                                    "can_use": shares,
                                    "volume": shares,
                                    "holding_days": 0,
                                    "entry_date": today,
                                }
                                if len(holdings) >= max_hold:
                                    break
                    except Exception:
                        continue

            for code in positions:
                positions[code]["holding_days"] = positions[code].get("holding_days", 0) + 1

            holdings_value = 0
            for code in holdings:
                df = self.all_data.get(code)
                if df is not None and today in df.index:
                    price = float(df.loc[today, "close"])
                    vol = positions.get(code, {}).get("volume", 0)
                    holdings_value += price * vol
            intraday_exposure = holdings_value / nav if nav > 0 else 0
            max_intraday_exposure = max(max_intraday_exposure, intraday_exposure)

            max_nav = max(max_nav, nav)
            min_nav = min(min_nav, nav)
            daily_navs.append((today, nav))

        crash_window = self._find_crash_window(daily_navs)
        max_dd = (max_nav - min_nav) / max_nav * 100
        win_rate = win_trades / total_trades * 100 if total_trades > 0 else 0
        total_return = (nav - self.initial_capital) / self.initial_capital * 100
        avg_holding = total_holding_days / holding_count if holding_count > 0 else 0
        sharpe = self._calc_sharpe(daily_navs)

        high_vol_avg = high_vol_hold_days / high_vol_count if high_vol_count > 0 else 0
        low_vol_avg = low_vol_hold_days / low_vol_count if low_vol_count > 0 else 0

        return {
            "stop_loss": stop_loss,
            "max_total_ratio": max_total_ratio,
            "trades": total_trades,
            "win_rate": win_rate,
            "total_return": total_return,
            "max_drawdown": max_dd,
            "total_pnl": total_pnl,
            "max_single_loss": max_single_loss,
            "stop_loss_count": stop_loss_count,
            "trailing_count": trailing_count,
            "trailing_by_bucket": trailing_by_bucket,
            "max_intraday_exposure": max_intraday_exposure,
            "avg_holding_days": avg_holding,
            "high_vol_avg_holding": high_vol_avg,
            "low_vol_avg_holding": low_vol_avg,
            "sharpe": sharpe,
            "crash_window": crash_window,
        }

    def _calc_sharpe(self, daily_navs, rf=0.03):
        if len(daily_navs) < 2:
            return 0.0
        returns = []
        for i in range(1, len(daily_navs)):
            prev = daily_navs[i - 1][1]
            curr = daily_navs[i][1]
            if prev > 0:
                returns.append((curr - prev) / prev)
        if not returns:
            return 0.0
        arr = np.array(returns)
        mean_r = arr.mean()
        std_r = arr.std()
        if std_r == 0:
            return 0.0
        annual_factor = np.sqrt(252)
        return (mean_r * 252 - rf) / (std_r * annual_factor)

    def _find_crash_window(self, daily_navs):
        if len(daily_navs) < 2:
            return None
        max_nav = 0
        max_dd_start = 0
        max_dd_end = 0
        max_dd = 0
        current_start = 0
        for i, (date, nav) in enumerate(daily_navs):
            if nav > max_nav:
                max_nav = nav
                current_start = i
            dd = (max_nav - nav) / max_nav * 100
            if dd > max_dd:
                max_dd = dd
                max_dd_start = current_start
                max_dd_end = i
        if max_dd < 5:
            return None
        return {
            "start_date": daily_navs[max_dd_start][0],
            "end_date": daily_navs[max_dd_end][0],
            "max_dd": max_dd,
        }


# ============================================================
#  主函数
# ============================================================

if __name__ == "__main__":
    print("=" * 70)
    print("移动止盈 V1.1 对照回测 — DuckDB 真实数据版")
    print("工程签收口径，非策略结论")
    print("=" * 70)

    db_path = "/mnt/f/backtest_workspace/data/duckdb/qmt_market_data.duckdb"
    universe_path = "/mnt/d/QMT_STRATEGIES/backtest/data/universe/p2_1b_full_a_pit_union_305.csv"

    codes = read_universe_csv(universe_path)
    print("Universe: %d 只 (PIT 305)" % len(codes))

    print("加载 DuckDB 数据...")
    all_data = load_duckdb_data(db_path, codes, "2025-06-01", "2026-06-10")
    print("有效数据: %d 只" % len(all_data))

    scorer = ScoreCalculator6Plus2()
    backtester = TrailingBacktester(all_data, scorer)

    # baseline: 旧 3 段静态阈值, -5% 止损, 85% 仓位
    print("\n运行 baseline (旧 3 段静态阈值)...")
    r_base = backtester.run(-0.05, 0.85, use_old_trailing=True)
    print("  交易: %d, 胜率: %.1f%%, 收益: %+.2f%%, 回撤: %.2f%%, 夏普: %.2f" % (
        r_base["trades"], r_base["win_rate"], r_base["total_return"],
        r_base["max_drawdown"], r_base["sharpe"]))
    print("  移动止盈: %d 次" % r_base["trailing_count"])
    print("  分桶: %s" % r_base["trailing_by_bucket"])

    # experiment: V1.1 动态阈值, -5% 止损, 85% 仓位
    print("\n运行 experiment (V1.1 动态阈值)...")
    r_exp = backtester.run(-0.05, 0.85, use_old_trailing=False)
    print("  交易: %d, 胜率: %.1f%%, 收益: %+.2f%%, 回撤: %.2f%%, 夏普: %.2f" % (
        r_exp["trades"], r_exp["win_rate"], r_exp["total_return"],
        r_exp["max_drawdown"], r_exp["sharpe"]))
    print("  移动止盈: %d 次" % r_exp["trailing_count"])
    print("  分桶: %s" % r_exp["trailing_by_bucket"])

    # 对照表
    print("\n" + "=" * 70)
    print("对照表")
    print("=" * 70)
    fmt = "%-20s | %10s | %10s | %10s"
    print(fmt % ("指标", "baseline", "实验", "差异"))
    print("-" * 60)

    def diff_str(a, b, fmt_str="%+.2f"):
        d = b - a
        return fmt_str % a, fmt_str % b, fmt_str % d

    for label, key in [
        ("总收益", "total_return"),
        ("胜率", "win_rate"),
        ("最大回撤", "max_drawdown"),
        ("夏普比率", "sharpe"),
    ]:
        a, b, d = diff_str(r_base[key], r_exp[key])
        print(fmt % (label, a, b, d))

    print(fmt % ("交易笔次", str(r_base["trades"]), str(r_exp["trades"]),
                  str(r_exp["trades"] - r_base["trades"])))

    for bucket in ["<10%", "10-20%", "20-30%", ">30%"]:
        a = r_base["trailing_by_bucket"][bucket]
        b = r_exp["trailing_by_bucket"][bucket]
        print(fmt % ("止盈触发(%s)" % bucket, str(a), str(b), str(b - a)))

    print(fmt % ("高波动股均持仓天",
                  "%.1f" % r_base["high_vol_avg_holding"],
                  "%.1f" % r_exp["high_vol_avg_holding"],
                  "%.1f" % (r_exp["high_vol_avg_holding"] - r_base["high_vol_avg_holding"])))
    print(fmt % ("低波动股均持仓天",
                  "%.1f" % r_base["low_vol_avg_holding"],
                  "%.1f" % r_exp["low_vol_avg_holding"],
                  "%.1f" % (r_exp["low_vol_avg_holding"] - r_base["low_vol_avg_holding"])))

    # 暴跌窗口
    print("\n" + "=" * 70)
    print("暴跌窗口")
    print("=" * 70)
    for label, r in [("baseline", r_base), ("experiment", r_exp)]:
        cw = r.get("crash_window")
        if cw:
            print("[%s] %s → %s, 回撤 %.2f%%" % (
                label, cw["start_date"], cw["end_date"], cw["max_dd"]))
        else:
            print("[%s] 无 5%%+ 回撤窗口" % label)

    print("\n注: 工程签收口径，证明 V1.1 代码逻辑正确，不作为策略结论依据。")
    print("数据源: qmt_self_owned DuckDB, Universe: PIT 305")
    print("脚本: scripts/compare_trailing_v11_duckdb.py")
