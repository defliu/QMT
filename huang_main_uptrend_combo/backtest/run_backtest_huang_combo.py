# coding=utf-8
"""huang combo selector historical backtest (Plan A: pure stock picking + holding period returns).

Data source: huicexitong daily_data."行情数据" (1990-12 ~ 2026-04)
Universe: backtest/data/universe/core_100.csv intersection huicexitong data availability
Range: 2023-06-01 ~ 2026-04-03
Holding periods: 5 / 10 / 20 days
Evaluation: daily through combo count, N-day win rate, avg return, max drawdown, empty days, benchmark comparison

Boundaries:
- Does not use backtest/engine/daily_engine.py (main source only 17 months)
- huicexitong uses standalone reader (consistent with huicexitong_reader.py boundary contract)
- Output to F:/backtest_workspace/huang_combo_backtest_<run_id>/ (not D:/)
- No order placement / no QMT connection
"""
import argparse, os, sys, json, hashlib
from datetime import datetime

sys.path.insert(0, 'D:/QMT_STRATEGIES')

import numpy as np
import pandas as pd

from huang_main_uptrend_combo.huang_main_uptrend_combo_selector import (
    select_huang_main_uptrend_combo, DEFAULT_PARAMS,
)
from huang_main_uptrend_combo.backtest.huice_loader import (
    load_ohlcv_from_huicexitong, load_benchmark_index,
)


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--start', default='2023-06-01')
    p.add_argument('--end', default='2026-04-03')
    p.add_argument('--universe', default='D:/QMT_STRATEGIES/backtest/data/universe/core_100.csv')
    p.add_argument('--benchmark', default='000001.SH')
    p.add_argument('--out-root', default='F:/backtest_workspace')
    p.add_argument('--hold-periods', default='5,10,20')
    return p.parse_args()


def _make_run_id(start, end, n_codes, n_trade_days):
    h = hashlib.md5(('%s|%s|%d|%d' % (start, end, n_codes, n_trade_days)).encode()).hexdigest()[:8]
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    return 'huang_combo_%s_%s' % (ts, h)


def run_backtest(args):
    uni_df = pd.read_csv(args.universe)
    codes = uni_df['code'].tolist()
    print('[step] universe core_100:', len(codes), 'codes')

    print('[step] loading OHLCV from huicexitong ...')
    ohlcv = load_ohlcv_from_huicexitong(codes, args.start, args.end)
    print('       available:', len(ohlcv), 'codes')
    if len(ohlcv) < int(len(codes) * 0.5):
        raise RuntimeError('available codes < half of universe, abort')

    print('[step] loading benchmark', args.benchmark, '...')
    bench = load_benchmark_index(args.benchmark, args.start, args.end)
    print('       benchmark rows:', len(bench))

    print('[step] running selector ...')
    result = select_huang_main_uptrend_combo(ohlcv, bench)
    print('       signal rows:', len(result))

    sig = result[result['combo_XG'] == True].copy()
    print('[step] combo_XG=True signals:', len(sig), '(across', sig['code'].nunique(), 'stocks,',
          sig['date'].nunique(), 'trading days)')

    hold_periods = [int(x) for x in args.hold_periods.split(',')]
    eval_rows = []
    for code, sub_sig in sig.groupby('code'):
        if code not in ohlcv:
            continue
        df = ohlcv[code]
        for _, row in sub_sig.iterrows():
            sig_date = row['date']
            future = df.loc[df.index > sig_date]
            if len(future) < 1:
                continue
            buy_date = future.index[0]
            buy_price = future.iloc[0]['open']
            if not (buy_price > 0):
                continue
            for n in hold_periods:
                if len(future) <= n:
                    continue
                sell_date = future.index[n]
                sell_price = future.iloc[n]['close']
                if not (sell_price > 0):
                    continue
                ret = sell_price / buy_price - 1.0
                eval_rows.append({
                    'code': code,
                    'signal_date': sig_date,
                    'buy_date': buy_date,
                    'hold_n': n,
                    'sell_date': sell_date,
                    'buy_price': buy_price,
                    'sell_price': sell_price,
                    'return': ret,
                })

    eval_df = pd.DataFrame(eval_rows, columns=['code', 'signal_date', 'buy_date', 'hold_n', 'sell_date', 'buy_price', 'sell_price', 'return'])
    print('[step] evaluation samples:', len(eval_df))

    stats = []
    for n in hold_periods:
        sub = eval_df[eval_df['hold_n'] == n]
        if len(sub) == 0:
            stats.append({'hold_n': n, 'n': 0})
            continue
        rets = sub['return']
        sub_sorted = sub.sort_values('signal_date')
        cum = (1 + sub_sorted['return']).cumprod()
        peak = cum.cummax()
        drawdown = (cum - peak) / peak
        stats.append({
            'hold_n': n,
            'n_signals': len(rets),
            'win_rate': float((rets > 0).mean()),
            'avg_return': float(rets.mean()),
            'median_return': float(rets.median()),
            'std_return': float(rets.std()),
            'max_return': float(rets.max()),
            'min_return': float(rets.min()),
            'max_drawdown': float(drawdown.min()),
            'sharpe_like': float(rets.mean() / rets.std() * np.sqrt(252.0 / n)) if rets.std() > 0 else 0.0,
        })

    stats_df = pd.DataFrame(stats)
    print('[step] stats:')
    print(stats_df.to_string(index=False))

    bench_compare = []
    bench['close_norm'] = bench['close']
    for n in hold_periods:
        bench_rets = []
        for sig_date in sig['date'].unique():
            future = bench.loc[bench.index > sig_date]
            if len(future) <= n:
                continue
            bp = future.iloc[0]['close']
            sp = future.iloc[n]['close']
            if bp > 0 and sp > 0:
                bench_rets.append(sp / bp - 1.0)
        if bench_rets:
            bench_compare.append({
                'hold_n': n,
                'bench_n': len(bench_rets),
                'bench_avg_return': float(np.mean(bench_rets)),
                'bench_win_rate': float(np.mean([r > 0 for r in bench_rets])),
            })

    bench_df = pd.DataFrame(bench_compare)
    print('[step] benchmark comparison:')
    print(bench_df.to_string(index=False))

    all_trading_days = set(bench.index)
    signal_days = set(sig['date'].unique())
    empty_days = all_trading_days - signal_days
    print('[step] empty days:', len(empty_days), '/', len(all_trading_days),
          '(%.1f%%)' % (100.0 * len(empty_days) / max(1, len(all_trading_days))))

    run_id = _make_run_id(args.start, args.end, len(codes), len(bench))
    out_dir = os.path.join(args.out_root, run_id)
    os.makedirs(out_dir, exist_ok=True)

    sig.to_csv(os.path.join(out_dir, 'signals.csv'), index=False, encoding='utf-8')
    eval_df.to_csv(os.path.join(out_dir, 'eval_trades.csv'), index=False, encoding='utf-8')
    stats_df.to_csv(os.path.join(out_dir, 'stats.csv'), index=False, encoding='utf-8')
    bench_df.to_csv(os.path.join(out_dir, 'bench_compare.csv'), index=False, encoding='utf-8')

    summary = {
        'run_id': run_id,
        'start': args.start,
        'end': args.end,
        'universe_path': args.universe,
        'universe_size': len(codes),
        'codes_with_data': len(ohlcv),
        'benchmark': args.benchmark,
        'benchmark_rows': len(bench),
        'total_trading_days': len(bench),
        'signal_rows': int(len(sig)),
        'signal_unique_stocks': int(sig['code'].nunique()),
        'signal_unique_days': int(sig['date'].nunique()),
        'empty_days': len(empty_days),
        'empty_days_pct': 100.0 * len(empty_days) / max(1, len(bench)),
        'stats': stats,
        'bench_compare': bench_compare,
        'created': datetime.now().isoformat(),
    }
    with open(os.path.join(out_dir, 'summary.json'), 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print('[done] output to:', out_dir)
    return summary


if __name__ == '__main__':
    args = parse_args()
    run_backtest(args)
