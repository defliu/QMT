# MIMO 工单：黄氏 zhongjun + 6+2 + V1.1 移植到聚宽 (尾盘版)

## 目的

诚哥要在聚宽 (joinquant) 平台跑同一套策略 (zhongjun + 6+2 + V1.1) 做平台对比, 验证 QMT/独立脚本回测和聚宽是否一致, 也看聚宽真实"当日尾盘 14:55 成交"的真实表现.

**输出物**: 1 个聚宽可直接上传的 Python 文件 `huang_main_uptrend_combo/jq_strategies/huang_zhongjun_jq_close.py`, 含 initialize/before_trading_start/handle_func/run_daily 完整聚宽策略结构.

本工单**只做尾盘版** (14:55 决策 + 14:55 撮合). 盘中版 (10:00 决策 + 10:00 撮合) 由 Part-JQ-B 复用本 Part 文件改时间和撮合点.

**前置 commit**: `c82d508` (master HEAD)
**预计工时**: 90-120 分钟

---

## 一、核心要点

### 聚宽与 QMT/工厂的关键差异

| 维度 | QMT/工厂 | 聚宽 |
|---|---|---|
| 撮合时点 | 仅 next_open | `run_daily(time='14:55')` 真支持 14:55 撮合 |
| 数据 API | duckdb_reader + huicexitong | `get_price` / `attribute_history` / `get_all_securities` |
| 大盘指数 | huicexitong 板块指数 000001.SH | 聚宽里上证综指 = `'000001.XSHG'` (注意 .XSHG 后缀) |
| 股票代码格式 | 000001.SZ / 600000.SH | 000001.XSHE / 600000.XSHG |
| 仓位 API | 自管 cash + positions | `context.portfolio.positions` / `order_target_value` |
| 状态持久化 | json 文件 | `g.xxx` 全局对象 (跨 bar 保留) |
| 板块/情绪数据 | sector_heat.json (D:/QMT_POOL) | 聚宽里没有, 6+2 用 zero 模式跳过 |
| 滑点 / 佣金 | yaml 配置 | `set_slippage(FixedSlippage)` + `set_commission` |

### 移植边界

**不需要**:
- selector.py 全部 286 行 (黄氏 SPEC v1.2 完整, 我们只用 double_zhongjun_XG 部分逻辑)
- risk_manager.py 全部 1163 行 (V1.1 含 4 层结构, 我们核心需要的是 evaluate 主入口逻辑)
- dimension6plus2.py 全部 551 行 (6+2 的 6 维 + 情绪 + 板块, 我们用 sector_heat_mode='zero' 跳过板块)
- utils.py 全部 251 行 (只用 calc_ma_angle / calc_bias / detect_volume_price_divergence 等几个)

**需要翻译过去 (估 ~600-800 行单文件)**:
- 8 个 TDX 映射函数 (tdx_ma / tdx_ema / tdx_ref / tdx_hhv / tdx_llv / tdx_cross / tdx_avedev / tdx_count)
- `_calc_double_zhongjun_conditions` 函数 (双中军 8 项子条件)
- 6+2 核心 6 维 + 情绪 (sector zero) 评分逻辑
- V1.1 SellStrategyEngine 核心 evaluate + _evaluate_position 逻辑 (4 层: 底线/预警/确认/清仓 + 移动止盈)

**不翻译**:
- 文件持久化 (state.json) → 改 g.* 全局
- D:/QMT_POOL/sector_heat.json 读取 → 直接 sector_heat_mode='zero'
- 工厂的 daily_engine / portfolio / metrics → 聚宽自管
- T+1 锁仓 → 聚宽 backtest 自动 T+1

---

## 二、必做（8 步）

### TASK-0. 时间戳

```bash
date -u +"%Y-%m-%dT%H:%M:%SZ"
```

### TASK-1. 预检

```bash
cd D:/QMT_STRATEGIES
git log -1 --oneline
ls huang_main_uptrend_combo/jq_strategies/ 2>&1
```

期望:
- HEAD = `c82d508`
- `jq_strategies/` 不存在 (将新建)

把输出贴回执.

### TASK-2. 创建目录 + README

新建:
```
huang_main_uptrend_combo/jq_strategies/
  README.md                                  (说明本目录用途, ~30 行)
  huang_zhongjun_jq_close.py                 (尾盘版聚宽策略, ~600-800 行)
```

**README.md** 内容:

```markdown
# 黄氏 zhongjun + 6+2 + V1.1 聚宽 (joinquant) 策略

## 目的

把 huang_main_uptrend_combo (黄氏 zhongjun 选股) + production/ima_uptrend_v31/scoring_adapter (6+2 评分) + core/risk_manager.py (V1.1 风控) 移植到聚宽平台跑回测.

平台对比目的: 验证 QMT/独立脚本与聚宽的回测一致性, 也看聚宽真实"当日尾盘 14:55 成交"的实际表现.

## 文件

- `huang_zhongjun_jq_close.py`: 尾盘版 (14:55 决策 + 14:55 撮合)
- `huang_zhongjun_jq_open.py`: 盘中版 (10:00 决策 + 10:00 撮合) — Part-JQ-B 生成

## 使用方法

1. 登录聚宽 https://www.joinquant.com
2. 进策略 → 新建 → 复制粘贴对应 .py 文件全文
3. 回测设置:
   - 时间: 2023-06-01 ~ 2026-04-03
   - 初始资金: 1,000,000
   - 频率: 日 (尾盘版) 或 分钟 (盘中版)
   - 标的池: 自定义 (策略内部用 get_all_securities + 市值 < 100亿 过滤构造中小盘池)

## 与本地回测的对应

| 项 | 本地 | 聚宽 |
|---|---|---|
| 选股 | huang_main_uptrend_combo selector.double_zhongjun_XG | 内嵌, 等价复刻 |
| 评分 | production/ima_uptrend_v31/scoring_adapter.score_universe (sector_heat=zero) | 内嵌, 等价复刻 |
| 风控 | core/risk_manager.py V1.1 (commit 503f475) | 内嵌, 等价复刻 |
| 数据源 | huicexitong | 聚宽内置 |
| 撮合 | T 日 close / T+1 next_open | 聚宽 14:55 (尾盘) / 10:00 (盘中) 同日撮合 |

## 已知简化

1. 6+2 板块情绪 (sector_heat) 用 zero 模式跳过 (聚宽里没有 D:/QMT_POOL/sector_heat.json)
2. V1.1 状态持久化用 g.* 全局对象 (聚宽自动跨 bar 保留, 无 json 文件)
3. 股票代码格式: 000001.SZ → 000001.XSHE, 600000.SH → 600000.XSHG

## 参考

- 黄氏 SPEC v1.2: `specs/SPEC_HUANG_MAIN_UPTREND_TDX_TO_QMT.md`
- 本地回测报告: `huang_main_uptrend_combo/backtest/reports/backtest_report_full_engine_compare.md`
- Hermes 双中军评审: `agent_hub/2026-06-23_huang_main_uptrend/90_hermes_summary.md`
```

### TASK-3. 写 `huang_zhongjun_jq_close.py` (主体)

**结构**:

```python
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
  - 黄氏 SPEC v1.2 §A/B/C: specs/SPEC_HUANG_MAIN_UPTREND_TDX_TO_QMT.md
  - 6+2 评分: backtest/strategies/production/ima_uptrend_v31/scoring_adapter.py
  - V1.1 风控: core/risk_manager.py (commit 503f475)
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
    'score_gap_threshold': 15.0,
    
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
    
    # V1.1 移动止盈 (动态阈值)
    'trailing_activate_pct': 0.10,      # 浮盈 10% 激活
    'trailing_drawdown_pct': 0.05,      # 回撤 5% 触发
    
    # 黄氏双中军参数 (SPEC §D)
    'zj_ma5': 5, 'zj_ma10': 10, 'zj_ma20': 20, 'zj_ma60': 60, 'zj_ma120': 120,
    'zj_angle_thresh': 30.0,
    'zj_divergence_thresh': 1.05,
    'zj_macd_fast': 12, 'zj_macd_slow': 26, 'zj_macd_signal': 9,
    'zj_cci_period': 14, 'zj_cci_thresh': 100.0,
    'zj_breakout_N': 20, 'zj_breakout_upper': 1.08,
    'zj_ma20_up_n': 5, 'zj_ma60_up_n': 5,
    
    # 股票池过滤
    'universe_max_mv_yi': 100,  # 流通市值上限 100 亿 (单位: 亿元)
    'history_bars': 130,  # selector 需要至少 120 日, 取 130 保险
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
        close_tax=0.001,       # 印花税
        open_commission=0.00025, close_commission=0.00025,
        min_commission=5),
        type='stock')
    
    # V1.1 全局状态 (聚宽自动跨 bar 保留)
    g.highest_prices = {}      # {code: 跟踪过的最高价}
    g.position_states = {}     # {code: {entry_date, cost_price, ...}}
    g.last_trade_count = 0
    
    # 14:55 尾盘决策 (实盘 14:40-14:57 窗口的代表时点)
    run_daily(handle_market_close, time='14:55', reference_security='000001.XSHG')


def before_trading_start(context):
    """开盘前: 同步持仓状态."""
    # 清掉已平仓的 highest_prices
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
    """构造中小盘股池 (流通市值 < 100 亿).
    
    用聚宽 get_all_securities + valuation 表过滤.
    """
    try:
        all_stocks = list(get_all_securities(['stock'], date=context.current_dt).index)
    except Exception as e:
        log.error('get_all_securities 失败: %s' % e)
        return []
    
    # 用 query + valuation 查流通市值
    from jqdata import finance
    q = query(
        valuation.code, valuation.circulating_market_cap
    ).filter(
        valuation.code.in_(all_stocks),
        valuation.circulating_market_cap < CFG['universe_max_mv_yi'],  # 单位: 亿元
        valuation.circulating_market_cap > 0,
    )
    try:
        df = get_fundamentals(q, date=context.previous_date)
    except Exception as e:
        log.error('get_fundamentals 失败: %s' % e)
        return []
    
    if df is None or len(df) == 0:
        return []
    
    # 排除 ST / 退市 / 停牌
    universe = []
    for code in df['code'].tolist():
        info = get_security_info(code, date=context.current_dt)
        if info is None:
            continue
        # 排除 ST (display_name 含 'ST')
        if 'ST' in info.display_name.upper():
            continue
        universe.append(code)
    
    return universe


# =================================================================
# Step 2: 黄氏 zhongjun 信号 (SPEC v1.2 §B)
# =================================================================
def tdx_ma(s, n):
    return s.rolling(window=n, min_periods=n).mean()

def tdx_ema(s, n):
    return s.ewm(alpha=2.0/(n+1), adjust=False).mean()

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


def _calc_zhongjun_signals(context, universe):
    """对 universe 批量算 zhongjun_XG 信号.
    
    使用聚宽 get_price (一次批量取多股 N 日数据).
    """
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
    
    # 个股批量 (分批避免单次太大)
    zhongjun_codes = []
    batch_size = 200
    for i in range(0, len(universe), batch_size):
        batch = universe[i:i+batch_size]
        try:
            price_panel = get_price(
                batch, count=n_bars, end_date=today,
                frequency='1d',
                fields=['open', 'close', 'high', 'low', 'volume'],
                skip_paused=False, fq='pre',
            )
        except Exception as e:
            log.warn('get_price batch %d-%d 失败: %s' % (i, i+batch_size, e))
            continue
        
        if price_panel is None:
            continue
        
        # 聚宽 multi-stock 返回 dict-like: dict of DataFrame (每只一份)
        # 或者 panel (取决于版本). 标准化访问:
        if isinstance(price_panel, dict):
            iter_items = price_panel.items()
        else:
            # panel-like, transpose access
            iter_items = []
            for code in batch:
                try:
                    iter_items.append((code, price_panel.minor_xs(code) if hasattr(price_panel, 'minor_xs')
                                              else price_panel[code]))
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
    """对单只股票算 zhongjun_XG (复用本地 selector._calc_double_zhongjun_conditions 逻辑).
    
    输入:
        df: pandas DataFrame, index=date, columns=[open/close/high/low/volume]
        bench_close: pandas Series, 大盘 close 序列 (与 df 同长)
    
    返回: True/False (当日 zhongjun_XG)
    """
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
    
    # 2. 均线发散
    ma5_prev = MA5.iloc[-2] if len(MA5) >= 2 else MA5.iloc[-1]
    if ma5_prev == 0 or pd.isna(ma5_prev):
        return False
    angle_pct = (MA5.iloc[-1] / ma5_prev - 1.0) * 100.0
    ma5_angle = math.degrees(math.atan(angle_pct))
    diverge_ok = (ma5_angle > p['zj_angle_thresh']) and \
                 (MA5.iloc[-1] / MA20.iloc[-1] > p['zj_divergence_thresh'])
    if not diverge_ok:
        return False
    
    # 3. MACD
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
    
    # 4. CCI
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
    ma20_up = MA20.iloc[-1] > MA20.iloc[-1-p['zj_ma20_up_n']] if len(MA20) > p['zj_ma20_up_n'] else False
    ma60_up = MA60.iloc[-1] > MA60.iloc[-1-p['zj_ma60_up_n']] if len(MA60) > p['zj_ma60_up_n'] else False
    if not (ma20_up and ma60_up):
        return False
    
    # 8: 大盘条件 (已在外层判断, 此处省略)
    return True


# =================================================================
# Step 3: V1.1 风控
# =================================================================
def _run_v11_risk(context):
    """对已持仓评估 V1.1 卖出.
    
    简化版 V1.1 (核心 4 层 + 移动止盈):
      - 底线层: 累计亏损 < -5% OR 单日跌幅 < -7% → 全清
      - 移动止盈: 浮盈 ≥10%, 从高点回撤 ≥5% → 全清
      - 预警/确认层: (简化), 暂用 -3%/-5% 阶梯减仓
    """
    today = context.current_dt
    
    for code in list(context.portfolio.positions.keys()):
        pos = context.portfolio.positions[code]
        if pos.total_amount <= 0:
            continue
        if pos.closeable_amount <= 0:
            continue  # T+1 锁仓
        
        cost = pos.avg_cost
        if cost <= 0:
            continue
        
        # 取最新价 (当前 bar)
        cur_price = pos.price
        if cur_price <= 0:
            continue
        
        # 移动止盈: 高点跟踪
        if code not in g.highest_prices:
            g.highest_prices[code] = max(cost, cur_price)
        else:
            g.highest_prices[code] = max(g.highest_prices[code], cur_price)
        highest = g.highest_prices[code]
        
        cum_pnl = (cur_price - cost) / cost
        
        # 底线层 1: 累计亏损 < -5%
        if cum_pnl <= CFG['bottom_line_loss_pct']:
            log.info('[V1.1 底线-累亏] %s 清仓 cost=%.2f cur=%.2f pnl=%.2f%%' %
                     (code, cost, cur_price, cum_pnl*100))
            order_target_value(code, 0)
            _clear_state(code)
            continue
        
        # 底线层 2: 单日跌幅 < -7% (取上一交易日 close 计算)
        try:
            prev_df = get_price(code, count=2, end_date=today, frequency='1d',
                                fields=['close'], fq='pre')
            if prev_df is not None and len(prev_df) >= 2:
                prev_close = float(prev_df['close'].iloc[-2])
                if prev_close > 0:
                    daily_drop = (cur_price - prev_close) / prev_close
                    if daily_drop <= CFG['bottom_line_daily_drop_pct']:
                        log.info('[V1.1 底线-日跌] %s 清仓 prev=%.2f cur=%.2f drop=%.2f%%' %
                                 (code, prev_close, cur_price, daily_drop*100))
                        order_target_value(code, 0)
                        _clear_state(code)
                        continue
        except Exception:
            pass
        
        # 移动止盈: 浮盈 ≥10%, 从高点回撤 ≥5%
        if cum_pnl >= CFG['trailing_activate_pct']:
            drawdown_from_high = (cur_price - highest) / highest
            if drawdown_from_high <= -CFG['trailing_drawdown_pct']:
                log.info('[V1.1 移动止盈] %s 清仓 cost=%.2f highest=%.2f cur=%.2f draw=%.2f%%' %
                         (code, cost, highest, cur_price, drawdown_from_high*100))
                order_target_value(code, 0)
                _clear_state(code)
                continue
        
        # (预警层 / 确认层 简化版省略, 黄氏 zhongjun 退出主要靠底线和移动止盈)


def _clear_state(code):
    if code in g.highest_prices:
        del g.highest_prices[code]
    if code in g.position_states:
        del g.position_states[code]


# =================================================================
# Step 4: 6+2 评分 + 入场
# =================================================================
def _run_scoring_and_entry(context, candidates, slots):
    """对 candidates 算 6+2 评分, 排序前 slots 个买入.
    
    6+2 简化版 (sector_heat=zero, 6 核心维度 + 情绪 5d return).
    """
    today = context.current_dt
    n_bars = 60  # 6+2 评分至少需要 60 日历史
    
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
        scores.append({'code': code, **score})
    
    if not scores:
        return
    
    scores.sort(key=lambda x: x['score_total'], reverse=True)
    
    cash_per_slot = context.portfolio.available_cash / slots if slots > 0 else 0
    for s in scores[:slots]:
        if cash_per_slot < 5000:  # 最小买入 5000 元
            break
        try:
            order_target_value(s['code'], cash_per_slot)
            log.info('[买入] %s score=%.1f target=%.0f' %
                     (s['code'], s['score_total'], cash_per_slot))
        except Exception as e:
            log.error('order 失败 %s: %s' % (s['code'], e))


def _calc_6plus2_score(df):
    """6+2 评分核心: 突破 / 趋势 / 整理 / 量价 / MACD / 估值 6 维 + 情绪 (5d return).
    
    sector_heat=zero 模式跳过板块维度.
    返回 {'score_total': float, 'core_sum': float, 'bias5': float, 'daily_pct': float}
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
    
    # bias5
    ma5 = tdx_ma(close, 5).iloc[-1]
    bias5 = (last_c - ma5) / ma5 * 100 if ma5 > 0 else 0
    
    # daily_pct
    prev_c = float(close.iloc[-2]) if len(close) >= 2 else last_c
    daily_pct = (last_c - prev_c) / prev_c * 100 if prev_c > 0 else 0
    
    # 5d return (情绪维度)
    c_5d_ago = float(close.iloc[-6]) if len(close) >= 6 else float(close.iloc[0])
    ret_5d = (last_c - c_5d_ago) / c_5d_ago * 100 if c_5d_ago > 0 else 0
    
    # === 核心 6 维度 (每个 0-10 分) ===
    
    # 1. 突破: close 接近 20 日高点
    high_20 = tdx_hhv(high, 20).iloc[-1]
    s_breakout = min(10.0, max(0.0, last_c / high_20 * 10)) if high_20 > 0 else 0
    
    # 2. 趋势: MA5 > MA10 > MA20 > MA60
    ma10 = tdx_ma(close, 10).iloc[-1]
    ma20 = tdx_ma(close, 20).iloc[-1]
    ma60 = tdx_ma(close, 60).iloc[-1] if len(close) >= 60 else ma20
    s_trend = 0.0
    if ma5 > ma10: s_trend += 2.5
    if ma10 > ma20: s_trend += 2.5
    if ma20 > ma60: s_trend += 2.5
    if last_c > ma5: s_trend += 2.5
    
    # 3. 整理 (60 日震荡幅度小): 振幅 < 30% 给满分
    ll_60 = tdx_llv(low, 60).iloc[-1] if len(low) >= 60 else low.min()
    hh_60 = tdx_hhv(high, 60).iloc[-1] if len(high) >= 60 else high.max()
    if ll_60 > 0:
        amp = (hh_60 - ll_60) / ll_60 * 100
        s_consol = 10.0 if amp < 30 else max(0, 10 - (amp - 30) / 5)
    else:
        s_consol = 0
    
    # 4. 量价: 量比 > 1.5
    vol_5 = tdx_ma(volume, 5).iloc[-1]
    vol_ratio = volume.iloc[-1] / vol_5 if vol_5 > 0 else 0
    s_volume = min(10.0, vol_ratio * 5)
    
    # 5. MACD: DIF > DEA AND DIF > 0
    dif = tdx_ema(close, 12) - tdx_ema(close, 26)
    dea = tdx_ema(dif, 9)
    s_macd = 0.0
    if dif.iloc[-1] > dea.iloc[-1]: s_macd += 5
    if dif.iloc[-1] > 0: s_macd += 5
    
    # 6. 估值 (用 PE 代替, 简化: 用 5d 涨幅替代): 涨幅 5-20% 给满分, 过高扣分
    s_valuation = 10.0 if 5 <= ret_5d <= 20 else max(0, 10 - abs(ret_5d - 12) / 2)
    
    core_sum = s_breakout + s_trend + s_consol + s_volume + s_macd + s_valuation
    
    # === 情绪 (1 维, 0-10): 5d return 适中给高分 ===
    s_sentiment = 10.0 if 3 <= ret_5d <= 15 else max(0, 10 - abs(ret_5d - 9) / 2)
    
    # === 板块 (sector_heat=zero, 直接 0) ===
    s_sector = 0.0
    
    # 总分 = 核心 6 维 * 1.0 + 情绪 0.5 + 板块 0.5
    # (与 production/ima_uptrend_v31/scoring_adapter 加权一致)
    score_total = core_sum + s_sentiment * 0.5 + s_sector * 0.5
    
    return {
        'score_total': score_total,
        'core_sum': core_sum,
        'bias5': bias5,
        'daily_pct': daily_pct,
        'ret_5d': ret_5d,
    }
```

**关键说明** (MIMO 写代码时务必遵守):

1. 上面是**框架**, 具体细节 MIMO 可以补全 (比如 V1.1 的"预警层 / 确认层"如需补强, 可以加).
2. **聚宽 API 兼容性**: `get_price` 在不同聚宽版本返回结构不同, 代码里**已有兜底** (dict / panel 双路径).
3. **股票代码格式**: 聚宽内 SH → XSHG, SZ → XSHE. `get_all_securities` 返回的就是聚宽格式, 不需要转.
4. **不动**: 不要试图重现 6+2 全部 551 行细节 (sector_heat / 板块情绪复杂), 简化 6 维 + 5d 情绪 + sector=0 就够测试用.
5. **V1.1 简化**: 复杂的预警/确认层先省略 (核心 4 层中最常触发的就是底线 + 移动止盈), 后续如果需要补强可以再加.

### TASK-4. 不写单测 (聚宽脚本无法本地跑)

聚宽脚本依赖 `jqdata`、`get_price` 等聚宽专有 API, **本地无法运行单测**. 替代验证:

```bash
cd D:/QMT_STRATEGIES
py -3.10 -c "
# 静态检查: 至少 import 不抛 SyntaxError
import ast
with open('huang_main_uptrend_combo/jq_strategies/huang_zhongjun_jq_close.py', encoding='utf-8') as f:
    src = f.read()
try:
    ast.parse(src)
    print('syntax OK')
except SyntaxError as e:
    print('SYNTAX ERROR:', e)
    raise
# 检查关键函数都定义了
for name in ['initialize', 'before_trading_start', 'handle_market_close',
             'tdx_ma', 'tdx_ema', 'tdx_ref', '_zhongjun_check_single',
             '_run_v11_risk', '_calc_6plus2_score', '_get_small_mid_universe',
             '_run_scoring_and_entry']:
    if name not in src:
        print('MISSING:', name)
        raise SystemExit(1)
print('all required functions present')
print('LOC:', len(src.split(chr(10))))
"
```

期望:
- syntax OK
- all required functions present
- LOC 在 500-900 之间

**FAIL → 停**. 把输出贴回执.

### TASK-5. 写一份操作指南 `huang_main_uptrend_combo/jq_strategies/USAGE.md`

```markdown
# 聚宽策略使用指南

## 上传到聚宽

1. 访问 https://www.joinquant.com → 登录
2. 进 "策略" → "新建策略" → "新建普通策略"
3. 删掉模板, 复制粘贴 `huang_zhongjun_jq_close.py` 全文

## 回测配置

| 项 | 值 |
|---|---|
| 时间 | 2023-06-01 ~ 2026-04-03 |
| 初始资金 | 1,000,000 |
| 频率 | 日 |
| 标的 | 不需手动指定 (策略内部 get_all_securities + 市值过滤) |
| 滑点 | 已在 initialize 设 FixedSlippage(0.02) |
| 手续费 | 已在 initialize 设 (0.025% 佣金 + 0.1% 印花) |

## 等待回测完成后

聚宽会输出:
- 收益曲线图
- 年化 / 最大回撤 / 夏普
- 交易明细

请把以下结果摘抄发回 CC:
- 最终净值
- 累计收益 vs 大盘 (000001.XSHG)
- 最大回撤
- 交易次数 (买入 / 卖出)
- 胜率
- 主要触发原因分布 (V1.1 底线 / 移动止盈 / 单日跌幅)

CC 会跟本地回测 (Part 8 v3 -64.71%) 做对比.

## 常见问题

### Q: 跑得很慢?
A: 每日 14:55 要扫全市场中小盘 ~3000 只算 zhongjun, 单日可能 30-60s, 3 年总共 1-2 小时正常.

### Q: 报错 'finance' module not found?
A: 删掉 `from jqdata import finance` 那行, 用 `valuation.code.in_(...)` 即可.

### Q: 6+2 评分跟本地结果差很多?
A: 聚宽版是简化版 (没接板块情绪, sector=0). 这是已知差异, 设计如此. 报告里标注 "聚宽板块维度=0" 即可.

### Q: V1.1 风控触发频率比本地低?
A: 聚宽版只实现了"底线 + 移动止盈"2 层 (本地 V1.1 是 4 层). 这也是已知简化.
```

### TASK-6. 写完成报告 `huang_main_uptrend_combo/jq_strategies/MIGRATION_REPORT.md`

```markdown
# 聚宽移植报告

## 已实现 (与本地等价)

| 模块 | 本地源 | 聚宽实现 | 等价度 |
|---|---|---|---|
| 黄氏 zhongjun 8 项子条件 | selector.py `_calc_double_zhongjun_conditions` | `_zhongjun_check_single` | 100% |
| TDX 工具函数 (MA/EMA/REF/HHV/LLV/CROSS/AVEDEV) | selector.py L48-85 | 同名函数 | 100% |
| 中小盘股池 (流通市值 < 100 亿) | huicexitong build_universe_small_mid.py | `_get_small_mid_universe` (用 valuation) | 等价 |
| 大盘条件过滤 (000001.SH MA20>MA60) | selector.py | `_calc_zhongjun_signals` 内置 | 100% |

## 简化 (功能保留, 复杂度降低)

| 模块 | 简化项 | 原因 |
|---|---|---|
| 6+2 评分 | 板块情绪 sector_heat 用 zero | 聚宽里没有 D:/QMT_POOL/sector_heat.json. 与本地 baseline.yaml sector_heat_mode='zero' 一致. |
| V1.1 风控 | 4 层中只实现"底线 + 移动止盈"两层 | "预警层"和"确认层"用法少, 简化版可以下次补 |

## 已知差异

| 差异 | 影响 |
|---|---|
| 撮合时点 | 本地 T 日 close, 聚宽 14:55 (接近但非严格相同). 当日 14:55-15:00 间股价波动可能造成偏差 |
| T+1 锁仓 | 本地手工实现, 聚宽自动. 行为应一致, 但需观察 |
| 历史数据 | 本地 huicexitong, 聚宽自有数据. 复权方式、停牌处理可能微差 |

## 不能完全等价的根因

- 6+2 评分本地 551 行, 聚宽版 ~120 行 (核心 6 维 + 情绪): **预期 6+2 评分结果不完全一致**, 但排序结果应相似
- V1.1 本地 1163 行, 聚宽版 ~80 行: 卖出触发频率可能低于本地

## 建议

跑完聚宽回测后, 用以下指标跟本地 Part 8 v3 对照:
- 累计收益 (本地 -64.71%): 偏差 < 20% 视为一致
- 交易次数 (本地 481): 偏差 < 30% 视为一致
- 胜率 (本地 30.7%): 偏差 < 10pp 视为一致
- 最大回撤 (本地 -69.91%): 偏差 < 20pp 视为一致

如果偏差超过上述范围, 是 6+2 / V1.1 简化导致, 不是 bug.
```

### TASK-7. 精确 add + commit (4 文件)

```bash
cd D:/QMT_STRATEGIES
git add huang_main_uptrend_combo/jq_strategies/huang_zhongjun_jq_close.py
git add huang_main_uptrend_combo/jq_strategies/README.md
git add huang_main_uptrend_combo/jq_strategies/USAGE.md
git add huang_main_uptrend_combo/jq_strategies/MIGRATION_REPORT.md
git add agent_hub/2026-06-23_huang_main_uptrend/Mimo_HUANG_PART_JQ_A.md

git diff --cached --name-only
```

**期望 5 行**:
```
agent_hub/2026-06-23_huang_main_uptrend/Mimo_HUANG_PART_JQ_A.md
huang_main_uptrend_combo/jq_strategies/MIGRATION_REPORT.md
huang_main_uptrend_combo/jq_strategies/README.md
huang_main_uptrend_combo/jq_strategies/USAGE.md
huang_main_uptrend_combo/jq_strategies/huang_zhongjun_jq_close.py
```

**staged 不是 5 → 停**.

```bash
git commit -m "$(cat <<'EOF'
feat(huang_combo): 聚宽 (joinquant) 平台移植 Part-JQ-A 尾盘版

诚哥需要在聚宽平台跑同套策略做平台对比.

新增 (不动本地 selector / scoring / risk_manager 任何代码):
- huang_main_uptrend_combo/jq_strategies/huang_zhongjun_jq_close.py
  * 单文件聚宽策略 (~600-800 行)
  * 双中军 zhongjun 8 项子条件 100% 复刻 (SPEC v1.2)
  * 6+2 评分简化版 (核心 6 维 + 情绪, sector=zero)
  * V1.1 风控简化版 (底线 + 移动止盈, 2/4 层)
  * 中小盘股池 (流通市值 < 100 亿, 聚宽 valuation 实时构造)
  * 撮合: run_daily(time='14:55') 真实 14:55 尾盘成交
- README.md / USAGE.md / MIGRATION_REPORT.md

与本地 Part 8 v3 对比基线:
- 本地累计收益: -64.71%, 大盘 +21.08%
- 本地胜率: 30.7%, 交易次数 481
- 聚宽预期偏差 < 20% (因 6+2 简化 + 数据微差)

盘中版 (10:00 决策) 由 Part-JQ-B 完成.

Refs:
- specs/SPEC_HUANG_MAIN_UPTREND_TDX_TO_QMT.md (v1.2)
- huang_main_uptrend_combo/backtest/reports/backtest_report_full_engine_compare.md
EOF
)"

git log -1 --stat HEAD
```

把 commit 完整输出贴回执.

### TASK-8. 最终核查

```bash
cd D:/QMT_STRATEGIES
git status --short huang_main_uptrend_combo/jq_strategies/
ls -la huang_main_uptrend_combo/jq_strategies/
git log -1 --oneline
```

期望:
- `git status` 工作树干净 (无新 dirty)
- 4 个文件齐全
- HEAD 是新 commit

---

## 三、严禁

1. **严禁** `git add .` / `git add -A` / 整目录 add
2. **严禁** push / amend / --no-verify
3. **严禁** 改 `huang_main_uptrend_combo/huang_main_uptrend_combo_selector.py`
4. **严禁** 改 `core/risk_manager.py` / `core/scoring/dimension6plus2.py`
5. **严禁** 改 `backtest/strategies/production/` / `backtest/engine/`
6. **严禁** 改 adapters / strategy_*.py / SPEC
7. **严禁** 引入 mock / passorder / xttrader / xtquant 到聚宽脚本里 (聚宽用 jqdata)
8. **严禁** 用 placeholder 时间戳
9. **严禁** TASK-3 自创聚宽 API (`get_price` / `order_target_value` / `run_daily` 等只能用聚宽真有的 API)
10. **严禁** 写超过 1200 行 (单文件不要太大, 600-800 行刚好)
11. **遇任一异常必停**:
    - TASK-1 HEAD 不是 c82d508 → 停
    - TASK-2 jq_strategies/ 目录已存在 → 停
    - TASK-4 syntax/import 检查失败 → 停
    - staged 不是 5 个 → 停
    - **不得自判"无关"继续**
12. **回执只能在工单 EOF 追加**

---

## 四、完成回执 (在工单 EOF 追加)

```markdown

---

## 完成回执

**执行时间**: <真实 date -u 输出>
**MIMO 模型**: <实际名>

### TASK-0: 真实时间戳
### TASK-1: 预检
### TASK-2: 目录创建
### TASK-3: 策略主文件 huang_zhongjun_jq_close.py
- [ ] 全部 11 个关键函数已实现
- LOC: <填>

### TASK-4: 静态检查
<贴 ast.parse + 函数存在检查输出>

### TASK-5: USAGE.md
### TASK-6: MIGRATION_REPORT.md
### TASK-7: git diff --cached + commit
<贴 5 行 + git log -1 --stat>

### TASK-8: 最终核查

### 自检
- [ ] 时间戳真跑 date
- [ ] selector.py 未改
- [ ] core/risk_manager.py 未改
- [ ] core/scoring 未改
- [ ] backtest/strategies/production 未改
- [ ] 聚宽脚本 syntax OK
- [ ] 11 个关键函数齐全
- [ ] 无聚宽不存在的 API (e.g. 不要写 'order_market_close' 之类自创的)
- [ ] 滑点 / 手续费 / 印花已设
- [ ] 14:55 run_daily 注册
- [ ] T+1 由聚宽自动处理 (本工单未自己实现)
- [ ] staged 只有 5 个文件
- [ ] commit 成功
- [ ] 回执在 EOF 追加
```
