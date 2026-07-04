# coding=utf-8
"""尾盘30分钟选股法 — 精简版隔夜回测（独立脚本）

T日收盘 close 买入 + T+1 开盘 open 卖出的隔夜策略。
全A股 universe，回测 2023-01 ~ 2026-06，输出工厂标准6文件。
"""
import csv
import json
import math
import os
import time
from datetime import datetime

import numpy as np
import pandas as pd

# ── 参数 ──────────────────────────────────────────────────────────────
START_DATE = "2023-01-01"
END_DATE = "2026-06-30"
INITIAL_CASH = 1_000_000.0
MAX_POSITIONS = 5
COMMISSION_RATE = 0.00025
SLIPPAGE = 0.001
TAX_RATE = 0.001

DATA_PATH = "E:/astock/daily/stock_daily.parquet"
UNIVERSE_PATH = "D:/QMT_STRATEGIES/backtest/data/universe/full_a_sh_sz.csv"
RESULTS_BASE = "F:/backtest_workspace/results"

# ── 数据加载 ──────────────────────────────────────────────────────────

def load_universe(path):
    """读取 universe CSV，只取 enabled=true 的 code。"""
    df = pd.read_csv(path, encoding="utf-8-sig")
    df["enabled"] = df["enabled"].astype(str).str.lower().str.strip()
    codes = df.loc[df["enabled"] == "true", "code"].tolist()
    name_map = dict(zip(df["code"], df["name"].fillna("")))
    return codes, name_map


def load_parquet(path):
    """读取 astock daily parquet (MultiIndex: trade_date, ts_code)。
    复权: open/high/low/close × adj_factor；vol/turnover_rate/circ_mv 不复权。
    """
    print("[DATA] Reading parquet ...")
    raw = pd.read_parquet(path)
    if isinstance(raw.index, pd.MultiIndex):
        raw = raw.reset_index()
    # 确保 trade_date 是字符串格式 YYYYMMDD
    raw["trade_date"] = raw["trade_date"].astype(str).str[:8]
    print("[DATA] Loaded %d rows, columns: %s" % (len(raw), list(raw.columns)))
    return raw


# ── 指标计算 ──────────────────────────────────────────────────────────

def compute_indicators(df):
    """单 code 全序列向量化指标计算。PIT安全，rolling 只用过去数据。
    返回添加了指标列的 DataFrame。
    """
    out = df.copy()
    close = out["close"]
    vol = out["vol"]

    # pct_chg: 当日涨幅 (hfq close)
    out["pct_chg"] = close / close.shift(1) - 1

    # vol_ratio: 量比 = vol[t] / mean(vol[t-1..t-5])
    prev_vol_ma5 = vol.shift(1).rolling(5, min_periods=5).mean()
    out["vol_ratio"] = np.where(
        (prev_vol_ma5.notna()) & (prev_vol_ma5 > 0),
        vol / prev_vol_ma5,
        np.nan,
    )

    # MA 多头排列
    out["ma5"] = close.rolling(5, min_periods=5).mean()
    out["ma10"] = close.rolling(10, min_periods=10).mean()
    out["ma20"] = close.rolling(20, min_periods=20).mean()
    out["ma60"] = close.rolling(60, min_periods=60).mean()

    # circ_mv 转亿
    if "circ_mv" in out.columns:
        out["circ_mv_yi"] = out["circ_mv"] / 10000.0
    else:
        out["circ_mv_yi"] = np.nan

    return out


# ── 信号筛选 ──────────────────────────────────────────────────────────

def generate_signals(all_data, universe_codes, name_map, trading_days):
    """向量化生成每日信号。返回 dict: {trade_date_str: [code, ...]}"""
    print("[SIGNAL] Generating signals ...")
    signals = {}
    # 条件统计
    cond_stats = {
        "pct_chg_pass": 0, "vol_ratio_pass": 0, "turnover_pass": 0,
        "circ_mv_pass": 0, "ma_bull_pass": 0, "all_pass": 0,
        "blocked_st": 0, "blocked_new": 0, "blocked_limitup": 0,
    }

    # 过滤 universe
    data = all_data[all_data["ts_code"].isin(universe_codes)].copy()

    # 按 code 分组计算指标
    print("[SIGNAL] Computing indicators per code ...")
    indicator_dfs = []
    codes_in_data = data["ts_code"].unique()
    total_codes = len(codes_in_data)
    for i, code in enumerate(codes_in_data):
        if (i + 1) % 500 == 0:
            print("  ... processed %d / %d codes" % (i + 1, total_codes))
        cdf = data[data["ts_code"] == code].copy()
        cdf = cdf.sort_values("trade_date").reset_index(drop=True)
        # 次新过滤：序号 < 60 跳过
        cdf["listed_days"] = np.arange(len(cdf))
        cdf = compute_indicators(cdf)
        indicator_dfs.append(cdf)

    all_ind = pd.concat(indicator_dfs, ignore_index=True)
    print("[SIGNAL] Indicators computed. Total rows: %d" % len(all_ind))

    # ST 过滤
    st_mask = all_ind["ts_code"].map(name_map).fillna("").str.contains("ST", na=False)
    new_mask = all_ind["listed_days"] < 60
    limitup_mask = (all_ind["pct_chg"] >= 0.0995) & (all_ind.get("high", 0) == all_ind.get("low", 0))

    cond_stats["blocked_st"] = int(st_mask.sum())
    cond_stats["blocked_new"] = int(new_mask.sum())
    cond_stats["blocked_limitup"] = int(limitup_mask.sum())

    # 6 条件 (不含条件6，条件6是撮合层)
    c1 = (all_ind["pct_chg"] >= 0.03) & (all_ind["pct_chg"] <= 0.05)
    c2 = all_ind["vol_ratio"] >= 1.5
    c3 = (all_ind["turnover_rate"] >= 5.0) & (all_ind["turnover_rate"] <= 10.0)
    c4 = (all_ind["circ_mv_yi"] >= 50.0) & (all_ind["circ_mv_yi"] <= 200.0)
    c5 = (all_ind["ma5"] > all_ind["ma10"]) & (all_ind["ma10"] > all_ind["ma20"]) & (all_ind["ma20"] > all_ind["ma60"])

    cond_stats["pct_chg_pass"] = int(c1.sum())
    cond_stats["vol_ratio_pass"] = int(c2.sum())
    cond_stats["turnover_pass"] = int(c3.sum())
    cond_stats["circ_mv_pass"] = int(c4.sum())
    cond_stats["ma_bull_pass"] = int(c5.sum())

    # 通过卫生过滤
    hygiene_pass = ~st_mask & ~new_mask & ~limitup_mask

    # 6条件全部满足
    all_cond = c1 & c2 & c3 & c4 & c5 & hygiene_pass
    cond_stats["all_pass"] = int(all_cond.sum())

    # 按日期分组
    passed = all_ind.loc[all_cond, ["trade_date", "ts_code"]].copy()
    for dt, grp in passed.groupby("trade_date"):
        signals[dt] = grp["ts_code"].tolist()

    days_with_signals = len(signals)
    total_signals = cond_stats["all_pass"]
    avg_per_day = total_signals / max(days_with_signals, 1)
    signal_counts = [len(v) for v in signals.values()]
    median_per_day = float(np.median(signal_counts)) if signal_counts else 0
    max_per_day = max(signal_counts) if signal_counts else 0

    print("[SIGNAL] Done. total_signals=%d, days_with_signals=%d/%d, avg=%.1f, median=%.0f, max=%d"
          % (total_signals, days_with_signals, len(trading_days), avg_per_day, median_per_day, max_per_day))

    signal_stats = {
        "total_signals": total_signals,
        "avg_signals_per_day": round(avg_per_day, 2),
        "median_signals_per_day": median_per_day,
        "max_signals_per_day": max_per_day,
        "days_with_signals": days_with_signals,
        "days_total": len(trading_days),
    }
    return signals, cond_stats, signal_stats


# ── 撮合引擎 ──────────────────────────────────────────────────────────

def run_matching(all_data, signals, trading_days, name_map):
    """隔夜撮合: T日 close 买 + T+1 open 卖。
    返回 trades, equity_rows, positions_rows, daily_logs, unfilled_logs。
    """
    print("[MATCH] Running overnight matching engine ...")
    # 建立 (date, code) → 行的快速索引
    all_data = all_data.set_index(["trade_date", "ts_code"])
    all_data = all_data.sort_index()

    cash = INITIAL_CASH
    holdings = []  # list of dict: {code, volume, buy_price, buy_date, target_sell_date}
    trades = []
    equity_rows = []
    daily_logs = []
    unfilled_logs = []

    day_to_idx = {d: i for i, d in enumerate(trading_days)}

    for day_idx, today in enumerate(trading_days):
        # T+1 date
        if day_idx + 1 >= len(trading_days):
            next_day = None
        else:
            next_day = trading_days[day_idx + 1]

        # ── 卖出 T-1 买入的持仓（在 T 日 open 卖） ──
        # 实际上是 T-1 日买入的在 T 日 open 卖
        # 但我们按日期遍历，所以 T 日先处理昨日买入的卖出
        # 重新设计：买入在 T 日 close，卖出在 T+1 open
        # 所以 holdings 里存的是 "将在 next_day open 卖" 的持仓
        # 每天开始时，先检查是否有持仓需要在 today open 卖出

        # 查找需要在 today open 卖出的持仓 (昨天买入的)
        to_sell = [h for h in holdings if h["target_sell_date"] == today]
        remaining = [h for h in holdings if h["target_sell_date"] != today]

        for h in to_sell:
            code = h["code"]
            volume = h["volume"]
            buy_price = h["buy_price"]
            buy_date = h["buy_date"]

            # 查 T 日 open
            key = (today, code)
            if key in all_data.index:
                row = all_data.loc[key]
                if isinstance(row, pd.DataFrame):
                    row = row.iloc[0]
                open_price = row["open"]
                # 检查一字跌停
                high = row["high"]
                low = row["low"]
                prev_close = row.get("close", open_price)
                # 简化跌停判断：open == low 且 open 相对前收跌幅大
                # 实际跌停判断需要前一日 close，这里用 open <= prev_close * 0.91 近似
                if not np.isnan(open_price) and open_price > 0:
                    sell_price = open_price * (1 - SLIPPAGE)
                    sell_amount = sell_price * volume
                    commission = sell_amount * COMMISSION_RATE
                    tax = sell_amount * TAX_RATE
                    net = sell_amount - commission - tax
                    cash += net
                    ret = (sell_price - buy_price) / buy_price - COMMISSION_RATE * 2 - TAX_RATE
                    trades.append({
                        "run_id": "", "date": today, "code": code,
                        "side": "sell", "volume": volume,
                        "price": round(sell_price, 4),
                        "amount": round(sell_amount, 2),
                        "slippage_amt": round(open_price * SLIPPAGE * volume, 2),
                        "commission": round(commission, 2),
                        "tax": round(tax, 2),
                        "reason": "overnight_sell",
                        "layer": "",
                        "model": "next_open",
                    })
                else:
                    # 停牌或无数据，顺延
                    unfilled_logs.append("[WARN] UNFILLED sell %s %s vol=%d reason=no_data_or_suspended" % (today, code, volume))
                    h["target_sell_date"] = None  # 标记需要找下一个有数据的交易日
                    remaining.append(h)
            else:
                # 停牌，顺延
                unfilled_logs.append("[WARN] UNFILLED sell %s %s vol=%d reason=suspended" % (today, code, volume))
                h["target_sell_date"] = None
                remaining.append(h)

        # 顺延未成交的持仓到下一个有数据的交易日
        for h in remaining:
            if h["target_sell_date"] is None or h["target_sell_date"] == today:
                # 找下一个有数据的交易日
                start_idx = day_to_idx.get(today, 0) + 1
                found = False
                for fwd in range(start_idx, min(start_idx + 20, len(trading_days))):
                    fwd_day = trading_days[fwd]
                    key = (fwd_day, h["code"])
                    if key in all_data.index:
                        row = all_data.loc[key]
                        if isinstance(row, pd.DataFrame):
                            row = row.iloc[0]
                        if not np.isnan(row["open"]) and row["open"] > 0:
                            h["target_sell_date"] = fwd_day
                            found = True
                            break
                if not found:
                    unfilled_logs.append("[WARN] UNFILLED sell %s %s vol=%d reason=no_data_20days" % (today, h["code"], h["volume"]))

        holdings = remaining

        # ── 扫描今日信号 ──
        sig_codes = signals.get(today, [])
        scanned = len(all_data.loc[today].index.get_level_values("ts_code").unique()) if today in all_data.index.get_level_values(0) else 0

        # ── 买入（T 日 close）──
        max_can_buy = MAX_POSITIONS - len(holdings)
        if max_can_buy > 0 and sig_codes:
            target_cash = (cash + sum(
                holdings_data["volume"] * _get_close(all_data, today, holdings_data["code"])
                for holdings_data in holdings
            )) / MAX_POSITIONS if MAX_POSITIONS > 0 else 0
            target_cash = min(target_cash, cash / max_can_buy) if max_can_buy > 0 else 0

            bought = 0
            for code in sig_codes:
                if bought >= max_can_buy:
                    break
                if code in [h["code"] for h in holdings]:
                    continue  # 已持有

                key = (today, code)
                if key not in all_data.index:
                    continue
                row = all_data.loc[key]
                if isinstance(row, pd.DataFrame):
                    row = row.iloc[0]
                close_price = row["close"]
                if np.isnan(close_price) or close_price <= 0:
                    continue

                buy_price = close_price * (1 + SLIPPAGE)
                volume = math.floor(target_cash / buy_price / 100) * 100
                if volume <= 0:
                    continue

                buy_amount = buy_price * volume
                commission = buy_amount * COMMISSION_RATE
                total_cost = buy_amount + commission
                if total_cost > cash:
                    # 资金不足，尝试减量
                    volume = math.floor((cash - 100) / buy_price / 100) * 100
                    if volume <= 0:
                        continue
                    buy_amount = buy_price * volume
                    commission = buy_amount * COMMISSION_RATE
                    total_cost = buy_amount + commission
                    if total_cost > cash:
                        continue

                cash -= total_cost
                holdings.append({
                    "code": code,
                    "volume": volume,
                    "buy_price": buy_price,
                    "buy_date": today,
                    "target_sell_date": next_day,
                })
                trades.append({
                    "run_id": "", "date": today, "code": code,
                    "side": "buy", "volume": volume,
                    "price": round(buy_price, 4),
                    "amount": round(buy_amount, 2),
                    "slippage_amt": round(close_price * SLIPPAGE * volume, 2),
                    "commission": round(commission, 2),
                    "tax": 0,
                    "reason": "tail_30min_signal",
                    "layer": "",
                    "model": "close",
                })
                bought += 1

        # ── 净值 ──
        market_value = 0
        for h in holdings:
            key = (today, h["code"])
            if key in all_data.index:
                row = all_data.loc[key]
                if isinstance(row, pd.DataFrame):
                    row = row.iloc[0]
                close_p = row["close"]
                if not np.isnan(close_p):
                    market_value += close_p * h["volume"]

        total_asset = cash + market_value
        daily_ret = 0.0
        if len(equity_rows) > 0 and equity_rows[-1]["total_asset"] > 0:
            daily_ret = (total_asset - equity_rows[-1]["total_asset"]) / equity_rows[-1]["total_asset"]

        equity_rows.append({
            "run_id": "",
            "date": today,
            "total_asset": round(total_asset, 2),
            "cash": round(cash, 2),
            "market_value": round(market_value, 2),
            "daily_return": round(daily_ret, 6),
            "benchmark_close": 0,
            "benchmark_return": 0,
        })

        # ── positions ──
        for h in holdings:
            key = (today, h["code"])
            last_price = 0
            if key in all_data.index:
                row = all_data.loc[key]
                if isinstance(row, pd.DataFrame):
                    row = row.iloc[0]
                last_price = row["close"] if not np.isnan(row["close"]) else 0
            pnl = (last_price - h["buy_price"]) * h["volume"]
            holding_days = day_idx - day_to_idx.get(h["buy_date"], day_idx) + 1
            equity_rows[-1]  # just for context
            # 追加到 daily positions (we'll build positions_rows later)

        # ── 日志 ──
        n_buy = sum(1 for t in trades if t["date"] == today and t["side"] == "buy")
        n_sell = sum(1 for t in trades if t["date"] == today and t["side"] == "sell")
        daily_logs.append("date=%s scanned=%d passed=%d buy=%d sell=%d" % (
            today, scanned, len(sig_codes), n_buy, n_sell))

    # 构建 positions_rows
    positions_rows = []
    for eq in equity_rows:
        dt = eq["date"]
        for h in holdings:
            if h["buy_date"] <= dt:
                key = (dt, h["code"])
                last_price = 0
                if key in all_data.index:
                    row = all_data.loc[key]
                    if isinstance(row, pd.DataFrame):
                        row = row.iloc[0]
                    last_price = row["close"] if not np.isnan(row["close"]) else 0
                pnl = (last_price - h["buy_price"]) * h["volume"]
                positions_rows.append({
                    "run_id": "",
                    "date": dt,
                    "code": h["code"],
                    "volume": h["volume"],
                    "available_volume": 0,
                    "cost_price": round(h["buy_price"], 4),
                    "last_price": round(last_price, 4),
                    "unrealized_pnl": round(pnl, 2),
                    "holding_days": 0,
                })

    return trades, equity_rows, positions_rows, daily_logs, unfilled_logs


def _get_close(all_data, date, code):
    """安全获取 close 价格。"""
    key = (date, code)
    if key in all_data.index:
        row = all_data.loc[key]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        c = row["close"]
        return c if not np.isnan(c) else 0
    return 0


# ── 绩效指标 ──────────────────────────────────────────────────────────

def compute_performance(equity_rows, trades):
    """计算核心绩效指标。"""
    if not equity_rows:
        return {}

    assets = [e["total_asset"] for e in equity_rows]
    total_return = (assets[-1] / INITIAL_CASH) - 1.0

    # 年化
    n_days = len(equity_rows)
    years = n_days / 252.0
    annual_return = (1 + total_return) ** (1.0 / max(years, 0.01)) - 1.0 if total_return > -1 else -1.0

    # 最大回撤
    peak = assets[0]
    max_dd = 0.0
    for a in assets:
        if a > peak:
            peak = a
        dd = (peak - a) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    # Sharpe
    rets = [e["daily_return"] for e in equity_rows]
    rets_arr = np.array(rets)
    sharpe = (np.mean(rets_arr) / np.std(rets_arr) * np.sqrt(252)) if np.std(rets_arr) > 0 else 0

    # Calmar
    calmar = annual_return / max_dd if max_dd > 0 else 0

    # 胜率 / 盈亏比
    buy_trades = [t for t in trades if t["side"] == "buy"]
    sell_trades = [t for t in trades if t["side"] == "sell"]
    # 配对
    pairs = []
    for bt in buy_trades:
        for st in sell_trades:
            if st["code"] == bt["code"] and st["date"] > bt["date"]:
                pairs.append((bt, st))
                break

    n_trades = len(pairs)
    n_win = sum(1 for b, s in pairs if s["price"] * s["volume"] > b["price"] * b["volume"])
    win_rate = n_win / n_trades if n_trades > 0 else 0

    wins = [s["price"] / b["price"] - 1 for b, s in pairs if s["price"] * s["volume"] > b["price"] * b["volume"]]
    losses = [1 - s["price"] / b["price"] for b, s in pairs if s["price"] * s["volume"] <= b["price"] * b["volume"]]
    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 0.001
    profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0

    return {
        "total_return": round(total_return, 6),
        "annual_return": round(annual_return, 6),
        "max_drawdown": round(max_dd, 6),
        "sharpe": round(sharpe, 4),
        "calmar": round(calmar, 4),
        "win_rate": round(win_rate, 4),
        "profit_loss_ratio": round(profit_loss_ratio, 4),
        "n_trades": n_trades,
        "n_buy": len(buy_trades),
        "n_sell": len(sell_trades),
    }


# ── 输出6文件 ─────────────────────────────────────────────────────────

def make_results_dir():
    """创建结果目录 F:/backtest_workspace/results/tail_30min_<YYYYMMDD_HHMMSS>/"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dirname = "tail_30min_%s" % ts
    path = os.path.join(RESULTS_BASE, dirname)
    os.makedirs(path, exist_ok=True)
    return path


def write_csv(path, rows, columns):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_all_files(results_dir, summary, trades, equity_rows, positions_rows, daily_logs, unfilled_logs):
    """输出工厂标准6文件。"""
    # 1. summary.json
    with open(os.path.join(results_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

    # 2. trades.csv
    trades_cols = ["run_id", "date", "code", "side", "volume", "price", "amount",
                   "slippage_amt", "commission", "tax", "reason", "layer", "model"]
    write_csv(os.path.join(results_dir, "trades.csv"), trades, trades_cols)

    # 3. equity_curve.csv
    equity_cols = ["run_id", "date", "total_asset", "cash", "market_value",
                   "daily_return", "benchmark_close", "benchmark_return"]
    write_csv(os.path.join(results_dir, "equity_curve.csv"), equity_rows, equity_cols)

    # 4. positions.csv
    positions_cols = ["run_id", "date", "code", "volume", "available_volume",
                      "cost_price", "last_price", "unrealized_pnl", "holding_days"]
    write_csv(os.path.join(results_dir, "positions.csv"), positions_rows, positions_cols)

    # 5. logs.txt
    with open(os.path.join(results_dir, "logs.txt"), "w", encoding="utf-8") as f:
        # WARN 块
        if unfilled_logs:
            for line in unfilled_logs:
                f.write(line + "\n")
            f.write("\n")
        for line in daily_logs:
            f.write(line + "\n")

    # 6. report.md
    write_report_md(results_dir, summary, equity_rows, positions_rows, daily_logs)


def write_report_md(results_dir, summary, equity_rows, positions_rows, daily_logs):
    perf = summary.get("performance", {})
    sig = summary.get("signal_stats", {})
    parts = []
    parts.append("# Backtest Report -- tail_30min\n")

    parts.append("## Run 元信息\n")
    parts.append("| 项 | 值 |")
    parts.append("|---|---|")
    parts.append("| run_id | %s |" % summary.get("run_id", ""))
    parts.append("| run_started_at | %s |" % summary.get("run_started_at", ""))
    parts.append("| runtime_seconds | %s |" % str(summary.get("runtime_seconds", "")))
    parts.append("| config_name | %s |" % summary.get("config_name", ""))
    parts.append("| data_source | %s |" % summary.get("data_source", ""))
    parts.append("| data_adjustment | %s |" % summary.get("data_adjustment", ""))
    parts.append("")

    parts.append("## 业绩指标\n")
    parts.append("| 指标 | 值 |")
    parts.append("|---|---|")
    parts.append("| total_return | %.2f%% |" % (perf.get("total_return", 0) * 100))
    parts.append("| annual_return | %.2f%% |" % (perf.get("annual_return", 0) * 100))
    parts.append("| max_drawdown | %.2f%% |" % (perf.get("max_drawdown", 0) * 100))
    parts.append("| sharpe | %.3f |" % perf.get("sharpe", 0))
    parts.append("| calmar | %.3f |" % perf.get("calmar", 0))
    parts.append("| win_rate | %.2f%% |" % (perf.get("win_rate", 0) * 100))
    parts.append("| profit_loss_ratio | %.2f |" % perf.get("profit_loss_ratio", 0))
    parts.append("| n_trades | %d |" % perf.get("n_trades", 0))
    parts.append("")

    parts.append("## 信号稀疏度\n")
    parts.append("| 指标 | 值 |")
    parts.append("|---|---|")
    parts.append("| total_signals | %d |" % sig.get("total_signals", 0))
    parts.append("| avg_signals_per_day | %.1f |" % sig.get("avg_signals_per_day", 0))
    parts.append("| median_signals_per_day | %.0f |" % sig.get("median_signals_per_day", 0))
    parts.append("| max_signals_per_day | %d |" % sig.get("max_signals_per_day", 0))
    parts.append("| days_with_signals | %d / %d |" % (sig.get("days_with_signals", 0), sig.get("days_total", 0)))
    parts.append("")

    parts.append("## 持仓概览（期末）\n")
    parts.append("| code | volume | cost | last | pnl |")
    parts.append("|---|---|---|---|---|")
    if equity_rows:
        end_date = equity_rows[-1]["date"]
        last_pos = [r for r in positions_rows if r["date"] == end_date]
        for r in last_pos[-5:]:
            parts.append("| %s | %d | %.2f | %.2f | %.2f |" % (
                r["code"], r["volume"], r["cost_price"], r["last_price"], r["unrealized_pnl"]))
    parts.append("")

    parts.append("## 数据元信息\n")
    parts.append("- data_path: %s" % summary.get("data_path", DATA_PATH))
    parts.append("- data_adjustment: hfq (后复权)")
    parts.append("- universe_size: %d" % summary.get("universe_size", 0))
    parts.append("- trading_days: %d" % summary.get("trading_days", 0))
    parts.append("- benchmark: %s" % ("enabled" if summary.get("benchmark_available") else "disabled"))
    parts.append("")

    parts.append("## 复现命令\n")
    parts.append("```bash")
    parts.append("py -3.10 scripts/backtest_tail_30min.py")
    parts.append("```\n")

    with open(os.path.join(results_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(parts))


# ── 主入口 ──────────────────────────────────────────────────────────

def main():
    t0 = time.time()
    run_id = datetime.now().strftime("tail30_%Y%m%d_%H%M%S")
    print("=" * 60)
    print("尾盘30分钟选股法 — 隔夜回测")
    print("run_id: %s" % run_id)
    print("=" * 60)

    # 加载数据
    universe_codes, name_map = load_universe(UNIVERSE_PATH)
    print("[UNIVERSE] %d enabled codes" % len(universe_codes))

    raw = load_parquet(DATA_PATH)

    # 过滤日期范围
    raw = raw[(raw["trade_date"] >= START_DATE.replace("-", "")) &
              (raw["trade_date"] <= END_DATE.replace("-", ""))]
    print("[DATA] After date filter: %d rows" % len(raw))

    # 交易日列表
    trading_days = sorted(raw["trade_date"].unique())
    print("[DATA] Trading days: %d (%s ~ %s)" % (len(trading_days), trading_days[0], trading_days[-1]))

    # 指标计算
    print("[INDICATORS] Computing ...")
    indicator_dfs = []
    codes_in_data = raw["ts_code"].unique()
    codes_in_universe = [c for c in codes_in_data if c in set(universe_codes)]
    print("[INDICATORS] Codes in data & universe: %d / %d" % (len(codes_in_universe), len(universe_codes)))

    for i, code in enumerate(codes_in_universe):
        if (i + 1) % 500 == 0:
            print("  ... %d / %d codes processed" % (i + 1, len(codes_in_universe)))
        cdf = raw[raw["ts_code"] == code].copy()
        cdf = cdf.sort_values("trade_date").reset_index(drop=True)
        cdf["listed_days"] = np.arange(len(cdf))
        cdf = compute_indicators(cdf)
        indicator_dfs.append(cdf)

    all_ind = pd.concat(indicator_dfs, ignore_index=True)
    print("[INDICATORS] Total rows: %d" % len(all_ind))

    # 信号生成
    cond_stats = {
        "pct_chg_pass": 0, "vol_ratio_pass": 0, "turnover_pass": 0,
        "circ_mv_pass": 0, "ma_bull_pass": 0, "all_pass": 0,
        "blocked_st": 0, "blocked_new": 0, "blocked_limitup": 0,
    }
    signals = {}
    signal_counts_by_day = []

    st_mask = all_ind["ts_code"].map(name_map).fillna("").str.contains("ST", na=False)
    new_mask = all_ind["listed_days"] < 60
    if "high" in all_ind.columns and "low" in all_ind.columns:
        limitup_mask = (all_ind["pct_chg"] >= 0.0995) & (all_ind["high"] == all_ind["low"])
    else:
        limitup_mask = pd.Series(False, index=all_ind.index)

    cond_stats["blocked_st"] = int(st_mask.sum())
    cond_stats["blocked_new"] = int(new_mask.sum())
    cond_stats["blocked_limitup"] = int(limitup_mask.sum())

    c1 = (all_ind["pct_chg"] >= 0.03) & (all_ind["pct_chg"] <= 0.05)
    c2 = all_ind["vol_ratio"] >= 1.5
    c3 = (all_ind["turnover_rate"] >= 5.0) & (all_ind["turnover_rate"] <= 10.0)
    c4 = (all_ind["circ_mv_yi"] >= 50.0) & (all_ind["circ_mv_yi"] <= 200.0)
    c5 = (all_ind["ma5"] > all_ind["ma10"]) & (all_ind["ma10"] > all_ind["ma20"]) & (all_ind["ma20"] > all_ind["ma60"])

    cond_stats["pct_chg_pass"] = int(c1.sum())
    cond_stats["vol_ratio_pass"] = int(c2.sum())
    cond_stats["turnover_pass"] = int(c3.sum())
    cond_stats["circ_mv_pass"] = int(c4.sum())
    cond_stats["ma_bull_pass"] = int(c5.sum())

    hygiene_pass = ~st_mask & ~new_mask & ~limitup_mask
    all_cond = c1 & c2 & c3 & c4 & c5 & hygiene_pass
    cond_stats["all_pass"] = int(all_cond.sum())

    passed = all_ind.loc[all_cond, ["trade_date", "ts_code"]].copy()
    for dt, grp in passed.groupby("trade_date"):
        signals[dt] = grp["ts_code"].tolist()
        signal_counts_by_day.append(len(grp))

    days_with_signals = len(signals)
    total_signals = cond_stats["all_pass"]
    avg_per_day = total_signals / max(days_with_signals, 1)
    median_per_day = float(np.median(signal_counts_by_day)) if signal_counts_by_day else 0
    max_per_day = max(signal_counts_by_day) if signal_counts_by_day else 0

    print("[SIGNAL] total=%d, days_with=%d/%d, avg=%.1f, median=%.0f, max=%d" % (
        total_signals, days_with_signals, len(trading_days),
        avg_per_day, median_per_day, max_per_day))
    print("[SIGNAL] cond pass counts: pct_chg=%d, vol_ratio=%d, turnover=%d, circ_mv=%d, ma_bull=%d" % (
        cond_stats["pct_chg_pass"], cond_stats["vol_ratio_pass"],
        cond_stats["turnover_pass"], cond_stats["circ_mv_pass"],
        cond_stats["ma_bull_pass"]))
    print("[SIGNAL] hygiene block: st=%d, new=%d, limitup=%d" % (
        cond_stats["blocked_st"], cond_stats["blocked_new"], cond_stats["blocked_limitup"]))

    signal_stats = {
        "total_signals": total_signals,
        "avg_signals_per_day": round(avg_per_day, 2),
        "median_signals_per_day": median_per_day,
        "max_signals_per_day": max_per_day,
        "days_with_signals": days_with_signals,
        "days_total": len(trading_days),
    }

    # 撮合
    raw_indexed = raw.set_index(["trade_date", "ts_code"]).sort_index()
    trades, equity_rows, positions_rows, daily_logs, unfilled_logs = run_matching_v2(
        raw_indexed, signals, trading_days, name_map, run_id)

    # 绩效
    performance = compute_performance(equity_rows, trades)
    print("[PERF] %s" % json.dumps(performance, indent=2))

    # 输出
    results_dir = make_results_dir()
    print("[OUTPUT] %s" % results_dir)

    runtime = round(time.time() - t0, 1)
    summary = {
        "run_id": run_id,
        "run_started_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "runtime_seconds": runtime,
        "config_name": "tail_30min",
        "data_source": "astock",
        "data_adjustment": "hfq",
        "start_date": START_DATE,
        "end_date": END_DATE,
        "initial_cash": INITIAL_CASH,
        "final_asset": equity_rows[-1]["total_asset"] if equity_rows else INITIAL_CASH,
        "universe_size": len(universe_codes),
        "trading_days": len(trading_days),
        "benchmark_available": False,
        "performance": performance,
        "signal_stats": signal_stats,
        "results_dir": results_dir,
        "data_path": DATA_PATH,
    }

    write_all_files(results_dir, summary, trades, equity_rows, positions_rows, daily_logs, unfilled_logs)

    print("=" * 60)
    print("DONE. Runtime: %.1fs" % runtime)
    print("Results: %s" % results_dir)
    print("Files: summary.json, trades.csv, equity_curve.csv, positions.csv, logs.txt, report.md")
    print("=" * 60)

    # ── 自检 ──
    print("\n[SELFCHECK]")
    ok = True

    # 1. 6文件存在
    expected_files = ["summary.json", "trades.csv", "equity_curve.csv", "positions.csv", "logs.txt", "report.md"]
    for fn in expected_files:
        fp = os.path.join(results_dir, fn)
        exists = os.path.exists(fp)
        print("  [%s] %s" % ("PASS" if exists else "FAIL", fn))
        if not exists:
            ok = False

    # 2. trades 有 buy + sell
    n_buy = sum(1 for t in trades if t["side"] == "buy")
    n_sell = sum(1 for t in trades if t["side"] == "sell")
    has_both = n_buy > 0 and n_sell > 0
    print("  [%s] trades: %d buy, %d sell" % ("PASS" if has_both else "FAIL", n_buy, n_sell))
    if not has_both:
        ok = False

    # 3. buy price 非零非NaN
    buy_prices = [t["price"] for t in trades if t["side"] == "buy"][:3]
    all_valid = all(p > 0 and not math.isnan(p) for p in buy_prices)
    print("  [%s] buy prices (sample 3): %s" % ("PASS" if all_valid else "FAIL", buy_prices))
    if not all_valid:
        ok = False

    # 4. sell price 非零非NaN
    sell_prices = [t["price"] for t in trades if t["side"] == "sell"][:3]
    all_valid = all(p > 0 and not math.isnan(p) for p in sell_prices)
    print("  [%s] sell prices (sample 3): %s" % ("PASS" if all_valid else "FAIL", sell_prices))
    if not all_valid:
        ok = False

    # 5. 信号稀疏度
    sig_ok = 0 < avg_per_day < 200
    print("  [%s] avg_signals_per_day=%.1f (expect 0 < x < 200)" % ("PASS" if sig_ok else "FAIL", avg_per_day))
    if not sig_ok:
        ok = False

    # 6. 胜率/盈亏比非NaN
    wr = performance.get("win_rate", float("nan"))
    plr = performance.get("profit_loss_ratio", float("nan"))
    tr = performance.get("total_return", float("nan"))
    vals_ok = not any(math.isnan(v) for v in [wr, plr, tr])
    print("  [%s] win_rate=%.2f, plr=%.2f, total_return=%.2f%%" % (
        "PASS" if vals_ok else "FAIL", wr, plr, tr * 100))
    if not vals_ok:
        ok = False

    # 7. equity_curve 行数 ≈ 交易日数
    eq_len = len(equity_rows)
    ratio = abs(eq_len - len(trading_days)) / max(len(trading_days), 1)
    eq_ok = ratio < 0.05
    print("  [%s] equity_curve=%d rows, trading_days=%d (diff=%.1f%%)" % (
        "PASS" if eq_ok else "FAIL", eq_len, len(trading_days), ratio * 100))
    if not eq_ok:
        ok = False

    print("\n[SELFCHECK] %s" % ("ALL PASSED" if ok else "SOME FAILED"))
    return ok


# ── 撮合引擎 v2（使用预索引数据）──────────────────────────────────────

def run_matching_v2(all_data, signals, trading_days, name_map, run_id=""):
    """隔夜撮合 v2: 使用已建索引的 DataFrame。
    T日 close 买 + T+1 open 卖。
    """
    print("[MATCH] Running overnight matching engine v2 ...")
    cash = INITIAL_CASH
    holdings = []  # {code, volume, buy_price, buy_date, target_sell_date}
    trades = []
    equity_rows = []
    daily_logs = []
    unfilled_logs = []
    all_positions = []

    day_to_idx = {d: i for i, d in enumerate(trading_days)}

    for day_idx, today in enumerate(trading_days):
        next_day = trading_days[day_idx + 1] if day_idx + 1 < len(trading_days) else None

        # ── 先处理卖出：昨日买入的持仓在今日 open 卖 ──
        to_sell = [h for h in holdings if h["target_sell_date"] == today]
        keep = [h for h in holdings if h["target_sell_date"] != today]

        for h in to_sell:
            code = h["code"]
            vol = h["volume"]
            buy_p = h["buy_price"]

            key = (today, code)
            if key in all_data.index:
                row = all_data.loc[key]
                if isinstance(row, pd.DataFrame):
                    row = row.iloc[0]
                open_p = row["open"]
                if not np.isnan(open_p) and open_p > 0:
                    sell_p = open_p * (1 - SLIPPAGE)
                    sell_amt = sell_p * vol
                    comm = sell_amt * COMMISSION_RATE
                    tax = sell_amt * TAX_RATE
                    cash += sell_amt - comm - tax
                    trades.append({
                        "run_id": run_id,
                        "date": today, "code": code, "side": "sell",
                        "volume": vol, "price": round(sell_p, 4),
                        "amount": round(sell_amt, 2),
                        "slippage_amt": round(open_p * SLIPPAGE * vol, 2),
                        "commission": round(comm, 2), "tax": round(tax, 2),
                        "reason": "overnight_sell", "layer": "",
                        "model": "next_open",
                    })
                else:
                    # 停牌顺延
                    unfilled_logs.append(
                        "[WARN] UNFILLED sell %s %s vol=%d reason=no_open_data"
                        % (today, code, vol))
                    h["target_sell_date"] = None
                    keep.append(h)
            else:
                unfilled_logs.append(
                    "[WARN] UNFILLED sell %s %s vol=%d reason=suspended"
                    % (today, code, vol))
                h["target_sell_date"] = None
                keep.append(h)

        # 顺延 target_sell_date=None 的持仓
        final_holdings = []
        for h in keep:
            if h["target_sell_date"] is None or h["target_sell_date"] == today:
                start_idx = day_to_idx.get(today, 0) + 1
                found = False
                for fwd in range(start_idx, min(start_idx + 20, len(trading_days))):
                    fwd_day = trading_days[fwd]
                    k2 = (fwd_day, h["code"])
                    if k2 in all_data.index:
                        r2 = all_data.loc[k2]
                        if isinstance(r2, pd.DataFrame):
                            r2 = r2.iloc[0]
                        if not np.isnan(r2["open"]) and r2["open"] > 0:
                            h["target_sell_date"] = fwd_day
                            found = True
                            break
                if not found:
                    unfilled_logs.append(
                        "[WARN] UNFILLED sell %s %s vol=%d reason=no_data_20d"
                        % (today, h["code"], h["volume"]))
            final_holdings.append(h)
        holdings = final_holdings

        # ── 扫描信号 & 买入 ──
        sig_codes = signals.get(today, [])
        scanned = 0
        if today in all_data.index.get_level_values(0):
            scanned = len(all_data.loc[today].index.get_level_values("ts_code").unique())

        max_can_buy = MAX_POSITIONS - len(holdings)
        if max_can_buy > 0 and sig_codes:
            # 计算当前总资产用于等权分配
            mv = 0
            for h in holdings:
                k3 = (today, h["code"])
                if k3 in all_data.index:
                    r3 = all_data.loc[k3]
                    if isinstance(r3, pd.DataFrame):
                        r3 = r3.iloc[0]
                    cp = r3["close"]
                    if not np.isnan(cp):
                        mv += cp * h["volume"]
            total_asset = cash + mv
            target_cash = total_asset / MAX_POSITIONS

            bought = 0
            held_codes = set(h["code"] for h in holdings)
            for code in sig_codes:
                if bought >= max_can_buy or code in held_codes:
                    continue
                k4 = (today, code)
                if k4 not in all_data.index:
                    continue
                r4 = all_data.loc[k4]
                if isinstance(r4, pd.DataFrame):
                    r4 = r4.iloc[0]
                cl = r4["close"]
                if np.isnan(cl) or cl <= 0:
                    continue

                bp = cl * (1 + SLIPPAGE)
                vol = math.floor(target_cash / bp / 100) * 100
                if vol <= 0:
                    continue
                ba = bp * vol
                comm = ba * COMMISSION_RATE
                tc = ba + comm
                if tc > cash:
                    vol = math.floor((cash - 100) / bp / 100) * 100
                    if vol <= 0:
                        continue
                    ba = bp * vol
                    comm = ba * COMMISSION_RATE
                    tc = ba + comm
                    if tc > cash:
                        continue

                cash -= tc
                holdings.append({
                    "code": code, "volume": vol, "buy_price": bp,
                    "buy_date": today, "target_sell_date": next_day,
                })
                trades.append({
                    "run_id": "",
                    "date": today, "code": code, "side": "buy",
                    "volume": vol, "price": round(bp, 4),
                    "amount": round(ba, 2),
                    "slippage_amt": round(cl * SLIPPAGE * vol, 2),
                    "commission": round(comm, 2), "tax": 0,
                    "reason": "tail_30min_signal", "layer": "",
                    "model": "close",
                })
                bought += 1

        # ── 日终净值 ──
        mv_end = 0
        for h in holdings:
            k5 = (today, h["code"])
            if k5 in all_data.index:
                r5 = all_data.loc[k5]
                if isinstance(r5, pd.DataFrame):
                    r5 = r5.iloc[0]
                cp = r5["close"]
                if not np.isnan(cp):
                    mv_end += cp * h["volume"]

        total = cash + mv_end
        dr = 0.0
        if equity_rows and equity_rows[-1]["total_asset"] > 0:
            dr = (total - equity_rows[-1]["total_asset"]) / equity_rows[-1]["total_asset"]

        equity_rows.append({
            "run_id": "", "date": today,
            "total_asset": round(total, 2), "cash": round(cash, 2),
            "market_value": round(mv_end, 2), "daily_return": round(dr, 6),
            "benchmark_close": 0, "benchmark_return": 0,
        })

        # positions
        for h in holdings:
            k6 = (today, h["code"])
            lp = 0
            if k6 in all_data.index:
                r6 = all_data.loc[k6]
                if isinstance(r6, pd.DataFrame):
                    r6 = r6.iloc[0]
                lp = r6["close"] if not np.isnan(r6["close"]) else 0
            pnl = (lp - h["buy_price"]) * h["volume"]
            all_positions.append({
                "run_id": "", "date": today, "code": h["code"],
                "volume": h["volume"], "available_volume": 0,
                "cost_price": round(h["buy_price"], 4),
                "last_price": round(lp, 4),
                "unrealized_pnl": round(pnl, 2),
                "holding_days": 0,
            })

        n_b = sum(1 for t in trades if t["date"] == today and t["side"] == "buy")
        n_s = sum(1 for t in trades if t["date"] == today and t["side"] == "sell")
        daily_logs.append("date=%s scanned=%d passed=%d buy=%d sell=%d" % (
            today, scanned, len(sig_codes), n_b, n_s))

    print("[MATCH] Done. trades=%d, holdings=%d" % (len(trades), len(holdings)))
    return trades, equity_rows, all_positions, daily_logs, unfilled_logs


if __name__ == "__main__":
    main()
