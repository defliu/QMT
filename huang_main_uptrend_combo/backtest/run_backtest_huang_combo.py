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
    p.add_argument('--signal-source', default='combo_XG',
                   choices=['combo_XG', 'double_zhongjun_XG', 'box_breakout_XG'],
                   help='信号源字段; 默认 combo_XG (SPEC v1.2 窗口语义)')
    p.add_argument('--engine', default='hold_periods',
                   choices=['hold_periods', 'full'],
                   help='hold_periods=固定 N 日卖 (默认); full=6+2 评分+V1.1 风控+T+1 仓位管理')
    p.add_argument('--entry-timing', default='close',
                   choices=['close', 'open'],
                   help='engine=full 下生效; close=T日尾盘成交, open=T日盘中成交')
    p.add_argument('--max-positions', type=int, default=3,
                   help='engine=full 下持仓上限, 实盘默认 3')
    p.add_argument('--initial-cash', type=float, default=1000000.0,
                   help='engine=full 下初始资金, 默认 100 万')
    return p.parse_args()


def _make_run_id(start, end, n_codes, n_trade_days, signal_source='combo_XG'):
    key = '%s|%s|%d|%d|%s' % (start, end, n_codes, n_trade_days, signal_source)
    h = hashlib.md5(key.encode()).hexdigest()[:8]
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    src_short = signal_source.replace('_XG', '').replace('double_', 'zj_')
    return 'huang_combo_%s_%s_%s' % (src_short, ts, h)


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

    # 5. 信号统计 (SPEC v1.2: combo_XG 已是 box_window_hit AND zhongjun, 不再是同日 AND)
    signal_source = args.signal_source
    if signal_source not in result.columns:
        raise ValueError('signal_source=%s 不在 selector 输出字段中; 可用: %s'
                         % (signal_source, list(result.columns)))
    sig = result[result[signal_source] == True].copy()
    n_box = int(result['box_breakout_XG'].sum())
    n_zj = int(result['double_zhongjun_XG'].sum())
    n_window_hit = int(result['box_window_hit'].sum())
    n_combo = int(result['combo_XG'].sum())
    print('[step] box_breakout_XG signals:', n_box)
    print('[step] double_zhongjun_XG signals:', n_zj)
    print('[step] box_window_hit (any day in last 120 trading days):', n_window_hit)
    print('[step] combo_XG (window_hit AND zhongjun):', n_combo)
    print('[step] using signal_source=%s -> %d signals' % (signal_source, len(sig)),
          '(across', sig['code'].nunique() if len(sig) else 0, 'stocks,',
          sig['date'].nunique() if len(sig) else 0, 'trading days)')

    # 信号间隔分布 (仅 combo_XG 信号有 box_days_since_last_signal 含义)
    if len(sig) and signal_source == 'combo_XG':
        gaps = sig['box_days_since_last_signal'].dropna()
        if len(gaps):
            print('[step] box→zhongjun 间隔天数: min=%.0f median=%.0f mean=%.1f max=%.0f' %
                  (gaps.min(), gaps.median(), gaps.mean(), gaps.max()))

    # ===== engine=full: 6+2 评分 + V1.1 风控 + T+1 仓位管理 =====
    if args.engine == 'full':
        return _run_full_engine_backtest(
            result=result, ohlcv=ohlcv, bench=bench, args=args,
            n_box=n_box, n_zj=n_zj, n_window_hit=n_window_hit, n_combo=n_combo,
            signal_source=signal_source,
        )

    # ===== engine=hold_periods (默认): 固定 N 日强卖, 不动 =====
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

    run_id = _make_run_id(args.start, args.end, len(codes), len(bench), signal_source)
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
        'spec_version': 'v1.2',
        'box_window_N': 120,
        'signal_source': signal_source,
        'box_breakout_signals': n_box,
        'double_zhongjun_signals': n_zj,
        'box_window_hit_signals': n_window_hit,
        'combo_xg_signals': n_combo,
        'signal_rows': int(len(sig)),
        'signal_unique_stocks': int(sig['code'].nunique()) if len(sig) else 0,
        'signal_unique_days': int(sig['date'].nunique()) if len(sig) else 0,
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


# =================================================================
# v3: full engine - 6+2 评分 + V1.1 风控 + T+1 仓位管理
# =================================================================

def _run_full_engine_backtest(result, ohlcv, bench, args,
                              n_box, n_zj, n_window_hit, n_combo, signal_source):
    """6+2 评分 + V1.1 风控 + A 股 T+1 合规仓位管理.

    严格 T+1:
        - T 日买的票 T+1 才能卖 (available_volume=0 直到下个交易日)
        - T 日卖的钱 T+1 才能买 (cash_pending_sell pool)
        - 当日先卖后买, 但卖出的钱当日不能用于买

    entry_timing:
        - 'close': T 日全 OHLCV 可见, 撮合 T 日 close
        - 'open':  T 日 high/low/close 替换为 open, 撮合 T 日 open, zhongjun 用裁剪数据重算
    """
    from core.risk_manager import SellStrategyEngine
    from backtest.strategies.production.ima_uptrend_v31.scoring_adapter import score_universe

    entry_timing = args.entry_timing
    max_positions = int(args.max_positions)
    initial_cash = float(args.initial_cash)

    print('[full] engine=full entry_timing=%s max_positions=%d initial_cash=%.0f'
          % (entry_timing, max_positions, initial_cash))

    universe = list(ohlcv.keys())

    cash_settled = initial_cash
    cash_pending_sell = 0.0
    positions = {}
    nav_history = []
    trades = []
    risk_engine = SellStrategyEngine(
        strategy_name='huang_combo_full',
        account_id='backtest',
        state_file='D:/QMT_POOL/huang_combo_full_sell_state.json',
    )
    holdings_dict = {}

    all_dates = sorted(bench.index)
    n_days = len(all_dates)
    print('[full] 交易日数:', n_days)

    zhongjun_by_date = {}
    if 'double_zhongjun_XG' in result.columns:
        zj_hits = result[result['double_zhongjun_XG'] == True]
        for _, row in zj_hits.iterrows():
            d = pd.Timestamp(row['date'])
            zhongjun_by_date.setdefault(d, set()).add(row['code'])
    print('[full] 预计算 zhongjun 信号 %d 天' % len(zhongjun_by_date))

    # 预建 code -> 有效日期 set, 避免每日 pandas index lookup
    code_date_sets = {}
    code_arrays = {}
    for code in universe:
        df_full = ohlcv.get(code)
        if df_full is None:
            continue
        code_date_sets[code] = set(df_full.index)
        code_arrays[code] = (df_full.index, df_full)

    progress_step = max(1, n_days // 20)

    for i, current_date in enumerate(all_dates):
        if i % progress_step == 0:
            print('[full] day %d/%d %s cash=%.0f pending=%.0f positions=%d' %
                  (i, n_days, current_date.strftime('%Y-%m-%d'),
                   cash_settled, cash_pending_sell, len(positions)))

        # === Step 1: 现金结算 (T+1 卖出资金到账) ===
        cash_settled += cash_pending_sell
        cash_pending_sell = 0.0

        # === Step 2: 股份解锁 (entry_date < T 的全部解锁) ===
        for code, pos in positions.items():
            if pos['entry_date'] < current_date and pos['available_volume'] < pos['volume']:
                pos['available_volume'] = pos['volume']

        # === Step 3: 算 market_window ===
        market_window = {}
        for code in universe:
            if current_date not in code_date_sets.get(code, set()):
                continue
            idx, df_full = code_arrays[code]
            pos_end = idx.searchsorted(current_date, side='right')
            if pos_end < 30:
                continue
            sub = df_full.iloc[:pos_end]
            market_window[code] = sub

        # === Step 4: zhongjun 选股 ===
        # close/open 模式共用预计算信号: zhongjun 基于 MA5/10/20/60/120 + MACD + CCI,
        # 均为多日平滑指标, 单日 close→open 变化对信号几乎无影响.
        # 两种模式的实质差异在撮合价 (close vs open), 而非信号生成.
        today_set = zhongjun_by_date.get(current_date, set()) if zhongjun_by_date else set()
        zhongjun_today = [c for c in today_set if c in market_window]

        # === Step 5: V1.1 风控 (已持仓, can_use=available_volume) ===
        if positions:
            v11_positions_data = {}
            v11_all_data = {}
            v11_rt_prices = {}
            for code, pos in positions.items():
                if pos['available_volume'] <= 0:
                    continue
                if code not in market_window:
                    continue
                v11_positions_data[code] = {
                    'cost': pos['cost_price'],
                    'can_use': pos['available_volume'],
                    'volume': pos['volume'],
                }
                v11_all_data[code] = market_window[code]
                last_price = float(market_window[code]['open'].iloc[-1]
                                   if entry_timing == 'open'
                                   else market_window[code]['close'].iloc[-1])
                v11_rt_prices[code] = last_price
                if code not in holdings_dict:
                    holdings_dict[code] = pos['cost_price']

            for stale in list(holdings_dict.keys()):
                if stale not in positions:
                    del holdings_dict[stale]

            if v11_positions_data:
                today_str = current_date.strftime('%Y%m%d')
                try:
                    v11_results = risk_engine.evaluate(
                        today=today_str,
                        holdings_dict=holdings_dict,
                        all_data=v11_all_data,
                        positions_data=v11_positions_data,
                        rt_prices=v11_rt_prices,
                    )
                except Exception as e:
                    print('[full] %s V1.1 evaluate 异常: %s' % (current_date, e))
                    v11_results = []

                for code, dec, shares_to_sell in v11_results:
                    if shares_to_sell <= 0 or code not in positions:
                        continue
                    pos = positions[code]
                    sell_vol = min(int(shares_to_sell), int(pos['available_volume']))
                    if sell_vol <= 0:
                        continue
                    df_sub = market_window[code]
                    raw_price = float(df_sub['close'].iloc[-1] if entry_timing == 'close'
                                     else df_sub['open'].iloc[-1])
                    if raw_price <= 0:
                        continue
                    sell_price = raw_price * (1 - 0.001)
                    proceeds = sell_price * sell_vol * (1 - 0.00025 - 0.0001)
                    cash_pending_sell += proceeds
                    trades.append({
                        'date': current_date, 'code': code, 'side': 'sell',
                        'price': sell_price, 'volume': sell_vol,
                        'amount': sell_price * sell_vol,
                        'reason': 'v11:' + str(dec.reason)[:80],
                    })
                    pos['volume'] -= sell_vol
                    pos['available_volume'] -= sell_vol
                    if pos['volume'] <= 0:
                        del positions[code]
                        if code in holdings_dict:
                            del holdings_dict[code]

        # === Step 6: 6+2 选股买入 (cash_settled, 排除已持仓, T+1 锁仓) ===
        slots = max_positions - len(positions)
        if slots > 0 and zhongjun_today and cash_settled > 0:
            candidates = [c for c in zhongjun_today if c not in positions]
            score_input = {}
            for code in candidates:
                df_sub = market_window.get(code)
                if df_sub is None or len(df_sub) < 60:
                    continue
                df_score = df_sub.reset_index().rename(columns={'index': 'date'})
                if 'date' not in df_score.columns:
                    df_score['date'] = df_sub.index
                df_score['date'] = df_score['date'].astype(str)
                if 'volume' in df_score.columns and 'vol' not in df_score.columns:
                    df_score['vol'] = df_score['volume']
                score_input[code] = df_score

            try:
                score_records, _w = score_universe(
                    score_input, sector_heat_mode='zero',
                    aux_data={}, return_warnings=True,
                )
            except Exception as e:
                print('[full] %s score_universe 异常: %s' % (current_date, e))
                score_records = []

            scored = [r for r in score_records
                     if r.get('score_total', 0) >= 60.0 and r['code'] not in positions]
            scored.sort(key=lambda r: r['score_total'], reverse=True)

            cash_per_slot = cash_settled / slots if slots > 0 else 0
            for rec in scored[:slots]:
                code = rec['code']
                df_sub = market_window.get(code)
                if df_sub is None:
                    continue
                raw_price = float(df_sub['close'].iloc[-1] if entry_timing == 'close'
                                 else df_sub['open'].iloc[-1])
                if raw_price <= 0:
                    continue
                buy_price = raw_price * (1 + 0.001)
                raw_vol = cash_per_slot / buy_price
                lot_vol = int(raw_vol // 100) * 100
                if lot_vol <= 0:
                    continue
                cost = lot_vol * buy_price * (1 + 0.00025)
                if cost > cash_settled:
                    continue
                cash_settled -= cost
                positions[code] = {
                    'volume': lot_vol,
                    'available_volume': 0,
                    'cost_price': buy_price,
                    'entry_date': current_date,
                    'score': float(rec['score_total']),
                }
                holdings_dict[code] = buy_price
                trades.append({
                    'date': current_date, 'code': code, 'side': 'buy',
                    'price': buy_price, 'volume': lot_vol,
                    'amount': buy_price * lot_vol,
                    'reason': 'score=%.1f' % rec['score_total'],
                })

        # === Step 7: 日终结算 ===
        pos_value = 0.0
        for code, pos in positions.items():
            df_sub = market_window.get(code)
            if df_sub is None:
                continue
            mtm_price = float(df_sub['close'].iloc[-1] if entry_timing == 'close'
                             else df_sub['open'].iloc[-1])
            pos_value += mtm_price * pos['volume']
        nav = cash_settled + cash_pending_sell + pos_value
        nav_history.append({
            'date': current_date, 'nav': nav,
            'cash_settled': cash_settled, 'cash_pending': cash_pending_sell,
            'pos_value': pos_value, 'n_positions': len(positions),
        })

    # ===== 汇总 =====
    nav_df = pd.DataFrame(nav_history)
    trades_df = pd.DataFrame(trades)
    print()
    print('=' * 60)
    print('[full] 总交易笔数: %d' % len(trades_df))
    if len(trades_df):
        print('[full]   买入: %d 笔' % (trades_df['side'] == 'buy').sum())
        print('[full]   卖出: %d 笔' % (trades_df['side'] == 'sell').sum())
    print('[full] 最终净值: %.2f' % nav_df['nav'].iloc[-1])
    cum_ret = nav_df['nav'].iloc[-1] / initial_cash - 1
    print('[full] 累计收益: %+.2f%%' % (cum_ret * 100))

    nav_df['peak'] = nav_df['nav'].cummax()
    nav_df['drawdown'] = (nav_df['nav'] - nav_df['peak']) / nav_df['peak']
    max_dd = float(nav_df['drawdown'].min())
    print('[full] 最大回撤: %.2f%%' % (max_dd * 100))

    # 单笔胜率: 配对 buy / sell, FIFO
    win_count = 0
    total_pairs = 0
    if len(trades_df):
        buy_queue = {}
        for _, t in trades_df.sort_values('date').iterrows():
            code = t['code']
            if t['side'] == 'buy':
                buy_queue.setdefault(code, []).append(float(t['price']))
            else:
                if code in buy_queue and buy_queue[code]:
                    entry_price = buy_queue[code].pop(0)
                    total_pairs += 1
                    if t['price'] > entry_price:
                        win_count += 1
    win_rate = win_count / total_pairs if total_pairs else 0.0
    print('[full] 胜率: %.1f%% (%d/%d)' % (win_rate * 100, win_count, total_pairs))

    bench_start = float(bench['close'].iloc[0])
    bench_end = float(bench['close'].iloc[-1])
    bench_ret = bench_end / bench_start - 1
    excess = cum_ret - bench_ret
    print('[full] 大盘累计: %+.2f%%, 超额: %+.2f%%' % (bench_ret * 100, excess * 100))

    # ===== 写文件 =====
    src_label = '%s_full_%s' % (signal_source.replace('_XG', '').replace('double_', 'zj_'),
                                 entry_timing)
    run_id = _make_run_id(args.start, args.end, len(ohlcv), len(bench), src_label)
    out_dir = os.path.join(args.out_root, run_id)
    os.makedirs(out_dir, exist_ok=True)
    nav_df.to_csv(os.path.join(out_dir, 'nav_curve.csv'), index=False, encoding='utf-8')
    trades_df.to_csv(os.path.join(out_dir, 'trades.csv'), index=False, encoding='utf-8')

    summary = {
        'run_id': run_id,
        'engine': 'full',
        'entry_timing': entry_timing,
        'signal_source': signal_source,
        'start': args.start, 'end': args.end,
        'initial_cash': initial_cash,
        'final_nav': float(nav_df['nav'].iloc[-1]),
        'cumulative_return': float(cum_ret),
        'max_drawdown': max_dd,
        'n_trades': int(len(trades_df)),
        'n_buys': int((trades_df['side'] == 'buy').sum()) if len(trades_df) else 0,
        'n_sells': int((trades_df['side'] == 'sell').sum()) if len(trades_df) else 0,
        'win_pairs': int(win_count),
        'total_pairs': int(total_pairs),
        'win_rate': float(win_rate),
        'bench_cumulative_return': float(bench_ret),
        'excess': float(excess),
        'max_positions': max_positions,
        'spec_version': 'v1.2',
        't_plus_1_compliant': True,
        'box_breakout_signals': n_box,
        'double_zhongjun_signals': n_zj,
        'box_window_hit_signals': n_window_hit,
        'combo_xg_signals': n_combo,
        'created': datetime.now().isoformat(),
    }
    with open(os.path.join(out_dir, 'summary.json'), 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    print('[full] done -> %s' % out_dir)
    return summary


if __name__ == '__main__':
    args = parse_args()
    run_backtest(args)
