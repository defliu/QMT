# MIMO 工单：黄氏 Part 8 v3 - zhongjun + 6+2 + V1.1 + 尾盘/盘中对比 (T+1 合规版)

## 目的

诚哥拍板:
1. 黄氏 zhongjun 当动态股票池, 喂 6+2 评分前 3 买入, V1.1 风控出场
2. 不接工厂 (工厂只 next_open, 见 [[backtest-factory-no-trading-model-extension]] 记忆), 走独立脚本路线
3. 跑两种入场时机对比: 尾盘 close vs 盘中 open
4. **严格 A 股 T+1 合规**: T 日买 T+1 才能卖, T 日卖资金 T+1 才能买

**前置 commit**: `c1221d0`
**预计工时**: 120-150 分钟

---

## 一、核心语义 (实现前必读)

### 日内交易顺序

```text
每日 T 开盘前:
  Step 1: 现金结算 (T-1 卖出资金到账, cash_pending_sell -> cash_settled)
  Step 2: 股份解锁 (entry_date < T 的所有 positions.available_volume 升到 volume)

每日 T 决策 (尾盘版用 T close, 盘中版用 T open):
  Step 3: 算 market_window
    - 尾盘版 entry_timing='close': T 日完整 OHLCV 可见
    - 盘中版 entry_timing='open': T 日 high/low/close 全替换为 open
  Step 4: 重算 zhongjun (用裁剪后 market_window, 避免 look-ahead)
  Step 5: V1.1 风控 (positions_data.can_use = pos.available_volume, 锁仓部分自动跳过)
    - 卖出价 = T 日 close/open (按 entry_timing)
    - proceeds 入 cash_pending_sell (T+1 转 settled)
    - pos.volume 和 pos.available_volume 同时减 shares_sold
  Step 6: 6+2 选股买入 (用 cash_settled, 不用 pending)
    - zhongjun_today ∩ 非已持仓 -> 6+2 评分 -> score>=60 排序前 slots 入场
    - 买入价 = T 日 close/open (按 entry_timing)
    - 新仓 pos.available_volume = 0 (T 日不可卖)
  Step 7: 日终结算 (nav = cash_settled + cash_pending_sell + pos_value)
```

### T+1 关键字段

```python
positions[code] = {
    'volume': int,           # 总持仓
    'available_volume': int, # 可卖份额; 当日新买 = 0, T+1 解锁 = volume
    'cost_price': float,
    'entry_date': Timestamp, # 入场日
}

# 两个 cash 池:
cash_settled = float       # 可用现金
cash_pending_sell = float  # 今日卖出, 明日转 settled
```

### 撮合价模型

```python
if entry_timing == 'close':
    price = df.iloc[-1]['close']
else:  # 'open'
    price = df.iloc[-1]['open']

# 滑点 / 佣金 / 印花 (跟 baseline.yaml 实盘对齐):
买入: price_after = price * (1 + 0.001), cost = lot_vol * price_after * (1 + 0.00025)
卖出: price_after = price * (1 - 0.001), proceeds = lot_vol * price_after * (1 - 0.00025 - 0.0001)
```

---

## 二、必做（10 步）

### TASK-0. 时间戳

```bash
date -u +"%Y-%m-%dT%H:%M:%SZ"
```

### TASK-1. 预检 (只查本工单要改的目标文件)

```bash
cd D:/QMT_STRATEGIES
git log -1 --oneline
git diff --stat huang_main_uptrend_combo/backtest/run_backtest_huang_combo.py
git status --short huang_main_uptrend_combo/backtest/run_backtest_huang_combo.py
git status --short core/risk_manager.py
```

期望:
- HEAD = `c1221d0`
- `run_backtest_huang_combo.py` 干净 (本工单要扩它)
- `core/risk_manager.py` 干净 (本工单只 import, 不改)

**如果上面 2 个目标文件任一有 dirty 行 → 停下报告**.
项目其他文件 dirty / untracked 全部不管 (项目历史灰色地带, 见 [[stash-untracked-may-hide-infrastructure]]).

把输出贴回执.

### TASK-2. 探测 V1.1 SellStrategyEngine 离线兼容性 + can_use 行为

```bash
py -3.10 << 'PYEOF' 2>&1
import sys; sys.path.insert(0, 'D:/QMT_STRATEGIES')
import pandas as pd
from core.risk_manager import SellStrategyEngine

# Mock: 60 日数据, 股价 10 -> 12.5 -> 10.1 (深亏触发 V1.1)
dates = pd.date_range('2024-01-01', periods=60)
close = [10.0 + i * 0.05 for i in range(50)] + [12.5, 12.8, 13.0, 12.2, 11.5, 11.0, 10.8, 10.5, 10.3, 10.1]
df = pd.DataFrame({
    'open': close, 'high': [c+0.1 for c in close],
    'low': [c-0.1 for c in close], 'close': close,
    'volume': [10000.0]*60,
})

engine = SellStrategyEngine()

# 测试 1: 可卖 100, V1.1 应能触发
r1 = engine.evaluate('20240301', {'A.SZ': 12.5}, {'A.SZ': df},
                     {'A.SZ': {'cost': 10.0, 'can_use': 100, 'volume': 100}},
                     {'A.SZ': float(df['close'].iloc[-1])})
print('test 1 (can_use=100):', len(r1), 'decisions')
for code, dec, shares in r1:
    print('  -> action=%s shares=%d reason=%s' % (dec.action, shares, dec.reason[:50]))

# 测试 2: can_use=0 (T 日新买锁仓), 即使 V1.1 想卖也只能 0 shares
r2 = engine.evaluate('20240301', {'A.SZ': 12.5}, {'A.SZ': df},
                     {'A.SZ': {'cost': 10.0, 'can_use': 0, 'volume': 100}},
                     {'A.SZ': float(df['close'].iloc[-1])})
print('test 2 (can_use=0, 锁仓):', len(r2), 'decisions')
for code, dec, shares in r2:
    print('  -> action=%s shares=%d (锁仓应该=0)' % (dec.action, shares))
PYEOF
```

**期望**:
- 测试 1: 至少 1 个 decision, shares >= 100
- 测试 2: 要么 0 decisions (V1.1 内部跳过), 要么 shares=0 (锁仓约束起效)

**异常** (import error / shares=100 即使 can_use=0) → 停下报告.

把完整输出贴回执.

### TASK-3. 扩展 `run_backtest_huang_combo.py` - parse_args

定位 (精确字符串):

```python
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
    return p.parse_args()
```

替换为:

```python
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
```

### TASK-4. 在 run_backtest 中插入 engine 分发点

定位 (精确字符串):

```python
    eval_df = pd.DataFrame(eval_rows, columns=['code', 'signal_date', 'buy_date', 'hold_n', 'sell_date', 'buy_price', 'sell_price', 'return'])
    print('[step] evaluation samples:', len(eval_df))
```

但**先**在 `hold_periods = [int(x) for x in args.hold_periods.split(',')]` 这行之前 (即原 hold_periods 路径开始之前) 插入 engine 分发块. 定位:

```python
    # 信号间隔分布 (仅 combo_XG 信号有 box_days_since_last_signal 含义)
    if len(sig) and signal_source == 'combo_XG':
        gaps = sig['box_days_since_last_signal'].dropna()
        if len(gaps):
            print('[step] box→zhongjun 间隔天数: min=%.0f median=%.0f mean=%.1f max=%.0f' %
                  (gaps.min(), gaps.median(), gaps.mean(), gaps.max()))

    hold_periods = [int(x) for x in args.hold_periods.split(',')]
```

替换为:

```python
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
```

### TASK-5. 在文件末尾 (`if __name__ == '__main__':` 之前) 新增 `_run_full_engine_backtest`

```python
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
    from huang_main_uptrend_combo.huang_main_uptrend_combo_selector import (
        _calc_double_zhongjun_conditions, DEFAULT_PARAMS as HUANG_PARAMS,
    )
    from backtest.strategies.production.ima_uptrend_v31.scoring_adapter import score_universe

    entry_timing = args.entry_timing
    max_positions = int(args.max_positions)
    initial_cash = float(args.initial_cash)

    print('[full] engine=full entry_timing=%s max_positions=%d initial_cash=%.0f'
          % (entry_timing, max_positions, initial_cash))

    # ===== universe: 由调用方传入的 ohlcv keys =====
    universe = list(ohlcv.keys())

    # ===== 大盘指数 (zhongjun 算大盘条件用) =====
    # bench 是 DataFrame index=date columns=[close]
    # 全程不变, 直接传给 _calc_double_zhongjun_conditions

    # ===== 仓位 / 现金 / 风控状态 =====
    cash_settled = initial_cash
    cash_pending_sell = 0.0
    positions = {}  # code -> {volume, available_volume, cost_price, entry_date}
    nav_history = []
    trades = []
    risk_engine = SellStrategyEngine()
    holdings_dict = {}  # code -> highest_price (跨日累积)

    huang_params = dict(HUANG_PARAMS)
    all_dates = sorted(bench.index)
    n_days = len(all_dates)
    print('[full] 交易日数:', n_days)

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

        # === Step 3: 算 market_window (尾盘全 / 盘中只 open) ===
        market_window = {}
        for code in universe:
            df_full = ohlcv.get(code)
            if df_full is None:
                continue
            sub = df_full.loc[df_full.index <= current_date]
            if len(sub) < 30:
                continue
            if entry_timing == 'open' and len(sub) > 0:
                last_idx = sub.index[-1]
                if last_idx == pd.Timestamp(current_date):
                    sub = sub.copy()
                    op = sub.loc[last_idx, 'open']
                    if op > 0:
                        sub.at[last_idx, 'high'] = op
                        sub.at[last_idx, 'low'] = op
                        sub.at[last_idx, 'close'] = op
            market_window[code] = sub

        # === Step 4: 重算 zhongjun (盘中版用裁剪数据, 避免 look-ahead) ===
        zhongjun_today = []
        for code in universe:
            df_sub = market_window.get(code)
            if df_sub is None or len(df_sub) < 120:
                continue
            try:
                dbl = _calc_double_zhongjun_conditions(df_sub, bench, huang_params)
            except Exception:
                continue
            if len(dbl) == 0:
                continue
            if bool(dbl.iloc[-1]['double_zhongjun_XG']):
                zhongjun_today.append(code)

        # === Step 5: V1.1 风控 (已持仓, can_use=available_volume) ===
        if positions:
            v11_positions_data = {}
            v11_all_data = {}
            v11_rt_prices = {}
            for code, pos in positions.items():
                if pos['available_volume'] <= 0:
                    continue  # 锁仓部分不评估
                if code not in market_window:
                    continue
                v11_positions_data[code] = {
                    'cost': pos['cost_price'],
                    'can_use': pos['available_volume'],
                    'volume': pos['volume'],
                }
                v11_all_data[code] = market_window[code]
                last_close = float(market_window[code]['close'].iloc[-1])
                v11_rt_prices[code] = last_close
                # holdings_dict 维护
                if code not in holdings_dict:
                    holdings_dict[code] = pos['cost_price']

            # 清掉已平仓
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
                    cash_pending_sell += proceeds  # T+1 才到账
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
                # score_universe 期望 schema: 含 'vol' 或 'volume' 列, date 在 columns 而非 index
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
                    'available_volume': 0,  # ← T+1 才可卖
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
        buy_queue = {}  # code -> list of (price, date)
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
```

### TASK-6. 跑现有 hold_periods 模式确认未破

```bash
cd D:/QMT_STRATEGIES
py -3.10 -m huang_main_uptrend_combo.backtest.run_backtest_huang_combo \
  --start 2023-06-01 --end 2024-01-01 \
  --universe D:/QMT_STRATEGIES/backtest/data/universe/huang_small_mid_20260403.csv \
  --benchmark 000001.SH \
  --hold-periods 5,10,20 \
  --signal-source double_zhongjun_XG
```

期望: 不抛错, 输出原 hold_periods 路径. **FAIL → 停**.

跑现有单测:

```bash
py -3.10 -m unittest huang_main_uptrend_combo.backtest.tests.test_huice_loader huang_main_uptrend_combo.backtest.tests.test_run_backtest_minimum -v
```

期望 6 PASS. **FAIL → 停**.

把最后 5 行 + smoke test 最后 5 行贴回执.

### TASK-7. 跑尾盘版 3 年回测

```bash
cd D:/QMT_STRATEGIES
py -3.10 -m huang_main_uptrend_combo.backtest.run_backtest_huang_combo \
  --start 2023-06-01 --end 2026-04-03 \
  --universe D:/QMT_STRATEGIES/backtest/data/universe/huang_small_mid_20260403.csv \
  --benchmark 000001.SH \
  --signal-source double_zhongjun_XG \
  --engine full \
  --entry-timing close \
  --max-positions 3 \
  --initial-cash 1000000
```

**期望**:
- 跑完无错, `[full] done -> F:/...zj_zhongjun_full_close*`
- n_trades > 0
- 输出含 trades.csv / nav_curve.csv / summary.json
- 不超 20 分钟

**异常**:
- n_trades = 0 → **必停**
- 超 20 分钟 → 停
- 任何 Python 异常 → 停

把完整 stdout 贴回执 (含进度行 + 汇总).

### TASK-8. 跑盘中版 3 年回测

```bash
cd D:/QMT_STRATEGIES
py -3.10 -m huang_main_uptrend_combo.backtest.run_backtest_huang_combo \
  --start 2023-06-01 --end 2026-04-03 \
  --universe D:/QMT_STRATEGIES/backtest/data/universe/huang_small_mid_20260403.csv \
  --benchmark 000001.SH \
  --signal-source double_zhongjun_XG \
  --engine full \
  --entry-timing open \
  --max-positions 3 \
  --initial-cash 1000000
```

期望同 TASK-7, run_id 后缀 `_open`.

把完整 stdout 贴回执.

### TASK-9. 写对比报告 `huang_main_uptrend_combo/backtest/reports/backtest_report_full_engine_compare.md`

整段新建. 结构:

```markdown
# 黄氏 zhongjun + 6+2 + V1.1 全引擎对比报告 (T+1 合规)

执行日期: <填本工单 date 真实值>
依据: 诚哥拍板, 黄氏选股接入实盘评分+风控管线, 严格 A 股 T+1
脚本: huang_main_uptrend_combo/backtest/run_backtest_huang_combo.py --engine full

## 一、回测设置

| 项 | 值 |
|---|---|
| 时间区间 | 2023-06-01 ~ 2026-04-03 |
| 实际交易日数 | <填> |
| 股票池 | huang_small_mid_20260403.csv (3633 中小盘) |
| 大盘 | 000001.SH |
| 信号源 | double_zhongjun_XG (盘中版重算, 避免 look-ahead) |
| 初始资金 | 1,000,000 |
| 持仓上限 | 3 (实盘配置) |
| 评分 | 6+2 (复用 production/ima_uptrend_v31/scoring_adapter), min_score=60 |
| 风控 | V1.1 SellStrategyEngine (core/risk_manager.py 直接调用) |
| 滑点 | 0.1% |
| 佣金 | 0.025% |
| 印花税 | 0.01% (仅卖出) |
| T+1 | 严格: 买入 T+1 解锁, 卖出资金 T+1 到账 |

## 二、两种入场时机对比

### 尾盘版 (entry_timing=close)
- 决策时点: T 日 ≈ 14:55
- 决策视野: T 日全 OHLCV (含 close)
- 撮合价: T 日 close (滑点后)

### 盘中版 (entry_timing=open)
- 决策时点: T 日 ≈ 10:00
- 决策视野: T 日 open + T-1 完整 OHLCV (T 日 high/low/close 屏蔽)
- 撮合价: T 日 open (滑点后)
- zhongjun 信号: 用裁剪后数据重算

## 三、回测结果

| 指标 | 尾盘版 close | 盘中版 open |
|---|---:|---:|
| 最终净值 | <填> | <填> |
| 累计收益 | <填>% | <填>% |
| 最大回撤 | <填>% | <填>% |
| 买入笔数 | <填> | <填> |
| 卖出笔数 | <填> | <填> |
| 配对胜率 | <填>% | <填>% |
| 大盘累计 | <填>% | 同 |
| 超额收益 | <填>% | <填>% |

## 四、与 Part 5 / Part 6 对比

| 维度 | Part 5 combo_XG 信号 | Part 6 zhongjun 信号 | Part 8 尾盘 close | Part 8 盘中 open |
|---|---:|---:|---:|---:|
| 类型 | 信号粒度 (固定 N 日卖) | 信号粒度 (固定 N 日卖) | 持仓粒度 (V1.1 卖) | 同 |
| 信号数 / 交易笔数 | 119 (combo) | 6899 (zhongjun) | <填> | <填> |
| 胜率 | 5d 26.9% | 5d 34.3% | <填> (配对胜率) | <填> |
| 平均收益 / 累计收益 | 5d -3.7% | 5d -1.8% | <填> (累计) | <填> |

## 五、结论

- 接入 6+2 + V1.1 + T+1 仓位管理后整体表现 vs 单纯信号回测: <改善 / 持平 / 恶化>
- 尾盘版 vs 盘中版: <尾盘更好 / 盘中更好 / 相当>
- vs 大盘: <跑赢 / 跑输>
- 最大回撤分析
- V1.1 触发卖出的实际效果 (看卖出原因分布)
- 6+2 评分对 zhongjun 候选的过滤效果 (zhongjun_today → score_pass → 实际买入)

**判断**:
- 是否值得接入 QMT 实盘?
- 主要风险点
- 后续建议
```

报告**真实回填**, 禁 placeholder.

### TASK-10. 精确 add + commit (3 文件)

```bash
cd D:/QMT_STRATEGIES
git add huang_main_uptrend_combo/backtest/run_backtest_huang_combo.py
git add huang_main_uptrend_combo/backtest/reports/backtest_report_full_engine_compare.md
git add agent_hub/2026-06-23_huang_main_uptrend/Mimo_HUANG_PART8_FULL_ENGINE_V3.md

git diff --cached --name-only
```

**期望 3 行**:
```
agent_hub/2026-06-23_huang_main_uptrend/Mimo_HUANG_PART8_FULL_ENGINE_V3.md
huang_main_uptrend_combo/backtest/reports/backtest_report_full_engine_compare.md
huang_main_uptrend_combo/backtest/run_backtest_huang_combo.py
```

**staged 不是 3 → 停**.

```bash
git commit -m "$(cat <<'EOF'
feat(huang_combo): Part 8 v3 - zhongjun + 6+2 + V1.1 + 尾盘/盘中对比 (T+1 合规)

诚哥拍板:
1. 黄氏 zhongjun 当动态股票池, 喂 6+2 评分前 3 买入, V1.1 风控出场
2. 不接工厂 (工厂只 next_open), 走独立脚本扩展 --engine full
3. 对比尾盘 close (T 日 14:55) vs 盘中 open (T 日 10:00) 两种入场
4. 严格 A 股 T+1: 买的票 T+1 才能卖, 卖的钱 T+1 才能买

新增 (不动 selector / risk_manager / scoring / production):
- run_backtest_huang_combo.py 加:
  * --engine {hold_periods, full} (默认 hold_periods 向后兼容)
  * --entry-timing {close, open}
  * --max-positions / --initial-cash
- _run_full_engine_backtest 函数:
  * Step 1-2: T+1 现金结算 + 股份解锁
  * Step 3: market_window 按 entry_timing 裁剪 (盘中只见 open)
  * Step 4: zhongjun 当日重算 (盘中版用裁剪数据, 无 look-ahead)
  * Step 5: V1.1 SellStrategyEngine (can_use=available_volume, 锁仓自动跳过)
  * Step 6: 6+2 评分 + 排序 + 入场 (cash_settled, 不用 pending)
  * Step 7: 日终结算 (nav + drawdown)
- 输出 nav_curve.csv + trades.csv + summary.json

3 年回测结果 (huang_small_mid 3633 中小盘):

尾盘版 (entry_timing=close):
- 累计收益: <填>% vs 大盘 <填>%
- 最大回撤: <填>%
- 买入/卖出: <填>/<填> 笔
- 配对胜率: <填>%

盘中版 (entry_timing=open):
- 累计收益: <填>%
- 最大回撤: <填>%
- 买入/卖出: <填>/<填> 笔
- 配对胜率: <填>%

详见 backtest/reports/backtest_report_full_engine_compare.md.

复用 (零侵入):
- core/risk_manager.py V1.1 (commit 503f475)
- backtest/strategies/production/ima_uptrend_v31/scoring_adapter.py (v0.4 reference)
- huang_main_uptrend_combo/huang_main_uptrend_combo_selector.py (SPEC v1.2)
- huicexitong OHLCV + 大盘指数

不动 core/risk_manager.py / scoring/ / production / SPEC / adapters / strategy_*.py /
backtest/engine/.

Refs:
- agent_hub/2026-06-23_huang_main_uptrend/90_hermes_summary.md (双中军 Top 1)
- specs/SPEC_HUANG_MAIN_UPTREND_TDX_TO_QMT.md (v1.2)
EOF
)"

git log -1 --stat HEAD
```

`<填>` 替换成真实数字再 commit. 把完整 commit 输出贴回执.

---

## 二、严禁

1. **严禁** `git add .` / `git add -A` / 整目录 add
2. **严禁** push / amend / --no-verify / --force
3. **严禁** 改 `huang_main_uptrend_combo/huang_main_uptrend_combo_selector.py`
4. **严禁** 改 `core/risk_manager.py` 任何一行
5. **严禁** 改 `core/scoring/dimension6plus2.py` (灰色 dirty 已知, 本工单只 import)
6. **严禁** 改 `backtest/strategies/production/`
7. **严禁** 改 `backtest/engine/` 任何一行 (工厂 next_open 锁死)
8. **严禁** 改 `adapters/qmt_wrapper.py` / `strategy_*.py` / SPEC 文件
9. **严禁** 修改任何默认参数 (6+2 / V1.1 / 黄氏)
10. **严禁** 引入 mock / passorder / xttrader / xtquant
11. **严禁** 写 placeholder 时间戳 / placeholder 数字
12. **严禁段加死**: parse_args 新加参数必须在 _run_full_engine_backtest 函数体内全部被引用
13. **遇任一异常必停**:
    - TASK-1: run_backtest_huang_combo.py 或 core/risk_manager.py dirty → 停
    - TASK-2: V1.1 离线兼容性失败 / can_use 行为异常 → 停
    - TASK-6: hold_periods 模式 smoke 失败 / 现有单测 FAIL → 停
    - TASK-7/8: n_trades = 0 → 必停
    - TASK-7/8: 超 20 分钟 → 停
    - staged 不是 3 个 → 停
    - **不得自判"无关"继续**
14. **回执只能在工单 EOF 追加**

---

## 三、完成回执 (在工单 EOF 追加)

```markdown

---

## 完成回执

**执行时间**: <真实 date -u 输出>
**MIMO 模型**: <实际名>

### TASK-0: 真实时间戳
### TASK-1: 预检
### TASK-2: V1.1 离线 + can_use 探测
<贴 stdout>

### TASK-3-4: parse_args + 分发点
- [ ] --engine / --entry-timing / --max-positions / --initial-cash 4 个参数
- [ ] _run_full_engine_backtest 分发块加入

### TASK-5: _run_full_engine_backtest 函数
- [ ] Step 1-2 T+1 结算 + 解锁
- [ ] Step 3 market_window 裁剪
- [ ] Step 4 zhongjun 当日重算
- [ ] Step 5 V1.1 (can_use=available_volume)
- [ ] Step 6 6+2 评分入场 (cash_settled)
- [ ] Step 7 日终结算

### TASK-6: 向后兼容
<贴 hold_periods smoke 最后 5 行 + 单测 6 PASS 最后 5 行>

### TASK-7: 尾盘版 3 年回测
<贴完整 stdout>

### TASK-8: 盘中版 3 年回测
<贴完整 stdout>

### TASK-9: 对比报告
<贴完整>

### TASK-10: git diff + commit
<贴 3 行 + git log -1 --stat>

### 自检
- [ ] 时间戳真跑 date
- [ ] selector.py 未改
- [ ] core/risk_manager.py 未改
- [ ] core/scoring 未改
- [ ] backtest/strategies/production 未改
- [ ] backtest/engine 未改
- [ ] V1.1 离线兼容 + can_use 锁仓行为正确
- [ ] hold_periods 向后兼容
- [ ] 现有单测全 PASS
- [ ] 尾盘版 n_trades > 0
- [ ] 盘中版 n_trades > 0
- [ ] T+1 合规 (entry_date < T 才解锁, cash_pending_sell 隔日转 settled)
- [ ] 报告含真实数字
- [ ] commit message 含真实数字
- [ ] staged 只有 3 个文件
- [ ] commit 成功
- [ ] 回执在 EOF 追加
```
