# coding=utf-8
"""
海龟策略A股双均线择时+量能过滤回测 v6.0
基于v5(MA20择时)升级为双均线多头(沪深300>MA20 AND MA20>MA60)+量能过滤(突破日量比>=1.5)
止损/离场/仓位同基线不变
"""
import os
import json
import warnings
import numpy as np
import pandas as pd
from datetime import datetime

warnings.filterwarnings("ignore")

# ===== 硬编码参数（同基线/v5 + 新增） =====
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

# 择时参数（升级双均线）
MARKET_TIMING_MA_SHORT = 20
MARKET_TIMING_MA_LONG = 60
MARKET_TIMING_INDEX = "sh000300"

# 量能过滤参数（新增）
VOLUME_RATIO_THRESHOLD = 1.5
VOLUME_RATIO_PERIOD = 5

OUT_DIR = "D:/QMT_STRATEGIES/backtest_results/turtle_timing_volume"
BASELINE_DIR = "D:/QMT_STRATEGIES/backtest_results/turtle_baseline"
V5_DIR = "D:/QMT_STRATEGIES/backtest_results/turtle_timing"


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


def load_market_timing():
    """加载沪深300指数日线，计算双均线(ma20/ma60)，缓存到本地"""
    import akshare as ak

    os.makedirs(OUT_DIR, exist_ok=True)
    cache_path = os.path.join(OUT_DIR, "_hs300_index.csv")

    if os.path.exists(cache_path):
        df = pd.read_csv(cache_path)
        df["date"] = df["date"].astype(str)
        print("[DATA] Using cached HS300 index: {} rows".format(len(df)))
        return df

    print("[DATA] Fetching HS300 index from akshare...")
    bench = ak.stock_zh_index_daily(symbol=MARKET_TIMING_INDEX)
    bench["date"] = bench["date"].astype(str)
    bench = bench.sort_values("date")

    bench = bench[(bench["date"] >= WARMUP_START) & (bench["date"] <= END_DATE)]
    if len(bench) < MARKET_TIMING_MA_LONG:
        raise RuntimeError("HS300 index data too short: {} rows, need >= {}".format(
            len(bench), MARKET_TIMING_MA_LONG))

    bench = bench[["date", "close"]].copy()
    bench["ma20"] = bench["close"].rolling(MARKET_TIMING_MA_SHORT, min_periods=MARKET_TIMING_MA_SHORT).mean()
    bench["ma60"] = bench["close"].rolling(MARKET_TIMING_MA_LONG, min_periods=MARKET_TIMING_MA_LONG).mean()
    # 双均线多头排列: 收盘>MA20 AND MA20>MA60
    bench["bull"] = (bench["close"] > bench["ma20"]) & (bench["ma20"] > bench["ma60"])

    bench.to_csv(cache_path, index=False)
    print("[DATA] Loaded HS300 index: {} rows, date range {} ~ {}".format(
        len(bench), bench["date"].iloc[0], bench["date"].iloc[-1]))
    return bench


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
        bench = ak.stock_zh_index_daily(symbol=MARKET_TIMING_INDEX)
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
    """预计算海龟指标 + 量比（向量化，PIT安全）"""
    cdf = cdf.copy()
    high = cdf["high"].values
    low = cdf["low"].values
    close = cdf["close"].values
    vol = cdf["vol"].values

    tr = np.zeros(len(cdf))
    tr[0] = np.nan
    for i in range(1, len(cdf)):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
    cdf["tr"] = tr

    cdf["atr"] = pd.Series(tr).rolling(ATR_PERIOD, min_periods=ATR_PERIOD).mean().values
    cdf["entry_high"] = pd.Series(close).shift(1).rolling(ENTRY_BREAKOUT, min_periods=ENTRY_BREAKOUT).max().values
    cdf["exit_low"] = pd.Series(close).shift(1).rolling(EXIT_BREAKOUT, min_periods=EXIT_BREAKOUT).min().values

    # 量比 = 当日vol / 前5日均vol(不含当日, PIT安全)
    vol_series = pd.Series(vol)
    vol_ma5 = vol_series.shift(1).rolling(VOLUME_RATIO_PERIOD, min_periods=VOLUME_RATIO_PERIOD).mean()
    cdf["vol_ratio"] = vol_series / vol_ma5

    return cdf


def run_backtest_single(code, cdf, trading_days, timing_df):
    """单只股票独立回测（带双均线择时+量能过滤）"""
    td_set = set(cdf["date"].tolist())
    cdf_idx = cdf.set_index("date")

    timing_idx = timing_df.set_index("date")

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

            # 双均线择时过滤: 沪深300收盘 > MA20 AND MA20 > MA60
            market_bullish = False
            vol_ratio_ok = False
            if td in timing_idx.index:
                timing_row = timing_idx.loc[td]
                if isinstance(timing_row, pd.DataFrame):
                    timing_row = timing_row.iloc[0]
                if (not pd.isna(timing_row.get("bull", np.nan))) and timing_row["bull"]:
                    market_bullish = True

            # 量能过滤: vol_ratio >= 1.5
            vr = bar.get("vol_ratio", np.nan)
            if (not pd.isna(vr)) and vr >= VOLUME_RATIO_THRESHOLD:
                vol_ratio_ok = True

            if (not pd.isna(entry_high_val)) and (not pd.isna(atr_val)) and (atr_val > 0) and (close_val > entry_high_val) and market_bullish and vol_ratio_ok:
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
                                "commission": commission, "transfer": transfer,
                                "vol_ratio_at_entry": vr if not pd.isna(vr) else None
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
                        "sell_cost": s_commission + s_tax + s_transfer,
                        "vol_ratio_at_entry": position.get("vol_ratio_at_entry")
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


def load_other_result(result_dir, label):
    """读取其他版本的 result_summary.json"""
    path = os.path.join(result_dir, "result_summary.json")
    if not os.path.exists(path):
        print("[WARN] {} result not found at {}".format(label, path))
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def fmt_pct(v):
    if v is None:
        return "N/A"
    return "{:.1f}%".format(v * 100)


def fmt_pct2(v):
    if v is None:
        return "N/A"
    return "{:.2f}%".format(v * 100)


def fmt_plr(v):
    if v is None:
        return "N/A"
    return "{:.2f}".format(v)


def fmt_change(v6_val, base_val, is_pct=True):
    if v6_val is None or base_val is None:
        return "N/A"
    diff = v6_val - base_val
    sign = "+" if diff > 0 else ""
    if is_pct:
        return "{}{:.2f}%".format(sign, diff * 100)
    else:
        return "{}{:.0f}".format(sign, diff)


def generate_report(per_stock_summary, aggregate, position_diag, cost_diag, data_comp,
                    benchmark_ret, trades_all, daily_data=None, baseline_result=None, v5_result=None):
    """生成 report.md（含三列对比表: 基线/v5/v6）"""
    lines = []
    lines.append("# 海龟策略A股双均线择时+量能过滤回测报告 v6.0\n")

    # 一句话结论
    lines.append("## 一句话结论\n")
    v6_ann = aggregate.get("annualized_return_mean") or 0
    v6_wr = aggregate.get("win_rate_mean") or 0
    v6_plr = aggregate.get("profit_loss_ratio_mean") or 0
    improvements = []
    if baseline_result and "aggregate" in baseline_result:
        base_agg = baseline_result["aggregate"]
        if v6_ann > (base_agg.get("annualized_return_mean") or 0):
            improvements.append("年化收益")
        if v6_wr > (base_agg.get("win_rate_mean") or 0):
            improvements.append("胜率")
        if v6_plr > (base_agg.get("profit_loss_ratio_mean") or 0):
            improvements.append("盈亏比")
    if v5_result and "aggregate" in v5_result:
        v5_agg = v5_result["aggregate"]
        v5_notes = []
        if v6_ann > (v5_agg.get("annualized_return_mean") or 0):
            v5_notes.append("年化收益")
        if v6_wr > (v5_agg.get("win_rate_mean") or 0):
            v5_notes.append("胜率")
        if v6_plr > (v5_agg.get("profit_loss_ratio_mean") or 0):
            v5_notes.append("盈亏比")
        if improvements or v5_notes:
            all_items = list(set(improvements + v5_notes))
            conclusion = "v6(双均线+量能)相比基线和v5(MA20)，{}有所改善。".format("、".join(all_items))
        else:
            conclusion = "v6(双均线+量能)相比基线和v5(MA20)，核心指标未见明显改善。"
    elif improvements:
        conclusion = "v6(双均线+量能)相比基线，{}有所改善。".format("、".join(improvements))
    else:
        conclusion = "v6(双均线+量能)回测完成。"
    lines.append(conclusion + "\n")

    # 三列对比表
    lines.append("## 三列对比表\n")
    lines.append("| 指标 | 基线(无择时) | v5(MA20) | v6(双均线+量能) |")
    lines.append("|---|---|---|---|")

    base_agg = baseline_result["aggregate"] if baseline_result and "aggregate" in baseline_result else {}
    v5_agg = v5_result["aggregate"] if v5_result and "aggregate" in v5_result else {}
    base_pos = baseline_result.get("position_diagnostic", {}) if baseline_result else {}
    v5_pos = v5_result.get("position_diagnostic", {}) if v5_result else {}

    # 交易笔数
    base_trades = sum(s.get("n_trades", 0) for s in baseline_result.get("per_stock_summary", [])) if baseline_result else 0
    v5_trades = sum(s.get("n_trades", 0) for s in v5_result.get("per_stock_summary", [])) if v5_result else 0
    v6_trades = len(trades_all)

    lines.append("| 年化收益均值 | {} | {} | {} |".format(
        fmt_pct(base_agg.get("annualized_return_mean")),
        fmt_pct(v5_agg.get("annualized_return_mean")),
        fmt_pct(aggregate.get("annualized_return_mean"))))
    lines.append("| 年化收益中位 | {} | {} | {} |".format(
        fmt_pct(base_agg.get("annualized_return_median")),
        fmt_pct(v5_agg.get("annualized_return_median")),
        fmt_pct(aggregate.get("annualized_return_median"))))
    lines.append("| 胜率均值 | {} | {} | {} |".format(
        fmt_pct(base_agg.get("win_rate_mean")),
        fmt_pct(v5_agg.get("win_rate_mean")),
        fmt_pct(aggregate.get("win_rate_mean"))))
    lines.append("| 盈亏比均值 | {} | {} | {} |".format(
        fmt_plr(base_agg.get("profit_loss_ratio_mean")),
        fmt_plr(v5_agg.get("profit_loss_ratio_mean")),
        fmt_plr(aggregate.get("profit_loss_ratio_mean"))))
    lines.append("| 正收益占比 | {} | {} | {} |".format(
        fmt_pct(base_agg.get("positive_return_ratio")),
        fmt_pct(v5_agg.get("positive_return_ratio")),
        fmt_pct(aggregate.get("positive_return_ratio"))))
    lines.append("| 跑赢沪深300 | {} | {} | {} |".format(
        fmt_pct(base_agg.get("beat_benchmark_ratio")),
        fmt_pct(v5_agg.get("beat_benchmark_ratio")),
        fmt_pct(aggregate.get("beat_benchmark_ratio"))))
    lines.append("| 最大回撤均值 | {} | {} | {} |".format(
        fmt_pct(base_agg.get("max_drawdown_mean")),
        fmt_pct(v5_agg.get("max_drawdown_mean")),
        fmt_pct(aggregate.get("max_drawdown_mean"))))
    lines.append("| 交易笔数 | {} | {} | {} |".format(
        base_trades, v5_trades, v6_trades))
    lines.append("| 平均仓位 | {} | {} | {} |".format(
        fmt_pct(base_pos.get("avg_position_pct", 0)),
        fmt_pct(v5_pos.get("avg_position_pct", 0)),
        fmt_pct(position_diag["avg_position_pct"])))
    lines.append("| 平均单笔风险 | {} | {} | {} |".format(
        fmt_pct(base_pos.get("avg_risk_pct", 0)),
        fmt_pct(v5_pos.get("avg_risk_pct", 0)),
        fmt_pct(position_diag["avg_risk_pct"])))
    lines.append("")

    # 仓位诊断
    lines.append("## 仓位诊断\n")
    lines.append("| 指标 | 值 |")
    lines.append("|------|-----|")
    lines.append("| 平均仓位占比 | {:.4f}% |".format(position_diag["avg_position_pct"] * 100))
    lines.append("| 平均单笔风险占比 | {:.4f}% |".format(position_diag["avg_risk_pct"] * 100))
    lines.append("")

    # 汇总指标
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
    lines.append("")

    # 成本诊断
    lines.append("## 成本诊断\n")
    lines.append("| 项目 | 实际摩擦占比 |")
    lines.append("|------|-------------|")
    lines.append("| 买入平均摩擦 | {:.4f}% |".format(cost_diag["avg_buy_cost_pct"] * 100))
    lines.append("| 卖出平均摩擦 | {:.4f}% |".format(cost_diag["avg_sell_cost_pct"] * 100))
    lines.append("")

    # 数据完整性
    lines.append("## 数据完整性\n")
    lines.append("| 指标 | 值 |")
    lines.append("|------|-----|")
    lines.append("| 平均缺失日期比例 | {:.4f}% |".format(data_comp["avg_missing_date_ratio"] * 100))
    lines.append("| 超1%缺失的股票数 | {} |".format(data_comp["n_stocks_above_1pct_missing"]))
    lines.append("")

    # 抽查验证（含双均线多头判断 + 量比数值）
    lines.append("## 抽查验证\n")
    if trades_all:
        np.random.seed(42)
        sample_trades = np.random.choice(trades_all, min(3, len(trades_all)), replace=False)
        lines.append("### 交易信号抽查\n")

        timing_cache = os.path.join(OUT_DIR, "_hs300_index.csv")
        timing_df_for_check = None
        if os.path.exists(timing_cache):
            timing_df_for_check = pd.read_csv(timing_cache)
            timing_df_for_check["date"] = timing_df_for_check["date"].astype(str)

        for i, t in enumerate(sample_trades):
            lines.append("**交易{}: {}**".format(i + 1, t["code"]))
            lines.append("- 信号日: {}, 买入日: {}, 买入价: {:.2f}".format(
                t["signal_date"], t["buy_date"], t["buy_price"]))
            lines.append("- 卖出日: {}, 卖出价: {:.2f}, 盈亏: {:.2f}元".format(
                t["sell_date"], t["sell_price"], t["pnl"]))
            lines.append("- 退出原因: {}, 持仓天数: {}".format(t["exit_reason"], t["days_held"]))
            lines.append("- 入场量比: {}".format(
                "{:.4f}".format(t["vol_ratio_at_entry"]) if t.get("vol_ratio_at_entry") is not None else "N/A"))

            if daily_data and t["code"] in daily_data:
                cdf = daily_data[t["code"]]
                sig_bar = cdf[cdf["date"] == t["signal_date"]]
                if len(sig_bar) > 0:
                    sig_close = sig_bar.iloc[0]["close"]
                    entry_high = sig_bar.iloc[0]["entry_high"]
                    vr = sig_bar.iloc[0].get("vol_ratio", np.nan)
                    lines.append("- 信号日 close[T]={:.2f}, entry_high(20日最高不含T)={:.2f}".format(
                        sig_close, entry_high))
                    lines.append("- 信号日 vol_ratio={}".format(
                        "{:.4f}".format(vr) if not pd.isna(vr) else "NaN"))
                    if not pd.isna(entry_high) and not pd.isna(sig_close):
                        if sig_close > entry_high:
                            lines.append("- 突破判断: {:.2f} > {:.2f} 突破确认".format(sig_close, entry_high))
                        else:
                            lines.append("- 突破判断: {:.2f} <= {:.2f} 未突破".format(sig_close, entry_high))

            # 双均线多头判断
            if timing_df_for_check is not None:
                sig_date = t["signal_date"]
                t_row = timing_df_for_check[timing_df_for_check["date"] == sig_date]
                if len(t_row) > 0:
                    hs300_c = t_row.iloc[0]["close"]
                    hs300_ma20 = t_row.iloc[0]["ma20"]
                    hs300_ma60 = t_row.iloc[0]["ma60"]
                    bull = t_row.iloc[0]["bull"]
                    lines.append("- 双均线: hs300_close={:.2f}, ma20={:.2f}, ma60={:.2f} -> close>ma20={} & ma20>ma60={} -> bull={}".format(
                        hs300_c, hs300_ma20, hs300_ma60,
                        "YES" if hs300_c > hs300_ma20 else "NO",
                        "YES" if hs300_ma20 > hs300_ma60 else "NO",
                        "YES (允许开仓)" if bull else "NO (已开仓)"))
                else:
                    lines.append("- 双均线: 信号日 {} 沪深300数据缺失".format(sig_date))

            lines.append("")

    lines.append("## 复权与数据说明\n")
    lines.append("- 复权方式: 前复权，基准日 2026-06-22（adj_factor末日）")
    lines.append("- 数据源: astock parquet (E:/astock/daily/stock_daily.parquet)")
    lines.append("- 成分股取数日期: {}".format(datetime.now().strftime("%Y-%m-%d")))
    lines.append("- 基准: 沪深300指数同期收益率 {}".format(
        "{:.4f}".format(benchmark_ret) if benchmark_ret is not None else "取数失败"))
    lines.append("- 大盘择时: 沪深300收盘 > MA{} AND MA{} > MA{} 才允许开仓".format(
        MARKET_TIMING_MA_SHORT, MARKET_TIMING_MA_SHORT, MARKET_TIMING_MA_LONG))
    lines.append("- 量能过滤: 突破日量比 >= {} 才允许开仓".format(VOLUME_RATIO_THRESHOLD))
    lines.append("")

    # 过滤过严检测
    n_trades = len(trades_all)
    if n_trades < 1000:
        lines.append("## 过滤过严警告\n")
        lines.append("**交易笔数 {} < 1000，双均线+量能过滤过严，样本不足，建议降阈值**\n".format(n_trades))

    return "\n".join(lines)


def main():
    print("=" * 60)
    print("海龟策略A股双均线择时+量能过滤回测 v6.0")
    print("dual_ma20_60 + vol_ratio>={}".format(VOLUME_RATIO_THRESHOLD))
    print("=" * 60)

    os.makedirs(OUT_DIR, exist_ok=True)

    codes, names = get_hs300_constituents()
    code_name_map = dict(zip(codes, names))

    all_daily = pd.read_parquet(DATA_PARQUET)
    all_daily = all_daily.reset_index()

    trading_days = get_trading_days(all_daily)
    benchmark_ret = get_hs300_benchmark(all_daily)

    daily_data = load_daily(codes)

    # 加载双均线择时数据
    timing_df = load_market_timing()

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
        trades, equity = run_backtest_single(code, cdf, trading_days, timing_df)
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
    pos_returns = [s for s in per_stock_summary if s.get("total_return") is not None and s["total_return"] > 0]
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
            "benchmark_ret": benchmark_ret,
            "market_timing": "dual_ma20_60",
            "market_timing_ma_short": MARKET_TIMING_MA_SHORT,
            "market_timing_ma_long": MARKET_TIMING_MA_LONG,
            "market_timing_index": MARKET_TIMING_INDEX,
            "volume_ratio_threshold": VOLUME_RATIO_THRESHOLD,
            "volume_ratio_period": VOLUME_RATIO_PERIOD
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

    # 读取基线和v5结果用于对比
    baseline_result = load_other_result(BASELINE_DIR, "baseline")
    v5_result = load_other_result(V5_DIR, "v5")

    report = generate_report(per_stock_summary, aggregate, position_diag, cost_diag, data_comp,
                             benchmark_ret, all_trades, daily_data, baseline_result, v5_result)
    with open(os.path.join(OUT_DIR, "report.md"), "w", encoding="utf-8") as f:
        f.write(report)

    ann_mean_str = "{:.4f}".format(aggregate["annualized_return_mean"]) if aggregate["annualized_return_mean"] is not None else "N/A"
    wr_mean_str = "{:.4f}".format(aggregate["win_rate_mean"]) if aggregate["win_rate_mean"] is not None else "N/A"
    bb_str = "{:.1f}".format(aggregate["beat_benchmark_ratio"] * 100) if aggregate["beat_benchmark_ratio"] is not None else "N/A"
    plr_str = "{:.2f}".format(aggregate["profit_loss_ratio_mean"]) if aggregate["profit_loss_ratio_mean"] is not None else "N/A"

    print("=" * 60)
    print("[turtle_timing_volume] done: {} stocks, {} trades, avg_ann_ret={}, win_rate_mean={}, plr_mean={}, beat_bench={}%, mode=dual_ma20_60+vol_ratio>={}".format(
        len(codes), total_n_trades, ann_mean_str, wr_mean_str, plr_str, bb_str, VOLUME_RATIO_THRESHOLD))
    print("avg_risk_pct={:.4f}%  avg_position_pct={:.4f}%".format(avg_risk_pct * 100, avg_position_pct * 100))
    print("Output directory: {}".format(OUT_DIR))
    print("=" * 60)


if __name__ == "__main__":
    main()
