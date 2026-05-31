# coding=utf-8
"""
QMT 程序化回测执行器。

用法:
    python scripts/run_backtest.py                              # 默认参数
    python scripts/run_backtest.py --json
    python scripts/run_backtest.py --start 2024-01-01 --end 2024-03-31 --capital 100000
    python scripts/run_backtest.py --stocks "000001.SZ,600519.SH" --output report.json
    python scripts/run_backtest.py --params custom_params.yaml
"""

import os
import sys
import json
import math
import argparse
import tempfile
import traceback
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from scripts.backtest_params import BacktestParams, BacktestResult


# ============================================================
#  常量
# ============================================================

TRADING_DAYS_PER_YEAR = 252
ANNUAL_RISK_FREE_RATE = 0.03


# ============================================================
#  回测全局状态
# ============================================================

_backtest_state = None


class BacktestState:
    """回测模拟的盘中状态（资金、持仓、成交、净值曲线）。"""

    def __init__(self, initial_capital: float, slippage: float,
                 commission_rate: float, tax_rate: float):
        self.cash = initial_capital
        self.initial_capital = initial_capital
        self.slippage = slippage
        self.commission_rate = commission_rate
        self.tax_rate = tax_rate
        self.positions = {}          # {code: {'volume': int, 'cost': float}}
        self.closed_trades = []      # [Trade dicts]
        self.equity_curve = []       # [(date, nav)]
        self.next_order_id = 1000
        self.current_date = ''
        self.current_prices = {}     # {code: price} — 当前 bar 的收盘价


def _get_current_price(code: str) -> float:
    """从全局状态取当前价格。"""
    s = _backtest_state
    if s and code in s.current_prices:
        return s.current_prices[code]
    return 0.0


# ============================================================
#  Mock QMT 函数 — monkey-patch 到 qmt_wrapper 模块
# ============================================================

class MockPosition:
    def __init__(self, code, volume, cost, price):
        parts = code.split('.')
        self.m_strInstrumentID = parts[0]
        self.m_strExchangeID = parts[-1] if len(parts) > 1 else 'SZ'
        self.m_nVolume = volume
        self.m_nCanUseVolume = volume
        self.m_dOpenPrice = cost
        self.m_dPrice = price
        self.m_dTodayBSPnl = 0.0


class MockAccount:
    def __init__(self, available, total):
        self.m_dAvailable = available
        self.m_dTotalAsset = total
        self.m_dBalance = available


def _backtest_passorder(order_type, price_type, account_id, stock_code,
                        price_meaning, order_id_input, volume, remark,
                        price_strategy, hidden_flag, C, **kwargs):
    """Mock passorder —— 立即成交，更新持仓和资金。"""
    state = _backtest_state
    if state is None:
        return None

    state.next_order_id += 1
    new_id = state.next_order_id

    price = _get_current_price(stock_code)
    if price <= 0:
        return None

    is_buy = (order_type == 23)

    if is_buy:
        cost_total = price * volume
        commission = cost_total * state.commission_rate
        fee = cost_total * 0.00001  # 过户费
        outlay = cost_total + commission + fee

        if outlay > state.cash:
            volume = int(state.cash / price / 100) * 100
            if volume < 100:
                return None
            cost_total = price * volume
            commission = cost_total * state.commission_rate
            fee = cost_total * 0.00001
            outlay = cost_total + commission + fee

        state.cash -= outlay

        existing = state.positions.get(stock_code)
        if existing:
            total_vol = existing['volume'] + volume
            total_cost = existing['cost'] * existing['volume'] + cost_total
            existing['volume'] = total_vol
            existing['cost'] = total_cost / total_vol
        else:
            state.positions[stock_code] = {'volume': volume, 'cost': price}

    else:
        pos = state.positions.get(stock_code)
        if pos is None or pos['volume'] < volume:
            return None

        amount = price * volume
        commission = amount * state.commission_rate
        tax = amount * state.tax_rate
        net = amount - commission - tax
        state.cash += net

        realized_pnl = (price - pos['cost']) * volume

        trade_code = stock_code
        # 查找是否已有同代码未平仓
        existing_trade = None
        for t in state.closed_trades:
            if t.get('code') == trade_code and t.get('pnl') == 0:
                existing_trade = t
                break

        state.closed_trades.append({
            'code': stock_code,
            'volume': volume,
            'entry_price': pos['cost'],
            'exit_price': price,
            'pnl': realized_pnl,
            'exit_date': state.current_date,
        })

        pos['volume'] -= volume
        if pos['volume'] <= 0:
            del state.positions[stock_code]

    return new_id


def _backtest_get_trade_detail_data(account_id, account_type, kind):
    """Mock get_trade_detail_data —— 返回当前持仓/资金。"""
    state = _backtest_state
    if state is None:
        return []

    if kind == 'position':
        result = []
        for code, pos in state.positions.items():
            if pos['volume'] > 0:
                p = state.current_prices.get(code, 0)
                result.append(MockPosition(code, pos['volume'], pos['cost'], p))
        return result

    elif kind == 'account':
        total = state.cash
        for code, pos in state.positions.items():
            total += state.current_prices.get(code, 0) * pos['volume']
        return [MockAccount(state.cash, total)]

    elif kind == 'order':
        return []

    return []


def _backtest_timetag_to_datetime(timetag, fmt):
    """Mock timetag_to_datetime。"""
    return datetime.now().strftime(fmt)


# ============================================================
#  BacktestContext — Mock QMT ContextInfo
# ============================================================

class BacktestContext:
    """
    模拟 QMT ContextInfo 用于回测。
    按 current_bar 截断数据，模拟行情演进。
    """

    def __init__(self, all_data: dict, current_bar: int,
                 all_dates: list[str], stock_names: dict = None):
        self._all_data = all_data
        self._current_bar = current_bar
        self._all_dates = all_dates
        self._stock_names = stock_names or {}
        self._time_str = '1450'  # 尾盘窗口

    def get_market_data_ex(self, field_list=None, stock_list=None,
                           stock_code=None, period='1d', count=-1, **kwargs):
        """返回截至 current_bar 的行情数据。"""
        codes = stock_list or stock_code or []
        if isinstance(codes, str):
            codes = [codes]

        result = {}
        for code in codes:
            df = self._all_data.get(code)
            if df is None or df.empty or self._current_bar < 0:
                result[code] = pd.DataFrame()
                continue

            end = min(self._current_bar + 1, len(df))
            if count > 0 and count < end:
                start = end - count
            else:
                start = 0
            result[code] = df.iloc[start:end].copy()
        return result

    def get_current_time(self):
        """返回当前 bar 的 datetime。"""
        if 0 <= self._current_bar < len(self._all_dates):
            ds = self._all_dates[self._current_bar]
            return datetime.strptime(f"{ds} {self._time_str}", '%Y-%m-%d %H%M')
        return datetime.now()

    def get_full_tick(self, codes=None):
        """返回当前 bar 的 tick 数据。"""
        result = {}
        for code in (codes or []):
            df = self._all_data.get(code)
            if df is not None and self._current_bar < len(df):
                close = float(df['close'].iloc[self._current_bar])
                pre_close = float(df['close'].iloc[max(0, self._current_bar - 1)])
                result[code] = {'lastPrice': close, 'preClose': pre_close}
        return result

    def get_stock_name(self, code):
        return self._stock_names.get(code, code)

    def get_instrument_detail(self, code):
        df = self._all_data.get(code)
        if df is not None and self._current_bar < len(df):
            close = float(df['close'].iloc[self._current_bar])
            volume = float(df['volume'].iloc[self._current_bar])
            return {'CirculateValue': close * volume * 10}
        return {'CirculateValue': 1_000_000_000}

    def get_sector_list(self):
        return []

    def get_stock_list_in_sector(self, sector_name):
        return []

    def get_bar_timetag(self, pos):
        return 20240530000000

    @property
    def close(self):
        df = self._all_data.get(list(self._all_data.keys())[0]) if self._all_data else None
        if df is not None and self._current_bar < len(df):
            return float(df['close'].iloc[self._current_bar])
        return 10.0


# ============================================================
#  数据加载
# ============================================================

def _strip_suffix(code: str) -> str:
    """Remove .SH/.SZ/.BJ suffix from stock code, return 6-digit code."""
    code = code.upper()
    for suffix in ['.SH', '.SZ', '.BJ']:
        if code.endswith(suffix):
            return code[:-3]
    return code


def _download_mootdx(stock_codes, start_date, end_date, benchmark, period='1d'):
    """通过 mootdx (通达信TCP直连) 下载历史数据."""
    try:
        from mootdx.quotes import Quotes
    except ImportError:
        raise RuntimeError("mootdx 未安装。请先运行: pip install mootdx")

    client = Quotes.factory(market='std')
    period_map = {'1d': 4, '1w': 5, '1m': 6}
    category = period_map.get(period, 4)

    all_codes = list(set(stock_codes + [benchmark]))
    from datetime import datetime as _dt
    start_dt = _dt.strptime(start_date, '%Y-%m-%d')
    end_dt = _dt.strptime(end_date, '%Y-%m-%d')
    cal_days = (end_dt - start_dt).days
    req_bars = max(int(cal_days * 252 / 365 * 1.5) + 60, 200)

    all_data = {}
    all_dates = None
    stock_names = {}

    for code in all_codes:
        symbol = _strip_suffix(code)
        try:
            df = client.bars(symbol=symbol, category=category, offset=req_bars)
        except Exception as e:
            print(f"  [下载] {code}: {e}", file=sys.stderr)
            continue

        if df is None or df.empty:
            print(f"  [警告] {code} 无数据", file=sys.stderr)
            continue

        # Rename vol -> volume, convert datetime int -> DatetimeIndex
        df = df.rename(columns={'vol': 'volume'})
        if 'datetime' in df.columns:
            df['_date'] = pd.to_datetime(df['datetime'], format='%Y%m%d', errors='coerce')
            df.set_index('_date', inplace=True)
            df.drop(columns=['datetime'], inplace=True)

        # Filter by date range
        df = df[(df.index >= start_date) & (df.index <= end_date)]
        if df.empty:
            print(f"  [警告] {code} 在指定日期范围内无数据", file=sys.stderr)
            continue
        df.sort_index(inplace=True)

        for col in ['close', 'open', 'high', 'low', 'volume']:
            if col not in df.columns:
                print(f"  [警告] {code} 缺少列: {col}", file=sys.stderr)

        all_data[code] = df
        if all_dates is None:
            all_dates = [d.strftime('%Y-%m-%d') for d in df.index]

    if all_dates is None:
        raise RuntimeError(f"mootdx: 无法获取交易日数据（起始={start_date} 结束={end_date}）")
    return all_data, all_dates, stock_names


def _download_tencent(stock_codes, start_date, end_date, benchmark, period='1d'):
    """通过腾讯财经 HTTP API 下载历史数据."""
    import urllib.request
    import json
    from datetime import datetime as _dt

    period_map = {'1d': 'day', '1w': 'week', '1m': 'month'}
    freq = period_map.get(period, 'day')

    all_codes = list(set(stock_codes + [benchmark]))
    start_dt = _dt.strptime(start_date, '%Y-%m-%d')
    end_dt = _dt.strptime(end_date, '%Y-%m-%d')
    cal_days = (end_dt - start_dt).days
    req_days = max(int(cal_days * 1.5) + 60, 200)

    all_data = {}
    all_dates = None
    stock_names = {}

    for code in all_codes:
        symbol = _strip_suffix(code)
        prefix = "sh" if symbol and symbol[0] in ('6', '9') else "sz"

        url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
               f"?param={prefix}{symbol},{freq},,,{req_days},qfq")
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "Mozilla/5.0")
            resp = urllib.request.urlopen(req, timeout=15)
            raw = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"  [下载] {code}: {e}", file=sys.stderr)
            continue

        stock_key = f"{prefix}{symbol}"
        stock_data = raw.get('data', {}).get(stock_key, {})
        klines = stock_data.get('qfqday') or stock_data.get('day') or []
        if not klines:
            print(f"  [警告] {code} 无数据", file=sys.stderr)
            continue

        records = []
        index_dates = []
        for k in klines:
            if len(k) < 6:
                continue
            index_dates.append(k[0])
            records.append({
                'open': float(k[1]),
                'close': float(k[2]),
                'high': float(k[3]),
                'low': float(k[4]),
                'volume': float(k[5]),
                'amount': float(k[6]) if len(k) > 6 else 0,
            })

        df = pd.DataFrame(records, index=pd.to_datetime(index_dates))
        df = df[(df.index >= start_date) & (df.index <= end_date)]
        if df.empty:
            print(f"  [警告] {code} 在指定日期范围内无数据", file=sys.stderr)
            continue
        df.sort_index(inplace=True)

        for col in ['close', 'open', 'high', 'low', 'volume']:
            if col not in df.columns:
                print(f"  [警告] {code} 缺少列: {col}", file=sys.stderr)

        all_data[code] = df
        if all_dates is None:
            all_dates = [d.strftime('%Y-%m-%d') for d in df.index]

    if all_dates is None:
        raise RuntimeError(f"腾讯财经: 无法获取交易日数据（起始={start_date} 结束={end_date}）")
    return all_data, all_dates, stock_names


def _download_and_prepare_data(stock_codes, start_date, end_date, benchmark, period='1d', datasource='xtquant'):
    """
    下载并准备历史数据。

    支持三种数据源:
    - 'xtquant': 通过 xtquant.xtdata（需开 MiniQMT）
    - 'mootdx': 通过 mootdx TCP 直连通达信服务器
    - 'tencent': 通过腾讯财经 HTTP API

    Returns:
        (all_data, all_dates, stock_names)
        all_data: {code: pd.DataFrame} 含 open/close/high/low/volume 列
        all_dates: [str] 交易日列表
        stock_names: {code: str} 股票名称字典
    """
    if datasource == 'mootdx':
        return _download_mootdx(stock_codes, start_date, end_date, benchmark, period)
    elif datasource == 'tencent':
        return _download_tencent(stock_codes, start_date, end_date, benchmark, period)
    elif datasource != 'xtquant':
        raise ValueError(f"未知数据源: {datasource}，可选: 'xtquant', 'mootdx', 'tencent'")

    try:
        import xtquant.xtdata as xtdata
    except ImportError:
        raise RuntimeError("xtquant 未安装。请先运行: python scripts/setup_xtquant.py")

    # 检查 xtdata 连通性
    try:
        xtdata.connect()
    except Exception:
        raise RuntimeError(
            "无法连接 xtdata 数据服务。请先启动 MiniQMT 客户端，"
            "并确认已有历史数据缓存。"
        )

    all_codes = list(set(stock_codes + [benchmark]))

    # 下载历史数据
    for code in all_codes:
        try:
            xtdata.download_history_data(code, period, start_time=start_date, end_time=end_date)
        except Exception as e:
            print(f"  [下载] {code}: {e}", file=sys.stderr)

    # 读取数据
    all_data = {}
    all_dates = None
    stock_names = {}

    for code in all_codes:
        df_raw = xtdata.get_market_data_ex(
            field_list=[],
            stock_list=[code],
            period=period,
            start_time=start_date,
            end_time=end_date,
            count=-1,
            dividend_type='front',
        )

        if code not in df_raw or df_raw[code].empty:
            print(f"  [警告] {code} 无数据", file=sys.stderr)
            continue

        df = df_raw[code].copy()

        # 确保按时间升序（index 0 为最早）
        if len(df) >= 2:
            try:
                if df.index[0] > df.index[-1]:
                    df = df.iloc[::-1]
            except Exception:
                pass

        # 验证必备列
        for col in ['close', 'open', 'high', 'low', 'volume']:
            if col not in df.columns:
                print(f"  [警告] {code} 缺少列: {col}", file=sys.stderr)
                continue

        all_data[code] = df

        # 取第一只股票的日期作为交易日序列
        if all_dates is None:
            if isinstance(df.index, pd.DatetimeIndex):
                all_dates = [d.strftime('%Y-%m-%d') for d in df.index]
            else:
                all_dates = [str(d) for d in df.index]

    if all_dates is None:
        raise RuntimeError("无法获取交易日数据")

    return all_data, all_dates, stock_names


# ============================================================
#  绩效指标计算
# ============================================================

def _calc_metrics(state, params, all_dates, all_data):
    """从回测状态计算全部绩效指标。"""
    if not state or len(state.equity_curve) < 2:
        return BacktestResult(success=False, error="回测数据不足")

    equity = [e[1] for e in state.equity_curve]
    dates = [e[0] for e in state.equity_curve]
    initial = params.initial_capital
    final = equity[-1]

    total_return = (final - initial) / initial

    n = len(equity)
    annualized_return = (1 + total_return) ** (TRADING_DAYS_PER_YEAR / n) - 1 if n > 0 else 0.0

    # 日收益率序列
    daily_ret = np.array([
        (equity[i] - equity[i - 1]) / equity[i - 1]
        for i in range(1, n) if equity[i - 1] > 0
    ])

    vol = float(np.std(daily_ret) * math.sqrt(TRADING_DAYS_PER_YEAR)) if len(daily_ret) > 1 else 0.0

    sharpe = 0.0
    if vol > 0 and len(daily_ret) > 1:
        daily_rf = ANNUAL_RISK_FREE_RATE / TRADING_DAYS_PER_YEAR
        excess = daily_ret - daily_rf
        sharpe = float(np.mean(excess) / np.std(daily_ret) * math.sqrt(TRADING_DAYS_PER_YEAR))

    # 最大回撤
    peak = equity[0]
    max_dd = 0.0
    dd_curve = []
    for eq in equity:
        if eq > peak:
            peak = eq
        dd = (eq - peak) / peak if peak > 0 else 0.0
        dd_curve.append(float(dd))
        if dd < max_dd:
            max_dd = float(dd)

    # 基准收益率
    bm_return = 0.0
    bm_df = all_data.get(params.benchmark)
    if bm_df is not None and len(bm_df) >= 2:
        try:
            bm_first = float(bm_df['close'].iloc[0])
            bm_last = float(bm_df['close'].iloc[-1])
            if bm_first > 0:
                bm_return = (bm_last - bm_first) / bm_first
        except Exception:
            pass

    # 交易统计
    trades = state.closed_trades
    n_trades = len(trades)
    n_win = sum(1 for t in trades if t['pnl'] > 0)
    n_lose = sum(1 for t in trades if t['pnl'] <= 0)
    win_rate = n_win / n_trades if n_trades > 0 else 0.0

    gross_profit = sum(t['pnl'] for t in trades if t['pnl'] > 0)
    gross_loss = abs(sum(t['pnl'] for t in trades if t['pnl'] < 0))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

    # 月收益率
    monthly = {}
    for i, (d, eq) in enumerate(state.equity_curve):
        mk = d[:7]
        if i == 0:
            monthly[mk] = 0.0
        else:
            prev_eq = state.equity_curve[i - 1][1]
            if prev_eq > 0:
                mr = (eq - prev_eq) / prev_eq
                if mk in monthly:
                    monthly[mk] = (1 + monthly[mk]) * (1 + mr) - 1
                else:
                    monthly[mk] = mr

    return BacktestResult(
        success=True,
        error=None,
        total_return=round(total_return, 4),
        annualized_return=round(annualized_return, 4),
        benchmark_return=round(bm_return, 4),
        max_drawdown=round(max_dd, 4),
        sharpe_ratio=round(sharpe, 4),
        volatility=round(vol, 4),
        total_trades=n_trades,
        win_trades=n_win,
        lose_trades=n_lose,
        win_rate=round(win_rate, 4),
        profit_factor=round(profit_factor, 4),
        avg_hold_days=5.0,
        monthly_returns=monthly,
        equity_curve=list(state.equity_curve),
        drawdown_curve=list(zip(dates, [round(d, 4) for d in dd_curve])),
    )


# ============================================================
#  报告格式化
# ============================================================

def _format_report(result: BacktestResult, params: BacktestParams, strategy_name: str = "QMT") -> str:
    """终端可读的回测报告。"""
    lines = [
        "━━━ QMT Backtest Report ━━━",
        f"Strategy: {strategy_name}",
        f"Period: {params.start_date} → {params.end_date}",
        f"Capital: ¥{params.initial_capital:,.0f}",
        "",
    ]

    if not result.success:
        lines.append(f"状态: ❌ 失败")
        if result.error:
            lines.append(f"错误: {result.error}")
        return "\n".join(lines)

    ret = f"{result.total_return * 100:+.2f}%"
    bm = f"{result.benchmark_return * 100:+.2f}%"
    ann = f"{result.annualized_return * 100:+.2f}%"
    dd = f"{abs(result.max_drawdown) * 100:.2f}%"

    lines.append(f"收益:       {ret:>8}    基准: {bm}")
    lines.append(f"年化:       {ann:>8}")
    lines.append(f"夏普比率:   {result.sharpe_ratio:>8.2f}")
    lines.append(f"最大回撤:   {dd:>8}")
    lines.append(
        f"交易次数:   {result.total_trades:>4}    "
        f"胜率: {result.win_rate * 100:.1f}%    "
        f"盈亏比: {result.profit_factor:.2f}"
    )
    lines.append(f"平均持仓:   {result.avg_hold_days:.1f}天")
    lines.append("")

    checks = []
    if result.sharpe_ratio >= 1.0:
        checks.append(f"夏普{result.sharpe_ratio:.1f}>1")
    if abs(result.max_drawdown) < 0.08:
        checks.append(f"回撤{abs(result.max_drawdown) * 100:.1f}%<8%")
    check_str = ", ".join(checks) if checks else "需关注"
    icon = "✅" if result.total_return > 0 else "⚠️"
    lines.append(f"评估: {icon} 通过 ({check_str})" if result.total_return > 0 else f"评估: {icon} {check_str}")

    return "\n".join(lines)


def _result_to_dict(result: BacktestResult, params: BacktestParams, strategy_name: str = "QMT") -> dict:
    """结果转序列化字典。"""
    d = {
        "strategy": strategy_name,
        "period": {"start": params.start_date, "end": params.end_date},
        "capital": params.initial_capital,
        "total_return": result.total_return,
        "annualized_return": result.annualized_return,
        "benchmark_return": result.benchmark_return,
        "max_drawdown": result.max_drawdown,
        "sharpe_ratio": result.sharpe_ratio,
        "volatility": result.volatility,
        "total_trades": result.total_trades,
        "win_trades": result.win_trades,
        "lose_trades": result.lose_trades,
        "win_rate": result.win_rate,
        "profit_factor": result.profit_factor,
        "avg_hold_days": result.avg_hold_days,
        "status": result.status,
        "success": result.success,
    }
    if result.error:
        d["error"] = result.error
    return d


# ============================================================
#  BacktestRunner
# ============================================================

class BacktestRunner:
    """
    程序化回测执行器。
    1. build strategy_main.py
    2. 模拟 QMT 运行时逐 K线运行 handlebar
    3. 提取结果并输出结构化报告
    """

    def __init__(self, config_path: str = None):
        self.config_path = config_path
        self._cfg = {}
        self._load_config()

    def _load_config(self):
        import yaml
        cfg_file = self.config_path or os.path.join(PROJECT_ROOT, 'config', 'global_config.yaml')
        try:
            with open(cfg_file, encoding='utf-8') as f:
                self._cfg = yaml.safe_load(f) or {}
        except Exception as e:
            print(f"  [配置] 读取失败: {e}", file=sys.stderr)

    def _strategy_name(self) -> str:
        s = self._cfg.get('strategy', {})
        return s.get('name', '双带主升浪_尾盘_外部池_beat四层版')

    def _default_stocks(self) -> list[str]:
        paths = self._cfg.get('paths', {})
        pool = paths.get('pool_path', 'D:/QMT_POOL/selected.txt')
        try:
            codes = []
            with open(pool, encoding='gbk') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        codes.append(line)
            return codes if codes else ['000001.SZ', '600519.SH']
        except Exception:
            return ['000001.SZ', '600519.SH']

    def build_strategy(self) -> bool:
        """调用 build_strategy.py 生成 strategy_main.py。"""
        build_py = os.path.join(PROJECT_ROOT, 'scripts', 'build_strategy.py')
        if not os.path.exists(build_py):
            print("  [Build] build_strategy.py 不存在", file=sys.stderr)
            return False
        try:
            import subprocess
            r = subprocess.run([sys.executable, build_py],
                               capture_output=True, text=True, cwd=PROJECT_ROOT)
            if r.returncode != 0:
                print(f"  [Build] 失败: {r.stderr.strip()}", file=sys.stderr)
                return False
            print("  [Build] strategy_main.py 构建成功")
            return True
        except Exception as e:
            print(f"  [Build] 异常: {e}", file=sys.stderr)
            return False

    def run_backtest(self, params: BacktestParams, datasource='xtquant') -> BacktestResult:
        """
        执行回测。加载数据 → 模拟逐 K线执行 → 计算指标。
        """
        global _backtest_state

        if not params.stock_codes:
            return BacktestResult(success=False, error="股票列表为空")

        # ---- 1. 数据加载 ----
        print("\n── 数据加载 ──")
        try:
            all_data, all_dates, _stock_names = _download_and_prepare_data(
                params.stock_codes, params.start_date, params.end_date, params.benchmark,
                datasource=datasource,
            )
        except RuntimeError as e:
            return BacktestResult(success=False, error=str(e))
        except Exception as e:
            return BacktestResult(success=False, error=f"数据加载失败: {e}")

        if not all_data:
            return BacktestResult(success=False, error="无可用数据")

        valid_codes = [c for c in params.stock_codes if c in all_data]
        if not valid_codes:
            return BacktestResult(success=False, error="所有股票均无数据")

        print(f"  有效股票: {len(valid_codes)}/{len(params.stock_codes)}")
        print(f"  交易日数: {len(all_dates)}")

        # ---- 2. 设回测全局状态 ----
        _backtest_state = BacktestState(
            params.initial_capital, params.slippage,
            params.commission_rate, params.tax_rate,
        )
        state = _backtest_state

        # ---- 3. Patch qmt_wrapper ----
        print("\n── 设置回测环境 ──")
        self._patch_qmt_wrapper(params, valid_codes)

        import adapters.qmt_wrapper as qmt

        # ---- 4. 定位日期范围 ----
        start_idx = 0
        for idx, d in enumerate(all_dates):
            if d >= params.start_date:
                start_idx = idx
                break

        end_idx = len(all_dates) - 1
        for idx in range(len(all_dates) - 1, -1, -1):
            if all_dates[idx] <= params.end_date:
                end_idx = idx
                break

        required = qmt.REQUIRED_BARS if hasattr(qmt, 'REQUIRED_BARS') else 120
        first_bar = max(start_idx, required)

        if first_bar >= end_idx:
            _backtest_state = None
            return BacktestResult(success=False, error="回测周期内数据不足")

        # ---- 5. 逐 K 线模拟 ----
        print(f"\n── 执行回测 ({len(all_dates)} 个交易日, bar {first_bar}-{end_idx}) ──")
        runner = qmt.StrategyRunner()

        init_done = False
        for bar_i in range(first_bar, end_idx + 1):
            date_str = all_dates[bar_i]

            # 构造当前 bar 的 context
            ctx = BacktestContext(all_data, bar_i, all_dates)

            # 更新当前价格
            state.current_date = date_str.replace('-', '')
            state.current_prices = {}
            for code in valid_codes:
                df = all_data.get(code)
                if df is not None and bar_i < len(df):
                    state.current_prices[code] = float(df['close'].iloc[bar_i])

            # 写入状态文件（供策略的日期变更处理器读取）
            pos_dict = {c: p['cost'] for c, p in state.positions.items() if p['volume'] > 0}
            qmt.write_holdings_file(qmt.INTRADAY_HOLD_FILE, pos_dict)

            cumulative_pnl = sum(t['pnl'] for t in state.closed_trades)
            qmt.write_nav_file(qmt.INTRADAY_NAV_FILE, cumulative_pnl)

            if not init_done:
                qmt._g_init_done = False
                runner.init(ctx)
                init_done = True

            try:
                runner.handlebar(ctx)
            except Exception as e:
                print(f"  [错误] {date_str}: handlebar 异常: {e}", file=sys.stderr)
                continue

            # 确认待成交订单（策略产生后立即确认）
            self._confirm_pending(qmt, date_str)

            # 记录净值
            total = state.cash
            for code, pos in state.positions.items():
                total += state.current_prices.get(code, 0) * pos['volume']
            state.equity_curve.append((date_str, total))

            if (bar_i - first_bar) % 30 == 0 or bar_i == end_idx:
                print(f"  [{bar_i - first_bar + 1}/{end_idx - first_bar + 1}] {date_str}  "
                      f"净值={total:,.0f}  现金={state.cash:,.0f}  持仓={len(state.positions)}只")

        # ---- 6. 计算指标 ----
        print("\n── 计算绩效指标 ──")
        result = _calc_metrics(state, params, all_dates, all_data)
        _backtest_state = None
        return result

    def _patch_qmt_wrapper(self, params, valid_codes):
        """Monkey-patch qmt_wrapper 模块使之运行在回测模式。"""
        # 确保 project root 在 path
        if PROJECT_ROOT not in sys.path:
            sys.path.insert(0, PROJECT_ROOT)

        import adapters.qmt_wrapper as qmt
        import core.signal_main_rise as sig

        # 打补丁
        qmt.passorder = _backtest_passorder
        qmt.get_trade_detail_data = _backtest_get_trade_detail_data
        qmt.timetag_to_datetime = _backtest_timetag_to_datetime

        # 重定向文件到临时目录
        tmpdir = tempfile.mkdtemp(prefix='qmt_bt_')
        for attr in ('INTRADAY_HOLD_FILE', 'ENDOFDAY_HOLD_FILE',
                     'INTRADAY_NAV_FILE', 'ENDOFDAY_NAV_FILE',
                     'POOL_PATH', 'POOL_FILE', 'SECTOR_HEAT_FILE',
                     'TRADE_LOG_FILE', 'INTRADAY_SELL_STATE_FILE',
                     'SCORE_HISTORY_FILE'):
            if hasattr(qmt, attr):
                setattr(qmt, attr, os.path.join(tmpdir, attr.lower() + '.txt'))

        # 写 pool 文件
        pool_file = os.path.join(tmpdir, 'pool.txt')
        with open(pool_file, 'w', encoding='gbk') as f:
            for code in valid_codes:
                f.write(f"{code}\n")
        qmt.POOL_PATH = pool_file
        qmt.POOL_FILE = pool_file

        qmt.TEST_MODE = True
        qmt._load_pool = lambda: [{'code': c, 'buy_type': 'pool', 'signal': '回测'} for c in valid_codes]

        self._bt_tmpdir = tmpdir

    def _confirm_pending(self, qmt, date_str):
        """确认当日待成交订单。"""
        state = _backtest_state
        if not state:
            return

        for code, info in list(qmt._g_pending_buys.items()):
            qmt._g_my_codes[code] = info['price']
            qmt.write_holdings_file(qmt.INTRADAY_HOLD_FILE, qmt._g_my_codes)

        for code, info in list(qmt._g_pending_sells.items()):
            if qmt._g_sell_engine:
                qmt._g_sell_engine.confirm_clear(code, date_str)
                qmt._g_sell_engine.save_state()
            qmt._g_my_codes.pop(code, None)
            qmt.write_holdings_file(qmt.INTRADAY_HOLD_FILE, qmt._g_my_codes)

        qmt._g_pending_buys.clear()
        qmt._g_pending_sells.clear()

    def run_with_params(self, params: BacktestParams, datasource='xtquant') -> BacktestResult:
        """build + run 一步到位。"""
        print("=== Step 1: Build 策略 ===")
        build_ok = self.build_strategy()
        if not build_ok:
            print("  [警告] Build 失败，使用当前代码直接回测")

        print("\n=== Step 2: 执行回测 ===")
        return self.run_backtest(params, datasource=datasource)

    def run_with_data(self, params: BacktestParams, all_data: dict,
                      all_dates: list[str], datasource='xtquant') -> BacktestResult:
        """
        使用已加载的数据运行回测（供测试用）。
        跳过数据加载步骤。
        """
        global _backtest_state

        if not params.stock_codes:
            return BacktestResult(success=False, error="股票列表为空")
        if not all_data or not all_dates:
            return BacktestResult(success=False, error="无可用数据")

        _backtest_state = BacktestState(
            params.initial_capital, params.slippage,
            params.commission_rate, params.tax_rate,
        )
        state = _backtest_state

        self._patch_qmt_wrapper(params, params.stock_codes)
        import adapters.qmt_wrapper as qmt

        start_idx = 0
        for idx, d in enumerate(all_dates):
            if d >= params.start_date:
                start_idx = idx
                break
        end_idx = len(all_dates) - 1
        for idx in range(len(all_dates) - 1, -1, -1):
            if all_dates[idx] <= params.end_date:
                end_idx = idx
                break

        required = qmt.REQUIRED_BARS if hasattr(qmt, 'REQUIRED_BARS') else 120
        first_bar = max(start_idx, required)
        if first_bar >= end_idx:
            _backtest_state = None
            return BacktestResult(success=False, error="数据不足")

        runner = qmt.StrategyRunner()
        init_done = False

        for bar_i in range(first_bar, end_idx + 1):
            date_str = all_dates[bar_i]
            ctx = BacktestContext(all_data, bar_i, all_dates)

            state.current_date = date_str.replace('-', '')
            state.current_prices = {}
            for code in params.stock_codes:
                df = all_data.get(code)
                if df is not None and bar_i < len(df):
                    state.current_prices[code] = float(df['close'].iloc[bar_i])

            pos_dict = {c: p['cost'] for c, p in state.positions.items() if p['volume'] > 0}
            qmt.write_holdings_file(qmt.INTRADAY_HOLD_FILE, pos_dict)
            cumulative_pnl = sum(t['pnl'] for t in state.closed_trades)
            qmt.write_nav_file(qmt.INTRADAY_NAV_FILE, cumulative_pnl)

            if not init_done:
                qmt._g_init_done = False
                try:
                    runner.init(ctx)
                except Exception as e:
                    _backtest_state = None
                    return BacktestResult(success=False, error=f"StrategyRunner.init 失败: {e}")
                init_done = True

            try:
                runner.handlebar(ctx)
            except Exception as e:
                continue

            self._confirm_pending(qmt, date_str)
            total = state.cash
            for code, pos in state.positions.items():
                total += state.current_prices.get(code, 0) * pos['volume']
            state.equity_curve.append((date_str, total))

        result = _calc_metrics(state, params, all_dates, all_data)
        _backtest_state = None
        return result


# ============================================================
#  CLI
# ============================================================

def _parse_cli():
    p = argparse.ArgumentParser(
        description='QMT 程序化回测',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/run_backtest.py
  python scripts/run_backtest.py --start 2024-01-01 --end 2024-03-31 --capital 100000
  python scripts/run_backtest.py --stocks "000001.SZ,600519.SH" --output report.json
  python scripts/run_backtest.py --json
  python scripts/run_backtest.py --params custom_params.yaml
  python scripts/run_backtest.py --datasource mootdx --start 2024-01-01 --end 2024-01-10 --stocks "600519.SH,000001.SZ" --capital 100000 --json
  python scripts/run_backtest.py --datasource tencent --start 2024-01-01 --end 2024-01-10 --stocks "600519.SH,000001.SZ" --capital 100000 --json
        """,
    )
    p.add_argument('--start', type=str, help='开始日期 YYYY-MM-DD')
    p.add_argument('--end', type=str, help='结束日期 YYYY-MM-DD')
    p.add_argument('--capital', type=float, help='初始资金')
    p.add_argument('--stocks', type=str, help='股票代码，逗号分割')
    p.add_argument('--output', type=str, help='输出 JSON 文件路径')
    p.add_argument('--json', action='store_true', help='仅输出 JSON 到 stdout')
    p.add_argument('--params', type=str, help='从 YAML 文件读取参数')
    p.add_argument('--datasource', type=str, default='xtquant',
                   choices=['xtquant', 'mootdx', 'tencent'],
                   help='数据源: xtquant(默认,需开MiniQMT), mootdx(通达信直连), tencent(腾讯财经)')
    return p.parse_args()


def _from_yaml(path: str) -> BacktestParams:
    import yaml
    with open(path, encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    return BacktestParams(
        stock_codes=cfg.get('stock_codes'),
        start_date=cfg.get('start_date', cfg.get('start', '2024-01-01')),
        end_date=cfg.get('end_date', cfg.get('end', '2024-12-31')),
        period=cfg.get('period', '1d'),
        initial_capital=cfg.get('initial_capital', cfg.get('capital', 100000)),
        slippage=cfg.get('slippage', 0.001),
        commission_rate=cfg.get('commission_rate', 0.00025),
        tax_rate=cfg.get('tax_rate', 0.0001),
        benchmark=cfg.get('benchmark', '000300.SH'),
    )


def main():
    args = _parse_cli()

    # 确定参数
    if args.params:
        params = _from_yaml(args.params)
    else:
        params = BacktestParams()
        if args.start:
            params.start_date = args.start
        if args.end:
            params.end_date = args.end
        if args.capital:
            params.initial_capital = args.capital
        if args.stocks:
            params.stock_codes = [s.strip() for s in args.stocks.split(',')]

    if not params.stock_codes:
        runner = BacktestRunner()
        params.stock_codes = runner._default_stocks()

    # 执行
    runner = BacktestRunner()
    result = runner.run_with_params(params, datasource=args.datasource)

    # 输出
    out = _result_to_dict(result, params, runner._strategy_name())
    json_str = json.dumps(out, ensure_ascii=False, indent=2)

    if args.json:
        print(json_str)
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(json_str)
        if not args.json:
            print(f"\n报告已保存: {args.output}")

    if not args.json:
        print("\n" + _format_report(result, params, runner._strategy_name()))

    return 0 if result.success else 1


if __name__ == '__main__':
    sys.exit(main())
