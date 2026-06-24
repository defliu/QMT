# coding: utf-8
"""黄氏 zhongjun + 6+2 评分 + V1.1 风控 聚宽尾盘版.

策略逻辑 (实盘等价):
  - 每日 14:55:
    1. 全市场 (中小盘股池) 重算 zhongjun 信号
    2. zhongjun_XG=True 的票送 6+2 评分 (sector_heat=zero)
    3. 已持仓: V1.1 SellStrategyEngine 评估卖出 (按 14:55 close)
    4. 空仓位: 6+2 score>=60 排序前 (max_positions - len(positions)) 入场 (按 14:55 close)
  - 持仓上限: 3
  - 初始资金: 1,000,000
  - T+1: 聚宽 backtest 自动

参考:
  - 黄氏 SPEC v1.2: specs/SPEC_HUANG_MAIN_UPTREND_TDX_TO_QMT.md
  - 6+2 评分: backtest/strategies/production/ima_uptrend_v31/scoring_adapter.py
  - V1.1 风控: core/risk_manager.py
"""
from jqdata import *
import pandas as pd
import numpy as np
import math


# =================================================================
# 配置区
# =================================================================
CFG = {
    'max_positions': 3,
    'min_score': 60.0,
    'min_core': 32.0,
    'max_bias5': 10.0,
    'max_daily_pct': 9.0,

    # V1.1 风控阈值
    'bottom_line_loss_pct': -0.05,
    'bottom_line_daily_drop_pct': -0.07,
    'warning_reduce_pct': 0.30,
    'warning_add_reduce_pct': 0.20,
    'confirm_reduce_pct': 0.50,
    'volume_ratio_threshold': 1.5,
    'volume_diverge_threshold': 0.70,
    'macd_shorten_days': 3,
    'ma5_slope_flat_deg': 15,
    'clear_ma20_days': 3,
    'rebound_window_days': 3,

    # V1.1 移动止盈 (简化: 固定阈值, 非 ATR 自适应)
    'trailing_activate_pct': 0.10,
    'trailing_drawdown_pct': 0.06,

    # 黄氏双中军参数 (SPEC v1.2 §D)
    'zj_ma5': 5, 'zj_ma10': 10, 'zj_ma20': 20, 'zj_ma60': 60, 'zj_ma120': 120,
    'zj_angle_thresh': 30.0,
    'zj_divergence_thresh': 1.05,
    'zj_macd_fast': 12, 'zj_macd_slow': 26, 'zj_macd_signal': 9,
    'zj_cci_period': 14, 'zj_cci_thresh': 100.0,
    'zj_breakout_N': 20, 'zj_breakout_upper': 1.08,
    'zj_ma20_up_n': 5, 'zj_ma60_up_n': 5,

    # 股票池过滤
    'universe_max_mv_yi': 100,
    'history_bars': 130,
}


def initialize(context):
    log.info("=" * 60)
    log.info("黄氏 zhongjun + 6+2 + V1.1 聚宽尾盘版")
    log.info("=" * 60)
    set_benchmark('000001.XSHG')
    set_option('use_real_price', True)
    set_option('avoid_future_data', True)
    set_slippage(FixedSlippage(0.02))
    set_order_cost(OrderCost(
        close_tax=0.001,
        open_commission=0.00025, close_commission=0.00025,
        min_commission=5),
        type='stock')

    # V1.1 全局状态 (聚宽自动跨 bar 保留)
    g.highest_prices = {}
    g.position_states = {}
    g.last_trade_count = 0

    # 14:55 尾盘决策
    run_daily(handle_market_close, time='14:55', reference_security='000001.XSHG')


def before_trading_start(context):
    """开盘前: 同步持仓状态."""
    held = set(context.portfolio.positions.keys())
    for code in list(g.highest_prices.keys()):
        if code not in held:
            del g.highest_prices[code]
    for code in list(g.position_states.keys()):
        if code not in held:
            del g.position_states[code]


def handle_market_close(context):
    """14:55 尾盘决策入口."""
    today = context.current_dt.strftime('%Y-%m-%d')
    log.info('[%s] === 14:55 尾盘决策 ===' % today)

    # === Step 1: 构造中小盘股池 ===
    universe = _get_small_mid_universe(context)
    if not universe:
        log.info('[%s] 股票池为空, 跳过' % today)
        return

    # === Step 2: 重算 zhongjun 信号 ===
    zhongjun_today = _calc_zhongjun_signals(context, universe)
    log.info('[%s] zhongjun 触发: %d 只' % (today, len(zhongjun_today)))

    # === Step 3: V1.1 风控 (已持仓评估) ===
    if context.portfolio.positions:
        _run_v11_risk(context)

    # === Step 4: 6+2 评分 + 入场 ===
    slots = CFG['max_positions'] - len(context.portfolio.positions)
    if slots > 0 and zhongjun_today:
        _run_scoring_and_entry(context, zhongjun_today, slots)

    # === Step 5: 日终统计 ===
    nav = context.portfolio.total_value
    log.info('[%s] 净值=%.2f cash=%.2f positions=%d (%s)' % (
        today, nav, context.portfolio.available_cash,
        len(context.portfolio.positions),
        ','.join(list(context.portfolio.positions.keys())[:5])
    ))


# =================================================================
# Step 1: 中小盘股池
# =================================================================
def _get_small_mid_universe(context):
    """构造中小盘股池 (流通市值 < 100 亿)."""
    try:
        all_stocks = list(get_all_securities(['stock'], date=context.current_dt).index)
    except Exception as e:
        log.error('get_all_securities 失败: %s' % e)
        return []

    q = query(
        valuation.code, valuation.circulating_market_cap
    ).filter(
        valuation.code.in_(all_stocks),
        valuation.circulating_market_cap < CFG['universe_max_mv_yi'],
        valuation.circulating_market_cap > 0,
    )
    try:
        df = get_fundamentals(q, date=context.previous_date)
    except Exception as e:
        log.error('get_fundamentals 失败: %s' % e)
        return []

    if df is None or len(df) == 0:
        return []

    universe = []
    for code in df['code'].tolist():
        info = get_security_info(code, date=context.current_dt)
        if info is None:
            continue
        if 'ST' in info.display_name.upper():
            continue
        universe.append(code)

    return universe


# =================================================================
# TDX 映射函数 (selector.py L48-87 等价)
# =================================================================
def tdx_ma(s, n):
    return s.rolling(window=n, min_periods=n).mean()

def tdx_ema(s, n):
    return s.ewm(alpha=2.0 / (n + 1), adjust=False).mean()

def tdx_ref(s, n):
    return s.shift(n)

def tdx_hhv(s, n):
    return s.rolling(window=n, min_periods=n).max()

def tdx_llv(s, n):
    return s.rolling(window=n, min_periods=n).min()

def tdx_cross(a, b):
    return (a > b) & (a.shift(1) <= b.shift(1))

def tdx_avedev(s, n):
    return s.rolling(window=n, min_periods=n).apply(
        lambda x: np.mean(np.abs(x - np.mean(x))), raw=True
    )

def tdx_count(cond, n):
    return cond.astype(float).rolling(window=n, min_periods=n).sum()


# =================================================================
# Step 2: 黄氏 zhongjun 信号 (SPEC v1.2 §B)
# =================================================================
def _calc_zhongjun_signals(context, universe):
    """对 universe 批量算 zhongjun_XG 信号."""
    today = context.current_dt
    n_bars = CFG['history_bars']

    # 大盘指数
    try:
        bench_df = get_price(
            '000001.XSHG', count=n_bars, end_date=today,
            frequency='1d', fields=['close'],
            skip_paused=False, fq='pre',
        )
    except Exception as e:
        log.error('get_price 大盘失败: %s' % e)
        return []

    if bench_df is None or len(bench_df) < 60:
        return []

    bench_close = bench_df['close']
    idx_ma20 = tdx_ma(bench_close, 20)
    idx_ma60 = tdx_ma(bench_close, 60)
    bench_ok = (bench_close.iloc[-1] > idx_ma20.iloc[-1]) and \
               (idx_ma20.iloc[-1] > idx_ma60.iloc[-1])

    if not bench_ok:
        log.info('[zhongjun] 大盘条件不通过 (close=%.2f MA20=%.2f MA60=%.2f), 跳过' %
                 (bench_close.iloc[-1], idx_ma20.iloc[-1], idx_ma60.iloc[-1]))
        return []

    # 个股批量
    zhongjun_codes = []
    batch_size = 200
    for i in range(0, len(universe), batch_size):
        batch = universe[i:i + batch_size]
        try:
            price_panel = get_price(
                batch, count=n_bars, end_date=today,
                frequency='1d',
                fields=['open', 'close', 'high', 'low', 'volume'],
                skip_paused=False, fq='pre',
            )
        except Exception as e:
            log.warn('get_price batch %d-%d 失败: %s' % (i, i + batch_size, e))
            continue

        if price_panel is None:
            continue

        if isinstance(price_panel, dict):
            iter_items = price_panel.items()
        else:
            iter_items = []
            for code in batch:
                try:
                    if hasattr(price_panel, 'minor_xs'):
                        iter_items.append((code, price_panel.minor_xs(code)))
                    else:
                        iter_items.append((code, price_panel[code]))
                except Exception:
                    continue

        for code, df in iter_items:
            if df is None or len(df) < 120:
                continue
            try:
                ok = _zhongjun_check_single(df, bench_close)
            except Exception:
                continue
            if ok:
                zhongjun_codes.append(code)

    return zhongjun_codes


def _zhongjun_check_single(df, bench_close):
    """单只股票 zhongjun_XG 8 项子条件 (selector._calc_double_zhongjun_conditions 等价)."""
    close = df['close']
    high = df['high']
    low = df['low']

    p = CFG
    MA5 = tdx_ma(close, p['zj_ma5'])
    MA10 = tdx_ma(close, p['zj_ma10'])
    MA20 = tdx_ma(close, p['zj_ma20'])
    MA60 = tdx_ma(close, p['zj_ma60'])
    MA120 = tdx_ma(close, p['zj_ma120'])

    # 1. 多头排列
    ma_align = (MA5.iloc[-1] > MA10.iloc[-1] > MA20.iloc[-1] > MA60.iloc[-1] > MA120.iloc[-1])
    if not ma_align:
        return False

    # 2. 均线发散 (MA5 角度 + MA5/MA20 发散度)
    ma5_prev = MA5.iloc[-2] if len(MA5) >= 2 else MA5.iloc[-1]
    if ma5_prev == 0 or pd.isna(ma5_prev):
        return False
    angle_pct = (MA5.iloc[-1] / ma5_prev - 1.0) * 100.0
    ma5_angle = math.degrees(math.atan(angle_pct))
    diverge_ok = (ma5_angle > p['zj_angle_thresh']) and \
                 (MA5.iloc[-1] / MA20.iloc[-1] > p['zj_divergence_thresh'])
    if not diverge_ok:
        return False

    # 3. MACD: 金叉(DEA>0) 或 DIF/DEA 趋势向上
    DIF = tdx_ema(close, p['zj_macd_fast']) - tdx_ema(close, p['zj_macd_slow'])
    DEA = tdx_ema(DIF, p['zj_macd_signal'])
    macd_cross = (DIF.iloc[-1] > DEA.iloc[-1]) and \
                 (DIF.iloc[-2] <= DEA.iloc[-2] if len(DIF) >= 2 else False) and \
                 (DEA.iloc[-1] > 0)
    macd_trend = (DIF.iloc[-1] > DEA.iloc[-1]) and \
                 (len(DIF) >= 2 and DIF.iloc[-1] > DIF.iloc[-2]) and \
                 (len(DEA) >= 2 and DEA.iloc[-1] > DEA.iloc[-2])
    macd_ok = macd_cross or macd_trend
    if not macd_ok:
        return False

    # 4. CCI: 金叉或趋势向上
    TYP = (high + low + close) / 3.0
    cci_p = p['zj_cci_period']
    cci = (TYP - tdx_ma(TYP, cci_p)) / (0.015 * tdx_avedev(TYP, cci_p))
    cci_cross = (cci.iloc[-1] > p['zj_cci_thresh']) and \
                (cci.iloc[-2] <= p['zj_cci_thresh'] if len(cci) >= 2 else False)
    cci_trend = (cci.iloc[-1] > p['zj_cci_thresh']) and \
                (len(cci) >= 2 and cci.iloc[-1] > cci.iloc[-2])
    cci_ok = cci_cross or cci_trend
    if not cci_ok:
        return False

    # 5. 突破压力位
    bk_N = p['zj_breakout_N']
    near_high = tdx_ref(tdx_hhv(high, bk_N), 1)
    breakthrough_ok = (close.iloc[-1] > near_high.iloc[-1]) and \
                      (close.iloc[-1] / near_high.iloc[-1] < p['zj_breakout_upper'])
    if not breakthrough_ok:
        return False

    # 6 & 7: MA20/MA60 向上
    ma20_up = MA20.iloc[-1] > MA20.iloc[-1 - p['zj_ma20_up_n']] if len(MA20) > p['zj_ma20_up_n'] else False
    ma60_up = MA60.iloc[-1] > MA60.iloc[-1 - p['zj_ma60_up_n']] if len(MA60) > p['zj_ma60_up_n'] else False
    if not (ma20_up and ma60_up):
        return False

    # 8: 大盘条件已在外层判断
    return True


# =================================================================
# Step 3: V1.1 风控 (risk_manager.py SellStrategyEngine 核心等价)
# =================================================================
def _run_v11_risk(context):
    """对已持仓评估 V1.1 卖出.

    简化版 V1.1 (核心 4 层):
      - 底线层: 累计亏损 < -5% OR 单日跌幅 < -7% -> 全清
      - 移动止盈: 浮盈 >=10%, 从高点回撤 >=6% -> 全清
      - 预警层: 量价背离 / MACD红柱缩短 / KDJ死叉 -> 减 30%
      - 确认层: 破10日线 / 高位长上影 / 高位天量收阴 -> 减 50%
    """
    today = context.current_dt

    for code in list(context.portfolio.positions.keys()):
        pos = context.portfolio.positions[code]
        if pos.total_amount <= 0:
            continue
        if pos.closeable_amount <= 0:
            continue

        cost = pos.avg_cost
        if cost <= 0:
            continue

        cur_price = pos.price
        if cur_price <= 0:
            continue

        # 高点跟踪
        if code not in g.highest_prices:
            g.highest_prices[code] = max(cost, cur_price)
        else:
            g.highest_prices[code] = max(g.highest_prices[code], cur_price)
        highest = g.highest_prices[code]

        cum_pnl = (cur_price - cost) / cost

        # ---- 底线层: 累计亏损 < -5% ----
        if cum_pnl <= CFG['bottom_line_loss_pct']:
            log.info('[V1.1 底线-累亏] %s 清仓 cost=%.2f cur=%.2f pnl=%.2f%%' %
                     (code, cost, cur_price, cum_pnl * 100))
            order_target_value(code, 0)
            _clear_state(code)
            continue

        # ---- 底线层: 单日跌幅 < -7% ----
        try:
            prev_df = get_price(code, count=2, end_date=today, frequency='1d',
                                fields=['close'], fq='pre')
            if prev_df is not None and len(prev_df) >= 2:
                prev_close = float(prev_df['close'].iloc[-2])
                if prev_close > 0:
                    daily_drop = (cur_price - prev_close) / prev_close
                    if daily_drop <= CFG['bottom_line_daily_drop_pct']:
                        log.info('[V1.1 底线-日跌] %s 清仓 prev=%.2f cur=%.2f drop=%.2f%%' %
                                 (code, prev_close, cur_price, daily_drop * 100))
                        order_target_value(code, 0)
                        _clear_state(code)
                        continue
        except Exception:
            pass

        # ---- 移动止盈: 浮盈 >=10%, 从高点回撤 >=6% ----
        if cum_pnl >= CFG['trailing_activate_pct']:
            drawdown_from_high = (cur_price - highest) / highest
            if drawdown_from_high <= -CFG['trailing_drawdown_pct']:
                log.info('[V1.1 移动止盈] %s 清仓 cost=%.2f highest=%.2f cur=%.2f draw=%.2f%%' %
                         (code, cost, highest, cur_price, drawdown_from_high * 100))
                order_target_value(code, 0)
                _clear_state(code)
                continue

        # ---- 预警层: 量价背离 / MACD缩短 / KDJ死叉 ----
        state = g.position_states.get(code, {})
        if not state.get('warning_reduced', False):
            try:
                hist_df = get_price(code, count=60, end_date=today, frequency='1d',
                                    fields=['open', 'close', 'high', 'low', 'volume'], fq='pre')
                if hist_df is not None and len(hist_df) >= 30:
                    warn_reasons = _check预警层(hist_df)
                    if warn_reasons:
                        state['warning_reduced'] = True
                        state['warning_reason'] = warn_reasons
                        g.position_states[code] = state
                        sell_pct = CFG['warning_reduce_pct']
                        order_target_value(code, cur_price * pos.total_amount * (1 - sell_pct))
                        log.info('[V1.1 预警] %s 减仓%.0f%% reason=%s' %
                                 (code, sell_pct * 100, warn_reasons))
                        continue
            except Exception:
                pass

        # ---- 确认层: 预警后破10日线 / 长上影 / 天量收阴 ----
        if state.get('warning_reduced', False) and not state.get('confirm_reduced', False):
            try:
                if 'hist_df' not in dir():
                    hist_df = get_price(code, count=60, end_date=today, frequency='1d',
                                        fields=['open', 'close', 'high', 'low', 'volume'], fq='pre')
                if hist_df is not None and len(hist_df) >= 30:
                    confirm_reasons = _check确认层(hist_df)
                    if confirm_reasons:
                        state['confirm_reduced'] = True
                        g.position_states[code] = state
                        sell_pct = CFG['confirm_reduce_pct']
                        order_target_value(code, cur_price * pos.total_amount * (1 - sell_pct))
                        log.info('[V1.1 确认] %s 减仓%.0f%% reason=%s' %
                                 (code, sell_pct * 100, confirm_reasons))
                        continue
            except Exception:
                pass

    # 清理临时变量
    if 'hist_df' in dir():
        del hist_df


def _check预警层(hist_df):
    """预警层 3 信号: 量价背离 / MACD红柱缩短 / KDJ死叉."""
    close = hist_df['close']
    high = hist_df['high']
    low = hist_df['low']
    open_ = hist_df['open']
    volume = hist_df['volume']
    reasons = []

    # B2: 量价背离 (价格创新高但量缩)
    if len(close) >= 6 and len(volume) >= 6:
        price_high = close.iloc[-1] >= close.iloc[-5:].max()
        vol_ratio = volume.iloc[-1] / volume.iloc[-2] if volume.iloc[-2] > 0 else 1
        if price_high and vol_ratio < CFG['volume_diverge_threshold']:
            reasons.append('量价背离')

    # C2: MACD 红柱连续缩短
    if len(close) >= CFG['macd_shorten_days'] + 26:
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        diff = ema12 - ema26
        dea = diff.ewm(span=9, adjust=False).mean()
        macd_bar = 2 * (diff - dea)
        n = CFG['macd_shorten_days']
        if len(macd_bar) >= n + 1 and macd_bar.iloc[-1] > 0:
            shrinking = all(macd_bar.iloc[-1 - i] < macd_bar.iloc[-2 - i] for i in range(n))
            if shrinking:
                reasons.append('MACD红柱缩短')

    # KDJ 死叉 + MA5 走平
    if len(close) >= 15:
        ma5 = close.rolling(5).mean()
        if len(ma5) >= 3:
            prev_ma5 = float(ma5.iloc[-2])
            curr_ma5 = float(ma5.iloc[-1])
            if prev_ma5 > 0:
                pct_chg = abs((curr_ma5 - prev_ma5) / prev_ma5)
                angle = math.degrees(math.atan(pct_chg * 100))
                if angle <= CFG['ma5_slope_flat_deg']:
                    L = low.rolling(9).min()
                    H = high.rolling(9).max()
                    rsv = (close - L) / (H - L) * 100
                    rsv = rsv.fillna(50)
                    k = rsv.ewm(alpha=1.0 / 3, adjust=False).mean()
                    d = k.ewm(alpha=1.0 / 3, adjust=False).mean()
                    if len(k) >= 2 and k.iloc[-1] < d.iloc[-1] and k.iloc[-2] >= d.iloc[-2]:
                        reasons.append('KDJ死叉')

    return ' | '.join(reasons) if reasons else ''


def _check确认层(hist_df):
    """确认层 3 信号: 破10日线 / 高位长上影 / 高位天量收阴."""
    close = hist_df['close']
    high = hist_df['high']
    open_ = hist_df['open']
    volume = hist_df['volume']
    reasons = []

    # A2: 破 10 日线
    if len(close) >= 11:
        ma10 = close.rolling(10).mean()
        if close.iloc[-1] < ma10.iloc[-1]:
            reasons.append('破10日线')

    # C1: 高位长上影
    if len(close) >= 10:
        recent_high = close.iloc[-5:].max()
        compare_price = float(close.iloc[-10])
        if compare_price > 0:
            price_increase = (recent_high - compare_price) / compare_price
            if price_increase >= 0.05:
                candle_body_top = max(close.iloc[-1], open_.iloc[-1])
                upper_shadow = high.iloc[-1] - candle_body_top
                total_range = high.iloc[-1] - min(close.iloc[-1], open_.iloc[-1])
                if total_range > 0 and upper_shadow / total_range >= 0.5:
                    reasons.append('高位长上影')

    # B3: 高位天量收阴
    if len(close) >= 20:
        if close.iloc[-1] < open_.iloc[-1]:
            vol_ma5 = volume.rolling(5).mean()
            if len(vol_ma5) >= 2 and vol_ma5.iloc[-1] > 0:
                if volume.iloc[-1] >= vol_ma5.iloc[-1] * CFG['volume_ratio_threshold']:
                    recent_max = close.iloc[-5:].max()
                    period_max = close.iloc[-20:].max()
                    if recent_max >= period_max * 0.95:
                        reasons.append('高位天量收阴')

    return ' | '.join(reasons) if reasons else ''


def _clear_state(code):
    if code in g.highest_prices:
        del g.highest_prices[code]
    if code in g.position_states:
        del g.position_states[code]


# =================================================================
# Step 4: 6+2 评分 + 入场
# =================================================================
def _run_scoring_and_entry(context, candidates, slots):
    """对 candidates 算 6+2 评分, 排序前 slots 个买入."""
    today = context.current_dt
    n_bars = 60

    scores = []
    for code in candidates:
        if code in context.portfolio.positions:
            continue
        try:
            df = get_price(code, count=n_bars, end_date=today, frequency='1d',
                           fields=['open', 'close', 'high', 'low', 'volume'],
                           fq='pre')
        except Exception:
            continue
        if df is None or len(df) < 60:
            continue

        score = _calc_6plus2_score(df)
        if score is None or score['score_total'] < CFG['min_score']:
            continue
        if score['core_sum'] < CFG['min_core']:
            continue
        if score['bias5'] > CFG['max_bias5']:
            continue
        if abs(score['daily_pct']) > CFG['max_daily_pct']:
            continue
        scores.append({'code': code, 'score': score})

    if not scores:
        return

    scores.sort(key=lambda x: x['score']['score_total'], reverse=True)

    cash_per_slot = context.portfolio.available_cash / slots if slots > 0 else 0
    for s in scores[:slots]:
        if cash_per_slot < 5000:
            break
        try:
            order_target_value(s['code'], cash_per_slot)
            log.info('[买入] %s score=%.1f target=%.0f' %
                     (s['code'], s['score']['score_total'], cash_per_slot))
        except Exception as e:
            log.error('order 失败 %s: %s' % (s['code'], e))


def _calc_6plus2_score(df):
    """6+2 评分: 6 核心维度 + 情绪 + 板块(sector=0).

    对应 scoring_adapter.py score_pool 的简化单股版.
    维度权重 (与 dimension6plus2.py 一致):
      breakout=22, trend=13, consolidation=20, volume_price=12, macd=12, valuation=7, sentiment=7, sector=7
      总分 = core_sum + sentiment + sector = 100 满分
    """
    if df is None or len(df) < 60:
        return None

    close = df['close']
    high = df['high']
    low = df['low']
    volume = df['volume']

    last_c = float(close.iloc[-1])
    if last_c <= 0:
        return None

    # bias5 & daily_pct (过滤用)
    ma5 = tdx_ma(close, 5).iloc[-1]
    bias5 = (last_c - ma5) / ma5 * 100 if ma5 > 0 else 0
    prev_c = float(close.iloc[-2]) if len(close) >= 2 else last_c
    daily_pct = (last_c - prev_c) / prev_c * 100 if prev_c > 0 else 0

    # 5d return
    c_5d_ago = float(close.iloc[-6]) if len(close) >= 6 else float(close.iloc[0])
    ret_5d = (last_c - c_5d_ago) / c_5d_ago * 100 if c_5d_ago > 0 else 0

    # === D1: 突破有效性 (22 分) ===
    resistance = high.rolling(20).max().shift(1)
    amp_20 = high.rolling(20).max() / low.rolling(20).min() - 1
    res_last = _safe_last(resistance)
    amp_last = _safe_last(amp_20)
    close_last = last_c
    is_dense = amp_last <= 0.20
    breakout_pct = (close_last - res_last) / res_last * 100.0 if res_last > 0 else 0
    is_breakout = breakout_pct > 0.0
    vol_ma5 = volume.rolling(5).mean()
    vol_ratio = _safe_last(volume) / _safe_last(vol_ma5) if _safe_last(vol_ma5) > 0 else 0

    if is_breakout and is_dense:
        base = 15.0
    elif is_breakout:
        base = 8.0
    else:
        base = 0.0
    vol_bonus = 7.0 if vol_ratio >= 2.0 else (4.0 if vol_ratio >= 1.2 else 0.0)
    s_breakout = min(base + vol_bonus, 22.0)

    # === D2: 趋势健康 (13 分) ===
    bias_5 = (close_last - float(ma5)) / float(ma5) * 100 if ma5 > 0 else 0
    if 0.0 < bias_5 <= 12.0:
        s_trend = 13.0
    elif 12.0 < bias_5 <= 15.0:
        s_trend = 7.0
    else:
        s_trend = 0.0

    # === D3: 整理强度 (20 分) ===
    ma5_series = tdx_ma(close, 5)
    n_avail = min(5, len(df))
    hold_days = 0
    for i in range(-n_avail, 0):
        thresh = ma5_series.iloc[i] * 0.998
        if pd.notna(thresh) and low.iloc[i] >= thresh:
            hold_days += 1
    if n_avail < 5:
        hold_days = int(round(hold_days * 5.0 / n_avail))
    if hold_days >= 5:
        s_consolidation = 20.0
    elif hold_days == 4:
        s_consolidation = 15.0
    elif hold_days == 3:
        s_consolidation = 10.0
    else:
        s_consolidation = 0.0

    # === D4: 量价健康 (12 分) ===
    if vol_ratio <= 1.5:
        s_volume = 12.0
    elif vol_ratio <= 2.5:
        s_volume = 12.0 * (2.5 - vol_ratio) / 1.0
    else:
        s_volume = 0.0

    # === D5: MACD 动量 (12 分) ===
    if len(close) >= 27:
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        diff = ema12 - ema26
        dea = diff.ewm(span=9, adjust=False).mean()
        macd_bar = 2 * (diff - dea)
        macd_today = _safe_last(macd_bar)
        macd_yesterday = float(macd_bar.iloc[-2]) if len(macd_bar) >= 2 and pd.notna(macd_bar.iloc[-2]) else 0.0
        if macd_today >= macd_yesterday:
            s_macd = 12.0
        elif macd_today > 0 and macd_yesterday > 0:
            s_macd = 6.0
        elif macd_today > 0 and macd_yesterday <= 0:
            s_macd = 9.0
        elif macd_today <= 0 and macd_yesterday > 0:
            s_macd = 3.0
        else:
            s_macd = 0.0
    else:
        s_macd = 0.0

    # === D6: 估值安全 (7 分) — 用 5d 涨幅代替 PE ===
    s_valuation = 7.0 if 5 <= ret_5d <= 20 else max(0, 7.0 - abs(ret_5d - 12) / 2)

    core_sum = s_breakout + s_trend + s_consolidation + s_volume + s_macd + s_valuation

    # === D7: 情绪 (7 分) — 跨截面百分位映射 (简化: 自身 5d return) ===
    if 3 <= ret_5d <= 15:
        s_sentiment = 7.0
    else:
        s_sentiment = max(0, 7.0 - abs(ret_5d - 9) / 2)

    # === D8: 板块热度 (7 分) — sector_heat=zero ===
    s_sector = 3.5

    # 总分 (与 dimension6plus2.py 加权一致)
    score_total = core_sum + s_sentiment + s_sector

    return {
        'score_total': score_total,
        'core_sum': core_sum,
        'bias5': bias5,
        'daily_pct': daily_pct,
        'ret_5d': ret_5d,
    }


def _safe_last(series):
    if series is None or len(series) == 0:
        return 0.0
    val = series.iloc[-1]
    return float(val) if pd.notna(val) else 0.0
