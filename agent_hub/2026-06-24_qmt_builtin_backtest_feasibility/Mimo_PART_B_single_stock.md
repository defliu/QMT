# MIMO 工单 — PART-B 单标的回测 + callback 落盘

任务：T-20260624-004 PART-B
SPEC：`D:/QMT_STRATEGIES/specs/SPEC_QMT_BUILTIN_BACKTEST_FEASIBILITY.md` 模块 2
Brief：`./00_brief.md`
前置：PART-A 已通过（见 `./Mimo_PART_A_REPLY.md`）
派单时间：2026-06-24
模式：CC 自动派单（[[cc-mimo-dispatch-mode]]）

---

## 0. 任务目标

**用 QMT 内置回测跑一次 000001.SZ 单标的简单买入持有策略，把 trades / nav / summary 三件套落盘。**

策略逻辑（**死简单，别加任何花活**）：
- 每月第一根 bar，如果当前空仓 → 全资产买入 000001.SZ
- 持有 5 个交易日后卖出
- 反复循环
- 目的：制造可观察的交易，**不是**为了策略本身赚钱

---

## 1. 任务范围（**不许超出**）

**只做的事**：
1. 写 `_qmt_probe_b_strategy.py`（探针 v2，含买卖 + callback）
2. 写 `run_probe_b.py`（驱动）
3. 跑一次 000001.SZ 2024-01-01 ~ 2024-03-31
4. 把 trades / nav / summary 落盘成 SPEC 指定的 JSON / CSV 结构
5. 写 `reports/02_single_stock_backtest.md` 报告

**禁止动作**（违反任一项立即停手）：
- 不改 `strategy_main.py` / `strategy_allday.py` / `release/` 任何生产文件
- 不动 `D:/QMT_POOL/`
- 不 commit
- 不调用真盘 passorder（QMT 回测里走 `C.passorder` 是引擎自己撮合的，**不会**真下单）
- 不"判定异常无关"自行继续（[[mimo-must-stop-on-any-failure]]）

---

## 2. 准备步骤

### 2.1 探针 v2 策略文件

路径：`D:/QMT_STRATEGIES/agent_hub/2026-06-24_qmt_builtin_backtest_feasibility/scripts/_qmt_probe_b_strategy.py`

内容**严格如下**（UTF-8，不许加私货）：

```python
# coding=utf-8
"""PART-B 探针 v2 — 单标的买入持有 5 日策略，含 callback 落盘。

策略：
  每月第一根 bar，空仓时买入 99% 资产；持有 5 个交易日后卖出。

落盘：
  data/qmt_backtest_trades.json  — deal_callback 累计
  data/qmt_backtest_nav.csv      — handlebar 末尾累计
  data/qmt_backtest_summary.json — stop 时算
  data/_probe_b_lifecycle.json   — 生命周期诊断
"""

import csv
import json
import os
import time

OUT_DIR = r'D:/QMT_STRATEGIES/agent_hub/2026-06-24_qmt_builtin_backtest_feasibility/data'
ACCOUNT_ID = '67014907'  # 模拟端测试账号（CLAUDE.md 备案）

_state = {
    'init_called': False,
    'after_init_called': False,
    'handlebar_count': 0,
    'stop_called': False,
    'first_bar_time': None,
    'last_bar_time': None,
    'timelist_before_clip': 0,
    'timelist_after_clip': 0,
    'buy_signals': 0,
    'sell_signals': 0,
    'deal_callback_count': 0,
    'order_callback_count': 0,
    'account_callback_count': 0,
    'orderError_count': 0,
    'orderError_msgs': [],
}

_trades = []          # deal_callback 落盘
_nav_rows = []        # [{date, nav}]
_position = {         # 当前持仓状态
    'holding': False,
    'entry_bar_idx': None,
    'entry_price': None,
    'entry_date': None,
}


def _bar_date_str(timetag_ms):
    # timetag 是毫秒
    try:
        t = time.localtime(timetag_ms / 1000)
        return time.strftime('%Y%m%d', t)
    except Exception:
        return ''


def init(C):
    _state['init_called'] = True
    C.start_time = C._param.get('start_time', '')
    C.end_time = C._param.get('end_time', '')
    # 手续费 / 滑点（保持工厂默认对比可比）
    C.open_commission = 0.0003
    C.close_commission = 0.0003
    C.min_commission = 5.0
    C.close_tax = 0.001
    C.slippage = 0.0
    C.slippage_type = 2


def after_init(C):
    """关键 workaround：stgframe.load_main_history 写死 start_time=''/count=-1，
    取到的是全历史；这里按 _param 的 start_time/end_time 裁剪 C.timelist。
    """
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

    if start_ms is None and end_ms is None:
        _state['timelist_after_clip'] = len(C.timelist)
        return

    new_list = []
    for t in C.timelist:
        if start_ms is not None and t < start_ms:
            continue
        if end_ms is not None and t > end_ms:
            continue
        new_list.append(t)
    C.timelist = new_list
    _state['timelist_after_clip'] = len(C.timelist)


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

        # ---------- 取最近一根 K 线收盘价 ----------
        try:
            md = C.get_market_data(
                fields=['close'], stock_code=[C.stock_code],
                period=C.period, count=1, dividend_type='front'
            )
            # 不同 QMT 版本返回结构可能不同，兼容多种
            close_px = None
            if isinstance(md, dict):
                # 形如 {'close': {'000001.SZ': [价格]}}
                cl = md.get('close')
                if isinstance(cl, dict):
                    arr = cl.get(C.stock_code) or list(cl.values())[0]
                    if hasattr(arr, '__len__') and len(arr) > 0:
                        close_px = float(arr[-1])
            if close_px is None:
                close_px = 0.0
        except Exception as e:
            close_px = 0.0
            _state.setdefault('md_errors', []).append(repr(e))

        # ---------- 取账户净值 ----------
        nav_val = None
        try:
            accs = C.get_trade_detail_data(ACCOUNT_ID, 'STOCK', 'ACCOUNT')
            if accs:
                a = accs[0]
                # 国金 QMT 字段：m_dAssetBalance（memory: qmt-account-asset-fields）
                for fld in ('m_dAssetBalance', 'm_dAsset', 'm_dTotalAsset'):
                    v = getattr(a, fld, None)
                    if v is not None:
                        nav_val = float(v)
                        break
        except Exception as e:
            _state.setdefault('acc_errors', []).append(repr(e))

        if nav_val is None:
            # 兜底用 C.capital
            nav_val = float(getattr(C, 'capital', 0) or C.asset)

        _nav_rows.append({'date': date_str, 'nav': nav_val, 'close': close_px})

        # ---------- 策略逻辑：月度首根买入 / 5 日后卖出 ----------
        prev_date = _bar_date_str(C.timelist[C.barpos - 1]) if C.barpos > 0 else ''
        is_month_first = (prev_date == '' or prev_date[:6] != date_str[:6])

        if not _position['holding'] and is_month_first and close_px > 0:
            # opType=23 股票买入, orderType=1102 单股单账号普通金额, prType=5 最新价
            vol_yuan = nav_val * 0.99
            try:
                C.passorder(23, 1102, ACCOUNT_ID, C.stock_code, 5, -1, vol_yuan, 'probe_b', 2, '')
                _position['holding'] = True
                _position['entry_bar_idx'] = C.barpos
                _position['entry_price'] = close_px
                _position['entry_date'] = date_str
                _state['buy_signals'] += 1
            except Exception as e:
                _state.setdefault('passorder_errors', []).append('BUY: ' + repr(e))
        elif _position['holding'] and _position['entry_bar_idx'] is not None:
            if C.barpos - _position['entry_bar_idx'] >= 5:
                # 全部卖出：opType=24, orderType=1123 单股账号可用比例, vol=1.0
                try:
                    C.passorder(24, 1123, ACCOUNT_ID, C.stock_code, 5, -1, 1.0, 'probe_b', 2, '')
                    _state['sell_signals'] += 1
                except Exception as e:
                    _state.setdefault('passorder_errors', []).append('SELL: ' + repr(e))
                _position['holding'] = False
                _position['entry_bar_idx'] = None
                _position['entry_price'] = None
                _position['entry_date'] = None

    except Exception as e:
        _state.setdefault('handlebar_errors', []).append(repr(e))


def deal_callback(C, deal_info):
    _state['deal_callback_count'] += 1
    try:
        row = {
            'no': len(_trades) + 1,
            'code': getattr(deal_info, 'm_strInstrumentID', ''),
            'time_str': getattr(deal_info, 'm_strTradeTime', ''),
            'direction': getattr(deal_info, 'm_strOptName', ''),  # 名字判方向（memory: qmt-passorder-async-lookup）
            'volume': getattr(deal_info, 'm_nVolume', getattr(deal_info, 'm_nTradeVolume', 0)),
            'price': getattr(deal_info, 'm_dPrice', getattr(deal_info, 'm_dTradePrice', 0.0)),
            'amount': getattr(deal_info, 'm_dTradeAmount', 0.0),
            'order_id': getattr(deal_info, 'm_strOrderSysID', ''),
        }
        _trades.append(row)
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

    # trades
    try:
        with open(os.path.join(OUT_DIR, 'qmt_backtest_trades.json'), 'w', encoding='utf-8') as f:
            json.dump({'trades': _trades, 'count': len(_trades)}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    # nav
    try:
        with open(os.path.join(OUT_DIR, 'qmt_backtest_nav.csv'), 'w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=['date', 'nav', 'close'])
            w.writeheader()
            for r in _nav_rows:
                w.writerow(r)
    except Exception:
        pass

    # summary
    try:
        navs = [r['nav'] for r in _nav_rows if r['nav']]
        init_nav = navs[0] if navs else 0.0
        end_nav = navs[-1] if navs else 0.0
        total_return = (end_nav / init_nav - 1.0) if init_nav else 0.0
        # 最大回撤
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
        }
        with open(os.path.join(OUT_DIR, 'qmt_backtest_summary.json'), 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    # lifecycle
    try:
        with open(os.path.join(OUT_DIR, '_probe_b_lifecycle.json'), 'w', encoding='utf-8') as f:
            json.dump(_state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
```

### 2.2 驱动脚本

路径：`D:/QMT_STRATEGIES/agent_hub/2026-06-24_qmt_builtin_backtest_feasibility/scripts/run_probe_b.py`

内容**严格如下**：

```python
# coding=utf-8
"""PART-B 驱动 — 单标的回测 + callback 落盘。"""

import json
import os
import sys
import time
import traceback

PROBE = r'D:/QMT_STRATEGIES/agent_hub/2026-06-24_qmt_builtin_backtest_feasibility/scripts/_qmt_probe_b_strategy.py'

PARAM = {
    'stock_code': '000001.SZ',
    'period': '1d',
    'start_time': '20240101',
    'end_time': '20240331',
    'trade_mode': 'backtest',
    'quote_mode': 'history',
    'asset': 1000000,
    'dividend_type': 'front',
    'title': 'probe_b_single_stock',
}


def main():
    print('[probe_b] python:', sys.executable)
    print('[probe_b] probe :', PROBE)
    print('[probe_b] param :', json.dumps(PARAM, ensure_ascii=False))

    t0 = time.time()
    try:
        from xtquant.qmttools import stgentry
        print('[probe_b] stgentry imported:', stgentry.__file__)
    except Exception:
        print('[probe_b] FAIL import stgentry')
        traceback.print_exc()
        return 10

    try:
        ret = stgentry.run_file(PROBE, PARAM)
        print('[probe_b] run_file returned:', repr(ret))
        print('[probe_b] elapsed (s)      :', round(time.time() - t0, 2))
    except Exception:
        print('[probe_b] FAIL run_file')
        print('[probe_b] elapsed (s)      :', round(time.time() - t0, 2))
        traceback.print_exc()
        return 20

    return 0


if __name__ == '__main__':
    sys.exit(main())
```

---

## 3. 执行步骤

### 3.1 确认 QMT 在跑

```cmd
tasklist | findstr /I XtMiniQmt
```

必须有 `XtMiniQmt.exe`，没有就停手等 CC。

### 3.2 跑驱动

```cmd
& "D:\国金证券QMT交易端\bin.x64\pythonw.exe" "D:\QMT_STRATEGIES\agent_hub\2026-06-24_qmt_builtin_backtest_feasibility\scripts\run_probe_b.py" 1> "D:\QMT_STRATEGIES\agent_hub\2026-06-24_qmt_builtin_backtest_feasibility\data\run_probe_b.log" 2>&1
```

超时 300 秒，超时强杀。

### 3.3 检查产物

应在 `data/` 下生成 5 个文件：
- `run_probe_b.log` — 驱动 stdout/stderr
- `qmt_backtest_trades.json` — 逐笔交易（必有 count ≥ 1）
- `qmt_backtest_nav.csv` — 每日净值（必有 ≈ 60 行）
- `qmt_backtest_summary.json` — 汇总指标
- `_probe_b_lifecycle.json` — 生命周期诊断

---

## 4. 回执（**写到** `Mimo_PART_B_REPLY.md`）

### 4.1 产物清单

按 `ls -la data/` 输出每个文件大小。

### 4.2 关键诊断（从 `_probe_b_lifecycle.json` 抄）

| 字段 | 值 | 预期 |
|---|---|---|
| init_called | | true |
| after_init_called | | true |
| handlebar_count | | ≈ 58 ± 5 |
| stop_called | | true |
| timelist_before_clip | | > 400（含全历史） |
| timelist_after_clip | | ≈ 58 ± 5（裁剪生效） |
| buy_signals | | 3（1/2/3 月各一） |
| sell_signals | | 3 |
| deal_callback_count | | ≥ 6（每笔买卖各触发一次） |
| order_callback_count | | ≥ 6 |
| account_callback_count | | ≥ 1 |
| orderError_count | | 0（>0 必贴 msgs） |
| md_errors / acc_errors / passorder_errors / handlebar_errors | | 无 / 列表为空 |

### 4.3 trades 内容

把 `qmt_backtest_trades.json` 全文贴出。

### 4.4 nav 前 3 + 后 3 行

```text
date,nav,close
20240102,...
20240103,...
20240104,...
...
20240327,...
20240328,...
20240329,...
```

### 4.5 summary 内容

`qmt_backtest_summary.json` 全文贴出。

### 4.6 run_probe_b.log 全文（>200 行截断规则同 PART-A）

### 4.7 报告

写 `reports/02_single_stock_backtest.md`，含：
- 实测耗时
- 关键诊断表（同 4.2）
- "after_init 截断 timelist 这个 workaround **生效 / 失效**"，给证据
- 局限性：哪些指标没算（夏普 / 年化 / 胜率 — 因为不是 PART-B 必交付，可在 PART-E 终审补全）

### 4.8 自检（必须全勾）

- [ ] 我没改任何生产文件（`git status` 贴一段）
- [ ] 我没 commit
- [ ] 我没动 `D:/QMT_POOL/`
- [ ] 我没"判定异常无关"自行继续
- [ ] 5 个产物文件齐（缺哪个明确说哪个）
- [ ] 探针/驱动脚本完全照抄 2.1 / 2.2，没加私货

---

## 5. 异常处理（[[mimo-must-stop-on-any-failure]]）

**立即停手、回报、不要自己改脚本**的情况：

| 现象 | 处理 |
|---|---|
| `from xtquant.qmttools import stgentry` 报错 | STOP，贴报错原文 |
| `run_file()` 抛异常 | STOP，贴 traceback |
| 进程 300s 未退出 | STOP（强杀后回报），贴最后 100 行 stdout |
| `_probe_b_lifecycle.json` 没生成 | STOP，贴 run_probe_b.log 全文 |
| `handlebar_count == 0` | STOP（说明 timelist 被裁空了），贴 `timelist_before_clip` / `timelist_after_clip` 数值 |
| `orderError_count > 0` | **不要 STOP**，但必须在 4.2 贴所有 orderError_msgs；CC 会判断 |
| `deal_callback_count == 0` 但 `buy_signals > 0` | STOP（passorder 没触发引擎撮合），贴 passorder_errors |
| `md_errors`/`acc_errors` 非空 | **不要 STOP**，照常落盘，把错列在 4.2，CC 判断是否影响结论 |

---

## 6. 完成判据

满足以下全部 = PART-B 完成，CC 验收 → 出 PART-C 工单：

- [ ] 5 个产物文件齐全
- [ ] 4.2 关键诊断表全部填完
- [ ] 4.3 / 4.4 / 4.5 数据贴全
- [ ] `reports/02_single_stock_backtest.md` 完成
- [ ] 自检 6 项全勾
- [ ] 没产生任何 commit
- [ ] 没碰生产文件

CC 验收重点：
1. `handlebar_count ≈ 58` 证明 after_init 截断生效
2. `deal_callback_count > 0` 证明回测引擎真的撮合了
3. trades 里 `m_strOptName` 字段有值（QMT 实盘是这样，回测里是否也填要看实测）
4. nav 末值 != init_nav 证明回测有真实的资产变化
