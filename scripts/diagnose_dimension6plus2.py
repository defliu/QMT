#!/usr/bin/env python3
# coding=utf-8
"""
诊断脚本: 6+2评分器 — 对池内股票打分并排序。

数据源: mootdx (通达信TCP)。
输出:   控制台排名表 + CSV (data/diagnose_6plus2_scores.csv)

用法:
    cd D:/QMT_STRATEGIES
    python scripts/diagnose_dimension6plus2.py
"""

import os
import sys
import json
import warnings

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
import numpy as np
from core.scoring.dimension6plus2 import ScoreCalculator6Plus2

# ── 配置 ──────────────────────────────────────────────────────
REQ_BARS = 150
DEFAULT_POOL = "D:/QMT_POOL/selected.txt"
SECTOR_HEAT_PATH = "D:/QMT_POOL/sector_heat.json"


# ── 工具函数 ──────────────────────────────────────────────────


def _strip_suffix(code: str) -> str:
    """移除股票代码后缀 .SH/.SZ/.BJ，返回纯6位代码。"""
    code = code.upper()
    for s in ['.SH', '.SZ', '.BJ']:
        if code.endswith(s):
            return code[:-3]
    return code


def _add_suffix(code6: str) -> str:
    """为6位纯代码添加交易所后缀。"""
    code6 = code6.strip().zfill(6)
    if code6.startswith(('6', '9')):
        return code6 + '.SH'
    else:
        return code6 + '.SZ'


def read_pool(path: str) -> list[str]:
    """读取股票池，返回6位纯代码列表。池文件不存在时返回空列表。"""
    if not os.path.isfile(path):
        print(f"  [WARN] 池文件不存在: {path}")
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
        print(f"  [ERROR] 读取池文件失败: {e}")
        return []
    return codes


def download_data(stock_codes: list[str], req_bars: int = 150):
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
        pass  # 名称非关键，静默跳过

    total = len(stock_codes)
    for idx, code6 in enumerate(stock_codes):
        try:
            bars = client.bars(symbol=code6, category=4, offset=req_bars)
            if bars is None or bars.empty:
                print(f"  SKIP {code6}: no data")
                continue

            # 列名统一 (vol → volume)
            if 'vol' in bars.columns and 'volume' not in bars.columns:
                bars = bars.rename(columns={'vol': 'volume'})
            elif 'vol' in bars.columns and 'volume' in bars.columns:
                bars = bars.drop(columns=['vol'])

            # 日期索引
            if 'datetime' in bars.columns:
                bars['_date'] = pd.to_datetime(bars['datetime'].str[:10], errors='coerce')
                bars.set_index('_date', inplace=True)
                bars.drop(columns=['datetime'], inplace=True)
            bars.sort_index(inplace=True)
            bars = bars[bars.index.notna()]
            bars = bars[bars['close'] > 0]

            needed = ['open', 'high', 'low', 'close', 'volume']
            if not all(c in bars.columns for c in needed):
                print(f"  SKIP {code6}: missing columns")
                continue

            df = bars[needed].dropna()
            if len(df) >= 30:
                all_data[code6] = df
                if (idx + 1) % 10 == 0:
                    print(f"  [{idx+1}/{total}] 已下载 {len(all_data)} 只...")
            else:
                print(f"  SKIP {code6}: only {len(df)} bars (<30)")

        except Exception as e:
            print(f"  SKIP {code6}: {e}")

    return all_data, stock_names


def load_sector_heat() -> dict:
    """加载板块热度 JSON。不存在时返回空 dict。"""
    try:
        if os.path.exists(SECTOR_HEAT_PATH):
            with open(SECTOR_HEAT_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            heat_map = data.get('stock_heat', data) if isinstance(data, dict) else {}
            if isinstance(heat_map, dict) and heat_map:
                print(f"  [板块] 加载 {len(heat_map)} 只股票的板块热度")
                return heat_map
    except Exception as e:
        print(f"  [板块] 加载失败: {e}")
    return {}


# ── 主流程 ──────────────────────────────────────────────────


def main():
    sector_heat = load_sector_heat()
    scorer = ScoreCalculator6Plus2(sector_heat_path=SECTOR_HEAT_PATH)

    print("=" * 70)
    print("  6+2 评分诊断")
    print(f"  池文件: {DEFAULT_POOL}")
    print(f"  板块热度: {'有' if sector_heat else '无(默认3.5分)'}")
    print("=" * 70)

    # ── 1. 读股票池 ──
    codes6 = read_pool(DEFAULT_POOL)
    if not codes6:
        print("\n  [WARN] 池为空或无法读取。使用示例股票演示。")
        codes6 = ["600519", "000858", "601318", "600036", "000333"]
        print(f"  使用示例股票: {codes6}")

    # ── 2. 下载 K 线 ──
    print(f"\n下载 {len(codes6)} 只股票数据 (mootdx, {REQ_BARS}根)...")
    all_data, stock_names = download_data(codes6, REQ_BARS)

    if not all_data:
        print("\n[ERROR] 无有效数据，退出。")
        return 1

    print(f"\n成功获取 {len(all_data)} 只股票数据。")

    # ── 3. 评分 ──
    print(f"评分 {len(all_data)} 只股票...")
    rows = []
    for code6, df in all_data.items():
        try:
            code_with_suffix = _add_suffix(code6)
            rec = scorer.score_single(code_with_suffix, df,
                                       dynamic_pe=20.0, static_pe=25.0)
            rows.append({
                "stock_code": code_with_suffix,
                "name": stock_names.get(code6, ""),
                "score_breakout": rec["score_breakout"],
                "score_trend": rec["score_trend"],
                "score_consolidation": rec["score_consolidation"],
                "score_volumeprice": rec["score_volumeprice"],
                "score_macd": rec["score_macd"],
                "score_valuation": rec["score_valuation"],
                "score_sentiment": rec["score_sentiment"],
                "score_sector": rec["score_sector"],
                "score_total": rec["score_total"],
            })
        except Exception as e:
            print(f"  ERROR {code6}: {e}")

    if not rows:
        print("\n无评分结果。")
        return 1

    result = pd.DataFrame(rows).sort_values("score_total", ascending=False)
    result = result.reset_index(drop=True)
    result.index = result.index + 1  # 1-based rank

    # ── 4. 打印排名表 ──
    print("\n" + "=" * 100)
    header = (f"{'排':>3} | {'代码':>9} | {'名称':<6} | "
              f"{'突破':>5}(22) | {'趋势':>5}(13) | {'整合':>5}(20) | "
              f"{'量价':>5}(12) | {'MACD':>5}(12) | {'估值':>5}(7) | "
              f"{'情绪':>5}(7) | {'板块':>5}(7) | {'总分':>6}(100)")
    print(header)
    print("-" * 100)
    for rank, row in result.iterrows():
        name = row.get('name', '')[:6]
        print(f"{rank:>3} | {row['stock_code']:>9} | {name:<6} | "
              f"{row['score_breakout']:>5.0f} | {row['score_trend']:>5.0f} | "
              f"{row['score_consolidation']:>5.0f} | {row['score_volumeprice']:>5.0f} | "
              f"{row['score_macd']:>5.0f} | {row['score_valuation']:>5.0f} | "
              f"{row['score_sentiment']:>5.0f} | {row['score_sector']:>5.0f} | "
              f"{row['score_total']:>6.1f}")

    print("-" * 100)
    print(f"  共 {len(result)} 只股票")

    # ── 5. 保存 CSV ──
    csv_dir = os.path.join(PROJECT_ROOT, 'data')
    os.makedirs(csv_dir, exist_ok=True)
    csv_path = os.path.join(csv_dir, 'diagnose_6plus2_scores.csv')
    result.to_csv(csv_path, index=False, encoding='utf-8-sig')
    print(f"\n  CSV 已保存: {csv_path}")

    # ── 6. 评分分布 ──
    print(f"\n  评分分布:")
    bins = [0, 20, 40, 60, 80, 100]
    labels = ['0-20', '20-40', '40-60', '60-80', '80-100']
    for lbl in labels:
        lo, hi = int(lbl.split('-')[0]), int(lbl.split('-')[1])
        cnt = ((result['score_total'] >= lo) & (result['score_total'] < hi)).sum()
        bar = '█' * max(1, cnt // 2)
        print(f"    {lbl:>7}: {cnt:>3}只 {bar}")

    # 前5名摘要
    print(f"\n  Top 5:")
    for rank, row in result.head(5).iterrows():
        name = row.get('name', '')[:6]
        print(f"    {rank}. {row['stock_code']} {name} — 总分 {row['score_total']:.1f}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
