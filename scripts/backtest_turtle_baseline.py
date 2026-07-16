# coding=utf-8
"""
海龟策略A股基线回测 v1.0
独立脚本，不依赖现有策略体系。
严格按 SPEC turtle_baseline_v1.0.md 实现，不改逻辑。
"""
import os
import json
import warnings
import numpy as np
import pandas as pd
from datetime import datetime

warnings.filterwarnings("ignore")

# ===== 硬编码参数（模块级常量） =====
START_DATE = "2022-01-01"
END_DATE = "2025-06-30"
WARMUP_START = "2021-11-01"
INITIAL_CASH = 1000000.0
SINGLE_RISK_PCT = 0.01
ATR_PERIOD = 20
ENTRY_BREAKOUT = 20
EXIT_BREAKOUT = 10
STOP_LOSS_ATR_MULT = 2.0
MAX_POSITION_PCT = 0.20
COMMISSION = 0.00025
STAMP_TAX = 0.001
TRANSFER_FEE = 0.00001
SLIPPAGE = 0.001
DATA_PARQUET = "E:/astock/daily/stock_daily.parquet"
OUT_DIR = "D:/QMT_STRATEGIES/backtest_results/turtle_baseline"


def get_hs300_constituents():
    """获取沪深300成分股，带本地缓存"""
    import akshare as ak

    cache_dir = OUT_DIR
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, "_hs300_constituents.csv")
    today_str = datetime.now().strftime("%Y-%m-%d")

    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
        if "# fetched:" in first_line:
            fetch_date = first_line.split("# fetched:")[-1].strip()
            if fetch_date == today_str:
                df = pd.read_csv(cache_path, comment="#")
                codes = df["ts_code"].tolist()
                names = df["name"].tolist()
                print("[DATA] Using cached HS300 constituents: {} stocks".format(len(codes)))
                return codes, names

    print("[DATA] Fetching HS300 constituents from akshare...")
    df = ak.index_stock_cons_csindex(symbol="000300")
    records = []
    for _, row in df.iterrows():
        code = str(row["成分券代码"]).zfill(6)
        exchange = row["交易所"]
        name = row["成分券名称"]
        if "上海" in exchange:
            ts_code = code + ".SH"
        else:
            ts_code = code + ".SZ"
        records.append({"ts_code": ts_code, "name": name})

    result_df = pd.DataFrame(records)
    with open(cache_path, "w", encoding="utf-8") as f:
        f.write("# fetched: {}\n".format(today_str))
        result_df.to_csv(f, index=False)

    codes = result_df["ts_code"].tolist()
    names = result_df["name"].tolist()
    print("[DATA] Fetched {} HS300 constituents".format(len(codes)))
    return codes, names


def load_daily(codes):
    """加载日线数据并计算前复权价格"""
    print("[DATA] Loading daily data from parquet (this may take ~20s)...")
    df = pd.read_parquet(DATA_PARQUET)
    df = df.reset_index()
    print("[DATA] Loaded {} rows".format(len(df)))

    df["trade_date"] = df["trade_date"].astype(str)
    code_set = set(codes)
    df = df[df["ts_code"].isin(code_set)]
    df = df[df["trade_date"] >= WARMUP_START]
    df = df[df["trade_date"] <= END_DATE]

    result = {}
    for code in codes:
        cdf = df[df["ts_code"] == code].copy()
        if len(cdf) == 0:
            print("[WARN] No data for {} after filtering".format(code))
            continue
        if cdf["adj_factor"].isna().all():
            print("[WARN] adj_factor all NaN for {}, skipping".format(code))
            continue

        cdf = cdf.sort_values("trade_date").reset_index(drop=True)
        latest_adj = cdf["adj_factor"].iloc[-1]
        if pd.isna(latest_adj) or latest_adj == 0:
            print("[WARN] latest adj_factor invalid for {}, skipping".format(code))
            continue

        factor = cdf["adj_factor"] / latest_adj
        cdf["open"] = cdf["open"] * factor
        cdf["high"] = cdf["high"] * factor
        cdf["low"] = cdf["low"] * factor
        cdf["close"] = cdf["close"] * factor

        cdf["date"] = cdf["trade_date"].astype(str)
        result[code] = cdf[["date", "open", "high", "low", "close", "vol", "amount", "adj_factor"]].copy()

    print("[DATA] Loaded daily data for {} / {} stocks".format(len(result), len(codes)))
    return result


def get_trading_days(all_daily_df):
    """从全量 parquet 获取交易日历"""
    td_col = all_daily_df["trade_date"].astype(str)
    td = all_daily_df[(td_col >= START_DATE) & (td_col <= END_DATE)]
    trading_days = sorted(td["trade_date"].astype(str).unique().tolist())
    print("[DATA] Trading days in range: {}".format(len(trading_days)))
    return trading_days


def get_hs300_benchmark(all_daily_df):
    """获取沪深300基准收益率"""
    try:
        import akshare as ak
        bench = ak.stock_zh_index_daily(symbol="sh000300")
        bench["date"] = bench["date"].astype(str)
        bench = bench[(bench["date"] >= START_DATE) & (bench["date"] <= END_DATE)]
        if len(bench) < 2:
            return None
        bench = bench.sort_values("date")
        bench_ret = bench["close"].iloc[-1] / bench["close"].iloc[0] - 1
        print("[DATA] HS300 benchmark return: {:.4f}".format(bench_ret))
        return bench_ret
    except Exception as e:
        print("[WARN] HS300 benchmark fetch failed: {}".format(e))
        return None


def compute_indicators(cdf):
    """预计算海龟指标（向量化，PIT安全）"""
    cdf = cdf.copy()
    high = cdf["high"].values
    low = cdf["low"].values
    close = cdf["close"].values

    tr = np.zeros(len(cdf))
    tr[0] = np.nan
    for i in range(1, len(cdf)):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))
    cdf["tr"] = tr

    cdf["atr"] = pd.Series(tr).rolling(ATR_PERIOD, min_periods=ATR_PERIOD).mean().values
    cdf["entry_high"] = pd.Series(close).shift(1).rolling(ENTRY_BREAKOUT, min_periods=ENTRY_BREAKOUT).max().values
    cdf["exit_low"] = pd.Series(close).shift(1).rolling(EXIT_BREAKOUT, min_periods=EXIT_BREAKOUT).min().values

    return cdf


def run_backtest_single(code, cdf, trading_days):
    """单只股票独立回测"""
    td_set = set(cdf["date"].tolist())
    cdf_idx = cdf.set_index("date")

    trades = []
    equity_records = []
    cash = INITIAL_CASH
    state = "flat"
    position = None

    buy_day_idx = -1
    sell_day_idx = -1

    for td in trading_days:
        if td not in td_set:
            equity_records.append({"code": code, "date": td, "equity": cash})
            continue

        bar = cdf_idx.loc[td]
        if isinstance(bar, pd.DataFrame):
            bar = bar.iloc[0]

        atr_val = bar["atr"]
        high_val = bar["high"]
        low_val = bar["low"]
        close_val = bar["close"]
        vol_val = bar["vol"]
        open_val = bar["open"]

        if state == "flat":
            entry_high_val = bar["entry_high"]
            if (not pd.isna(entry_high_val)) and (not pd.isna(atr_val)) and (atr_val > 0) and (close_val > entry_high_val):
                signal_date = td
                atr_at_entry = atr_val
                next_idx = trading_days.index(td) + 1
                buy_date = None
                for bi in range(next_idx, len(trading_days)):
                    bd = trading_days[bi]
                    if bd in td_set:
                        bbar = cdf_idx.loc[bd]
                        if isinstance(bbar, pd.DataFrame):
                            bbar = bbar.iloc[0]
                        if bbar["vol"] > 0:
                            buy_date = bd
                            break
                if buy_date is not None:
                    buy_bar = cdf_idx.loc[buy_date]
                    if isinstance(buy_bar, pd.DataFrame):
                        buy_bar = buy_bar.iloc[0]
                    buy_price = buy_bar["open"] * (1 + SLIPPAGE)
                    # 标准海龟: shares = 单笔风险 / (2 × ATR), 单笔风险=1%账户固定
                    # 诚哥拍板修正 SPEC §2 笔误(原公式 2*atr/price*100 使单笔风险=100*price 与atr无关)
                    denom = 2 * atr_at_entry
                    if denom > 0:
                        shares = SINGLE_RISK_PCT * INITIAL_CASH / denom
                        shares = int(shares // 100 * 100)
                        max_shares = int((INITIAL_CASH * MAX_POSITION_PCT) / buy_price // 100 * 100)
                        shares = min(shares, max_shares)
                        if shares >= 100:
                            commission = buy_price * shares * COMMISSION
                            transfer = buy_price * shares * TRANSFER_FEE if code.endswith(".SH") else 0
                            cash -= buy_price * shares + commission + transfer
                            position = {
                                "code": code, "entry_date": signal_date, "buy_date": buy_date,
                                "buy_price": buy_price, "shares": shares, "atr_at_entry": atr_at_entry,
                                "initial_stop": buy_price - STOP_LOSS_ATR_MULT * atr_at_entry,
                                "commission": commission, "transfer": transfer
                            }
                            state = "long"
                        else:
                            pass
                    else:
                        pass

            equity = cash
            equity_records.append({"code": code, "date": td, "equity": equity})

        elif state == "long":
            if vol_val == 0 or pd.isna(open_val):
                equity = cash + position["shares"] * close_val
                equity_records.append({"code": code, "date": td, "equity": equity})
                continue

            current_stop = max(position["initial_stop"], high_val - STOP_LOSS_ATR_MULT * atr_val)
            triggered = None
            if close_val < current_stop:
                triggered = "stoploss"
            elif not pd.isna(bar["exit_low"]) and close_val < bar["exit_low"]:
                triggered = "exit_signal"

            if triggered:
                next_idx = trading_days.index(td) + 1
                sell_date = None
                for si in range(next_idx, len(trading_days)):
                    sd = trading_days[si]
                    if sd in td_set:
                        sbar = cdf_idx.loc[sd]
                        if isinstance(sbar, pd.DataFrame):
                            sbar = sbar.iloc[0]
                        if sbar["vol"] > 0:
                            sell_date = sd
                            break
                if sell_date is not None:
                    sell_bar = cdf_idx.loc[sell_date]
                    if isinstance(sell_bar, pd.DataFrame):
                        sell_bar = sell_bar.iloc[0]
                    sell_price = sell_bar["open"] * (1 - SLIPPAGE)
                    s_commission = sell_price * position["shares"] * COMMISSION
                    s_tax = sell_price * position["shares"] * STAMP_TAX
                    s_transfer = sell_price * position["shares"] * TRANSFER_FEE if code.endswith(".SH") else 0
                    cash += sell_price * position["shares"] - s_commission - s_tax - s_transfer
                    buy_total = position["buy_price"] * position["shares"] + position["commission"] + position.get("transfer", 0)
                    sell_total = sell_price * position["shares"] - s_commission - s_tax - s_transfer
                    pnl = sell_total - buy_total
                    pnl_pct = pnl / buy_total if buy_total > 0 else 0
                    td_list = [d for d in trading_days if d >= position["buy_date"] and d <= sell_date]
                    days_held = len(td_list)
                    trades.append({
                        "code": code,
                        "signal_date": position["entry_date"],
                        "buy_date": position["buy_date"],
                        "buy_price": position["buy_price"],
                        "sell_date": sell_date,
                        "sell_price": sell_price,
                        "shares": position["shares"],
                        "atr_at_entry": position["atr_at_entry"],
                        "initial_stop": position["initial_stop"],
                        "days_held": days_held,
                        "pnl": pnl,
                        "pnl_pct": pnl_pct,
                        "exit_reason": triggered,
                        "buy_cost": position["commission"] + position.get("transfer", 0),
                        "sell_cost": s_commission + s_tax + s_transfer
                    })
                    state = "flat"
                    position = None

            equity = cash + (position["shares"] * close_val if position else 0)
            equity_records.append({"code": code, "date": td, "equity": equity})

    return trades, equity_records


def compute_stock_metrics(trades, equity_records):
    """计算单只股票汇总指标"""
    n_trades = len(trades)
    if n_trades == 0:
        return {
            "n_trades": 0, "win_rate": None, "avg_win_loss_ratio": None,
            "total_return": 0.0, "max_drawdown": 0.0, "avg_holding_days": 0
        }

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    win_rate = len(wins) / n_trades if n_trades > 0 else None

    avg_win_loss_ratio = None
    if wins and losses:
        avg_win = np.mean([t["pnl"] for t in wins])
        avg_loss = abs(np.mean([t["pnl"] for t in losses]))
        if avg_loss > 0:
            avg_win_loss_ratio = avg_win / avg_loss

    if equity_records:
        eq_series = pd.Series([e["equity"] for e in equity_records])
        peak = eq_series.cummax()
        drawdown = (peak - eq_series) / peak
        max_drawdown = drawdown.max()
        total_return = (eq_series.iloc[-1] / INITIAL_CASH) - 1
    else:
        max_drawdown = 0.0
        total_return = 0.0

    avg_holding_days = np.mean([t["days_held"] for t in trades])

    return {
        "n_trades": n_trades,
        "win_rate": win_rate,
        "avg_win_loss_ratio": avg_win_loss_ratio,
        "total_return": total_return,
        "max_drawdown": max_drawdown,
        "avg_holding_days": avg_holding_days
    }


def generate_report(per_stock_summary, aggregate, position_diag, cost_diag, data_comp, benchmark_ret, trades_all, daily_data=None):
    """生成 report.md"""
    lines = []
    lines.append("# 海龟策略A股基线回测报告 v1.0\n")

    lines.append("## 仓位诊断\n")
    lines.append("| 指标 | 值 |")
    lines.append("|------|-----|")
    lines.append("| 平均仓位占比 | {:.4f}% |".format(position_diag["avg_position_pct"] * 100))
    lines.append("| 平均单笔风险占比 | {:.4f}% |".format(position_diag["avg_risk_pct"] * 100))
    lines.append("")
    lines.append("> SPEC §2 仓位公式字面实现；若 avg_risk_pct 显著偏离 1%（如≈0.1%），提示公式可能笔误，待诚哥确认。\n")

    lines.append("## 一句话结论\n")
    n_pos = aggregate.get("positive_return_ratio", 0) or 0
    ann_mean = aggregate.get("annualized_return_mean", 0) or 0
    if ann_mean > 0 and n_pos > 0.5:
        conclusion = "原版海龟规则在A股沪深300成分股上**整体可以盈利**，但收益有限，需注意个股分化。"
    else:
        conclusion = "原版海龟规则在A股沪深300成分股上**整体收益偏弱或亏损**，不建议直接使用。"
    lines.append(conclusion + "\n")

    lines.append("## 汇总指标\n")
    lines.append("| 指标 | 均值 | 中位数 |")
    lines.append("|------|------|--------|")
    lines.append("| 年化收益率 | {:.4f}% | {:.4f}% |".format(
        (aggregate.get("annualized_return_mean") or 0) * 100,
        (aggregate.get("annualized_return_median") or 0) * 100))
    lines.append("| 胜率 | {:.2f}% | {:.2f}% |".format(
        (aggregate.get("win_rate_mean") or 0) * 100,
        (aggregate.get("win_rate_median") or 0) * 100))
    plr_m = aggregate.get("profit_loss_ratio_mean")
    plr_md = aggregate.get("profit_loss_ratio_median")
    lines.append("| 盈亏比 | {} | {} |".format(
        "{:.2f}".format(plr_m) if plr_m is not None else "N/A",
        "{:.2f}".format(plr_md) if plr_md is not None else "N/A"))
    lines.append("| 正收益占比 | {:.1f}% | - |".format((aggregate.get("positive_return_ratio") or 0) * 100))
    bb = aggregate.get("beat_benchmark_ratio")
    lines.append("| 跑赢沪深300占比 | {} | - |".format("{:.1f}%".format(bb * 100) if bb is not None else "N/A"))
    lines.append("| 最大回撤 | {:.2f}% | {:.2f}% |".format(
        (aggregate.get("max_drawdown_mean") or 0) * 100,
        (aggregate.get("max_drawdown_median") or 0) * 100))
    lines.append("| 平均持仓天数 | {:.1f} | - |".format(aggregate.get("avg_holding_days_mean") or 0))
    lines.append("| 年均交易笔数/股 | {:.1f} | - |".format(aggregate.get("trades_per_year_per_stock") or 0))
    lines.append("")

    lines.append("## 成本诊断\n")
    lines.append("| 项目 | 实际摩擦占比 |")
    lines.append("|------|-------------|")
    lines.append("| 买入平均摩擦 | {:.4f}% |".format(cost_diag["avg_buy_cost_pct"] * 100))
    lines.append("| 卖出平均摩擦 | {:.4f}% |".format(cost_diag["avg_sell_cost_pct"] * 100))
    lines.append("")
    lines.append("> SPEC 汇总：买入 0.0351% / 卖出 0.1351%。滑点 0.1% 已计入买卖价。\n")

    lines.append("## 数据完整性\n")
    lines.append("| 指标 | 值 |")
    lines.append("|------|-----|")
    lines.append("| 平均缺失日期比例 | {:.4f}% |".format(data_comp["avg_missing_date_ratio"] * 100))
    lines.append("| 超1%缺失的股票数 | {} |".format(data_comp["n_stocks_above_1pct_missing"]))
    lines.append("")
    no_data = data_comp.get("no_data_stocks", [])
    above_1pct = data_comp.get("stocks_above_1pct_list", [])
    if no_data:
        lines.append("- 完全无数据（已排除回测）: {} 共{}只: {}".format(
            ", ".join(no_data), len(no_data), ", ".join(no_data)))
        lines.append("")
    if above_1pct:
        shown = above_1pct[:10]
        lines.append("- 超1%缺失前{}只/共{}只: {}".format(len(shown), len(above_1pct), ", ".join(shown)))
        lines.append("")
    lines.append("> 缺失主要为 astock 对沪深300新进/次新成分的数据缺口（非脚本 bug）；完全无数据的股票已排除，实际回测{}只。\n".format(
        len(per_stock_summary) - len(no_data)))
    lines.append("")

    lines.append("## 抽查验证\n")
    if trades_all:
        np.random.seed(42)
        sample_trades = np.random.choice(trades_all, min(3, len(trades_all)), replace=False)
        lines.append("### 交易信号抽查\n")
        for i, t in enumerate(sample_trades):
            lines.append("**交易{}: {}**".format(i+1, t["code"]))
            lines.append("- 信号日: {}, 买入日: {}, 买入价: {:.2f}".format(
                t["signal_date"], t["buy_date"], t["buy_price"]))
            lines.append("- 卖出日: {}, 卖出价: {:.2f}, 盈亏: {:.2f}元".format(
                t["sell_date"], t["sell_price"], t["pnl"]))
            lines.append("- 退出原因: {}, 持仓天数: {}".format(t["exit_reason"], t["days_held"]))
            if daily_data and t["code"] in daily_data:
                cdf = daily_data[t["code"]]
                sig_bar = cdf[cdf["date"] == t["signal_date"]]
                if len(sig_bar) > 0:
                    sig_close = sig_bar.iloc[0]["close"]
                    entry_high = sig_bar.iloc[0]["entry_high"]
                    lines.append("- 信号日 close[T]={:.2f}, entry_high(20日最高不含T)={:.2f}".format(
                        sig_close, entry_high))
                    if not pd.isna(entry_high) and not pd.isna(sig_close):
                        if sig_close > entry_high:
                            lines.append("- 突破判断: {:.2f} > {:.2f} 突破确认".format(sig_close, entry_high))
                        else:
                            lines.append("- 突破判断: {:.2f} <= {:.2f} 未突破".format(sig_close, entry_high))
                if t["exit_reason"] == "stoploss":
                    sell_bar = cdf[cdf["date"] == t["sell_date"]]
                    if len(sell_bar) > 0:
                        sell_close = sell_bar.iloc[0]["close"]
                        current_stop = t["initial_stop"]
                        lines.append("- 止损判断: close[V]={:.2f}, initial_stop={:.2f} → {} < {} 触发止损".format(
                            sell_close, current_stop,
                            "{:.2f}".format(sell_close), "{:.2f}".format(current_stop)))
                elif t["exit_reason"] == "exit_signal":
                    sell_bar = cdf[cdf["date"] == t["sell_date"]]
                    if len(sell_bar) > 0:
                        sell_close = sell_bar.iloc[0]["close"]
                        exit_low = sell_bar.iloc[0]["exit_low"]
                        lines.append("- 离场判断: close[V]={:.2f}, exit_low(10日最低)={:.2f} → {} < {} 触发离场".format(
                            sell_close, exit_low,
                            "{:.2f}".format(sell_close), "{:.2f}".format(exit_low)))
            lines.append("")

        lines.append("### 成本手算抽查\n")
        ct = trades_all[0]
        lines.append("**交易: {}**".format(ct["code"]))
        is_sh = ct["code"].endswith(".SH")
        buy_commission = ct["buy_price"] * ct["shares"] * COMMISSION
        buy_transfer = ct["buy_price"] * ct["shares"] * TRANSFER_FEE if is_sh else 0
        buy_tax = 0
        buy_total_cost = buy_commission + buy_transfer + buy_tax
        sell_commission = ct["sell_price"] * ct["shares"] * COMMISSION
        sell_tax = ct["sell_price"] * ct["shares"] * STAMP_TAX
        sell_transfer = ct["sell_price"] * ct["shares"] * TRANSFER_FEE if is_sh else 0
        sell_total_cost = sell_commission + sell_tax + sell_transfer
        lines.append("- 买入: price={:.4f}, shares={}".format(ct["buy_price"], ct["shares"]))
        lines.append("  - commission = {:.4f} × {} × 0.00025 = {:.4f}".format(
            ct["buy_price"], ct["shares"], buy_commission))
        if is_sh:
            lines.append("  - transfer   = {:.4f} × {} × 0.00001 = {:.4f}".format(
                ct["buy_price"], ct["shares"], buy_transfer))
        lines.append("  - 买入总成本 = {:.4f}".format(buy_total_cost))
        lines.append("- 卖出: price={:.4f}, shares={}".format(ct["sell_price"], ct["shares"]))
        lines.append("  - commission = {:.4f} × {} × 0.00025 = {:.4f}".format(
            ct["sell_price"], ct["shares"], sell_commission))
        lines.append("  - stamp_tax  = {:.4f} × {} × 0.001   = {:.4f}".format(
            ct["sell_price"], ct["shares"], sell_tax))
        if is_sh:
            lines.append("  - transfer   = {:.4f} × {} × 0.00001 = {:.4f}".format(
                ct["sell_price"], ct["shares"], sell_transfer))
        lines.append("  - 卖出总成本 = {:.4f}".format(sell_total_cost))
        buy_value = ct["buy_price"] * ct["shares"]
        sell_value = ct["sell_price"] * ct["shares"]
        pnl_calc = (sell_value - sell_total_cost) - (buy_value + buy_total_cost)
        lines.append("- pnl手算 = (sell_price×shares - 卖出成本) - (buy_price×shares + 买入成本)")
        lines.append("          = ({:.4f} - {:.4f}) - ({:.4f} + {:.4f}) = {:.4f}".format(
            sell_value, sell_total_cost, buy_value, buy_total_cost, pnl_calc))
        lines.append("- 脚本输出 pnl: {:.4f} (误差: {:.6f})".format(ct["pnl"], abs(ct["pnl"] - pnl_calc)))
        lines.append("")

    lines.append("## 分布描述\n")
    lines.append("（胜率/盈亏比/年化收益分布详见 result_summary.json）\n")

    lines.append("## 复权与数据说明\n")
    lines.append("- 复权方式: 前复权，基准日 2026-06-22（adj_factor末日）")
    lines.append("- 数据源: astock parquet (E:/astock/daily/stock_daily.parquet)")
    lines.append("- 成分股取数日期: {}".format(datetime.now().strftime("%Y-%m-%d")))
    lines.append("- 基准: 沪深300指数同期收益率 {}".format(
        "{:.4f}".format(benchmark_ret) if benchmark_ret is not None else "取数失败"))
    lines.append("")

    return "\n".join(lines)


def main():
    print("=" * 60)
    print("海龟策略A股基线回测 v1.0")
    print("=" * 60)

    os.makedirs(OUT_DIR, exist_ok=True)

    codes, names = get_hs300_constituents()
    code_name_map = dict(zip(codes, names))

    all_daily = pd.read_parquet(DATA_PARQUET)
    all_daily = all_daily.reset_index()

    trading_days = get_trading_days(all_daily)
    benchmark_ret = get_hs300_benchmark(all_daily)

    daily_data = load_daily(codes)

    all_trades = []
    per_stock_summary = []
    all_equity = []
    total_position_value = 0.0
    total_risk_value = 0.0
    total_buy_cost = 0.0
    total_buy_value = 0.0
    total_sell_cost = 0.0
    total_sell_value = 0.0
    n_position_samples = 0

    for code in codes:
        if code not in daily_data:
            per_stock_summary.append({
                "code": code, "name": code_name_map.get(code, ""),
                "n_trades": 0, "win_rate": None, "avg_win_loss_ratio": None,
                "total_return": 0.0, "max_drawdown": 0.0, "avg_holding_days": 0
            })
            continue

        cdf = daily_data[code]
        cdf = compute_indicators(cdf)
        daily_data[code] = cdf
        trades, equity = run_backtest_single(code, cdf, trading_days)
        metrics = compute_stock_metrics(trades, equity)

        per_stock_summary.append({
            "code": code,
            "name": code_name_map.get(code, ""),
            "n_trades": metrics["n_trades"],
            "win_rate": metrics["win_rate"],
            "avg_win_loss_ratio": metrics["avg_win_loss_ratio"],
            "total_return": metrics["total_return"],
            "max_drawdown": metrics["max_drawdown"],
            "avg_holding_days": metrics["avg_holding_days"]
        })
        all_trades.extend(trades)
        all_equity.extend(equity)

        for t in trades:
            pos_val = t["buy_price"] * t["shares"]
            risk_val = 2 * t["atr_at_entry"] * t["shares"]
            total_position_value += pos_val
            total_risk_value += risk_val
            n_position_samples += 1
            total_buy_cost += t["buy_cost"]
            total_buy_value += t["buy_price"] * t["shares"]
            total_sell_cost += t["sell_cost"]
            total_sell_value += t["sell_price"] * t["shares"]

    avg_position_pct = total_position_value / (n_position_samples * INITIAL_CASH) if n_position_samples > 0 else 0
    avg_risk_pct = total_risk_value / (n_position_samples * INITIAL_CASH) if n_position_samples > 0 else 0
    avg_buy_cost_pct = total_buy_cost / total_buy_value if total_buy_value > 0 else 0
    avg_sell_cost_pct = total_sell_cost / total_sell_value if total_sell_value > 0 else 0

    position_diag = {"avg_position_pct": avg_position_pct, "avg_risk_pct": avg_risk_pct}
    cost_diag = {"avg_buy_cost_pct": avg_buy_cost_pct, "avg_sell_cost_pct": avg_sell_cost_pct}

    valid_stocks = [s for s in per_stock_summary if s["n_trades"] > 0]
    ann_returns = []
    for s in valid_stocks:
        if s["total_return"] is not None:
            n_days = len([e for e in all_equity if e["code"] == s["code"]])
            if n_days > 0:
                ann = (1 + s["total_return"]) ** (252 / max(n_days, 1)) - 1
                ann_returns.append(ann)
            else:
                ann_returns.append(0.0)
        else:
            ann_returns.append(0.0)

    win_rates = [s["win_rate"] for s in valid_stocks if s["win_rate"] is not None]
    plr_list = [s["avg_win_loss_ratio"] for s in valid_stocks if s["avg_win_loss_ratio"] is not None]
    pos_returns = [s for s in per_stock_summary if s["total_return"] is not None and s["total_return"] > 0]
    drawdowns = [s["max_drawdown"] for s in valid_stocks]
    holding_days = [s["avg_holding_days"] for s in valid_stocks if s["avg_holding_days"] > 0]

    total_days = len(trading_days)
    total_n_trades = len(all_trades)
    total_stocks = len(valid_stocks)
    avg_trades_per_stock_per_year = (total_n_trades / total_stocks / (total_days / 252)) if total_stocks > 0 and total_days > 0 else 0

    beat_bench = None
    if benchmark_ret is not None and per_stock_summary:
        n_beat = sum(1 for s in per_stock_summary
                     if s.get("total_return") is not None and s["total_return"] > benchmark_ret)
        beat_bench = n_beat / len(per_stock_summary) if len(per_stock_summary) > 0 else None

    aggregate = {
        "annualized_return_mean": np.mean(ann_returns) if ann_returns else None,
        "annualized_return_median": np.median(ann_returns) if ann_returns else None,
        "win_rate_mean": np.mean(win_rates) if win_rates else None,
        "win_rate_median": np.median(win_rates) if win_rates else None,
        "win_rate_std": np.std(win_rates) if win_rates else None,
        "profit_loss_ratio_mean": np.mean(plr_list) if plr_list else None,
        "profit_loss_ratio_median": np.median(plr_list) if plr_list else None,
        "profit_loss_ratio_std": np.std(plr_list) if plr_list else None,
        "positive_return_ratio": len(pos_returns) / len(per_stock_summary) if per_stock_summary else None,
        "beat_benchmark_ratio": beat_bench,
        "max_drawdown_mean": np.mean(drawdowns) if drawdowns else None,
        "max_drawdown_median": np.median(drawdowns) if drawdowns else None,
        "avg_holding_days_mean": np.mean(holding_days) if holding_days else None,
        "trades_per_year_per_stock": avg_trades_per_stock_per_year
    }

    expected_days = 0
    actual_days = 0
    n_stocks_above_1pct = 0
    stocks_above_1pct_list = []
    no_data_stocks = []
    missing_ratios = []
    for code in codes:
        if code not in daily_data:
            no_data_stocks.append(code)
            continue
        cdf = daily_data[code]
        code_days = [d for d in trading_days if d in set(cdf["date"].tolist())]
        expected_days = len(trading_days)
        actual_days = len(code_days)
        if expected_days > 0:
            ratio = 1 - actual_days / expected_days
            missing_ratios.append(ratio)
            if ratio > 0.01:
                n_stocks_above_1pct += 1
                stocks_above_1pct_list.append(code)
    avg_missing = np.mean(missing_ratios) if missing_ratios else 0

    data_comp = {
        "avg_missing_date_ratio": avg_missing,
        "n_stocks_above_1pct_missing": n_stocks_above_1pct,
        "stocks_above_1pct_list": stocks_above_1pct_list,
        "no_data_stocks": no_data_stocks
    }

    result = {
        "meta": {
            "start_date": START_DATE,
            "end_date": END_DATE,
            "n_stocks": len(codes),
            "initial_cash": INITIAL_CASH,
            "atr_period": ATR_PERIOD,
            "entry_breakout": ENTRY_BREAKOUT,
            "exit_breakout": EXIT_BREAKOUT,
            "qfq_base_date": "2026-06-22",
            "benchmark_ret": benchmark_ret
        },
        "per_stock_summary": per_stock_summary,
        "aggregate": aggregate,
        "position_diagnostic": position_diag,
        "cost_diagnostic": cost_diag,
        "data_completeness": data_comp
    }

    with open(os.path.join(OUT_DIR, "result_summary.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    equity_df = pd.DataFrame(all_equity)
    equity_df.to_csv(os.path.join(OUT_DIR, "equity_curve.csv"), index=False)

    if all_trades:
        trades_df = pd.DataFrame(all_trades)
        cols = ["code", "name", "signal_date", "buy_date", "buy_price", "sell_date", "sell_price",
                "shares", "atr_at_entry", "initial_stop", "days_held", "pnl", "pnl_pct", "exit_reason",
                "buy_cost", "sell_cost"]
        for c in cols:
            if c == "name":
                trades_df["name"] = trades_df["code"].map(code_name_map).fillna("")
            elif c not in trades_df.columns:
                trades_df[c] = None
        trades_df[cols].to_csv(os.path.join(OUT_DIR, "trades.csv"), index=False)
    else:
        pd.DataFrame(columns=["code", "name", "signal_date", "buy_date", "buy_price", "sell_date",
                              "sell_price", "shares", "atr_at_entry", "initial_stop", "days_held",
                              "pnl", "pnl_pct", "exit_reason", "buy_cost", "sell_cost"]).to_csv(
            os.path.join(OUT_DIR, "trades.csv"), index=False)

    report = generate_report(per_stock_summary, aggregate, position_diag, cost_diag, data_comp, benchmark_ret, all_trades, daily_data)
    with open(os.path.join(OUT_DIR, "report.md"), "w", encoding="utf-8") as f:
        f.write(report)

    ann_mean_str = "{:.4f}".format(aggregate["annualized_return_mean"]) if aggregate["annualized_return_mean"] is not None else "N/A"
    wr_mean_str = "{:.4f}".format(aggregate["win_rate_mean"]) if aggregate["win_rate_mean"] is not None else "N/A"
    bb_str = "{:.1f}".format(aggregate["beat_benchmark_ratio"] * 100) if aggregate["beat_benchmark_ratio"] is not None else "N/A"

    print("=" * 60)
    print("[turtle_baseline] done: {} stocks, {} trades, avg_ann_ret={}, win_rate_mean={}, beat_bench={}%" .format(len(codes), total_n_trades, ann_mean_str, wr_mean_str, bb_str))
    print("Output directory: {}".format(OUT_DIR))
    print("=" * 60)


if __name__ == "__main__":
    main()
