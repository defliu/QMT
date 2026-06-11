#!/usr/bin/env python3
# coding=utf-8
"""
快速回测: 6+2评分器 — 每日打分 → 选前N名买入 → 持有M天后卖出。
数据源: mootdx (通达信TCP)。

用法:
    python scripts/backtest_dimension6plus2.py                              # 默认参数
    python scripts/backtest_dimension6plus2.py --days 30 --top 5 --hold 2  # 自定义
    python scripts/backtest_dimension6plus2.py --pool D:/custom/pool.txt   # 自定义池

返回:
    pd.DataFrame 包含所有交易记录，同时打印统计摘要。
"""

import os
import sys
import argparse
import warnings
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
import numpy as np
from core.scoring.dimension6plus2 import ScoreCalculator6Plus2

# ── 常量 ──────────────────────────────────────────────────────
REQ_BARS = 800
DEFAULT_POOL = "D:/QMT_POOL/selected.txt"
SECTOR_HEAT_PATH = "D:/QMT_POOL/sector_heat.json"


# ── 工具函数 ──────────────────────────────────────────────────


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
    """读取股票池，返回6位纯代码列表。文件不存在时返回空列表。"""
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


def download_all(stock_codes: list[str], req_bars: int = 800):
    """下载所有股票的日K线，返回 {code6: DataFrame(open,high,low,close,volume)}。"""
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
                print(f"  下载 [{idx+1}/{total}] 已获取 {len(all_data)} 只...", flush=True)
        except Exception:
            pass
    return all_data


# ── 回测逻辑 ──────────────────────────────────────────────────


def run_backtest(
    pool_path: str = DEFAULT_POOL,
    backtest_days: int = 60,
    top_n: int = 3,
    hold_days: int = 1,
) -> pd.DataFrame:
    """
    执行 6+2 评分回测。

    参数:
        pool_path: 股票池文件路径
        backtest_days: 回测最近多少个交易日
        top_n: 每日选取前几名买入
        hold_days: 持仓天数

    返回:
        pd.DataFrame 包含所有交易记录 (code, buy_date, sell_date, buy_price,
                      sell_price, return, win) 或空 DataFrame。
    """
    scorer = ScoreCalculator6Plus2(sector_heat_path=SECTOR_HEAT_PATH)

    print("=" * 60)
    print("  6+2 评分器 — 快速回测")
    print(f"  池: {pool_path}")
    print(f"  回测周期: 最近 {backtest_days} 个交易日")
    print(f"  每日选前 {top_n} 名, 持有 {hold_days} 天")
    print("=" * 60)

    # 读取池 + 下载数据
    codes6 = read_pool(pool_path)
    if not codes6:
        codes6 = ["600519", "000858", "601318", "600036", "000333"]
        print(f"  池为空，使用示例: {codes6}")

    print(f"\n下载 {len(codes6)} 只股票数据...")
    all_data = download_all(codes6, REQ_BARS)
    print(f"  成功获取 {len(all_data)} 只")

    if len(all_data) < 3:
        print("  数据不足, 终止")
        return pd.DataFrame()

    # 找出所有交易日并排序
    all_dates = set()
    for df in all_data.values():
        all_dates.update(df.index.strftime('%Y-%m-%d'))
    all_dates = sorted(all_dates)
    print(f"  共有 {len(all_dates)} 个交易日")

    # 取最近 backtest_days 天
    test_dates = all_dates[-backtest_days:]
    print(f"  回测区间: {test_dates[0]} ~ {test_dates[-1]}")

    # 逐日回测
    trades = []
    portfolio = {}

    for i, today_str in enumerate(test_dates):
        today = pd.Timestamp(today_str)

        # 1) 检查卖出
        for code6 in list(portfolio.keys()):
            hold = portfolio[code6]
            days_held = (today - pd.Timestamp(hold['buy_date'])).days
            if days_held >= hold_days:
                df = all_data.get(code6)
                if df is not None and today_str in df.index:
                    sell_price = float(df.loc[today_str, 'close'])
                    buy_price = hold['buy_price']
                    ret = (sell_price - buy_price) / buy_price
                    trades.append({
                        'code': code6,
                        'buy_date': hold['buy_date'],
                        'sell_date': today_str,
                        'buy_price': round(buy_price, 2),
                        'sell_price': round(sell_price, 2),
                        'return': round(ret * 100, 2),
                    })
                del portfolio[code6]

        # 2) 对今日所有股票打分
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

        if not today_scores:
            continue

        # 3) 选前 top_n 名买入
        today_scores.sort(key=lambda x: -x[1])
        picks = today_scores[:top_n]

        for code6, score in picks:
            if code6 in portfolio:
                continue
            df = all_data.get(code6)
            if df is None or today_str not in df.index:
                continue
            buy_price = float(df.loc[today_str, 'close'])
            portfolio[code6] = {
                'buy_date': today_str,
                'buy_price': buy_price,
                'score': score,
            }

        if (i + 1) % 10 == 0 or i == len(test_dates) - 1:
            print(f"  进度 [{i+1}/{len(test_dates)}] 持仓 {len(portfolio)} 只, 已完交易 {len(trades)} 笔", flush=True)

    # 尾盘平仓
    for code6, hold in list(portfolio.items()):
        df = all_data.get(code6)
        if df is not None:
            last_date = df.index[-1].strftime('%Y-%m-%d')
            sell_price = float(df.iloc[-1]['close'])
            ret = (sell_price - hold['buy_price']) / hold['buy_price']
            trades.append({
                'code': code6,
                'buy_date': hold['buy_date'],
                'sell_date': last_date,
                'buy_price': round(hold['buy_price'], 2),
                'sell_price': round(sell_price, 2),
                'return': round(ret * 100, 2),
            })
        del portfolio[code6]

    # 结果统计
    if not trades:
        print("\n无交易记录")
        return pd.DataFrame()

    trades_df = pd.DataFrame(trades)
    trades_df['win'] = trades_df['return'] > 0

    win_rate = trades_df['win'].mean() * 100
    avg_ret = trades_df['return'].mean()
    total_ret = trades_df['return'].sum()
    max_win = trades_df['return'].max()
    max_loss = trades_df['return'].min()

    print("\n" + "=" * 60)
    print("  回测结果")
    print("=" * 60)
    print(f"  总交易: {len(trades_df)} 笔")
    print(f"  胜率:   {win_rate:.1f}%")
    print(f"  平均收益: {avg_ret:+.2f}%")
    print(f"  累计收益: {total_ret:+.2f}%")
    print(f"  最大盈利: {max_win:+.2f}%")
    print(f"  最大亏损: {max_loss:+.2f}%")
    print(f"  盈利交易: {(trades_df['win'].sum()):.0f} 笔")
    print(f"  亏损交易: {((~trades_df['win']).sum()):.0f} 笔")

    # 最近10笔交易
    print("\n  最近10笔交易:")
    print(f"  {'代码':>8} | {'买入':>10} | {'卖出':>10} | {'买价':>8} | {'卖价':>8} | {'收益':>7}")
    print("  " + "-" * 60)
    for _, r in trades_df.tail(10).iterrows():
        print(f"  {r['code']:>8} | {r['buy_date']:>10} | {r['sell_date']:>10} | {r['buy_price']:>8.2f} | {r['sell_price']:>8.2f} | {r['return']:>+6.2f}%")

    # 保存CSV
    csv_path = os.path.join(PROJECT_ROOT, "backtest_6plus2_result.csv")
    trades_df.to_csv(csv_path, index=False, encoding='utf-8')
    print(f"\n  详细记录: {csv_path}")

    return trades_df


# ── CLI 入口 ──────────────────────────────────────────────────


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="6+2 评分器 — 快速回测",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--days', type=int, default=60,
                        help='回测交易日数 (default: 60)')
    parser.add_argument('--top', type=int, default=3,
                        help='每日选股数量 (default: 3)')
    parser.add_argument('--hold', type=int, default=1,
                        help='持仓天数 (default: 1)')
    parser.add_argument('--pool', type=str, default=DEFAULT_POOL,
                        help=f'股票池路径 (default: {DEFAULT_POOL})')
    return parser.parse_args(argv)


def main():
    args = parse_args()
    result = run_backtest(
        pool_path=args.pool,
        backtest_days=args.days,
        top_n=args.top,
        hold_days=args.hold,
    )
    return 0 if not result.empty else 1


if __name__ == '__main__':
    sys.exit(main())
