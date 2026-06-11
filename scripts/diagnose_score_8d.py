#!/usr/bin/env python3
# coding=utf-8
"""
诊断脚本：逐维度拆解8D评分，定位短板。

对 selected.txt 排名最前的股票，用 mootdx 拉800根日K线，
在3个不同市场环境的交易日（2023-05-04上涨日、2024-01-18下跌日、2025-03-10震荡日），
拆开8D评分的每个维度，输出明细CSV并分析短板。

用法:
    cd /mnt/d/QMT_STRATEGIES && python3 scripts/diagnose_score_8d.py 2>&1
"""

import os
import sys
import json
import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.signal_main_rise import ScoreCalculator8D

# ── 配置 ──────────────────────────────────────────────────────────
TARGET_DATES = ['2023-05-04', '2024-01-18', '2025-03-10']
REQ_BARS = 800
TOP_N = 5  # 取前几只股票

# 维度展现顺序（与用户要求的CSV列顺序一致）
DIM_NAMES = ['基本面', '技术面', '资金面', '成长性', '估值', '情绪面', '板块面', '风险面']
DIM_WEIGHTS = {'基本面': 18, '技术面': 18, '资金面': 15, '成长性': 15,
               '估值': 12, '情绪面': 8, '板块面': 7, '风险面': 7}

# 内部 total_score() 返回的 key 与用户命名之间的映射
KEY_MAP = {'基本面': '基本面', '技术面': '技术面', '资金面': '资金面',
           '成长性': '成长面', '估值': '估值面',
           '情绪面': '情绪面', '板块面': '板块面', '风险面': '风险面'}

# ── 工具函数 ──────────────────────────────────────────────────────


def _strip_suffix(code: str) -> str:
    code = code.upper()
    for s in ['.SH', '.SZ', '.BJ']:
        if code.endswith(s):
            return code[:-3]
    return code


def read_pool(path: str) -> list[str]:
    """读取 stock pool，返回6位纯代码列表。"""
    codes = []
    with open(path, encoding='gbk') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            raw = line.split('\t')[0].strip()
            raw = _strip_suffix(raw)
            if raw.isdigit() and len(raw) == 6:
                codes.append(raw)
    return codes


def download_data(stock_codes: list[str], req_bars: int = 800):
    """
    通过 mootdx 下载日K线数据。
    返回 (all_data: {code6: DataFrame}, stock_names: {code6: str})
    """
    from mootdx.quotes import Quotes
    client = Quotes.factory(market='std')

    all_data = {}
    stock_names = {}

    # 批量获取名称
    try:
        for i in range(0, len(stock_codes), 200):
            batch = stock_codes[i:i + 200]
            q = client.quotes(symbol=batch)
            if q is not None and not q.empty:
                for _, row in q.iterrows():
                    if 'code' in q.columns and 'name' in q.columns:
                        c = str(row['code'])
                        n = str(row['name']).strip()
                        if c in stock_codes and n:
                            stock_names[c] = n
    except Exception:
        pass

    for code6 in stock_codes:
        try:
            df = client.bars(symbol=code6, category=4, offset=req_bars)
        except Exception as e:
            print(f"  [下载失败] {code6}: {e}")
            continue

        if df is None or df.empty:
            print(f"  [空数据] {code6}")
            continue

        # 列名统一
        if 'vol' in df.columns and 'volume' not in df.columns:
            df = df.rename(columns={'vol': 'volume'})
        elif 'vol' in df.columns and 'volume' in df.columns:
            df = df.drop(columns=['vol'])

        # 日期解析
        if 'datetime' in df.columns:
            df['_date'] = pd.to_datetime(df['datetime'].str[:10], errors='coerce')
            df.set_index('_date', inplace=True)
            df.drop(columns=['datetime'], inplace=True)
            df.index = df.index.normalize()
        df.sort_index(inplace=True)
        df = df[df.index.notna()]
        df = df[df['close'] > 0]

        if df.empty:
            print(f"  [过滤后空] {code6}")
            continue

        all_data[code6] = df

    return all_data, stock_names


def load_sector_heat():
    """加载板块热度 JSON，用于 板块面 评分。"""
    try:
        path = 'D:/QMT_POOL/sector_heat.json'
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            heat_map = data.get('stock_heat', data) if isinstance(data, dict) else {}
            if heat_map:
                print(f"  [板块] 加载 {len(heat_map)} 只股票的板块热度")
                return heat_map
    except Exception as e:
        print(f"  [板块] 加载失败: {e}")
    return {}


def fetch_index_data(req_bars: int = 800):
    """获取上证指数日K线，用于市场系数计算。"""
    try:
        from mootdx.quotes import Quotes
        client = Quotes.factory(market='std')
        # 上证指数: 代码 000001, 市场 1 (上海)
        df = client.bars(symbol='000001', market=1, category=4, offset=req_bars)
        if df is not None and not df.empty:
            if 'datetime' in df.columns:
                df.index = pd.to_datetime(df['datetime'].str[:10])
                df.drop(columns=['datetime'], inplace=True)
            df.sort_index(inplace=True)
            return df
    except Exception as e:
        print(f"  [指数] 获取上证指数失败: {e}")
    return None


def market_coeff_for_date(index_df, target_date: str):
    """计算指定日期的市场系数。"""
    if index_df is None or target_date not in index_df.index:
        return 1.0
    sub = index_df.loc[:target_date]
    if len(sub) < 60:
        return 1.0
    close = sub['close'].astype(float)
    c = float(close.iloc[-1])
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()
    m20 = float(ma20.iloc[-1]) if not pd.isna(ma20.iloc[-1]) else 0
    m60 = float(ma60.iloc[-1]) if not pd.isna(ma60.iloc[-1]) else 0
    if c > m20 > m60:
        return 1.0
    elif c > m20 or c > m60:
        return 0.85
    else:
        return 0.60


# ── 市场环境标签 ────────────────────────────────────────────────

MARKET_LABELS = {
    '2023-05-04': '上涨日',
    '2024-01-18': '下跌日',
    '2025-03-10': '震荡日',
}

# ── 主流程 ──────────────────────────────────────────────────────


def main():
    POOL_PATH = 'D:/QMT_POOL/selected.txt'

    print("=" * 70)
    print("  8D评分维度诊断")
    print(f"  目标日期:")
    for d, lbl in MARKET_LABELS.items():
        print(f"    {d} ({lbl})")
    print(f"\n  8D权重:")
    for d, w in DIM_WEIGHTS.items():
        print(f"    {d}: {w}%")
    print("=" * 70)

    # ── 1. 读股票池 ──
    print(f"\n[1/4] 读取股票池: {POOL_PATH}")
    stock_codes = read_pool(POOL_PATH)
    if not stock_codes:
        print("  [错误] 股票池为空")
        return 1
    top_codes = stock_codes[:TOP_N]
    print(f"  共 {len(stock_codes)} 只, 取前 {TOP_N} 只: {top_codes}")

    # ── 2. 下载 K 线 ──
    print(f"\n[2/4] 下载日K线 (mootdx, {REQ_BARS}根)")
    all_data, stock_names = download_data(top_codes, REQ_BARS)
    if not all_data:
        print("  [致命] 无任何数据，退出")
        return 1

    valid_codes = sorted(all_data.keys())
    print(f"  成功: {len(valid_codes)}/{len(top_codes)} 只")
    for c in valid_codes:
        df = all_data[c]
        print(f"    {c} {stock_names.get(c, ''):<6}  {df.index[0].strftime('%Y-%m-%d')} ~ {df.index[-1].strftime('%Y-%m-%d')}  ({len(df)}行)")

    # ── 3. 指数数据 + 板块热度 ──
    print(f"\n[3/4] 加载辅助数据")
    index_df = fetch_index_data(REQ_BARS)
    if index_df is not None:
        print(f"  上证指数: {index_df.index[0].strftime('%Y-%m-%d')} ~ {index_df.index[-1].strftime('%Y-%m-%d')}")
    else:
        print("  上证指数: 获取失败 (市场系数将默认 1.0)")

    sector_bonus = load_sector_heat()

    # ── 4. 初始化评分器 ──
    scorer = ScoreCalculator8D()
    if sector_bonus:
        scorer.update_sector_bonus(sector_bonus)

    # ── 5. 逐股票 × 日期 计算 8D ──
    print(f"\n[4/4] 计算 8D 评分明细")
    results = []

    for code6 in valid_codes:
        df = all_data[code6]
        name = stock_names.get(code6, code6)

        print(f"\n  ── {code6} ({name}) ──")

        for target_date in TARGET_DATES:
            date_match = df.index[df.index.strftime('%Y-%m-%d') == target_date]
            if len(date_match) == 0:
                print(f"    {target_date} ({MARKET_LABELS.get(target_date, '?')}): 无数据 (停牌/未上市)")
                results.append({'stock_code': code6, 'date': target_date,
                                **{d: None for d in DIM_NAMES}, '总分': None,
                                '市场系数': None, '最终总分': None})
                continue

            bar_idx = df.index.get_loc(date_match[0])
            sub = df.iloc[:bar_idx + 1].copy()

            if len(sub) < 60:
                print(f"    {target_date} ({MARKET_LABELS.get(target_date, '?')}): 数据不足 {len(sub)}/<60")
                results.append({'stock_code': code6, 'date': target_date,
                                **{d: None for d in DIM_NAMES}, '总分': None,
                                '市场系数': None, '最终总分': None})
                continue

            # 市场系数
            coeff = market_coeff_for_date(index_df, target_date)

            # 调用 total_score
            r = scorer.total_score(df=sub, stock_code=code6,
                                   index_close=(
                                       float(index_df.loc[target_date, 'close'])
                                       if index_df is not None and target_date in index_df.index else None),
                                   index_ma20=None, index_ma60=None)

            # 提取各维度得分（映射为用户命名）
            s = {}
            for user_key, internal_key in KEY_MAP.items():
                s[user_key] = r.get(internal_key, 0.0)

            total = r.get('raw_total', 0.0)

            results.append({
                'stock_code': code6, 'date': target_date,
                **s, '总分': total,
                '市场系数': coeff, '最终总分': round(total * coeff, 2),
            })

            # 打印明细
            parts = ' | '.join(f"{k}={v:.1f}" for k, v in s.items())
            market_tag = MARKET_LABELS.get(target_date, '?')
            print(f"    {target_date} [{market_tag}]  ∑={total:.1f}  ×{coeff:.2f}={total*coeff:.1f}")
            print(f"      {parts}")

    # ── 6. 输出 CSV ──
    print(f"\n{'=' * 70}")
    print("  CSV 输出")
    print(f"{'=' * 70}")

    csv_dir = os.path.join(PROJECT_ROOT, 'data')
    os.makedirs(csv_dir, exist_ok=True)
    csv_path = os.path.join(csv_dir, 'diagnose_8d_scores.csv')

    cols = ['stock_code', 'date'] + DIM_NAMES + ['总分', '市场系数', '最终总分']
    rows_out = []
    for r in results:
        row = [r['stock_code'], r['date']]
        for d in DIM_NAMES:
            v = r.get(d)
            row.append(f"{v:.2f}" if v is not None else 'N/A')
        total = r.get('总分')
        row.append(f"{total:.2f}" if total is not None else 'N/A')
        coeff = r.get('市场系数')
        row.append(f"{coeff:.2f}" if coeff is not None else 'N/A')
        ft = r.get('最终总分')
        row.append(f"{ft:.2f}" if ft is not None else 'N/A')
        rows_out.append(row)

    out_df = pd.DataFrame(rows_out, columns=cols)
    out_df.to_csv(csv_path, index=False, encoding='utf-8-sig')
    print(f"\n  保存: {csv_path}\n")
    print(out_df.to_string(index=False))

    # ── 7. 维度分析 ──
    print(f"\n{'=' * 70}")
    print("  维度分析")
    print(f"{'=' * 70}")

    # 收集有效得分
    dim_scores = {d: [] for d in DIM_NAMES}
    valid_rows = 0
    for r in results:
        if all(r.get(d) is not None for d in DIM_NAMES):
            valid_rows += 1
            for d in DIM_NAMES:
                dim_scores[d].append(r[d])

    if valid_rows == 0:
        print("\n  无有效数据，无法分析")
        return 1

    dim_avg = {d: float(np.mean(v)) for d, v in dim_scores.items() if v}
    total_avg = sum(dim_avg.values())

    print(f"\n  统计: {valid_rows} 条有效记录 (股票×日期)")
    print(f"  {'维度':<6} {'权重':>5} {'平均':>7} {'得分率':>7} {'占比':>7}  {'贡献'}")
    print(f"  {'─' * 50}")
    for d in DIM_NAMES:
        avg = dim_avg.get(d, 0)
        w = DIM_WEIGHTS.get(d, 0)
        rate = avg / w * 100 if w > 0 else 0
        pct = avg / total_avg * 100 if total_avg > 0 else 0
        bar = '█' * max(1, min(int(rate / 5), 20))
        gap = w - avg  # 与满分的差距
        print(f"  {d:<6} {w:>5}% {avg:>7.2f} {rate:>6.1f}% {pct:>6.1f}%  {bar}  缺口{gap:.1f}")

    # 识别短板
    sorted_dim = sorted(dim_avg.items(), key=lambda x: x[1])
    sorted_by_rate = sorted(dim_avg.items(), key=lambda x: x[1] / DIM_WEIGHTS.get(x[0], 1))

    print(f"\n  {'=' * 50}")
    print(f"  短板排名 (按得分率从低到高):")
    print(f"  {'=' * 50}")
    for rank, (d, v) in enumerate(sorted_by_rate, 1):
        w = DIM_WEIGHTS.get(d, 0)
        rate = v / w * 100 if w > 0 else 0
        print(f"    {rank}. {d:<6}  {v:.2f}/{w}  ({rate:.1f}%)")

    lowest_name = sorted_by_rate[0][0]
    lowest_val = sorted_by_rate[0][1]
    lowest_weight = DIM_WEIGHTS.get(lowest_name, 0)
    lowest_rate = lowest_val / lowest_weight * 100 if lowest_weight > 0 else 0

    second_name = sorted_by_rate[1][0]
    second_val = sorted_by_rate[1][1]
    second_weight = DIM_WEIGHTS.get(second_name, 0)
    second_rate = second_val / second_weight * 100 if second_weight > 0 else 0

    print(f"\n  {'=' * 50}")
    print(f"  结论")
    print(f"  {'=' * 50}")
    print(f"\n  平均总分(原始): {total_avg:.2f}/100 (不含市场系数)")
    print(f"\n  最低分维度: {lowest_name} ({lowest_val:.2f}/{lowest_weight}, 得分率{lowest_rate:.1f}%)")

    # 拉低主因分析
    def dim_analysis(dim_name):
        analyses = {
            '基本面': [
                "无 QMT 实时财务数据 → 默认中位分 9.0/18",
                "ROE、毛利率、净利润、负债率 四项子维度均未参与计算",
                "若实盘接入财务数据，基本面有望提升至 12~16 分",
            ],
            '技术面': [
                "核心门槛: MA5 > MA10 > MA20 > MA60 多头排列 (占 6 分)",
                "MACD 金叉 + RSI(40~80) + KDJ 多头 + 60日位置 + 乖离率",
                f"买点信号 bonus 因 check_buy() 未导入跳过 (损失至多 6 分)",
                "MA60 走平/向上是最大瓶颈 — 下跌日 MA60 大概率下行",
            ],
            '资金面': [
                "量比 VR 钟形映射: VR=1.0~2.0 得分最高, <0.5 或 >3.0 扣分",
                "涨幅钟形: 理想 3% 附近, 下跌日涨幅为负 → 得分极低",
                "下跌日资金面大幅拖累总分",
            ],
            '成长性': [
                "无 QMT 财务数据 → 净利润规模项不可用 (损失 6~10 分)",
                "仅量比参与评分 (满分 5), 实际得分约 2~3",
                "默认中位分约 7/15, 下跌日量比不足进一步压低",
            ],
            '估值': [
                "PE 钟形(理想15) + PB钟形(理想1.5) + 市值钟形(理想80亿)",
                "腾讯接口获取当前 PE/PB, 非历史同期值",
                "若股票 PE 偏高或 PB 偏低, 估值分天然承压",
            ],
            '情绪面': [
                "涨幅钟形 + 振幅钟形 + 量比钟形 — 三个钟形叠加",
                "下跌日/震荡日涨幅小、振幅窄、量能萎缩 → 三杀",
                "满分 8 分, 弱势市场通常仅 2~4 分",
            ],
            '板块面': [
                "量比钟形(中心1.8) + 振幅钟形(中心4%) + 涨幅强度",
                "有板块热度数据时最多 +2, 无数据时固定 +1",
                "板块面权重低(7%), 对总分影响有限",
            ],
            '风险面': [
                "初始 10 分扣减, 上限 7 分 (减 3 分基准)",
                "振幅>3%扣分 + 缩量<70%扣分 + 高位>70%扣分 + 高乖离扣分",
                "下跌日往往振幅大、缩量 → 风险分较低",
                "风险面天然是扣分项, 高分(>5)说明风险很低",
            ],
        }
        return analyses.get(dim_name, [])

    print(f"\n  拉低主因 ({lowest_name}):")
    for line in dim_analysis(lowest_name):
        print(f"    - {line}")

    if second_rate < 50:
        print(f"\n  次要短板 ({second_name}, 得分率{second_rate:.1f}%):")
        for line in dim_analysis(second_name):
            print(f"    - {line}")

    # 市场环境对比
    print(f"\n  {'=' * 50}")
    print(f"  分市场环境平均分:")
    print(f"  {'=' * 50}")
    for target_date in TARGET_DATES:
        date_results = [r for r in results if r['date'] == target_date and r.get('总分') is not None]
        if not date_results:
            continue
        date_avg = np.mean([r['总分'] for r in date_results])
        date_dim_avg = {}
        for d in DIM_NAMES:
            vals = [r[d] for r in date_results if r.get(d) is not None]
            date_dim_avg[d] = float(np.mean(vals)) if vals else 0
        market_tag = MARKET_LABELS.get(target_date, '?')
        parts = ' | '.join(f"{d}={v:.1f}" for d, v in date_dim_avg.items())
        print(f"\n    {target_date} [{market_tag}]  总分均={date_avg:.1f}")
        print(f"      {parts}")

    # 最终建议
    print(f"\n  {'=' * 50}")
    print(f"  改进建议")
    print(f"  {'=' * 50}")
    low_dims = [d for d, v in sorted_by_rate[:3]]
    suggestions = {
        '基本面': "接入 QMT get_financial_data() 或定期从财报导入 ROE/毛利率/净利润",
        '技术面': "等待 MA60 走平/向上时入场; 实现 check_buy() 函数获取买点 bonus",
        '资金面': "选择量比 > 1.0 且涨幅 2~4% 的交易日介入",
        '成长性': "接入财务数据让净利润规模项生效",
        '估值': "关注 PE 15 倍附近、PB 1.5 倍附近的标的",
        '情绪面': "弱势市场情绪面天然承压, 非选股因素",
        '板块面': "确保 sector_heat.json 每日更新以获取板块共振加分",
        '风险面': "避免振幅 > 3%、缩量 < 70%、60日高位 > 70% 的标的",
    }
    for d in low_dims:
        tip = suggestions.get(d, "")
        if tip:
            print(f"    [{d}] {tip}")

    print(f"\n{'=' * 70}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
