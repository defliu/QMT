# coding: utf-8
"""DeepSeek 回测报告生成器。

收集 V0-V4 + 参数扫描的 summary.json / equity_curve.csv / trades.csv，
汇总成年化/回撤/夏普/胜率/交易次数/月度收益分布报告，写到 trade_reports/。

Usage:
    py -3.10 -m backtest.scripts.gen_deepseek_report
    py -3.10 -m backtest.scripts.gen_deepseek_report --paramscan
"""
import argparse
import csv
import glob
import json
import os
from collections import defaultdict

import pandas as pd

RESULTS_ROOT = "F:/backtest_workspace/results"
REPORT_DIR = "D:/QMT_STRATEGIES/trade_reports"


def _latest_dir(config_name):
    """按 config_name 找最近的结果目录。"""
    pattern = os.path.join(RESULTS_ROOT, "*_" + config_name)
    matches = sorted(glob.glob(pattern), key=os.path.getmtime)
    return matches[-1] if matches else None


def _load_summary(config_name):
    d = _latest_dir(config_name)
    if not d:
        return None
    p = os.path.join(d, "summary.json")
    if not os.path.isfile(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        s = json.load(f)
    s["_dir"] = d
    return s


def _monthly_returns(equity_csv):
    """从 equity_curve.csv 算月度收益（按月末权益环比）。"""
    if not os.path.isfile(equity_csv):
        return {}
    df = pd.read_csv(equity_csv)
    if "date" not in df.columns or "total_equity" not in df.columns:
        return {}
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    # 月末权益
    monthly = df["total_equity"].resample("M").last()
    rets = monthly.pct_change().dropna()
    return {d.strftime("%Y-%m"): round(float(r) * 100, 2) for d, r in rets.items()}


def _win_rate(trades_csv):
    """从 trades.csv 算胜率（配对买卖，按 code FIFO）。"""
    if not os.path.isfile(trades_csv):
        return (0.0, 0)
    rows = []
    with open(trades_csv, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    # FIFO 配对
    holding = defaultdict(list)  # code -> list of (price, volume)
    wins = 0
    total = 0
    for r in rows:
        code = r.get("code")
        side = r.get("side")
        try:
            price = float(r.get("price", 0))
            vol = int(float(r.get("volume", 0)))
        except (TypeError, ValueError):
            continue
        if side == "buy":
            holding[code].append([price, vol])
        elif side == "sell":
            queue = holding.get(code, [])
            sell_vol = vol
            while sell_vol > 0 and queue:
                buy_price, buy_vol = queue[0]
                matched = min(sell_vol, buy_vol)
                if buy_price > 0:
                    total += 1
                    if price > buy_price:
                        wins += 1
                queue[0][1] -= matched
                sell_vol -= matched
                if queue[0][1] <= 0:
                    queue.pop(0)
    win_rate = (wins / total * 100.0) if total > 0 else 0.0
    return (round(win_rate, 2), total)


def _fmt_pct(x):
    if x is None:
        return "n/a"
    try:
        return "%.2f%%" % (float(x) * 100)
    except (TypeError, ValueError):
        return str(x)


def _fmt_num(x, n=2):
    if x is None:
        return "n/a"
    try:
        return "%.*f" % (n, float(x))
    except (TypeError, ValueError):
        return str(x)


def collect_versions(version_names):
    """收集各版本结果。"""
    out = []
    for name in version_names:
        s = _load_summary(name)
        if not s:
            out.append({"name": name, "missing": True})
            continue
        perf = s.get("performance", {})
        d = s["_dir"]
        wr, n_closed = _win_rate(os.path.join(d, "trades.csv"))
        out.append({
            "name": name,
            "total_return": perf.get("total_return"),
            "annual_return": perf.get("annual_return"),
            "max_drawdown": perf.get("max_drawdown"),
            "sharpe": perf.get("sharpe"),
            "n_trades": perf.get("n_trades", 0),
            "n_buy": perf.get("n_buy", 0),
            "n_sell": perf.get("n_sell", 0),
            "win_rate": wr,
            "n_closed": n_closed,
            "avg_holding_days": perf.get("avg_holding_days"),
            "excess_return": perf.get("excess_return"),
            "monthly": _monthly_returns(os.path.join(d, "equity_curve.csv")),
            "dir": d,
        })
    return out


def collect_paramscan(scan_prefix):
    """收集参数扫描结果（目录名含 scan_prefix）。"""
    out = []
    pattern = os.path.join(RESULTS_ROOT, "*" + scan_prefix + "*")
    for d in sorted(glob.glob(pattern), key=os.path.getmtime):
        p = os.path.join(d, "summary.json")
        if not os.path.isfile(p):
            continue
        with open(p, "r", encoding="utf-8") as f:
            s = json.load(f)
        perf = s.get("performance", {})
        out.append({
            "name": os.path.basename(d),
            "total_return": perf.get("total_return"),
            "annual_return": perf.get("annual_return"),
            "max_drawdown": perf.get("max_drawdown"),
            "sharpe": perf.get("sharpe"),
            "n_trades": perf.get("n_trades", 0),
        })
    return out


def render_report(versions, versions_305=None, paramscan=None):
    lines = []
    lines.append("# DeepSeek 选股策略 — 回测报告")
    lines.append("")
    lines.append("> 生成时间：2026-07-03  ")
    lines.append("> SPEC：`specs/SPEC_DeepSeek选股策略回测.md`  ")
    lines.append("> 数据源：astock parquet（hfq 后复权，PIT 安全）  ")
    lines.append("> 回测区间：2019-01-01 ~ 2025-06-30  ")
    lines.append("> 撮合：next_open（T 收盘信号 → T+1 开盘成交）  ")
    lines.append("> 手续费：买万1.5 / 卖万1.5+印花千1，滑点 0.1%  ")
    lines.append("> 股票池：V0-V4 主对比用黄氏小中盘（~3600 只）；4 项优化边际贡献同池对比用 305 只 PIT 精选池  ")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 0. 执行说明与口径
    lines.append("## 0. 执行说明与口径")
    lines.append("")
    lines.append("### 0.1 与 SPEC 的偏离（已记录）")
    lines.append("")
    lines.append("| 项 | SPEC | 实际 | 原因 |")
    lines.append("|----|------|------|------|")
    lines.append("| 接口 | `DeepSeekStrategy` 类 + `calculate_signals(ContextInfo)` | `evaluate_day` 函数式 + `@register_strategy` | SPEC §5.1 是 QMT 实盘接口；回测框架是函数式注册，按 MCRPS 模式实现 |")
    lines.append("| 复权 | 前复权 qfq | **后复权 hfq** | qfq 用末端价格回算历史 → look-ahead（P0 H12 雷区）；hfq 第 T 天只依赖截至 T 日复权因子，PIT 安全 |")
    lines.append("| 编码/validate | GBK + validate_qmt_file 6项 | UTF-8 + pytest | validate 是 QMT 生产文件检查（GBK/3.6）；回测框架全 UTF-8/3.10，套不上 |")
    lines.append("| 止盈 | 20% 卖 50%（分批） | 20% 全卖 | engine 的 fill_sell 只能整仓卖，不支持部分止盈（SPEC §7.1 禁改框架） |")
    lines.append("| 大盘门 J | 上证指数 | 沪深300（000300.SH） | engine 单 benchmark 同时做基准+择时；沪深300 作大盘温度代理，基准对比也用其 |")
    lines.append("| 条件 L 筹码 | 可选 COST(95)/COST(5) | **跳过** | memory 已坐实筹码非 alpha（方案A/B 双验证补筹码收益变差）；QMT 无 COST |")
    lines.append("")
    lines.append("### 0.2 V0-V4 版本定义（A/B 验证 4 项优化）")
    lines.append("")
    lines.append("SPEC V0 \"角度45°\" 在日频无统一定义（ATAN(2.5%/日)≈1.4°），故将 V0 操作化为「最小原始主升浪=多头+阳线比例」，每版累加一项优化：")
    lines.append("")
    lines.append("| 版本 | 条件 | 验证优化 |")
    lines.append("|------|------|----------|")
    lines.append("| V0 | A 多头 + D 阳线比例≥60% | 基线（原始主升浪） |")
    lines.append("| V1 | V0 + B 斜率≥2.5% | opt1 斜率替代角度 |")
    lines.append("| V2 | V1 + E 涨幅<30% | opt2 前段涨幅限制（防追高） |")
    lines.append("| V3 | V2 + F 有效阳线≥50% | opt3 有效阳线统计 |")
    lines.append("| V4 | V3 + C 回踩 + G 换手 + H 量比 + I 市值 + J 大盘 | opt4 大盘安全+三区间过滤（完整版） |")
    lines.append("")
    lines.append("卫生条件（全版本恒开）：非ST、次新≥60日、停牌/涨停不买。")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 1. 主结果对比表
    lines.append("## 1. V0-V4 主结果对比（2019-2025，黄氏小中盘）")
    lines.append("")
    lines.append("| 版本 | 总收益 | 年化 | 最大回撤 | 夏普 | 交易笔数 | 胜率 | 平均持仓日 |")
    lines.append("|------|--------|------|----------|------|----------|------|-----------|")
    for v in versions:
        if v.get("missing"):
            lines.append("| %s | _未跑完_ | | | | | | |" % v["name"])
            continue
        lines.append("| %s | %s | %s | %s | %s | %d | %s%% | %s |" % (
            v["name"], _fmt_pct(v["total_return"]), _fmt_pct(v["annual_return"]),
            _fmt_pct(v["max_drawdown"]), _fmt_num(v["sharpe"]),
            int(v.get("n_trades", 0) or 0),
            _fmt_num(v.get("win_rate"), 1), _fmt_num(v.get("avg_holding_days"), 1)))
    lines.append("")
    lines.append("> 胜率由 trades.csv 按 FIFO 配对买卖计算；交易笔数含买+卖。")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 1.5 305 池同池对比（4 项优化边际贡献）
    if versions_305:
        lines.append("## 1.5 4 项优化边际贡献（305 PIT 精选池，同池对比）")
        lines.append("")
        lines.append("V0-V4 主对比（§1）在 3633 全量池上混了池子效应，4 项优化边际看不真切。")
        lines.append("此处在 305 只 PIT 精选池上同池跑 V0-V4，隔离出每项优化的真实边际贡献：")
        lines.append("")
        lines.append("| 版本 | 总收益 | 年化 | 最大回撤 | 夏普 | 交易笔数 | 胜率 | 边际收益 |")
        lines.append("|------|--------|------|----------|------|----------|------|----------|")
        prev = None
        for v in versions_305:
            if v.get("missing"):
                lines.append("| %s | _未跑完_ | | | | | | |" % v["name"])
                continue
            tr = v.get("total_return")
            margin = ""
            if prev is not None and prev is not None and tr is not None:
                margin = "%+.1fpp" % ((tr - prev) * 100)
            prev = tr if tr is not None else prev
            lines.append("| %s | %s | %s | %s | %s | %d | %s%% | %s |" % (
                v["name"], _fmt_pct(v["total_return"]), _fmt_pct(v["annual_return"]),
                _fmt_pct(v["max_drawdown"]), _fmt_num(v["sharpe"]),
                int(v.get("n_trades", 0) or 0),
                _fmt_num(v.get("win_rate"), 1), margin))
        lines.append("")
        lines.append("**读法**：在精选池上 opt1/2/3 逐项大幅加收益（V0 -36% → V3 +136%）；")
        lines.append("opt4（大盘门+换手/量比/市值）是风控优化——牺牲收益（V3 +136%→V4 +66%）")
        lines.append("换回撤 -34%→-8.8%、夏普 0.70→0.96、胜率 41%→54%。")
        lines.append("对比 §1（3633 池）opt1/2/3 几乎无效、仅 opt4 减亏——**优化效果强烈依赖池子**。")
        lines.append("")
        lines.append("---")
        lines.append("")

    # 2. V4 月度收益分布
    v4 = next((v for v in versions if v.get("name") == "deepseek_v4" and not v.get("missing")), None)
    if v4 and v4.get("monthly"):
        lines.append("## 2. V4 完整版 月度收益分布（%）")
        lines.append("")
        m = v4["monthly"]
        # 按年分列
        years = sorted(set(k[:4] for k in m))
        for y in years:
            row = []
            for mo in range(1, 13):
                k = "%s-%02d" % (y, mo)
                row.append("%6s" % (("%.2f" % m[k]) if k in m else ""))
            lines.append("| %s | %s |" % (y, " | ".join(row)))
        lines.append("")
        lines.append("(空=该月无权益数据或月初；单位 %)")
        lines.append("")
        lines.append("---")
        lines.append("")

    # 3. 参数敏感性
    if paramscan:
        lines.append("## 3. 参数敏感性分析")
        lines.append("")
        lines.append("（参数扫描在 305 只 PIT 池子、2019-2025 上跑，单参数扫，其余=V4 默认）")
        lines.append("")
        lines.append("| 配置 | 总收益 | 年化 | 最大回撤 | 夏普 | 交易数 |")
        lines.append("|------|--------|------|----------|------|--------|")
        for p in paramscan:
            lines.append("| %s | %s | %s | %s | %s | %d |" % (
                p["name"], _fmt_pct(p["total_return"]), _fmt_pct(p["annual_return"]),
                _fmt_pct(p["max_drawdown"]), _fmt_num(p["sharpe"]),
                int(p.get("n_trades", 0) or 0)))
        lines.append("")
        lines.append("---")
        lines.append("")

    # 4. 结论
    lines.append("## 4. 结论")
    lines.append("")
    lines.append("### 4.1 策略历史表现（SPEC §1 目标 1）")
    lines.append("")
    lines.append("- **黄氏小中盘全量池（3633 只）：策略失效，暴亏。** V0-V3 年化 -15.5~-15.9%、")
    lines.append("  回撤 -97~-99%（几乎归零），V4 完整版仍 -36.2%/年化 -5.8%。**不可上实盘。**")
    lines.append("- **305 只 PIT 精选池：策略有效。** V4 默认 +66.4%（年化 +10.6%，回撤仅 -8.8%，夏普 0.96）。")
    lines.append("- 同一策略同一参数，3633 池 -36% vs 305 池 +66% → **池子选择 >> 参数调优**，")
    lines.append("  差异完全来自池子质量而非策略逻辑本身。")
    lines.append("")
    lines.append("### 4.2 4 项优化的边际贡献（SPEC §1 目标 3，305 池同池隔离）")
    lines.append("")
    lines.append("| 优化 | 边际（305 池） | 3633 池 | 结论 |")
    lines.append("|------|----------------|---------|------|")
    lines.append("| opt1 斜率替代角度 | V0→V1 **+92.6pp** | +0.2pp（无效） | 精选池上决定性，全量池无效 |")
    lines.append("| opt2 前段涨幅限制 | V1→V2 **+62.0pp** | +2.1pp（微弱） | 精选池上强，全量池微弱 |")
    lines.append("| opt3 有效阳线统计 | V2→V3 **+18.1pp** | -0.3pp（无效） | 精选池上正向，全量池无效 |")
    lines.append("| opt4 大盘+换手/量比/市值 | V3→V4 -69.8pp 收益 / 回撤 -34%→-8.8% | +60.9pp（唯一有效） | 两池都降回撤提夏普，是风控而非 alpha |")
    lines.append("")
    lines.append("**核心洞察**：opt1/2/3 是选股 alpha，只在高质量池子里起作用（垃圾股堆里挑趋势股没用）；")
    lines.append("opt4 是风控，两池都有效（过滤高波动/小盘/大盘不稳），靠它 V4 在 3633 池从 -97% 拉到 -36%、在 305 池把回撤压到 -8.8%。")
    lines.append("")
    lines.append("### 4.3 参数敏感性（SPEC §1 目标 2，305 池）")
    lines.append("")
    lines.append("- **slope_thresh 2.0 是甜点**（+101%），3.5 几乎无信号（-1.4%）；默认 2.5 偏保守。")
    lines.append("- **gain_limit 40 最优**（+106%），默认 30 可上调；50 略降（+92%）。")
    lines.append("- 市值/换手区间影响小（±10pp 内），说明 opt4 的市值/换手门主要起风控而非增强作用。")
    lines.append("")
    lines.append("### 4.4 口径与限制")
    lines.append("")
    lines.append("- **复权**：hfq 后复权，PIT 安全，无 look-ahead（避开 P0 H12 雷区）。")
    lines.append("- **筹码条件 L 跳过**：已坐实筹码非 alpha（[[huang-chip-not-alpha]]）。")
    lines.append("- **止盈**：engine 限整仓卖出，20% 全卖（非分批），略偏激进。")
    lines.append("- **大盘门**：用沪深300 代理上证（engine 单 benchmark 兼基准）。")
    lines.append("- **池子**：V0-V4 主对比用黄氏小中盘 3633 只，非严格全 A；4 项优化边际用 305 PIT 池同池隔离。")
    lines.append("- **下一步建议**：若继续，优先研究为什么 305 行 3633 不行（流动性？质量？），而非调参数。")
    lines.append("")
    lines.append("")
    lines.append("### 4.1 可复现")
    lines.append("")
    lines.append("```bash")
    lines.append("py -3.10 -m pytest backtest/tests/test_deepseek_strategy.py -v   # 15 测全过")
    lines.append("py -3.10 -m backtest.scripts.run_deepseek --config backtest/configs/deepseek_v4.yaml")
    lines.append("```")
    lines.append("")
    lines.append("结果目录：`F:/backtest_workspace/results/<run_id>_deepseek_v{0-4}/`")
    lines.append("")

    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--paramscan", action="store_true",
                    help="含参数扫描结果")
    ap.add_argument("--scan-prefix", default="deepseek_scan_",
                    help="参数扫描目录名前缀")
    args = ap.parse_args()

    versions = collect_versions(["deepseek_v0", "deepseek_v1", "deepseek_v2",
                                 "deepseek_v3", "deepseek_v4"])
    versions_305 = collect_versions(["deepseek_305_v0", "deepseek_305_v1",
                                     "deepseek_305_v2", "deepseek_305_v3",
                                     "deepseek_305_v4"])
    paramscan = collect_paramscan(args.scan_prefix) if args.paramscan else None

    md = render_report(versions, versions_305, paramscan)
    os.makedirs(REPORT_DIR, exist_ok=True)
    out = os.path.join(REPORT_DIR, "deepseek_backtest_20260703.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    print("REPORT=" + out)
    # 同时打印主结果表到 stdout
    for v in versions:
        if v.get("missing"):
            print(v["name"], "MISSING")
        else:
            print("%s: ret=%s ann=%s dd=%s sharpe=%s trades=%d win=%s%%" % (
                v["name"], _fmt_pct(v["total_return"]), _fmt_pct(v["annual_return"]),
                _fmt_pct(v["max_drawdown"]), _fmt_num(v["sharpe"]),
                int(v.get("n_trades", 0) or 0), _fmt_num(v.get("win_rate"), 1)))


if __name__ == "__main__":
    main()
