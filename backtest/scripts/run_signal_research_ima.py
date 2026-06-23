# coding: utf-8
r"""
IMA V3.1 Signal Research Script

Usage:
    py -3.10 backtest/scripts/run_signal_research_ima.py backtest/configs/base_ima.yaml

Outputs to F:\backtest_workspace\results\{run_id}_ima_uptrend_v31_signal_research\
"""

import os
import sys
import json
import hashlib
import datetime
import logging

import yaml
import pandas as pd

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backtest.paths import JINCE_DB_PATH, RESULTS_DIR, CACHE_DIR
from backtest.data_tools.duckdb_reader import DuckDBDailyReader
from backtest.strategies.production.ima_uptrend_v31.ima_uptrend_v31 import evaluate_ima_day

log = logging.getLogger(__name__)


def load_config(config_path):
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def generate_run_id():
    now = datetime.datetime.now()
    ts = now.strftime("%Y%m%d_%H%M%S")
    short = hashlib.md5(ts.encode()).hexdigest()[:6]
    return "%s_%s" % (ts, short)


def get_next_trading_day(date, calendar):
    """Get the next trading day after date."""
    for d in calendar:
        if d > date:
            return d
    return None


def compute_signal_returns(signals, market_window, calendar, horizons):
    """Compute T+1 open entry returns for each signal.

    Returns list of dicts with signal_date, code, entry_date, entry_open, ret_Xd, etc.
    """
    results = []

    for sig in signals:
        sig_date = sig["date"]
        code = sig["code"]

        entry_date = get_next_trading_day(sig_date, calendar)
        if entry_date is None:
            # Last trading day, no next day available
            results.append({
                "signal_date": sig_date,
                "code": code,
                "entry_date": None,
                "entry_open": None,
                "ret_1d": None,
                "ret_3d": None,
                "ret_5d": None,
                "ret_10d": None,
                "max_loss_10d": None,
                "max_gain_10d": None,
                "score": sig["score"],
                "h1_mode": sig.get("h1_mode", "disabled"),
                "status": "unfilled",
            })
            continue

        df = market_window.get(code)
        if df is None:
            continue

        # Find entry open price
        entry_row = df[df["date"] == entry_date]
        if len(entry_row) == 0:
            continue
        entry_open = float(entry_row["open"].iloc[0])

        # Find exit prices for each horizon
        rets = {}
        exit_dates = {}
        for h in horizons:
            idx = calendar.index(entry_date) if entry_date in calendar else -1
            target_idx = idx + h
            if target_idx < len(calendar):
                target_date = calendar[target_idx]
                exit_row = df[df["date"] == target_date]
                if len(exit_row) > 0:
                    exit_close = float(exit_row["close"].iloc[0])
                    rets[h] = (exit_close / entry_open - 1.0) * 100.0
                    exit_dates[h] = target_date
                else:
                    rets[h] = None
                    exit_dates[h] = None
            else:
                rets[h] = None
                exit_dates[h] = None

        # Compute max loss/gain in 10-day window
        max_loss = None
        max_gain = None
        idx = calendar.index(entry_date) if entry_date in calendar else -1
        end_idx = min(idx + 10, len(calendar) - 1)
        window_dates = calendar[idx + 1:end_idx + 1]
        if window_dates:
            window_rows = df[df["date"].isin(window_dates)]
            if len(window_rows) > 0:
                window_closes = window_rows["close"].astype(float).values
                window_rets = (window_closes / entry_open - 1.0) * 100.0
                max_loss = float(window_rets.min())
                max_gain = float(window_rets.max())

        results.append({
            "signal_date": sig_date,
            "code": code,
            "entry_date": entry_date,
            "entry_open": entry_open,
            "ret_1d": rets.get(1),
            "ret_3d": rets.get(3),
            "ret_5d": rets.get(5),
            "ret_10d": rets.get(10),
            "max_loss_10d": max_loss,
            "max_gain_10d": max_gain,
            "score": sig["score"],
            "h1_mode": sig.get("h1_mode", "disabled"),
            "status": "filled",
        })

    return results


def compute_summary(signals, returns, config):
    """Compute summary statistics."""
    strategy_cfg = config.get("strategy", {})
    research_cfg = config.get("research", {})

    total_signals = len(signals)
    filled = [r for r in returns if r["status"] == "filled"]
    unfilled = [r for r in returns if r["status"] == "unfilled"]

    # Win rates
    win_rates = {}
    avg_returns = {}
    for h in [1, 3, 5, 10]:
        key = "ret_%dd" % h
        valid = [r for r in filled if r.get(key) is not None]
        if valid:
            wins = [r for r in valid if r[key] > 0]
            win_rates[h] = len(wins) / len(valid) * 100.0
            avg_returns[h] = sum(r[key] for r in valid) / len(valid)
        else:
            win_rates[h] = None
            avg_returns[h] = None

    # Max single loss and max gain (10d)
    valid_10d = [r for r in filled if r.get("ret_10d") is not None]
    max_single_loss = min((r["ret_10d"] for r in valid_10d), default=None) if valid_10d else None
    max_single_gain = max((r["ret_10d"] for r in valid_10d), default=None) if valid_10d else None

    # Max loss/gain across all horizons
    all_losses = []
    all_gains = []
    for h in [1, 3, 5, 10]:
        key = "ret_%dd" % h
        for r in filled:
            if r.get(key) is not None:
                if r[key] < 0:
                    all_losses.append(r[key])
                elif r[key] > 0:
                    all_gains.append(r[key])
    max_loss_any = min(all_losses) if all_losses else None
    max_gain_any = max(all_gains) if all_gains else None

    # Profit/loss ratio (5d)
    valid_5d = [r for r in filled if r.get("ret_5d") is not None]
    if valid_5d:
        gains = [r["ret_5d"] for r in valid_5d if r["ret_5d"] > 0]
        losses = [abs(r["ret_5d"]) for r in valid_5d if r["ret_5d"] < 0]
        avg_gain = sum(gains) / len(gains) if gains else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
        profit_loss_ratio = avg_gain / avg_loss if avg_loss > 0 else None
    else:
        profit_loss_ratio = None

    # Profit/loss ratio (10d)
    if valid_10d:
        gains_10d = [r["ret_10d"] for r in valid_10d if r["ret_10d"] > 0]
        losses_10d = [abs(r["ret_10d"]) for r in valid_10d if r["ret_10d"] < 0]
        avg_gain_10d = sum(gains_10d) / len(gains_10d) if gains_10d else 0
        avg_loss_10d = sum(losses_10d) / len(losses_10d) if losses_10d else 0
        profit_loss_ratio_10d = avg_gain_10d / avg_loss_10d if avg_loss_10d > 0 else None
    else:
        profit_loss_ratio_10d = None

    # Stock concentration: top 10 stocks by signal count
    stock_counts = {}
    for s in signals:
        code = s["code"]
        stock_counts[code] = stock_counts.get(code, 0) + 1
    top_stocks = sorted(stock_counts.items(), key=lambda x: -x[1])[:10]

    # Consecutive signal intervals
    stock_signals = {}
    for s in signals:
        code = s["code"]
        if code not in stock_signals:
            stock_signals[code] = []
        stock_signals[code].append(s["date"])

    intervals = []
    for code, dates in stock_signals.items():
        dates_sorted = sorted(dates)
        for i in range(1, len(dates_sorted)):
            # Approximate trading days between signals
            d1 = pd.Timestamp(dates_sorted[i-1])
            d2 = pd.Timestamp(dates_sorted[i])
            trading_days = (d2 - d1).days * 5 / 7  # rough approximation
            intervals.append(trading_days)
    avg_interval = sum(intervals) / len(intervals) if intervals else None

    # Avg signals per day
    if signals:
        dates = set(s["date"] for s in signals)
        avg_per_day = total_signals / len(dates) if dates else 0
    else:
        avg_per_day = 0

    summary = {
        "strategy_name": "ima_uptrend_v31",
        "research_type": "signal_research",
        "is_trade_backtest": False,
        "sample_period_warning": {
            "is_short_sample": True,
            "requested_range": [research_cfg.get("start_date"), research_cfg.get("end_date")],
            "actual_range": [research_cfg.get("start_date"), research_cfg.get("end_date")],
            "trading_days": None,
            "warning": "样本期约 6 个月，结果仅用于 MVP 管线验证，不可作为策略最终定论",
        },
        "h1_mode": strategy_cfg.get("h1_mode", "disabled"),
        "sc_threshold": strategy_cfg.get("sc_threshold", 7),
        "signal_count_total": total_signals,
        "signal_count_filled": len(filled),
        "signal_count_unfilled": len(unfilled),
        "avg_signals_per_day": avg_per_day,
        "win_rate_1d": win_rates.get(1),
        "win_rate_3d": win_rates.get(3),
        "win_rate_5d": win_rates.get(5),
        "win_rate_10d": win_rates.get(10),
        "avg_return_1d": avg_returns.get(1),
        "avg_return_3d": avg_returns.get(3),
        "avg_return_5d": avg_returns.get(5),
        "avg_return_10d": avg_returns.get(10),
        "max_single_loss_10d": max_single_loss,
        "max_single_gain_10d": max_single_gain,
        "max_loss_any": max_loss_any,
        "max_gain_any": max_gain_any,
        "profit_loss_ratio_5d": profit_loss_ratio,
        "profit_loss_ratio_10d": profit_loss_ratio_10d,
        "unique_stocks": len(stock_counts),
        "top_stocks_by_signal": top_stocks,
        "avg_consecutive_interval": avg_interval,
        "total_consecutive_intervals": len(intervals),
        "data_backend": "duckdb",
        "data_source": "jince_zhisuan",
    }

    return summary


def generate_signal_report(summary, config):
    """Generate markdown signal report."""
    lines = []
    lines.append("# IMA V3.1 Signal Research Report")
    lines.append("")
    lines.append("> **样本期警告**: 本回测样本区间 %s ~ %s，约 6 个月，" % (
        summary["sample_period_warning"]["requested_range"][0],
        summary["sample_period_warning"]["requested_range"][1],
    ))
    lines.append("> **仅用于 MVP 管线验证**，**不可作为策略最终定论**。")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 配置")
    lines.append("")
    lines.append("- SC 阈值: %s" % summary["sc_threshold"])
    lines.append("- H1 模式: %s" % summary["h1_mode"])
    lines.append("")
    lines.append("## 信号统计")
    lines.append("")
    lines.append("- 总信号数: %d" % summary["signal_count_total"])
    lines.append("- 已计算收益: %d" % summary["signal_count_filled"])
    lines.append("- 未计算收益: %d" % summary["signal_count_unfilled"])
    lines.append("- 日均信号: %.1f" % summary["avg_signals_per_day"])
    lines.append("")
    lines.append("## 收益统计")
    lines.append("")
    lines.append("| 周期 | 胜率 | 平均收益 |")
    lines.append("|------|------|---------|")
    for h in [1, 3, 5, 10]:
        wr = summary.get("win_rate_%dd" % h)
        ar = summary.get("avg_return_%dd" % h)
        wr_str = "%.1f%%" % wr if wr is not None else "N/A"
        ar_str = "%.2f%%" % ar if ar is not None else "N/A"
        lines.append("| %d 日 | %s | %s |" % (h, wr_str, ar_str))
    lines.append("")
    lines.append("## 风险指标")
    lines.append("")
    lines.append("- 最大单笔亏损 (10日): %s" % (
        "%.2f%%" % summary["max_single_loss_10d"] if summary["max_single_loss_10d"] is not None else "N/A"
    ))
    lines.append("- 盈亏比 (5日): %s" % (
        "%.2f" % summary["profit_loss_ratio_5d"] if summary["profit_loss_ratio_5d"] is not None else "N/A"
    ))
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*报告由 MimoCode 自动生成*")

    return "\n".join(lines)


def main(config_path):
    """Main entry point."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    config = load_config(config_path)
    research_cfg = config.get("research", {})
    strategy_cfg = config.get("strategy", {})

    start_date = research_cfg.get("start_date", "2025-09-01")
    end_date = research_cfg.get("end_date", "2026-02-27")
    horizons = research_cfg.get("horizons", [1, 3, 5, 10])

    run_id = generate_run_id()
    run_dir = os.path.join(RESULTS_DIR, "%s_ima_uptrend_v31_signal_research" % run_id)
    os.makedirs(run_dir, exist_ok=True)

    print("=== IMA V3.1 Signal Research ===")
    print("Run ID: %s" % run_id)
    print("Date range: %s ~ %s" % (start_date, end_date))
    print("SC threshold: %s" % strategy_cfg.get("sc_threshold", 7))
    print("H1 mode: %s" % strategy_cfg.get("h1_mode", "disabled"))
    print("Output: %s" % run_dir)
    print("")

    # Load data
    print("Loading DuckDB data...")
    reader = DuckDBDailyReader(JINCE_DB_PATH)
    calendar = reader.trading_calendar(start_date, end_date)
    print("Trading days: %d" % len(calendar))

    # Load universe from data (all codes with data in range)
    all_codes = reader._conn.execute(
        "SELECT DISTINCT code FROM dat_day "
        "WHERE CAST(trade_time AS DATE) BETWEEN ? AND ?",
        [start_date, end_date]
    ).fetchall()
    universe = [r[0] for r in all_codes]
    print("Universe size (all): %d" % len(universe))

    # Limit to first 200 for initial run (full universe too slow)
    if len(universe) > 200:
        universe = universe[:200]
        print("Limited to first 200 stocks for initial run")

    # Load market window
    print("Loading market data...")
    market_window = reader.load_window(universe, start_date, end_date)
    print("Loaded %d stocks" % len(market_window))

    # Generate signals for each day
    print("Computing signals...")
    all_signals = []
    all_blocked = []
    all_diagnostics = []

    for day in calendar:
        # Truncate market_window to only include data up to current day
        # This is belt-and-suspenders with evaluate_ima_day's internal truncation
        market_window_day = {}
        for code in universe:
            df_full = market_window.get(code)
            if df_full is not None:
                df_truncated = df_full[df_full["date"] <= day]
                if len(df_truncated) > 0:
                    market_window_day[code] = df_truncated

        result = evaluate_ima_day(day, market_window_day, universe, config)
        all_signals.extend(result["signals"])
        all_blocked.extend(result["blocked"])
        all_diagnostics.append(result["diagnostics"])

    print("Total signals: %d" % len(all_signals))
    print("Total blocked: %d" % len(all_blocked))

    # Compute signal returns
    print("Computing signal returns...")
    returns = compute_signal_returns(all_signals, market_window, calendar, horizons)
    print("Returns computed: %d" % len(returns))

    # Compute summary
    summary = compute_summary(all_signals, returns, config)

    # Generate report
    report = generate_signal_report(summary, config)

    # Write outputs
    print("Writing outputs...")

    # signals.csv
    if all_signals:
        df_signals = pd.DataFrame(all_signals)
        df_signals.to_csv(os.path.join(run_dir, "signals.csv"), index=False)

    # signal_returns.csv
    if returns:
        df_returns = pd.DataFrame(returns)
        df_returns.to_csv(os.path.join(run_dir, "signal_returns.csv"), index=False)

    # factor_diagnostics.csv
    factor_counts = {}
    for diag in all_diagnostics:
        for k, v in diag.get("factor_pass_counts", {}).items():
            factor_counts[k] = factor_counts.get(k, 0) + v
    if factor_counts:
        df_factors = pd.DataFrame([factor_counts])
        df_factors.to_csv(os.path.join(run_dir, "factor_diagnostics.csv"), index=False)

    # summary.json
    with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    # signal_report.md
    with open(os.path.join(run_dir, "signal_report.md"), "w", encoding="utf-8") as f:
        f.write(report)

    # logs.txt
    log_lines = []
    log_lines.append("[WARN] SHORT_SAMPLE_PERIOD requested=%s..%s message=\"样本期约 6 个月，仅用于 MVP 管线验证，不可作为策略最终定论\"" % (start_date, end_date))
    log_lines.append("[WARN] BENCHMARK_DISABLED reason=\"DuckDB 当前无指数数据\"")
    log_lines.append("")
    log_lines.append("Run ID: %s" % run_id)
    log_lines.append("Config: %s" % config_path)
    log_lines.append("Date range: %s ~ %s" % (start_date, end_date))
    log_lines.append("SC threshold: %s" % strategy_cfg.get("sc_threshold", 7))
    log_lines.append("H1 mode: %s" % strategy_cfg.get("h1_mode", "disabled"))
    log_lines.append("Universe size: %d" % len(universe))
    log_lines.append("Trading days: %d" % len(calendar))
    log_lines.append("Total signals: %d" % len(all_signals))
    log_lines.append("Total blocked: %d" % len(all_blocked))

    with open(os.path.join(run_dir, "logs.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))

    print("")
    print("=== Complete ===")
    print("Summary:")
    print("  Signal count: %d" % summary["signal_count_total"])
    print("  Avg per day: %.1f" % summary["avg_signals_per_day"])
    print("  Win rate 1d: %s" % ("%.1f%%" % summary["win_rate_1d"] if summary["win_rate_1d"] else "N/A"))
    print("  Win rate 5d: %s" % ("%.1f%%" % summary["win_rate_5d"] if summary["win_rate_5d"] else "N/A"))
    print("  Win rate 10d: %s" % ("%.1f%%" % summary["win_rate_10d"] if summary["win_rate_10d"] else "N/A"))
    print("")
    print("Outputs: %s" % run_dir)

    return summary


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: py -3.10 run_signal_research_ima.py <config.yaml>")
        sys.exit(1)
    main(sys.argv[1])
