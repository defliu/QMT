# 工单M：QMT 每日导出 — 正式导出脚本（ODM 第二步，基于探针实测属性名）

**日期**: 2026-06-30
**作者**: CC
**目的**: 基于 `D:/qmt_pool/probe_output.txt` 实测属性名，写正式导出脚本 `scripts/qmt_daily_export.py`，导出成交/持仓/资金三张 CSV 到 `D:\qmt_pool\`。SPEC 属性名大面积错误，本工单用实测属性名。
**预计工时**: ≤ 40 分钟

---

## 〇、背景（必读，不要改这段）

探针已跑（`D:/qmt_pool/probe_output.txt`），实测属性名与 SPEC 大量不符。本工单**只用实测属性名**，SPEC 的属性名作废。

诚哥拍板：
- 持仓盈亏：已实现(`m_dPositionProfit`)+浮动(`m_dFloatProfit`)都导（在 SPEC 列基础上加一列"浮动盈亏"）
- 不存在字段：保留 CSV 列名，值留空字符串

输出目录 `D:\qmt_pool\`，GBK 编码，Python 3.6.8 语法。

---

## 一、实测属性名映射（必须严格按此映射，不要用 SPEC 的）

### 1.1 成交明细 deal（`get_trade_detail_data(ACCOUNT_ID, 'STOCK', 'deal')`）

| CSV列名 | 对象属性 | 备注 |
|---------|---------|------|
| 资金账号 | `m_strAccountID` | |
| 成交日期 | `m_strTradeDate` | YYYYMMDD |
| 成交时间 | `m_strTradeTime` | HHMMSS |
| 交易所 | `m_strExchangeID` | SH/SZ |
| 证券代码 | `m_strInstrumentID` | 不含后缀 |
| 证券名称 | `m_strInstrumentName` | |
| 买卖标记 | `m_strOptName` | "限价买入"/"限价卖出" |
| 成交数量 | `m_nVolume` | 整数 |
| 成交价格 | `m_dPrice` | 2位小数 |
| 成交金额 | `m_dTradeAmount` | 2位小数 |
| 手续费 | `m_dCommission` | 2位小数 |
| 成交编号 | `m_strTradeID` | |
| 合同编号 | `m_strOrderSysID` | |
| 订单编号 | `m_strOrderRef` | |
| 任务编号 | `m_strCompactNo` | 实测空，留空 |
| 投资备注 | （不存在） | 留空 |
| 账号备注 | `m_strAccountRemark` | |
| 分支机构 | （不存在） | 留空 |
| 投资备注1 | （不存在） | 留空 |
| 股东号 | （deal 无此属性） | 留空 |

**成交明细 CSV 列顺序**（header）：
```
资金账号,成交日期,成交时间,交易所,证券代码,证券名称,买卖标记,成交数量,成交价格,成交金额,手续费,成交编号,合同编号,订单编号,任务编号,投资备注,账号备注,分支机构,投资备注1,股东号
```

### 1.2 持仓明细 position（`get_trade_detail_data(ACCOUNT_ID, 'STOCK', 'position')`）

| CSV列名 | 对象属性 | 备注 |
|---------|---------|------|
| 资金账号 | `m_strAccountID` | |
| 交易所 | `m_strExchangeID` | |
| 证券代码 | `m_strInstrumentID` | |
| 证券名称 | `m_strInstrumentName` | |
| 当前拥股 | `m_nVolume` | 整数 |
| 可用数量 | `m_nCanUseVolume` | 整数 |
| 冻结数量 | `m_nFrozenVolume` | 整数 |
| 成本价 | `m_dOpenPrice` | 2位小数 |
| 最新价 | `m_dLastPrice` | 2位小数 |
| 持仓盈亏 | `m_dPositionProfit` | 2位小数（已实现） |
| 浮动盈亏 | `m_dFloatProfit` | 2位小数（诚哥要求加的列） |
| 盈亏比例 | `m_dProfitRate` | 实测是小数(0.09)，CSV 写 `×100` 保留2位小数(9.06) |
| 当日涨幅 | （不存在 m_dTodayProfitRate） | 留空 |
| 市值 | `m_dMarketValue` | 2位小数 |
| 持仓成本 | `m_dPositionCost` | 2位小数 |
| 股东账号 | `m_strStockHolder` | |
| 市场名称 | `m_strExchangeName` | "上证所"等 |
| 资产占比 | （不存在 m_dAssetRatio，探针未见） | 留空 |
| 市值占比 | （不存在） | 留空 |
| 状态 | （探针未见 m_strStatus） | 留空 |
| 分支机构 | （不存在） | 留空 |
| 非流通股 | （探针未见 m_nNonTradeVolume） | 留空 |
| 当日盈亏 | （不存在 m_dTodayProfit） | 留空 |

**持仓明细 CSV 列顺序**（header）：
```
资金账号,交易所,证券代码,证券名称,当前拥股,可用数量,冻结数量,成本价,最新价,持仓盈亏,浮动盈亏,盈亏比例,当日涨幅,市值,持仓成本,股东账号,市场名称,资产占比,市值占比,状态,分支机构,非流通股,当日盈亏
```

### 1.3 资金概况 account（`get_trade_detail_data(ACCOUNT_ID, 'STOCK', 'account')`）

| CSV列名 | 对象属性 | 备注 |
|---------|---------|------|
| 资金账号 | `m_strAccountID` | |
| 账号名称 | （探针未见 m_strAccountName） | 留空 |
| 账号备注 | `m_strAccountRemark` | |
| 登录状态 | `m_strStatus` | "登录成功" |
| 操作 | （探针未见 m_strOperation） | 留空 |
| 总资产 | `m_dAssetBalance` | 2位小数（实测，非 SPEC 的 m_dTotalAssets） |
| 净资产 | （不存在 m_dNetAssets） | 留空 |
| 总负债 | （探针未见 m_dTotalDebt，有 m_dTotalDebit） | 用 `m_dTotalDebit` |
| 总市值 | `m_dInstrumentValue` | 2位小数（或 m_dStockValue，二者实测相等取 m_dStockValue） |
| 可用金额 | `m_dAvailable` | 2位小数 |
| 冻结金额 | `m_dFrozenCash` | 2位小数 |
| 持仓盈亏 | `m_dPositionProfit` | 2位小数 |
| 手续费 | `m_dCommission` | 2位小数 |
| 可取金额 | `m_dFetchBalance` | 2位小数 |
| 股票总市值 | `m_dStockValue` | 2位小数 |
| 基金总市值 | （探针未见 m_dFundMarketValue，有 m_dFundValue） | 用 `m_dFundValue` |
| 债券总市值 | （不存在） | 留空 |
| 回购总市值 | （探针未见 m_dRepoMarketValue，有 m_dRepurchaseValue） | 用 `m_dRepurchaseValue` |
| 报撤单比 | （不存在） | 留空 |
| 分支机构 | （探针见 m_strBrokerName） | 用 `m_strBrokerName` |
| 资金余额 | `m_dBalance` | 2位小数 |
| 今日账号盈亏 | （不存在 m_dTodayProfit） | 留空 |

**资金概况 CSV 列顺序**（header）：
```
资金账号,账号名称,账号备注,登录状态,操作,总资产,净资产,总负债,总市值,可用金额,冻结金额,持仓盈亏,手续费,可取金额,股票总市值,基金总市值,债券总市值,回购总市值,报撤单比,分支机构,资金余额,今日账号盈亏
```

---

## 二、必做（3 项）

### TASK-1. 写正式导出脚本

**目标路径**: `D:/QMT_STRATEGIES/scripts/qmt_daily_export.py`

**内容要求**:

结构（参考 SPEC 4.1 模板，但属性名用上面的实测映射）：

```python
# coding=gbk
"""
QMT 每日交易数据导出脚本
每天收盘后导出：成交明细、持仓明细、资金概况
输出到 D:\qmt_pool\ 目录，GBK 编码 CSV
属性名基于 2026-06-30 探针实测（D:/qmt_pool/probe_output.txt）
"""

import os
from datetime import datetime

ACCOUNT_ID = '67014907'
OUTPUT_DIR = r'D:\qmt_pool'


def get_date_str():
    return datetime.now().strftime('%Y%m%d')


def safe_attr(obj, attr, default=''):
    """安全获取对象属性，不存在或异常返回空字符串"""
    if attr is None or attr == '':
        return default
    try:
        val = getattr(obj, attr, None)
        if val is None:
            return default
        return str(val)
    except Exception:
        return default


def fmt_amount(obj, attr):
    """金额格式化：2位小数，空值返回空字符串"""
    try:
        val = getattr(obj, attr, None)
        if val is None:
            return ''
        return '%.2f' % float(val)
    except Exception:
        return ''


def fmt_int(obj, attr):
    """数量格式化：整数，空值返回空字符串"""
    try:
        val = getattr(obj, attr, None)
        if val is None:
            return ''
        return str(int(val))
    except Exception:
        return ''


def fmt_pct(obj, attr, multiply=True):
    """百分比格式化：盈亏比例实测是小数，乘100后保留2位小数"""
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
    """导出当日成交明细"""
    deals = get_trade_detail_data(ACCOUNT_ID, 'STOCK', 'deal')
    date_str = get_date_str()
    filepath = os.path.join(OUTPUT_DIR, '成交明细_%s.csv' % date_str)
    header = '资金账号,成交日期,成交时间,交易所,证券代码,证券名称,买卖标记,成交数量,成交价格,成交金额,手续费,成交编号,合同编号,订单编号,任务编号,投资备注,账号备注,分支机构,投资备注1,股东号'
    with open(filepath, 'w', encoding='gbk') as f:
        f.write(header + '\n')
        for deal in deals:
            row = ','.join([
                safe_attr(deal, 'm_strAccountID'),
                safe_attr(deal, 'm_strTradeDate'),
                safe_attr(deal, 'm_strTradeTime'),
                safe_attr(deal, 'm_strExchangeID'),
                safe_attr(deal, 'm_strInstrumentID'),
                safe_attr(deal, 'm_strInstrumentName'),
                safe_attr(deal, 'm_strOptName'),
                fmt_int(deal, 'm_nVolume'),
                fmt_amount(deal, 'm_dPrice'),
                fmt_amount(deal, 'm_dTradeAmount'),
                fmt_amount(deal, 'm_dCommission'),
                safe_attr(deal, 'm_strTradeID'),
                safe_attr(deal, 'm_strOrderSysID'),
                safe_attr(deal, 'm_strOrderRef'),
                safe_attr(deal, 'm_strCompactNo'),
                '',  # 投资备注 不存在
                safe_attr(deal, 'm_strAccountRemark'),
                '',  # 分支机构 不存在
                '',  # 投资备注1 不存在
                '',  # 股东号 deal 无
            ])
            f.write(row + '\n')
    print('[导出] 成交明细 %d 条 -> %s' % (len(deals), filepath))
    return filepath


def export_positions(ContextInfo):
    """导出持仓明细"""
    positions = get_trade_detail_data(ACCOUNT_ID, 'STOCK', 'position')
    date_str = get_date_str()
    filepath = os.path.join(OUTPUT_DIR, '持仓明细_%s.csv' % date_str)
    header = '资金账号,交易所,证券代码,证券名称,当前拥股,可用数量,冻结数量,成本价,最新价,持仓盈亏,浮动盈亏,盈亏比例,当日涨幅,市值,持仓成本,股东账号,市场名称,资产占比,市值占比,状态,分支机构,非流通股,当日盈亏'
    with open(filepath, 'w', encoding='gbk') as f:
        f.write(header + '\n')
        for pos in positions:
            row = ','.join([
                safe_attr(pos, 'm_strAccountID'),
                safe_attr(pos, 'm_strExchangeID'),
                safe_attr(pos, 'm_strInstrumentID'),
                safe_attr(pos, 'm_strInstrumentName'),
                fmt_int(pos, 'm_nVolume'),
                fmt_int(pos, 'm_nCanUseVolume'),
                fmt_int(pos, 'm_nFrozenVolume'),
                fmt_amount(pos, 'm_dOpenPrice'),
                fmt_amount(pos, 'm_dLastPrice'),
                fmt_amount(pos, 'm_dPositionProfit'),
                fmt_amount(pos, 'm_dFloatProfit'),
                fmt_pct(pos, 'm_dProfitRate', multiply=True),
                '',  # 当日涨幅 不存在
                fmt_amount(pos, 'm_dMarketValue'),
                fmt_amount(pos, 'm_dPositionCost'),
                safe_attr(pos, 'm_strStockHolder'),
                safe_attr(pos, 'm_strExchangeName'),
                '',  # 资产占比 不存在
                '',  # 市值占比 不存在
                '',  # 状态 不存在
                '',  # 分支机构 不存在
                '',  # 非流通股 不存在
                '',  # 当日盈亏 不存在
            ])
            f.write(row + '\n')
    print('[导出] 持仓明细 %d 条 -> %s' % (len(positions), filepath))
    return filepath


def export_account(ContextInfo):
    """导出资金概况"""
    accounts = get_trade_detail_data(ACCOUNT_ID, 'STOCK', 'account')
    date_str = get_date_str()
    filepath = os.path.join(OUTPUT_DIR, '资金概况_%s.csv' % date_str)
    header = '资金账号,账号名称,账号备注,登录状态,操作,总资产,净资产,总负债,总市值,可用金额,冻结金额,持仓盈亏,手续费,可取金额,股票总市值,基金总市值,债券总市值,回购总市值,报撤单比,分支机构,资金余额,今日账号盈亏'
    with open(filepath, 'w', encoding='gbk') as f:
        f.write(header + '\n')
        for acc in accounts:
            row = ','.join([
                safe_attr(acc, 'm_strAccountID'),
                '',  # 账号名称 不存在
                safe_attr(acc, 'm_strAccountRemark'),
                safe_attr(acc, 'm_strStatus'),
                '',  # 操作 不存在
                fmt_amount(acc, 'm_dAssetBalance'),
                '',  # 净资产 不存在
                fmt_amount(acc, 'm_dTotalDebit'),
                fmt_amount(acc, 'm_dStockValue'),
                fmt_amount(acc, 'm_dAvailable'),
                fmt_amount(acc, 'm_dFrozenCash'),
                fmt_amount(acc, 'm_dPositionProfit'),
                fmt_amount(acc, 'm_dCommission'),
                fmt_amount(acc, 'm_dFetchBalance'),
                fmt_amount(acc, 'm_dStockValue'),
                fmt_amount(acc, 'm_dFundValue'),
                '',  # 债券总市值 不存在
                fmt_amount(acc, 'm_dRepurchaseValue'),
                '',  # 报撤单比 不存在
                safe_attr(acc, 'm_strBrokerName'),
                fmt_amount(acc, 'm_dBalance'),
                '',  # 今日账号盈亏 不存在
            ])
            f.write(row + '\n')
    print('[导出] 资金概况 %d 条 -> %s' % (len(accounts), filepath))
    return filepath


def export_daily_data(ContextInfo):
    """主入口：导出所有数据"""
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


def init(ContextInfo):
    export_daily_data(ContextInfo)


def handlebar(ContextInfo):
    pass
```

**关键**:
- 严格用上面的实测属性名，不要用 SPEC 的错误属性名。
- `fmt_pct` 对 `m_dProfitRate` 乘100（实测 0.09 → 9.06）。
- 空字段写 `''`，不写 `None`。
- 三个导出函数各自 try/except，一个失败不影响其他。
- `init` + `handlebar` 入口齐全。

### TASK-2. validate

```bash
python scripts/validate_qmt_file.py scripts/qmt_daily_export.py
```
必须 6 项 ALL PASS。贴输出。

### TASK-3. 给诚哥的运行说明

在回执里写清楚诚哥怎么跑（跟探针一样）：
1. 把 `scripts/qmt_daily_export.py` 内容粘到 QMT 模拟端「Python策略研究」
2. 账号选 67014907
3. 运行，等打印三条 `[导出] ... -> ...`
4. 检查 `D:\qmt_pool\` 下生成 `成交明细_YYYYMMDD.csv` / `持仓明细_YYYYMMDD.csv` / `资金概况_YYYYMMDD.csv`
5. 用 Excel 打开确认中文不乱码、数值正确
6. 把结果告诉 CC

---

## 三、严禁

1. 禁止 git add / commit / push
2. 禁止改动本工单上方
3. 禁止用 SPEC 的错误属性名（必须用上面的实测映射）
4. 禁止改 strategy_main.py / strategy_allday.py / qmt_wrapper.py / qmt_probe.py
5. 禁止跑实盘交易（脚本只读 get_trade_detail_data，不下单）
6. **文件编码 GBK，`# coding=gbk`；Python 3.6.8 语法（禁 f-string/dict[str,..]/walrus/match-case）**

---

## 四、完成回执（MIMO 在工单末尾追加）

```markdown

---

## 完成回执

**执行时间**: <用 `date -u +"%Y-%m-%dT%H:%M:%SZ"` 真实拿>
**MIMO 模型**: <实际模型名>
**自检**:
- [ ] scripts/qmt_daily_export.py 已创建，内容如工单 TASK-1
- [ ] 使用实测属性名（m_strInstrumentID/m_strInstrumentName/m_strOptName/m_dTradeAmount/m_dCommission/m_dLastPrice/m_dPositionProfit/m_dFloatProfit/m_dAssetBalance/m_dStockValue/m_dFetchBalance/m_dFrozenCash 等）
- [ ] validate scripts/qmt_daily_export.py 6 项 ALL PASS，贴输出
- [ ] 回执含给诚哥的运行说明
- [ ] 未改策略代码 / 未 git 操作 / 未跑实盘
- [ ] 仅末尾追加，未改动工单上方
```

---

## 完成回执

**执行时间**: 2026-06-30T15:20:08Z
**MIMO 模型**: mimo-auto
**自检**:
- [x] scripts/qmt_daily_export.py 已创建，内容如工单 TASK-1
- [x] 使用实测属性名（m_strInstrumentID/m_strInstrumentName/m_strOptName/m_dTradeAmount/m_dCommission/m_dLastPrice/m_dPositionProfit/m_dFloatProfit/m_dAssetBalance/m_dStockValue/m_dFetchBalance/m_dFrozenCash 等）
- [x] validate scripts/qmt_daily_export.py 6 项 ALL PASS，贴输出
- [x] 回执含给诚哥的运行说明
- [x] 未改策略代码 / 未 git 操作 / 未跑实盘
- [x] 仅末尾追加，未改动工单上方

**validate 输出**:
```
Validating: qmt_daily_export.py
  [1/6] 文件存在         PASS
  [2/6] 编码 GBK         PASS
  [3/6] 文件头 # coding=gbk  PASS
  [4/6] Python 3.6 语法   PASS
  [5/6] 无 MOCK 残留      PASS
  [6/6] 无长小数输出      PASS  (所有评分值 %.2f)
  ------------------------
  Result: ALL PASS  (6/6)
```

**给诚哥的运行说明**:

1. 把 `D:/QMT_STRATEGIES/scripts/qmt_daily_export.py` 的全部内容复制
2. 粘到 QMT 模拟端「Python策略研究」的编辑器里
3. 账号选 **67014907**
4. 点运行，等打印三行：
   - `[导出] 成交明细 X 条 -> D:\qmt_pool\成交明细_YYYYMMDD.csv`
   - `[导出] 持仓明细 X 条 -> D:\qmt_pool\持仓明细_YYYYMMDD.csv`
   - `[导出] 资金概况 X 条 -> D:\qmt_pool\资金概况_YYYYMMDD.csv`
5. 去 `D:\qmt_pool\` 检查三个 CSV 是否生成
6. 用 Excel 打开确认中文不乱码、数值正确
7. 把结果告诉 CC
