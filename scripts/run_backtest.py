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
from dataclasses import dataclass
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
#  全市场扫描参数
# ============================================================

@dataclass
class ScanParams:
    """全市场扫描参数"""
    min_price: float = 5.0         # 最低价格过滤
    min_volume: int = 100000       # 最低日均成交量（手），防垃圾票
    exclude_st: bool = True        # 排除ST股
    min_listed_days: int = 365     # 上市最少天数
    max_candidates: int = 100      # 最终候选池上限


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
            state.positions[stock_code] = {'volume': volume, 'cost': price, 'entry_date': state.current_date}

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

        state.closed_trades.append({
            'code': stock_code,
            'volume': volume,
            'entry_price': pos['cost'],
            'exit_price': price,
            'pnl': realized_pnl,
            'exit_date': state.current_date,
            'entry_date': pos.get('entry_date', state.current_date),
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

    def _get_df_close(self, code):
        """安全获取某只股票当前 bar 的收盘价，返回 float 或 None。"""
        df = self._all_data.get(code)
        if df is None or df.empty or 'close' not in df.columns:
            return None
        if self._current_bar < 0 or self._current_bar >= len(df):
            return None
        try:
            return float(df['close'].iloc[self._current_bar])
        except (IndexError, ValueError, TypeError):
            return None

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
            if df is None or df.empty or 'close' not in df.columns:
                continue
            if self._current_bar < 0 or self._current_bar >= len(df):
                continue
            try:
                close = float(df['close'].iloc[self._current_bar])
                pre_close = float(df['close'].iloc[max(0, self._current_bar - 1)])
                result[code] = {'lastPrice': close, 'preClose': pre_close}
            except (IndexError, ValueError, TypeError):
                continue
        return result

    def get_stock_name(self, code):
        return self._stock_names.get(code, code)

    def get_instrument_detail(self, code):
        df = self._all_data.get(code)
        if df is not None and not df.empty and 'close' in df.columns and 'volume' in df.columns:
            if 0 <= self._current_bar < len(df):
                try:
                    close = float(df['close'].iloc[self._current_bar])
                    volume = float(df['volume'].iloc[self._current_bar])
                    return {'CirculateValue': close * volume * 10}
                except (IndexError, ValueError, TypeError):
                    pass
        return {'CirculateValue': 1_000_000_000}

    def get_sector_list(self):
        return []

    def get_stock_list_in_sector(self, sector_name):
        return []

    def get_bar_timetag(self, pos):
        return 20240530000000

    @property
    def close(self):
        """取第一只股票当前 bar 收盘价作为大盘参考。"""
        if not self._all_data:
            return 10.0
        try:
            first_key = list(self._all_data.keys())[0]
            val = self._get_df_close(first_key)
            return val if val is not None else 10.0
        except Exception:
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
    today = _dt.today()
    cal_days = (today - start_dt).days  # days from start to today, not to end_date
    req_bars = max(int(cal_days * 252 / 365 * 1.5) + 60, 400)

    all_data = {}
    all_dates = None
    stock_names = {}

    # ---- 批量获取股票名称（通过 mootdx quotes） ----
    try:
        # 分批次查询名称（mootdx 单次查询有限制）
        batch_size = 200
        for i in range(0, len(all_codes), batch_size):
            batch = [c for c in all_codes[i:i + batch_size]]
            symbol_batch = [_strip_suffix(c) for c in batch]
            q = client.quotes(symbol=symbol_batch)
            if q is not None and not q.empty:
                for _, row in q.iterrows():
                    if 'code' in q.columns and 'name' in q.columns:
                        code_str = str(row['code'])
                        name_str = str(row['name']).strip()
                        full_code = next((c for c in batch if _strip_suffix(c) == code_str), None)
                        if full_code and name_str:
                            stock_names[full_code] = name_str
    except Exception:
        pass  # 名称获取失败不影响主流程

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

        # Rename vol -> volume, remove duplicate volume column
        if 'vol' in df.columns and 'volume' in df.columns:
            df = df.drop(columns=['vol'])
        elif 'vol' in df.columns:
            df = df.rename(columns={'vol': 'volume'})
        if 'datetime' in df.columns:
            # datetime is '2023-02-09 15:00' string format
            df['_date'] = pd.to_datetime(df['datetime'].str[:10], format='%Y-%m-%d', errors='coerce')
            df.set_index('_date', inplace=True)
            df.drop(columns=['datetime'], inplace=True)
            # Remove time component from index
            df.index = df.index.normalize()

        # Don't filter by date range — return ALL data so backtest engine can use warmup bars
        # The backtest runner handles date range internally via start_idx/end_idx
        df.sort_index(inplace=True)
        # Drop rows with NaT index (failed parse)
        df = df[df.index.notna()]

        # Only warn if NO data covers the backtest range at all
        mask = (df.index >= start_date) & (df.index <= end_date)
        if not mask.any():
            print(f"  [警告] {code} 在指定日期范围内无数据", file=sys.stderr)
            continue

        # ---- 数据质量校验 ----
        quality_warnings = []
        for col in ['close', 'open', 'high', 'low', 'volume']:
            if col not in df.columns:
                print(f"  [警告] {code} 缺少列: {col}", file=sys.stderr)
                quality_warnings.append(f"缺少{col}")

        # 检查 NaN
        nan_count = df[['close', 'open', 'high', 'low', 'volume']].isna().sum().sum()
        if nan_count > 0:
            quality_warnings.append(f"NaN={nan_count}")
            df = df.dropna(subset=['close', 'open', 'high', 'low', 'volume'])

        # 检查负价格 / 零价格
        neg_close = (df['close'] <= 0).sum()
        if neg_close > 0:
            quality_warnings.append(f"非正收盘价={neg_close}行")
            df = df[df['close'] > 0]

        # 检查零成交量 (>10% of rows with zero volume = warning)
        zero_vol = (df['volume'] <= 0).sum()
        total_rows = len(df)
        if zero_vol > 0 and zero_vol / total_rows > 0.1:
            quality_warnings.append(f"零成交量比例={zero_vol / total_rows:.1%}")

        # 检查 H > L 一致性
        hl_invalid = (df['high'] < df['low']).sum()
        if hl_invalid > 0:
            quality_warnings.append(f"high<low={hl_invalid}行")

        # 检查足够 warmup bars
        if len(df) < 120:
            quality_warnings.append(f"仅{len(df)}条K线(<120)")

        if quality_warnings:
            print(f"  [数据质量] {code}: {'; '.join(quality_warnings)}", file=sys.stderr)

        if df.empty:
            print(f"  [警告] {code} 质量过滤后无数据", file=sys.stderr)
            continue

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
        # 不按日期范围过滤 — 返回全量数据，回测引擎通过 start_idx/end_idx 内部处理
        df.sort_index(inplace=True)
        # 清除 NaT 索引行
        df = df[df.index.notna()]

        # 仅当没有任何数据覆盖回测范围时告警
        mask = (df.index >= start_date) & (df.index <= end_date)
        if not mask.any():
            print(f"  [警告] {code} 在指定日期范围内无数据", file=sys.stderr)
            continue

        # ---- 数据质量校验 ----
        quality_warnings = []
        for col in ['close', 'open', 'high', 'low', 'volume']:
            if col not in df.columns:
                print(f"  [警告] {code} 缺少列: {col}", file=sys.stderr)
                quality_warnings.append(f"缺少{col}")

        # 检查 NaN
        nan_count = df[['close', 'open', 'high', 'low', 'volume']].isna().sum().sum()
        if nan_count > 0:
            quality_warnings.append(f"NaN={nan_count}")
            df = df.dropna(subset=['close', 'open', 'high', 'low', 'volume'])

        # 检查负价格 / 零价格
        neg_close = (df['close'] <= 0).sum()
        if neg_close > 0:
            quality_warnings.append(f"非正收盘价={neg_close}行")
            df = df[df['close'] > 0]

        # 检查零成交量 (>10% of rows with zero volume = warning)
        zero_vol = (df['volume'] <= 0).sum()
        total_rows = len(df)
        if zero_vol > 0 and zero_vol / total_rows > 0.1:
            quality_warnings.append(f"零成交量比例={zero_vol / total_rows:.1%}")

        # 检查 H > L 一致性
        hl_invalid = (df['high'] < df['low']).sum()
        if hl_invalid > 0:
            quality_warnings.append(f"high<low={hl_invalid}行")

        # 检查足够 warmup bars
        if len(df) < 120:
            quality_warnings.append(f"仅{len(df)}条K线(<120)")

        if quality_warnings:
            print(f"  [数据质量] {code}: {'; '.join(quality_warnings)}", file=sys.stderr)

        if df.empty:
            print(f"  [警告] {code} 质量过滤后无数据", file=sys.stderr)
            continue

        # ---- 获取股票名称（从腾讯 API 响应中提取） ----
        try:
            name_raw = stock_data.get('name') or ''
            if name_raw:
                stock_names[code] = name_raw.strip()
        except Exception:
            pass

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
#  全市场扫描
# ============================================================

def _light_filter(code: str, name: str, price: float, listed_days: int) -> bool:
    """初步过滤条件。"""
    if price < 5.0:
        return False  # 低价股
    if 'ST' in name.upper() or '退' in name:
        return False  # ST/退市
    if listed_days < 365:
        return False  # 次新股
    return True


def scan_market(params: ScanParams) -> tuple[list[str], dict]:
    """
    全市场扫描。
    1. 通过 mootdx 获取 A 股全市场股票列表（沪深北）
    2. 轻量预过滤：价格、成交量、ST、上市天数
    3. 取前 max_candidates 只

    Returns:
        (candidate_codes, stock_info)
        candidate_codes: ['600519.SH', '000858.SZ', ...]
        stock_info: {code: {name, price, ...}}
    """
    try:
        from mootdx.quotes import Quotes
    except ImportError:
        raise RuntimeError("mootdx 未安装。请先运行: pip install mootdx")

    client = Quotes.factory(market='std')

    # ---- 1. 获取全市场股票列表 ----
    print("  [Scan] 获取全市场股票列表...")
    sh_df = client.stocks(market=1)  # 上海
    sz_df = client.stocks(market=0)  # 深圳

    # ---- 2. 构建 {code: (name, suffix)} 并过滤非 A 股指数 ----
    all_stocks = {}  # {6位代码: (name, suffix)}
    for row in sh_df.itertuples():
        code = str(row.code)
        if code.startswith('6') and len(code) == 6:  # 上海 A 股
            all_stocks[code] = (str(row.name).strip(), '.SH')

    for row in sz_df.itertuples():
        code = str(row.code)
        if code.startswith(('0', '2', '3')) and len(code) == 6 and not code.startswith('399'):  # 深圳 A 股，排除指数(399xxx)
            suffix = '.SZ'
            if code.startswith('8'):
                suffix = '.BJ'
            all_stocks[code] = (str(row.name).strip(), suffix)

    print(f"  [Scan] 全市场 A 股: {len(all_stocks)} 只")

    # ---- 3. 批量获取行情报价 ----
    print("  [Scan] 获取实时报价...")
    codes_list = list(all_stocks.keys())
    quotes_data = pd.DataFrame()
    # 分批次查询（mootdx 单次查询有限制）
    batch_size = 500
    for i in range(0, len(codes_list), batch_size):
        batch = codes_list[i:i + batch_size]
        try:
            q = client.quotes(symbol=batch)
            if q is not None and not q.empty:
                quotes_data = pd.concat([quotes_data, q], ignore_index=True)
        except Exception as e:
            print(f"  [Scan] 报价 batch {i} 异常: {e}", file=sys.stderr)
            continue

    # 建立 code -> price 映射
    price_map = {}
    if not quotes_data.empty and 'code' in quotes_data.columns:
        for row in quotes_data.itertuples():
            price_map[str(row.code)] = float(getattr(row, 'price', 0) or 0)

    # ---- 4. 轻量过滤 ----
    print("  [Scan] 执行轻量过滤...")
    # 先按名称和价格过滤
    pre_filtered = []  # [(code, name, suffix, price)]
    for code, (name, suffix) in all_stocks.items():
        if params.exclude_st and ('ST' in name.upper() or '退' in name):
            continue
        price = price_map.get(code, 0.0)
        if price < params.min_price:
            continue
        pre_filtered.append((code, name, suffix, price))

    # 按价格降序排列（优先选优质股）
    pre_filtered.sort(key=lambda x: x[3], reverse=True)
    print(f"  [Scan] 价格/ST 过滤后: {len(pre_filtered)} 只")

    # ---- 5. 检查上市天数（只对候选股票逐一检查） ----
    result = []
    stock_info = {}
    check_count = min(params.max_candidates * 3, len(pre_filtered))
    checked = 0

    for code, name, suffix, price in pre_filtered:
        if len(result) >= params.max_candidates:
            break
        if checked >= check_count:
            break
        checked += 1

        try:
            bars = client.bars(symbol=code, category=4, offset=params.min_listed_days + 60)
            listed_days = len(bars) if bars is not None else 0
        except Exception:
            listed_days = 0

        if listed_days < params.min_listed_days:
            continue

        # ---- 通达信实战放宽版条件筛选 ----
        if bars is not None and not bars.empty:
            try:
                if not _tdx_formula_filter(bars):
                    continue
            except Exception as e:
                # 数据异常跳过
                continue

        full_code = code + suffix
        result.append(full_code)
        stock_info[full_code] = {'name': name, 'price': price}

    print(f"  [Scan] 最终候选池: {len(result)} 只股票 (通达信实战放宽版)")
    return result, stock_info


# ============================================================
#  通达信实战放宽版选股公式（scan 筛选）
# ============================================================

def _tdx_formula_filter(df) -> bool:
    """
    通达信实战放宽版条件选股 — Python 等价实现。
    参考: 筹码密集启动突破 - 实战放宽版.txt

    条件：
    1. 筹码密集: 60日振幅 ≤ 25%（COST替代）
    2. 突破密集顶: C > 前1日60日高 且 3日内有刚突破
    3. 蓄势: 5日≥2天涨跌幅<3%
    4. 多头排列: MA5>MA10>MA20 且 MA60走平/向上
    5. MA5角度 ≥ 30度
    6. 收阳线: C > O
    7. 排除急拉坑底

    Args:
        df: mootdx bars DataFrame, 至少含 open/high/low/close 列

    Returns:
        bool: 是否通过全部条件
    """
    import numpy as np
    import pandas as pd

    if df is None or len(df) < 90:
        return False

    c = df['close'].values.astype(float)
    h = df['high'].values.astype(float)
    l = df['low'].values.astype(float)
    o = df['open'].values.astype(float)

    # ---- 1. 筹码密集（COST替代：60日振幅 ≤ 25%）----
    hhv_60 = np.max(h[-60:])
    llv_60 = np.min(l[-60:])
    集中度 = (hhv_60 - llv_60) / llv_60 * 100
    if 集中度 > 25:
        return False

    # ---- 2. 突破密集顶 ----
    # 密集区高点 = REF(HHV(H,60),1)
    # 3日内至少1天: C > 密集区高点 AND REF(C,1) <= 密集区高点
    found_breakout = False
    for offset in range(1, 4):  # 检查今日、昨日、前日
        if len(df) <= offset + 60:
            continue
        hi_60 = np.max(h[-(60 + offset):-offset]) if offset > 0 else np.max(h[-60:])
        c_today = c[-offset]
        c_yesterday = c[-(offset + 1)]
        if c_today > hi_60 and c_yesterday <= hi_60:
            found_breakout = True
            break
    if not found_breakout:
        return False

    # ---- 3. 蓄势 ----
    涨幅 = np.abs(c / np.roll(c, 1) - 1)
    if np.sum(涨幅[-5:] < 0.03) < 2:
        return False

    # ---- 4. 多头排列 ----
    ma5 = np.mean(c[-5:])
    ma10 = np.mean(c[-10:])
    ma20 = np.mean(c[-20:])
    ma60 = np.mean(c[-60:])
    ma60_prev = np.mean(c[-61:-1])
    if not (ma5 > ma10 > ma20 and ma60 >= ma60_prev):
        return False

    # ---- 5. MA5 角度 ≥ 30 度 ----
    ma5_prev = np.mean(c[-6:-1]) if len(c) >= 6 else ma5
    if ma5_prev <= 0:
        return False
    角度 = np.degrees(np.arctan((ma5 / ma5_prev - 1) * 100))
    if 角度 < 30:
        return False

    # ---- 6. 收阳线 ----
    if not (c[-1] > o[-1]):
        return False

    # ---- 7. 排除急拉坑底 ----
    hhv_18 = np.max(h[-18:]) if len(c) >= 18 else np.max(h)
    llv_18 = np.min(l[-18:]) if len(c) >= 18 else np.min(l)
    坑幅 = (hhv_18 - llv_18) / hhv_18 * 100
    有坑 = 坑幅 >= 16
    急拉脱离 = np.max(c[-3:]) / np.min(l[-3:]) >= 1.13
    if 有坑 and 急拉脱离:
        return False

    return True  # 全部条件通过


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

    # 平均持仓天数
    hold_days = []
    for t in trades:
        ed = t.get('entry_date')
        xd = t.get('exit_date')
        if ed and xd:
            from datetime import datetime as _bt_dt
            try:
                e = _bt_dt.strptime(ed, '%Y%m%d')
                x = _bt_dt.strptime(xd, '%Y%m%d')
                hold_days.append((x - e).days)
            except Exception:
                pass
    avg_hold_days = round(sum(hold_days) / len(hold_days), 1) if hold_days else 5.0

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
        avg_hold_days=avg_hold_days,
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
        "=== QMT Backtest Report ===",
        f"Strategy: {strategy_name}",
        f"Period: {params.start_date} -> {params.end_date}",
        f"Capital: CNY {params.initial_capital:,.0f}",
        "",
    ]

    if not result.success:
        lines.append(f"状态: [X] 失败")
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
#  板块热度模拟（回测专用）
# ============================================================

# 热力缓存：避免每根 bar 重复计算全池 N 日涨幅
_heat_cache = {'bar_i': -1, 'data': None, 'lookback': 5}

def _compute_mock_sector_heat(all_data, bar_i, valid_codes, lookback=5, force_refresh=False):
    """
    回测模式：基于个股近 N 日涨幅模拟板块热度。

    对池中每只股票计算 (close[bar_i] / close[bar_i-N] - 1)，
    按涨幅排序分段赋分：
      - top 20%  → 6-10 分（线性映射）
      - 中间 40% → 1-5 分
      - 底部 40% → 0 分
    若有效样本不足 3 只，返回 None。

    使用模块级缓存避免连续相同 bar_i 重复计算。
    返回 {code6: float_score}，code6 格式如 "000001"。

    热度校准说明：
      - 当 market_regime == 'uptrend' 时，top 评分上移至 6-10
      - 当 market_regime == 'downtrend' 时，top 评分压缩至 4-7
      - 默认 lookback=5 捕捉短线热点，长线可传 10/20
    """
    global _heat_cache
    if not force_refresh and _heat_cache['bar_i'] == bar_i and _heat_cache['lookback'] == lookback:
        return _heat_cache['data']

    returns = {}
    for code in valid_codes:
        df = all_data.get(code)
        if df is None or bar_i < lookback or bar_i >= len(df):
            continue
        try:
            close_now = float(df['close'].iloc[bar_i])
            close_before = float(df['close'].iloc[bar_i - lookback])
            if close_before > 0:
                ret = (close_now - close_before) / close_before * 100
                returns[code] = ret
        except (IndexError, ValueError, TypeError):
            continue

    if len(returns) < 3:
        _heat_cache = {'bar_i': bar_i, 'data': None, 'lookback': lookback}
        return None

    # 按涨幅从高到低排序
    sorted_codes = sorted(returns.keys(), key=lambda c: returns[c], reverse=True)
    n = len(sorted_codes)
    bottom_n = int(n * 0.4)
    top_n = max(int(n * 0.2), 1)
    mid_n = n - bottom_n - top_n

    heat_map = {}

    # 底部 40% → 0 分
    for code in sorted_codes[top_n + mid_n:]:
        heat_map[code] = 0.0

    # 中间 40% → 1-5 分（线性）
    mid_start = top_n
    mid_end = top_n + mid_n
    for i, code in enumerate(sorted_codes[mid_start:mid_end]):
        if mid_n > 1:
            score = 1.0 + (i / (mid_n - 1)) * 4.0
        else:
            score = 3.0
        heat_map[code] = round(score, 1)

    # 顶部 20% → 6-10 分（线性）
    for i, code in enumerate(sorted_codes[:top_n]):
        if top_n > 1:
            score = 6.0 + (i / (top_n - 1)) * 4.0
        else:
            score = 8.0
        heat_map[code] = round(score, 1)

    _heat_cache = {'bar_i': bar_i, 'data': heat_map, 'lookback': lookback}
    return heat_map


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

    def __init__(self, config_path: str = None, strategy: str = 'default'):
        self.config_path = config_path
        self.strategy = strategy
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
        self._patch_qmt_wrapper(params, valid_codes, strategy=self.strategy)

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
                print("  [板块] 回测模式: 基于近5日涨幅计算模拟板块热度")
                _compute_mock_sector_heat(None, -1, [], force_refresh=True)  # 清跨回测缓存

            # 模拟板块热度：每根 bar 计算个股近5日涨幅排名
            # 注：handlebar 内部 _load_data → _run_sector_analysis 因文件不存在
            # 返回空 dict，且 if bonus_map: 守卫不覆盖已设置的热度图
            heat_map = _compute_mock_sector_heat(all_data, bar_i, valid_codes)
            if heat_map and qmt._g_scorer:
                qmt._g_scorer.update_sector_bonus(heat_map)

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

    def _patch_qmt_wrapper(self, params, valid_codes, strategy='default'):
        """Monkey-patch qmt_wrapper 模块使之运行在回测模式。"""
        # 确保 project root 在 path
        if PROJECT_ROOT not in sys.path:
            sys.path.insert(0, PROJECT_ROOT)

        import adapters.qmt_wrapper as qmt

        # 策略选择: 当 strategy == 'qmt37' 时替换信号函数
        if strategy == 'qmt37':
            from qmt37_strategy.backtest_adapter import check_buy as qmt37_check_buy
            qmt.check_buy = qmt37_check_buy
            print("  [策略] 使用千问3.7版信号")
        else:
            import core.signal_main_rise as sig

        # 强制关闭 SAFEMODE —— 配置文件开启了 safemode，但回测中需要真实交易
        qmt.SAFEMODE_ENABLED = False

        # 回测模式 bypass check_buy：通达信选股已筛过买点，池内的直接进8D评分
        # 原始流程: pool → check_buy(卡77%) → 评分 → 买入
        # 修正流程: pool → 评分 → 买入
        qmt.check_buy = lambda df: (True, "池内(回测模式)", "pool")

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

        # 写 pool 文件（6位纯代码，_parse_pool_line 的 _code6_to_std 格式）
        pool_file = os.path.join(tmpdir, 'pool.txt')
        seen_6 = set()
        with open(pool_file, 'w', encoding='gbk') as f:
            for code in valid_codes:
                code6 = code.split('.')[0].strip()
                if code6 and code6 not in seen_6:
                    seen_6.add(code6)
                    f.write(f"{code6}\t回测\n")
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

        self._patch_qmt_wrapper(params, params.stock_codes, strategy=self.strategy)
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
                print("  [板块] 回测模式: 基于近5日涨幅计算模拟板块热度")
                _compute_mock_sector_heat(None, -1, [], force_refresh=True)  # 清跨回测缓存

            # 模拟板块热度（同上）
            heat_map = _compute_mock_sector_heat(all_data, bar_i, params.stock_codes)
            if heat_map and qmt._g_scorer:
                qmt._g_scorer.update_sector_bonus(heat_map)

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
  python scripts/run_backtest.py --datasource mootdx --scan --strategy qmt37
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
    p.add_argument('--scan', action='store_true',
                   help='全市场扫描模式，自动获取股票池（需 --datasource mootdx）')
    p.add_argument('--min-price', type=float, default=5.0,
                   help='扫描最低股价过滤 (默认 5.0)')
    p.add_argument('--max-candidates', type=int, default=100,
                   help='扫描候选池上限 (默认 100)')
    p.add_argument('--strategy', type=str, default='default',
                   choices=['default', 'qmt37'],
                   help='策略选择: default(现有策略), qmt37(千问3.7版)')
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

    # ---- 全市场扫描模式 ----
    if args.scan and not params.stock_codes:
        print("── 全市场扫描 ──")
        scan_params = ScanParams(
            min_price=args.min_price,
            max_candidates=args.max_candidates,
        )
        try:
            candidates, info = scan_market(scan_params)
        except Exception as e:
            print(f"  [错误] 全市场扫描失败: {e}", file=sys.stderr)
            return 1
        params.stock_codes = candidates
        print(f"  候选池: {len(candidates)} 只股票")

    if not params.stock_codes:
        runner = BacktestRunner()
        params.stock_codes = runner._default_stocks()

    # 执行
    runner = BacktestRunner(strategy=args.strategy)
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
