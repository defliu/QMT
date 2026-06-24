# coding=utf-8
"""PART-B v3 探针 — 修复 v2 API 错误：
1. 用 get_market_data_ex 一次性缓存全区间 DataFrame
2. 删 get_trade_detail_data，自维护 cash/shares
3. passorder 切换到 orderType=1101（股数为单位），账面运算干净
"""

import csv
import json
import os
import time

OUT_DIR = r'D:/QMT_STRATEGIES/agent_hub/2026-06-24_qmt_builtin_backtest_feasibility/data'
ACCOUNT_ID = '67014907'  # 模拟端测试账号；QMT 内置回测不真连账户，自维护 book

# ---- 生命周期诊断 ----
_state = {
    'init_called': False,
    'after_init_called': False,
    'handlebar_count': 0,
    'stop_called': False,
    'first_bar_time': None,
    'last_bar_time': None,
    'timelist_before_clip': 0,
    'timelist_after_clip': 0,
    'price_cache_size': 0,
    'buy_signals': 0,
    'sell_signals': 0,
    'deal_callback_count': 0,
    'order_callback_count': 0,
    'account_callback_count': 0,
    'orderError_count': 0,
    'orderError_msgs': [],
    'cache_miss_dates': [],
    'handlebar_errors': [],
    'passorder_errors': [],
}

# ---- 输出累计 ----
_trades = []     # deal_callback 落盘
_nav_rows = []   # [{date, nav, close}]

# ---- 自维护 book ----
_book = {
    'cash': 1000000.0,   # 初始资金（与 PARAM.asset 一致）
    'shares': 0,
    'last_close': 0.0,
}

# ---- 持仓状态机 ----
_position = {
    'holding': False,
    'entry_bar_idx': None,
    'entry_price': None,
    'entry_date': None,
}

# ---- 价格缓存：date_str(YYYYMMDD) -> close_price ----
_price_by_date = {}


def _bar_date_str(timetag_ms):
    try:
        t = time.localtime(timetag_ms / 1000)
        return time.strftime('%Y%m%d', t)
    except Exception:
        return ''


def init(C):
    _state['init_called'] = True
    C.start_time = C._param.get('start_time', '')
    C.end_time = C._param.get('end_time', '')
    C.open_commission = 0.0003
    C.close_commission = 0.0003
    C.min_commission = 5.0
    C.close_tax = 0.001
    C.slippage = 0.0
    C.slippage_type = 2
    _book['cash'] = float(C._param.get('asset', 1000000.0))

    # 打开回测 trade callback 总闸（源码 contextinfo.py:264-268）
    try:
        C.set_account(ACCOUNT_ID)
    except Exception as e:
        _state.setdefault('init_errors', []).append('set_account: ' + repr(e))
    try:
        C.set_auto_trade_callback(True)
    except Exception as e:
        _state.setdefault('init_errors', []).append('set_auto_trade_callback: ' + repr(e))
    try:
        C.do_back_test = True
    except Exception as e:
        _state.setdefault('init_errors', []).append('do_back_test: ' + repr(e))


def after_init(C):
    """裁剪 timelist + 一次性拉全区间 close 缓存。"""
    _state['after_init_called'] = True
    _state['timelist_before_clip'] = len(C.timelist)

    start = C._param.get('start_time', '')
    end = C._param.get('end_time', '')

    def _to_ms(yyyymmdd, end_of_day=False):
        if not yyyymmdd or len(yyyymmdd) < 8:
            return None
        try:
            tm = time.strptime(yyyymmdd[:8], '%Y%m%d')
            ts = time.mktime(tm)
            if end_of_day:
                ts += 86400 - 1
            return int(ts * 1000)
        except Exception:
            return None

    start_ms = _to_ms(start, end_of_day=False)
    end_ms = _to_ms(end, end_of_day=True)

    if start_ms is not None or end_ms is not None:
        new_list = []
        for t in C.timelist:
            if start_ms is not None and t < start_ms:
                continue
            if end_ms is not None and t > end_ms:
                continue
            new_list.append(t)
        C.timelist = new_list
    _state['timelist_after_clip'] = len(C.timelist)

    # 一次性拉全区间收盘 — 不吞异常，挂掉时直接停
    md = C.get_market_data_ex(
        fields=['close'], stock_code=[C.stock_code],
        period=C.period, start_time=start, end_time=end,
        dividend_type='front'
    )
    if not isinstance(md, dict) or C.stock_code not in md:
        raise RuntimeError(
            'get_market_data_ex returned unexpected structure: type={0} keys={1}'.format(
                type(md).__name__, list(md.keys()) if isinstance(md, dict) else 'N/A'
            )
        )
    df = md[C.stock_code]
    # df.index 是 stime 字符串（1d 时为 YYYYMMDD）
    for idx_val in df.index:
        date_key = str(idx_val)[:8]
        try:
            _price_by_date[date_key] = float(df.loc[idx_val, 'close'])
        except Exception as e:
            _state['handlebar_errors'].append(
                'price cache failed for {0}: {1}'.format(date_key, repr(e))
            )
    _state['price_cache_size'] = len(_price_by_date)


def handlebar(C):
    try:
        _state['handlebar_count'] += 1
        if C.barpos < 0 or C.barpos >= len(C.timelist):
            return
        bar_t = C.timelist[C.barpos]
        if _state['first_bar_time'] is None:
            _state['first_bar_time'] = bar_t
        _state['last_bar_time'] = bar_t

        date_str = _bar_date_str(bar_t)
        close_px = _price_by_date.get(date_str, 0.0)
        if close_px <= 0:
            _state['cache_miss_dates'].append(date_str)
        else:
            _book['last_close'] = close_px

        # 记录 nav（无论是否下单都记）
        nav_val = _book['cash'] + _book['shares'] * _book['last_close']
        _nav_rows.append({'date': date_str, 'nav': nav_val, 'close': close_px})

        # ---- 月度首根买入 ----
        prev_date = _bar_date_str(C.timelist[C.barpos - 1]) if C.barpos > 0 else ''
        is_month_first = (prev_date == '' or prev_date[:6] != date_str[:6])

        if (not _position['holding']) and is_month_first and close_px > 0:
            # 买入股数 = floor(cash * 0.99 / close_px / 100) * 100
            buy_shares = int(_book['cash'] * 0.99 / close_px / 100) * 100
            if buy_shares >= 100:
                try:
                    # opType=23 股票买入, orderType=1101, prType=11 指定价,
                    # modelprice=close_px, volume=股数
                    C.passorder(23, 1101, ACCOUNT_ID, C.stock_code, 11, float(close_px), buy_shares)
                    _position['holding'] = True
                    _position['entry_bar_idx'] = C.barpos
                    _position['entry_price'] = close_px
                    _position['entry_date'] = date_str
                    _state['buy_signals'] += 1
                except Exception as e:
                    _state['passorder_errors'].append('BUY {0}: {1}'.format(date_str, repr(e)))
        elif _position['holding'] and _position['entry_bar_idx'] is not None:
            if C.barpos - _position['entry_bar_idx'] >= 5:
                sell_shares = _book['shares']
                if sell_shares > 0:
                    try:
                        C.passorder(24, 1101, ACCOUNT_ID, C.stock_code, 11, float(_book['last_close']), sell_shares)
                        _state['sell_signals'] += 1
                    except Exception as e:
                        _state['passorder_errors'].append('SELL {0}: {1}'.format(date_str, repr(e)))
                _position['holding'] = False
                _position['entry_bar_idx'] = None
                _position['entry_price'] = None
                _position['entry_date'] = None

    except Exception as e:
        _state['handlebar_errors'].append(repr(e))


def deal_callback(C, deal_info):
    """根据 m_strOptName 判方向，更新自维护 book。"""
    _state['deal_callback_count'] += 1
    try:
        opt_name = str(getattr(deal_info, 'm_strOptName', '') or '')
        # 兼容字段命名
        vol = getattr(deal_info, 'm_nVolume', None)
        if vol is None:
            vol = getattr(deal_info, 'm_nTradeVolume', 0)
        vol = int(vol or 0)
        price = getattr(deal_info, 'm_dPrice', None)
        if price is None:
            price = getattr(deal_info, 'm_dTradePrice', 0.0)
        price = float(price or 0.0)
        amount = vol * price
        # 简化手续费：买卖均按 0.0003 计算（与 init 设置一致）
        fee = max(amount * 0.0003, 5.0)
        side = 'unknown'
        if '买' in opt_name or 'Buy' in opt_name or 'BUY' in opt_name:
            side = 'buy'
            _book['cash'] -= (amount + fee)
            _book['shares'] += vol
        elif '卖' in opt_name or 'Sell' in opt_name or 'SELL' in opt_name:
            side = 'sell'
            tax = amount * 0.001
            _book['cash'] += (amount - fee - tax)
            _book['shares'] -= vol
        _trades.append({
            'no': len(_trades) + 1,
            'code': getattr(deal_info, 'm_strInstrumentID', ''),
            'time_str': getattr(deal_info, 'm_strTradeTime', ''),
            'opt_name': opt_name,
            'side': side,
            'volume': vol,
            'price': price,
            'amount': amount,
            'order_id': getattr(deal_info, 'm_strOrderSysID', ''),
            'book_cash_after': _book['cash'],
            'book_shares_after': _book['shares'],
        })
    except Exception as e:
        _state.setdefault('deal_cb_errors', []).append(repr(e))


def order_callback(C, order_info):
    _state['order_callback_count'] += 1


def account_callback(C, account_info):
    _state['account_callback_count'] += 1


def orderError_callback(C, passorder_info, msg):
    _state['orderError_count'] += 1
    try:
        _state['orderError_msgs'].append(str(msg)[:200])
    except Exception:
        pass


def stop(C):
    _state['stop_called'] = True
    # hotfix-4: 主动拉 callback cache 探测引擎是否有撮合数据
    try:
        cache_deal = C.get_callback_cache('deal')
        _state['cache_deal_raw'] = repr(cache_deal)[:2000]
    except Exception as e:
        _state['cache_deal_err'] = repr(e)
    try:
        cache_order = C.get_callback_cache('order')
        _state['cache_order_raw'] = repr(cache_order)[:2000]
    except Exception as e:
        _state['cache_order_err'] = repr(e)
    try:
        cache_account = C.get_callback_cache('account')
        _state['cache_account_raw'] = repr(cache_account)[:2000]
    except Exception as e:
        _state['cache_account_err'] = repr(e)

    os.makedirs(OUT_DIR, exist_ok=True)

    try:
        with open(os.path.join(OUT_DIR, 'qmt_backtest_trades.json'), 'w', encoding='utf-8') as f:
            json.dump({'trades': _trades, 'count': len(_trades)}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    try:
        with open(os.path.join(OUT_DIR, 'qmt_backtest_nav.csv'), 'w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=['date', 'nav', 'close'])
            w.writeheader()
            for r in _nav_rows:
                w.writerow(r)
    except Exception:
        pass

    try:
        navs = [r['nav'] for r in _nav_rows if r['nav']]
        init_nav = navs[0] if navs else 0.0
        end_nav = navs[-1] if navs else 0.0
        total_return = (end_nav / init_nav - 1.0) if init_nav else 0.0
        peak = 0.0
        max_dd = 0.0
        for v in navs:
            if v > peak:
                peak = v
            if peak > 0:
                dd = v / peak - 1.0
                if dd < max_dd:
                    max_dd = dd
        summary = {
            'stock_code': C.stock_code,
            'start_time': C._param.get('start_time', ''),
            'end_time': C._param.get('end_time', ''),
            'init_nav': init_nav,
            'end_nav': end_nav,
            'total_return': round(total_return, 6),
            'max_drawdown': round(max_dd, 6),
            'total_trades': len(_trades),
            'buy_signals': _state['buy_signals'],
            'sell_signals': _state['sell_signals'],
            'nav_points': len(navs),
            'final_cash': _book['cash'],
            'final_shares': _book['shares'],
        }
        with open(os.path.join(OUT_DIR, 'qmt_backtest_summary.json'), 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    try:
        with open(os.path.join(OUT_DIR, '_probe_b_lifecycle.json'), 'w', encoding='utf-8') as f:
            json.dump(_state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
