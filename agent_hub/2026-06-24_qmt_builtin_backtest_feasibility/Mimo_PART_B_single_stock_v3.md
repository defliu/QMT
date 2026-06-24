# MIMO 工单 — PART-B v3 修订（API 修复版）

任务：T-20260624-004 PART-B v3
前置：PART-B v2 跑通 stgentry 通路但 buy=0/deal=0；CC 已根因 → 见 `Mimo_PART_B_REPLY.md`
派单时间：2026-06-24
模式：CC 自动派单
红线（不变）：严禁 commit、不碰生产文件、不动 D:/QMT_POOL/、异常立即停手回报

---

## 0. 目标

把 PART-B v2 的探针文件改对，跑通："**buy_signals=4, sell_signals=4, deal_callback_count≥8, nav 有真实波动**"。

数据区间不变：2024-09-01 ~ 2024-12-31。

---

## 1. 改什么

**只动一个文件**：`scripts/_qmt_probe_b_strategy.py` — **整体覆盖重写**（不要保留 v2 内容）

驱动 `scripts/run_probe_b.py` **一个字符不动**（含 PARAM 区间）。

---

## 2. v2 的根因（背景，不必处理）

| 现象 | 根因 | v3 怎么修 |
|---|---|---|
| close 全 0.0 | `C.get_market_data` 在历史模式 + 单 fields 返回 Series/标量被 try 吃掉 | 改用 `C.get_market_data_ex` 在 after_init 时**一次性拉全区间** DataFrame，handlebar 按 date 查表 |
| 80 条 `'ContextInfo' object has no attribute 'get_trade_detail_data'` | `get_trade_detail_data` 是 `functions` 全局函数不是 C 方法，且回测环境是否真返回数据未知 | **完全删掉**，自维护 `_book = {cash, shares}`，nav = cash + shares*close |
| buy=0 | `close_px > 0` 是 False，门没开 | close 拿对了，门自然开 |
| 异常被 try 吞 | 静默落 md_errors | 异常一律 raise 出来给 handlebar 外层 _state['handlebar_errors']，方便定位 |

---

## 3. v3 探针策略（严格照抄，UTF-8）

路径：`D:/QMT_STRATEGIES/agent_hub/2026-06-24_qmt_builtin_backtest_feasibility/scripts/_qmt_probe_b_strategy.py`

```python
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
                    # opType=23 股票买入, orderType=1101 单股普通股/手, prType=5 最新价,
                    # modelprice=-1（5最新价时忽略）, volume=股数, strategyName, quickTrade=2(立即触发)
                    C.passorder(23, 1101, ACCOUNT_ID, C.stock_code, 5, -1, buy_shares, 'probe_b', 2, '')
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
                        C.passorder(24, 1101, ACCOUNT_ID, C.stock_code, 5, -1, sell_shares, 'probe_b', 2, '')
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
```

---

## 4. 执行步骤

1. wmic 验 QMT 在跑（与上次一样）
2. **整体覆盖**写入 `_qmt_probe_b_strategy.py`（v2 内容全删）
3. 不动 `run_probe_b.py`
4. 删 `data/qmt_backtest_trades.json` / `data/qmt_backtest_nav.csv` / `data/qmt_backtest_summary.json` / `data/run_probe_b.log`（旧版会被覆盖但显式删一次更干净）。不删 `_probe_b_lifecycle.json`（会被覆盖）
5. 跑驱动：

```cmd
& "D:\国金证券QMT交易端\bin.x64\pythonw.exe" "D:\QMT_STRATEGIES\agent_hub\2026-06-24_qmt_builtin_backtest_feasibility\scripts\run_probe_b.py" 1> "D:\QMT_STRATEGIES\agent_hub\2026-06-24_qmt_builtin_backtest_feasibility\data\run_probe_b.log" 2>&1
```

超时 300s。

---

## 5. 回执（**追加到** `Mimo_PART_B_REPLY.md` 末尾，标题 `## 第三次重跑（v3 修复版）`）

### 5.1 五件套全部 inline 贴出来

- `run_probe_b.log` 全文
- `_probe_b_lifecycle.json` 全文
- `qmt_backtest_trades.json` 全文
- `qmt_backtest_summary.json` 全文
- `qmt_backtest_nav.csv` 前 5 行 + 后 5 行 + 总行数

### 5.2 关键诊断对照表

| 字段 | v2 实测 | v3 实测 | v3 期望 |
|---|---|---|---|
| timelist_after_clip | 80 |  | 80 |
| handlebar_count | 80 |  | 80 |
| price_cache_size | — |  | 80 |
| cache_miss_dates 数量 | — |  | 0 |
| buy_signals | 0 |  | 4 |
| sell_signals | 0 |  | 4 |
| deal_callback_count | 0 |  | ≥8 |
| order_callback_count | 0 |  | ≥8 |
| acc_errors（应该不存在了） | 80 条 |  | 字段不存在（已删该调用） |
| handlebar_errors | — |  | 空 |
| passorder_errors | — |  | 空 |
| orderError_count | 0 |  | 0 |
| nav 末值 == init_nav？ | 是 |  | **否**（必须有变化） |

### 5.3 报告整体重写

`reports/02_single_stock_backtest.md` 整体覆盖重写。结构：
- 一段总述（v1 → v2 → v3 三次迭代经过）
- 5.2 诊断表
- workaround 评价：after_init timelist 截断 + 全区间 price 缓存 + 自维护 book，三件套都已生效
- 局限性：trades 里 m_strOptName 字段是否真有内容（如果 side 全 unknown，说明这个字段在 QMT 回测里跟实盘行为不一致，需补 PART-E 调研）

### 5.4 自检

- [ ] 没改任何生产文件（git status 贴一段）
- [ ] 没 commit
- [ ] 没动 D:/QMT_POOL/
- [ ] 异常没自判跳过（除非工单 §6 明确说"不要 STOP"）
- [ ] 探针文件**整体覆盖**写入了，不是 patch
- [ ] 驱动文件**一字未动**

---

## 6. 异常处理

| 现象 | 处理 |
|---|---|
| `after_init` 抛 RuntimeError（get_market_data_ex 返回结构异常）| **STOP**，贴异常原文 + 截断后 timelist 前 3 个 timetag |
| handlebar_count = 0 | **STOP**（timelist 又裁空了，怪事） |
| price_cache_size = 0 | **STOP**（数据拉空了） |
| cache_miss_dates 数量 > 5 | **不要 STOP**，但回执里贴出所有 miss 的日期 |
| buy_signals = 0 但 price_cache_size > 0 | **STOP**，贴 handlebar_errors |
| deal_callback_count = 0 但 buy_signals > 0 | **STOP**，贴 passorder_errors + orderError_msgs |
| trades 里 side 全 'unknown' | **不要 STOP**，照常出回执，CC 看 m_strOptName 实际内容判断 |

---

## 7. 完成判据

满足以下全部 = v3 通过：

- [ ] handlebar_count == timelist_after_clip（=80）
- [ ] buy_signals == 4 且 sell_signals == 4
- [ ] deal_callback_count ≥ 8
- [ ] nav 末值 != init_nav
- [ ] orderError_count == 0
- [ ] handlebar_errors / passorder_errors 都为空
- [ ] 五件套齐 + 报告重写 + 自检全勾
