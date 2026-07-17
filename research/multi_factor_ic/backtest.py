# coding=utf-8
"""多因子评分组合回测：月度调仓、等权持仓、绩效分析。"""

import numpy as np
import pandas as pd
from pathlib import Path

from research.multi_factor_ic.data_loader import get_rebalance_dates, load_universe, build_panel
from research.multi_factor_ic.scoring import MultiFactorScorer
from research.multi_factor_ic.ic_test import calc_forward_return
from research.multi_factor_ic.config import OUTPUT_DIR


def _industry_cap(scores, industry_map, top_n, max_pct=0.25):
    """行业中性化选股：在评分排序基础上，确保单行业不超过 max_pct。"""
    sorted_stocks = scores.dropna().sort_values(ascending=False)
    selected = []
    industry_count = {}

    for code in sorted_stocks.index:
        ind = industry_map.get(code, "未知")
        current = industry_count.get(ind, 0)
        max_allowed = max(1, int(top_n * max_pct))
        if current >= max_allowed:
            continue
        selected.append(code)
        industry_count[ind] = current + 1
        if len(selected) >= top_n:
            break

    # 如果不够 top_n，从剩余中补足
    if len(selected) < top_n:
        for code in sorted_stocks.index:
            if code not in selected:
                selected.append(code)
                if len(selected) >= top_n:
                    break

    return selected


def backtest(panel, fin_ffill, top_n=20, hold=1,
             industry_map=None, max_industry_pct=0.25, freq="M"):
    """运行调仓回测。

    Args:
        panel: 面板数据
        fin_ffill: 财务数据
        top_n: 每期持仓数量
        hold: 持有期数（1=持有1期，即一个调仓周期）
        industry_map: 行业映射，None=不做行业中性化
        max_industry_pct: 单行业最大占比
        freq: 调仓频率 "M"=月 "2M"=双月 "Q"=季度

    Returns:
        equity_df, trades_df, metrics
    """
    rebalance_dates = get_rebalance_dates(panel, freq=freq)
    scorer = MultiFactorScorer()

    trade_dates = sorted(panel.index.get_level_values("trade_date").unique())
    warmup = max(120, int(len(trade_dates) * 0.05))
    valid_start = trade_dates[warmup] if warmup < len(trade_dates) else trade_dates[0]

    rebalance_dates = [d for d in rebalance_dates if d >= valid_start]
    print(f"[backtest] 回测区间: {rebalance_dates[0]} ~ {rebalance_dates[-1]}")
    print(f"[backtest] 调仓次数: {len(rebalance_dates)}")

    portfolio_value = 1.0
    equity_curve = []
    trades_records = []

    for i, rebal_date in enumerate(rebalance_dates):
        try:
            scores = scorer.score(panel, fin_ffill, rebal_date)
        except Exception as e:
            print(f"  [skip] {rebal_date}: {e}")
            continue

        if len(scores.dropna()) < top_n:
            print(f"  [skip] {rebal_date}: 评分不足 {top_n}")
            continue

        # 选股：行业中性化 or 直接取 TOP
        if industry_map is not None:
            top_stocks = _industry_cap(scores, industry_map, top_n, max_industry_pct)
        else:
            top_stocks = scores.dropna().sort_values(ascending=False).head(top_n).index.tolist()

        # 计算持有期收益
        for h in range(hold):
            hold_idx = i + h
            if hold_idx >= len(rebalance_dates) - 1:
                break
            entry_date = rebal_date
            exit_date = rebalance_dates[hold_idx + 1]

            # 计算每只股票的收益
            stock_returns = []
            held_stocks = []
            for code in top_stocks:
                entry_close = panel.loc[entry_date, "close"].get(code)
                exit_close = panel.loc[exit_date, "close"].get(code)

                if entry_close is None or exit_close is None or entry_close == 0:
                    continue
                if pd.isna(entry_close) or pd.isna(exit_close):
                    continue

                ret = exit_close / entry_close - 1.0
                stock_returns.append(ret)
                held_stocks.append(code)

            if len(stock_returns) == 0:
                continue

            # 等权组合收益
            portfolio_ret = np.mean(stock_returns)
            portfolio_value *= (1 + portfolio_ret)

            equity_curve.append({
                "date": exit_date,
                "portfolio_value": portfolio_value,
                "period_return": portfolio_ret,
                "n_stocks": len(held_stocks),
            })

            trades_records.append({
                "entry_date": entry_date,
                "exit_date": exit_date,
                "stocks": ";".join(held_stocks[:5]) + (f"...({len(held_stocks)})" if len(held_stocks) > 5 else ""),
                "n_stocks": len(held_stocks),
                "period_return": portfolio_ret,
            })

    equity_df = pd.DataFrame(equity_curve)
    trades_df = pd.DataFrame(trades_records)

    # 计算绩效指标
    metrics = _calc_metrics(equity_df, trades_df, panel)

    return equity_df, trades_df, metrics


def _calc_metrics(equity_df, trades_df, panel):
    """计算绩效指标。"""
    metrics = {}

    if len(equity_df) == 0:
        return metrics

    total_return = equity_df["portfolio_value"].iloc[-1] - 1.0

    # 年化收益（按实际交易日推算年化）
    n_periods = len(equity_df)
    years = n_periods / 12  # 月度调仓
    if years > 0:
        ann_return = (1 + total_return) ** (1 / years) - 1
    else:
        ann_return = 0

    # 最大回撤
    cummax = equity_df["portfolio_value"].cummax()
    drawdown = equity_df["portfolio_value"] / cummax - 1
    max_dd = drawdown.min()

    # 夏普比率（假设无风险利率 2.5%）
    rf = 0.025 / 12  # 月度无风险利率
    excess_returns = equity_df["period_return"] - rf
    if excess_returns.std() > 0:
        sharpe = np.sqrt(12) * excess_returns.mean() / excess_returns.std()
    else:
        sharpe = 0

    # 胜率
    win_rate = (equity_df["period_return"] > 0).mean()

    # 平均持仓数
    avg_hold = equity_df["n_stocks"].mean()

    # 月均换手率（每月全部换仓，100%）
    monthly_turnover = 1.0

    metrics.update({
        "总收益": f"{total_return:.1%}",
        "年化收益": f"{ann_return:.1%}",
        "最大回撤": f"{max_dd:.1%}",
        "夏普比率": f"{sharpe:.2f}",
        "胜率": f"{win_rate:.0%}",
        "月均换手": f"{monthly_turnover:.0%}",
        "平均持仓数": f"{avg_hold:.0f}",
        "调仓次数": len(equity_df),
    })

    return metrics


def run_backtest(panel, fin_ffill, top_n_list=None):
    """运行多组参数回测并汇总。"""
    if top_n_list is None:
        top_n_list = [10, 20, 30]

    all_results = []
    for top_n in top_n_list:
        print(f"\n--- TOP {top_n} 回测 ---")
        equity_df, trades_df, metrics = backtest(panel, fin_ffill, top_n=top_n)

        summary = {"top_n": top_n}
        summary.update(metrics)
        all_results.append(summary)

        # 保存明细
        top_dir = f"{OUTPUT_DIR}/backtest_top{top_n}"
        Path(top_dir).mkdir(parents=True, exist_ok=True)
        equity_df.to_csv(f"{top_dir}/equity.csv", index=False, encoding="utf-8-sig")
        trades_df.to_csv(f"{top_dir}/trades.csv", index=False, encoding="utf-8-sig")

    # 汇总比较
    summary_df = pd.DataFrame(all_results)
    summary_df.to_csv(f"{OUTPUT_DIR}/backtest_summary.csv",
                      index=False, encoding="utf-8-sig")

    print("\n" + "=" * 60)
    print("多因子选股回测汇总")
    print("=" * 60)
    print(summary_df.to_string(index=False))

    # 生成 HTML 回测报告
    _generate_html_report(summary_df)
    return summary_df


def _generate_html_report(summary_df):
    """生成回测 HTML 报告。"""
    from datetime import datetime
    table = summary_df.to_html(index=False)

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>多因子选股回测报告</title>
<style>
body {{ font-family: 'Microsoft YaHei', sans-serif; margin: 20px; }}
table {{ border-collapse: collapse; font-size: 14px; }}
th, td {{ border: 1px solid #ccc; padding: 6px 12px; text-align: center; }}
th {{ background: #f0f0f0; }}
.positive {{ color: green; }}
.negative {{ color: red; }}
</style>
</head>
<body>
<h1>多因子选股回测报告</h1>
<p>生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
<p>策略: BP(30%) + 反转(25%) + 低波(25%) + ROE(20%)</p>
<p>调仓频率: 月度 | 持仓方式: 等权</p>

<h2>多组参数对比</h2>
{table}

<h2>持仓明细</h2>
<p>详见各子目录:</p>
<ul>
{"".join(f'<li><a href="backtest_top{n}/trades.csv">TOP {n}</a></li>' for n in [10, 20, 30])}
</ul>
</body>
</html>"""
    with open(f"{OUTPUT_DIR}/backtest_report.html", "w", encoding="utf-8") as f:
        f.write(html)


def build_industry_map(basic_df):
    """从基础信息 DataFrame 构建 ts_code -> industry 映射。"""
    mapping = {}
    for _, row in basic_df.iterrows():
        ind = row.get("industry", "")
        if pd.isna(ind) or ind == "":
            ind = "未知"
        mapping[row["ts_code"]] = ind
    return mapping


def compare_industry_neutralize(panel, fin_ffill, basic_df):
    """对比行业中性化前后的回测效果。"""
    industry_map = build_industry_map(basic_df)

    results = []
    for top_n in [10, 20, 30]:
        for neutralize in [False, True]:
            label = f"TOP{top_n} {'+行业中性化' if neutralize else ''}"
            print(f"\n--- {label} ---")
            im = industry_map if neutralize else None
            eq, td, met = backtest(panel, fin_ffill, top_n=top_n,
                                   industry_map=im, max_industry_pct=0.25)
            met["参数"] = label
            results.append(met)

            out = f"{OUTPUT_DIR}/indneu_top{top_n}{'_neutralized' if neutralize else ''}"
            Path(out).mkdir(parents=True, exist_ok=True)
            eq.to_csv(f"{out}/equity.csv", index=False, encoding="utf-8-sig")
            td.to_csv(f"{out}/trades.csv", index=False, encoding="utf-8-sig")

    summary = pd.DataFrame(results)
    summary.to_csv(f"{OUTPUT_DIR}/industry_neutralize_compare.csv",
                   index=False, encoding="utf-8-sig")

    print("\n" + "=" * 70)
    print("行业中性化 - 对比")
    print("=" * 70)
    print(summary.to_string(index=False))

    _gen_indneu_html(summary)
    return summary


def compare_frequencies(panel, fin_ffill, top_n=20):
    """对比不同调仓频率的回测效果。"""
    freqs = [("周频", "W"), ("双周", "2W"), ("月频", "M"), ("双月", "2M"), ("季度", "Q")]
    results = []
    for label, freq in freqs:
        print(f"\n--- {label} ---")
        try:
            eq, td, met = backtest(panel, fin_ffill, top_n=top_n, freq=freq)
            met["参数"] = label
            results.append(met)
        except Exception as e:
            print(f"  [err] {label}: {e}")

    summary = pd.DataFrame(results)
    summary.to_csv(f"{OUTPUT_DIR}/freq_comparison.csv",
                   index=False, encoding="utf-8-sig")

    print("\n" + "=" * 70)
    print("调仓频率对比 (TOP {})".format(top_n))
    print("=" * 70)
    print(summary.to_string(index=False))

    _gen_freq_html(summary)
    return summary


def _gen_freq_html(summary_df):
    from datetime import datetime
    table = summary_df.to_html(index=False)
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>调仓频率对比</title>
<style>
body {{ font-family: 'Microsoft YaHei', sans-serif; margin: 20px; }}
table {{ border-collapse: collapse; font-size: 14px; }}
th, td {{ border: 1px solid #ccc; padding: 6px 12px; text-align: center; }}
th {{ background: #f0f0f0; }}
</style>
</head>
<body>
<h1>调仓频率对比报告</h1>
<p>生成: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
<p>策略: BP(30%)+反转(25%)+低波(25%)+ROE(20%) | TOP 20 等权</p>
{table}
</body>
</html>"""
    with open(f"{OUTPUT_DIR}/freq_comparison.html", "w", encoding="utf-8") as f:
        f.write(html)


def _gen_indneu_html(summary_df):
    from datetime import datetime
    table = summary_df.to_html(index=False)
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>行业中性化对比</title>
<style>
body {{ font-family: 'Microsoft YaHei', sans-serif; margin: 20px; }}
table {{ border-collapse: collapse; font-size: 14px; }}
th, td {{ border: 1px solid #ccc; padding: 6px 12px; text-align: center; }}
th {{ background: #f0f0f0; }}
.better {{ color: green; font-weight: bold; }}
</style>
</head>
<body>
<h1>行业中性化对比报告</h1>
<p>生成: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
<p>策略: BP(30%)+反转(25%)+低波(25%)+ROE(20%) | 月频调仓等权</p>
<p>行业中性化: 单行业 ≤ 25%</p>
{table}
</body>
</html>"""
    with open(f"{OUTPUT_DIR}/industry_neutralize_compare.html", "w", encoding="utf-8") as f:
        f.write(html)
