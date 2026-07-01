# 工单：导出脚本集成进主策略 + 时间锁

**日期**: 2026-07-01
**作者**: CC
**目的**: 把 `scripts/qmt_daily_export.py` 的每日导出能力集成进主策略，handlebar 检测 15:05 自动触发（防诚哥忘导导致 rebuild 累计盈亏数据源缺失）；同时给导出加时间锁（工作日 ≥15:05 才写文件），解决"只要运行就输出、盘中误跑写垃圾覆盖"问题。
**预计工时**: ≤ 45 分钟

---

## 〇、背景（必读，不要改这段）

### 诚哥拍板的决策
- 集成方式：**handlebar 定时触发**（不用 exit 钩子——exit 是策略被停止时才调，尾盘策略 14:58 设 today_done 后进程不退出一直跑，exit 可能第二天才触发，错过 deal 还在的窗口）
- 时机：15:05 后（给 QMT 接收全成交回报留时间）
- 时间锁：**工作日 ≥15:05 才导出**（周末/盘前跳过）

### 关键约束
- 模拟端不存历史：`get_trade_detail_data('deal')` 只返回当日，隔日清。必须收盘当天 deal 还在时导出
- `build_strategy.py` SOURCE_FILES（line 301-314）只内联 `core/*.py` + `adapters/qmt_wrapper.py`，**不含 scripts/**
- `qmt_daily_export.py` 有自己的 `init/handlebar` 入口——**不能原样内联进主策略**（会跟主策略 `def init(C)`/`def handlebar(C)` 冲突）。只搬**纯导出函数**到 qmt_wrapper
- `get_trade_detail_data` 是 QMT 内置全局，主策略 exec 环境可直接调（qmt_wrapper 已多处用）
- `adapters/qmt_wrapper.py` 实测 **UTF-8 编码**（文件头 `# coding=gbk` 是历史遗留错误标注，不要改文件头）。用 Edit 工具改没问题。
- Python 3.6.8 兼容（禁 f-string / dict[str,..] / walrus `:=` / match-case / `str|None`）

### 上一轮已落地（不要重复改）
上一工单（2026-07-01_pnl_rebuild_strategy_name）已把 `rebuild_cumulative_pnl_from_csv()` 加到 qmt_wrapper.py line 793 后，并把策略名改为 config 驱动 `主升浪6+2`。本次在其基础上加导出集成，**不要动 rebuild 函数和策略名**。

---

## 一、必做（5 项）

### TASK-1. qmt_wrapper.py 搬入导出函数 + 时间锁

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`

**内容/做法**:
在 `rebuild_cumulative_pnl_from_csv()` 函数之后（nav 工具区，line 793 附近）新增以下函数。从 `scripts/qmt_daily_export.py` 搬入纯导出逻辑，**去掉 init/handlebar 入口**（主策略有自己的），加时间锁。

```python
EXPORT_OUTPUT_DIR = r'D:\qmt_pool'


def _is_export_time():
    """工作日 15:05 后才允许导出。周末/盘前返回 False。"""
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    hm = now.strftime('%H%M')
    if hm < '1505':
        return False
    return True


def _export_safe_attr(obj, attr, default=''):
    if attr is None or attr == '':
        return default
    try:
        val = getattr(obj, attr, None)
        if val is None:
            return default
        return str(val)
    except Exception:
        return default


def _export_fmt_amount(obj, attr):
    try:
        val = getattr(obj, attr, None)
        if val is None:
            return ''
        return '%.2f' % float(val)
    except Exception:
        return ''


def _export_fmt_int(obj, attr):
    try:
        val = getattr(obj, attr, None)
        if val is None:
            return ''
        return str(int(val))
    except Exception:
        return ''


def _export_fmt_pct(obj, attr, multiply=True):
    try:
        val = getattr(obj, attr, None)
        if val is None:
            return ''
        v = float(val)
        if multiply:
            v = v * 100.0
        return '%.2f' % v
    except Exception:
        return ''


def export_deals(ContextInfo):
    deals = get_trade_detail_data(ACCOUNT_ID, 'STOCK', 'deal')
    date_str = datetime.now().strftime('%Y%m%d')
    filepath = os.path.join(EXPORT_OUTPUT_DIR, '成交明细_%s.csv' % date_str)
    header = '资金账号,成交日期,成交时间,交易所,证券代码,证券名称,买卖标记,成交数量,成交价格,成交金额,手续费,成交编号,合同编号,订单编号,任务编号,投资备注,账号备注,分支机构,投资备注1,股东号'
    with open(filepath, 'w', encoding='gbk') as f:
        f.write(header + '\n')
        for deal in deals:
            row = ','.join([
                _export_safe_attr(deal, 'm_strAccountID'),
                _export_safe_attr(deal, 'm_strTradeDate'),
                _export_safe_attr(deal, 'm_strTradeTime'),
                _export_safe_attr(deal, 'm_strExchangeID'),
                _export_safe_attr(deal, 'm_strInstrumentID'),
                _export_safe_attr(deal, 'm_strInstrumentName'),
                _export_safe_attr(deal, 'm_strOptName'),
                _export_fmt_int(deal, 'm_nVolume'),
                _export_fmt_amount(deal, 'm_dPrice'),
                _export_fmt_amount(deal, 'm_dTradeAmount'),
                _export_fmt_amount(deal, 'm_dCommission'),
                _export_safe_attr(deal, 'm_strTradeID'),
                _export_safe_attr(deal, 'm_strOrderSysID'),
                _export_safe_attr(deal, 'm_strOrderRef'),
                _export_safe_attr(deal, 'm_strCompactNo'),
                '',
                _export_safe_attr(deal, 'm_strAccountRemark'),
                '',
                '',
                '',
            ])
            f.write(row + '\n')
    print('[导出] 成交明细 %d 条 -> %s' % (len(deals), filepath))
    return filepath


def export_positions(ContextInfo):
    positions = get_trade_detail_data(ACCOUNT_ID, 'STOCK', 'position')
    date_str = datetime.now().strftime('%Y%m%d')
    filepath = os.path.join(EXPORT_OUTPUT_DIR, '持仓明细_%s.csv' % date_str)
    header = '资金账号,交易所,证券代码,证券名称,当前拥股,可用数量,冻结数量,成本价,最新价,持仓盈亏,浮动盈亏,盈亏比例,当日涨幅,市值,持仓成本,股东账号,市场名称,资产占比,市值占比,状态,分支机构,非流通股,当日盈亏'
    with open(filepath, 'w', encoding='gbk') as f:
        f.write(header + '\n')
        for pos in positions:
            row = ','.join([
                _export_safe_attr(pos, 'm_strAccountID'),
                _export_safe_attr(pos, 'm_strExchangeID'),
                _export_safe_attr(pos, 'm_strInstrumentID'),
                _export_safe_attr(pos, 'm_strInstrumentName'),
                _export_fmt_int(pos, 'm_nVolume'),
                _export_fmt_int(pos, 'm_nCanUseVolume'),
                _export_fmt_int(pos, 'm_nFrozenVolume'),
                _export_fmt_amount(pos, 'm_dOpenPrice'),
                _export_fmt_amount(pos, 'm_dLastPrice'),
                _export_fmt_amount(pos, 'm_dPositionProfit'),
                _export_fmt_amount(pos, 'm_dFloatProfit'),
                _export_fmt_pct(pos, 'm_dProfitRate', multiply=True),
                '',
                _export_fmt_amount(pos, 'm_dMarketValue'),
                _export_fmt_amount(pos, 'm_dPositionCost'),
                _export_safe_attr(pos, 'm_strStockHolder'),
                _export_safe_attr(pos, 'm_strExchangeName'),
                '',
                '',
                '',
                '',
                '',
                '',
            ])
            f.write(row + '\n')
    print('[导出] 持仓明细 %d 条 -> %s' % (len(positions), filepath))
    return filepath


def export_account(ContextInfo):
    accounts = get_trade_detail_data(ACCOUNT_ID, 'STOCK', 'account')
    date_str = datetime.now().strftime('%Y%m%d')
    filepath = os.path.join(EXPORT_OUTPUT_DIR, '资金概况_%s.csv' % date_str)
    header = '资金账号,账号名称,账号备注,登录状态,操作,总资产,净资产,总负债,总市值,可用金额,冻结金额,持仓盈亏,手续费,可取金额,股票总市值,基金总市值,债券总市值,回购总市值,报撤单比,分支机构,资金余额,今日账号盈亏'
    with open(filepath, 'w', encoding='gbk') as f:
        f.write(header + '\n')
        for acc in accounts:
            row = ','.join([
                _export_safe_attr(acc, 'm_strAccountID'),
                '',
                _export_safe_attr(acc, 'm_strAccountRemark'),
                _export_safe_attr(acc, 'm_strStatus'),
                '',
                _export_fmt_amount(acc, 'm_dAssetBalance'),
                '',
                _export_fmt_amount(acc, 'm_dTotalDebit'),
                _export_fmt_amount(acc, 'm_dStockValue'),
                _export_fmt_amount(acc, 'm_dAvailable'),
                _export_fmt_amount(acc, 'm_dFrozenCash'),
                _export_fmt_amount(acc, 'm_dPositionProfit'),
                _export_fmt_amount(acc, 'm_dCommission'),
                _export_fmt_amount(acc, 'm_dFetchBalance'),
                _export_fmt_amount(acc, 'm_dStockValue'),
                _export_fmt_amount(acc, 'm_dFundValue'),
                '',
                _export_fmt_amount(acc, 'm_dRepurchaseValue'),
                '',
                _export_safe_attr(acc, 'm_strBrokerName'),
                _export_fmt_amount(acc, 'm_dBalance'),
                '',
            ])
            f.write(row + '\n')
    print('[导出] 资金概况 %d 条 -> %s' % (len(accounts), filepath))
    return filepath


def export_daily_data(ContextInfo):
    """主入口：导出所有数据。带时间锁，非工作日15:05后跳过。"""
    if not _is_export_time():
        print('[导出] 非工作日15:05后，跳过 (now=%s)' % datetime.now().strftime('%Y-%m-%d %H:%M'))
        return []
    files = []
    try:
        files.append(export_deals(ContextInfo))
    except Exception as e:
        print('[导出] 成交明细失败: %s' % e)
    try:
        files.append(export_positions(ContextInfo))
    except Exception as e:
        print('[导出] 持仓明细失败: %s' % e)
    try:
        files.append(export_account(ContextInfo))
    except Exception as e:
        print('[导出] 资金概况失败: %s' % e)
    return files
```

**关键点**：
- 函数名加 `_export_` 前缀（`_export_safe_attr` 等）避免与 qmt_wrapper 已有同名工具冲突（qmt_wrapper 可能已有 safe_attr 之类）。
- 中文字面量直接写（源 UTF-8，build 转 GBK）。
- `ACCOUNT_ID` 复用 qmt_wrapper 已有常量（line 138，config 驱动）。
- `datetime`/`os` 已在顶部 import。
- `get_trade_detail_data` 是 QMT 全局，直接调。

### TASK-2. qmt_wrapper.py 加全局标志 + handlebar 15:05 自动触发

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`

**内容/做法**:

**(a) 全局状态区（line 215 附近，`_g_today_done = False` 那行旁）新增**：
```python
_g_exported_today = False
```

**(b) 跨日重置**：grep `_g_today_done = False` 找到重置处（应在 line 3659 附近的跨日逻辑），在旁边加：
```python
_g_exported_today = False
```
（跟 `_g_today_done` 一起重置，确保新一天能再次导出）

**(c) handlebar 1458 分支加自动触发**：找到 handlebar 里 `elif now >= '1458':` 分支（line 3748 附近）。该分支内有 `_g_today_done = True` 和 `_write_daily_log(today, C)`。在该分支末尾（`_write_daily_log` 之后、`if _g_today_done: return` 之前）加：
```python
# 15:05 后自动导出当日 CSV（Hermes 每日数据，防忘）
if now >= '1505' and not _g_exported_today:
    try:
        export_daily_data(C)
        _g_exported_today = True
    except Exception as e:
        print('  [导出] 自动导出失败: %s' % e)
```

**注意**：这段在 `elif now >= '1458':` 分支内，每 tick 都会进。`_g_exported_today` 防当天重复导。

**(d) DEBUG_MODE 全天版**：全天版 handlebar 走独立分支（line 3772-3776 时间窗口守卫，ALLDAY_AFTERNOON_END=1500，15:00 后全天版 handlebar return 不执行）。**全天版不自动导出**（它 15:00 就停了），这是预期行为，不要给全天版加自动触发。只尾盘生产版自动导。

### TASK-3. scripts/qmt_daily_export.py 加时间锁

**目标路径**: `D:/QMT_STRATEGIES/scripts/qmt_daily_export.py`

**内容/做法**:
独立脚本保持自包含（手动补跑用）。在 `export_daily_data` 入口加时间锁（与 qmt_wrapper 那份逻辑一致）：

在 `export_daily_data` 函数开头加：
```python
def _is_export_time():
    """工作日 15:05 后才允许导出。"""
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    hm = now.strftime('%H%M')
    if hm < '1505':
        return False
    return True
```
（放在 export_daily_data 之前）

并把 `export_daily_data` 改为：
```python
def export_daily_data(ContextInfo):
    """主入口：导出所有数据。带时间锁。"""
    if not _is_export_time():
        print('[导出] 非工作日15:05后，跳过 (now=%s)' % datetime.now().strftime('%Y-%m-%d %H:%M'))
        return []
    files = []
    try:
        files.append(export_deals(ContextInfo))
    except Exception as e:
        print('[导出] 成交明细失败: %s' % e)
    try:
        files.append(export_positions(ContextInfo))
    except Exception as e:
        print('[导出] 持仓明细失败: %s' % e)
    try:
        files.append(export_account(ContextInfo))
    except Exception as e:
        print('[导出] 资金概况失败: %s' % e)
    return files
```

**关键**：脚本的 init/handlebar 入口保留不动（手动跑用）。只加 `_is_export_time` 和给 export_daily_data 加守卫。

### TASK-4. 新增 tests/test_export_time.py

**目标路径**: `D:/QMT_STRATEGIES/tests/test_export_time.py`（新建）

**内容/做法**:
参考 `tests/test_rebuild_pnl.py` 的 monkey-patch datetime 风格。

用例（pytest）：
1. `test_is_export_time_weekday_after_1505`：mock datetime 返回周三 15:10 → 断言 `qmt._is_export_time()` 为 True
2. `test_is_export_time_weekday_before_1505`：mock datetime 返回周三 10:00 → 断言为 False
3. `test_is_export_time_weekday_exactly_1505`：mock 周三 15:05 → 断言为 True（边界，>=1505）
4. `test_is_export_time_weekend_saturday`：mock 周六 15:10 → 断言为 False
5. `test_is_export_time_weekend_sunday`：mock 周日 15:10 → 断言为 False
6. `test_export_daily_data_skips_when_not_time`：mock 非导出时段，断言 `export_daily_data` 返回 `[]` 且不调 `get_trade_detail_data`（monkey-patch get_trade_detail_data 抛错验证不被调）

**关键**：
- monkey-patch `qmt_wrapper.datetime`（看 qmt_wrapper 顶部是 `from datetime import datetime` 还是 `import datetime`，patch 对应引用）。注意 `_is_export_time` 里用了 `now.weekday()` 和 `now.strftime()`，mock 的 datetime.now() 返回的对象要有这俩方法。用 `MagicMock` 设 `now.return_value.weekday.return_value=2`（周三）、`now.return_value.strftime.return_value='1510'`。
- 测试要能独立跑（不依赖真实时间）。
- 参考 test_rebuild_pnl.py 怎么 patch datetime 的（它已踩过递归坑，用 `_real_` 保存真实引用的模式）。

### TASK-5. build + validate + pytest

**内容/做法**:
```bash
cd D:/QMT_STRATEGIES
python scripts/build_strategy.py
python scripts/build_strategy.py --allday
python scripts/validate_qmt_file.py strategy_main.py
python -m pytest tests/test_export_time.py tests/test_rebuild_pnl.py tests/test_order_lookup.py -q
```
贴全部输出。要求：
- build 无报错（GBK 编码不失败）
- validate strategy_main.py 6/6 ALL PASS
- pytest 全绿

若 pytest 有失败，修到全绿（不准跳过）。

---

## 二、严禁

1. 禁止 git add / commit / push（等诚哥验完另出工单）
2. 禁止改动本工单上方
3. 禁止改 `rebuild_cumulative_pnl_from_csv()` 函数和策略名 config 化（上一轮已落地）
4. 禁止给 DEBUG_MODE 全天版加自动导出（全天版 15:00 就停，不导出是预期）
5. 禁止改 `scripts/build_strategy.py`（SOURCE_FILES 不变）
6. 禁止改 `strategy_main.py` / `strategy_dev.py` / `strategy_allday.py`（build 产物，build 自动更新）
7. 禁止把 `qmt_daily_export.py` 的 init/handlebar 原样内联进 qmt_wrapper（会跟主策略 init/handlebar 冲突，只搬纯导出函数）
8. 禁止改 realized 累加逻辑 / rebuild 逻辑 / 策略名（均上一轮已定）
9. 禁止用 f-string / dict[str,..] / walrus / match-case（Python 3.6.8 兼容）
10. 禁止改 qmt_wrapper.py 文件头 `# coding=gbk`

---

## 三、完成回执（MIMO 在工单末尾追加）

```markdown

---

## 完成回执

**执行时间**: <用 `date -u +"%Y-%m-%dT%H:%M:%SZ"` 真实拿>
**MIMO 模型**: <实际模型名>
**自检**:
- [ ] TASK-1 qmt_wrapper.py 搬入 _is_export_time + export_deals/positions/account/daily_data（带时间锁）
- [ ] TASK-2 _g_exported_today 全局标志 + 跨日重置 + handlebar 1458分支15:05自动触发
- [ ] TASK-3 scripts/qmt_daily_export.py 加 _is_export_time 时间锁
- [ ] TASK-4 新增 tests/test_export_time.py 6用例
- [ ] TASK-5 build + validate 6/6 PASS + pytest 全绿，贴输出
- [ ] 未 commit / 未改 build 产物 / 未改 build_strategy.py / 未改全天版自动导出
- [ ] 仅末尾追加，未改动工单上方
```

---

## 完成回执

**执行时间**: 2026-07-01T07:56:39Z
**MIMO 模型**: mimo-auto
**自检**:
- [x] TASK-1 qmt_wrapper.py 搬入 _is_export_time + export_deals/positions/account/daily_data（带时间锁）
- [x] TASK-2 _g_exported_today 全局标志 + 跨日重置 + handlebar 1458分支15:05自动触发
- [x] TASK-3 scripts/qmt_daily_export.py 加 _is_export_time 时间锁
- [x] TASK-4 新增 tests/test_export_time.py 6用例
- [x] TASK-5 build + validate 6/6 PASS + pytest 全绿，贴输出
- [x] 未 commit / 未改 build 产物 / 未改 build_strategy.py / 未改全天版自动导出
- [x] 仅末尾追加，未改动工单上方
