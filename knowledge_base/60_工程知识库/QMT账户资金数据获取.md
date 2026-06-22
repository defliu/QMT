---
tags: [已验证, 可转SPEC]
---

# QMT 账户资金数据获取

> 工程踩坑：QMT `get_trade_detail_data(..., 'account')` 返回的 account 对象字段名随版本变化，老代码按 `m_dTotalAsset` 取总资产会走到 fallback，最终把"可用资金"误当"总资产"返回。本文记录实测字段映射 + 诊断方法，作为后续 Hermes 每日资金统计、多策略分账核算的底座。

关联：[[QMT_passorder异步与反查订单号]]、[[QMT编码制度]]、[[QMT新设备部署清单]]

---

## 一、API 通道

```python
# QMT 内建 API（strategy_main.py exec() 环境 + 实盘模式可用）
accounts  = get_trade_detail_data(acct_id, 'STOCK', 'account')   # 账户资金
positions = get_trade_detail_data(acct_id, 'STOCK', 'position')  # 持仓明细
orders    = get_trade_detail_data(acct_id, 'STOCK', 'order')     # 委托
deals     = get_trade_detail_data(acct_id, 'STOCK', 'deal')      # 成交
```

**前提条件**：
1. QMT 交易端已登录（不是只登行情端）
2. 策略运行模式是 **实盘**，不是回测
3. 顶层代码调用会报 `'NoneType' object has no attribute 'request_id'` —— 必须包到 `def init(ContextInfo):` 里，等 QMT 把交易通道接上后再调
4. 若 init 里仍偶尔返回 None，加 1-15 秒重试

---

## 二、实测字段映射（2026-06-22，国金 QMT 模拟端，账户 67014907）

### account 对象（类型 `CAccountDetail`，63 个属性）

| 语义 | 实测字段 | 实测值 | 备注 |
|---|---|---|---|
| **总资产** | `m_dAssetBalance` / `m_dBalance` / `m_dAssureAsset` / `m_dEntrustAsset` | 10024703.36 | 4 个字段同值，任取其一 |
| 可用资金 | `m_dAvailable` | 9945015.36 | 现金可用 |
| 总市值 | `m_dStockValue` / `m_dInstrumentValue` | 80095.0 | 2 个字段同值 |
| 冻结资金 | `m_dFrozenCash` | 0.0 | |
| 保证金占用 | `m_dCurrMargin` | 79687.0 | |
| 持仓盈亏 | `m_dPositionProfit` | 4390.75 | |
| 平仓盈亏 | `m_dCloseProfit` | 0.0 | |
| 手续费 | `m_dCommission` | 10.49 | |
| 昨日余额 | `m_dPreBalance` | 10024702.36 | |
| 账户 ID | `m_strAccountID` | 67014907 | |
| 账户状态 | `m_strStatus` | `登录失败` | ⚠️ **误导性字段**，实测通道正常时也显示"登录失败"，不要据此判断通道状态 |
| 交易日 | `m_strTradingDate` | 20260622 | |

**踩过的坑**：老代码 fallback 链 `m_dTotalAsset → totalAsset → m_dTotal → 市值+可用`，前 3 个字段在国金 QMT 版本里**都不存在**，走到 `m_dMarketValue` 也不存在（返回 0），最终只剩 `m_dAvailable` —— **把可用资金误当总资产返回**，导致报表显示"总资产 = 可用资金"。

### position 对象（类型 `CPositionDetail`，61 个属性）

| 语义 | 实测字段 | 实测值 | 备注 |
|---|---|---|---|
| 持仓量 | `m_nVolume` | 0 / 400 | **T+1 当日买入显示 0**，要看 `m_nYesterdayVolume` |
| 昨日持仓 | `m_nYesterdayVolume` | 400 | T+1 可卖部分 |
| 可用量 | `m_nCanUseVolume` | 0 | |
| 开仓均价 | `m_dAvgOpenPrice` | 13.91 | |
| 最新价 | `m_dLastPrice` | 17.15 | |
| 浮动盈亏 | `m_dFloatProfit` | -356.0 | |
| 持仓盈亏 | `m_dPositionProfit` | 2536.9 | ⚠️ 与 `m_dFloatProfit` 语义不同，需进一步验证 |
| 证券代码 | `m_strInstrumentID` | 600110 | 不带交易所后缀 |
| 交易所 | `m_strExchangeID` | SH | |
| 证券名称 | `m_strInstrumentName` | 诺德股份 | |
| 股东代码 | `m_strStockHolder` | A218044003 | |
| 是否今日新仓 | `m_bIsToday` | True | |

**坑**：position 列表会返回**已清仓但当日有成交的记录**（`m_nVolume = 0`），遍历时要 `if pos.m_nVolume > 0` 过滤。

---

## 三、推荐封装（QMT 各版本兼容）

```python
def get_total_asset(self):
    """总资产 —— 跨 QMT 版本字段兼容"""
    try:
        accounts = get_trade_detail_data(self.acct, self.acct_type, 'account')
        if accounts:
            acct = accounts[0]
            # 新字段优先级（按 2026-06-22 国金 QMT 实测）
            for attr in ('m_dAssetBalance', 'm_dBalance', 'm_dAssureAsset',
                         'm_dTotalAsset', 'totalAsset', 'm_dTotal'):
                val = getattr(acct, attr, None)
                if val is not None and float(val) > 0:
                    return float(val)
            # fallback: 可用 + 市值
            avail = float(getattr(acct, 'm_dAvailable', 0) or 0)
            mv = float(getattr(acct, 'm_dStockValue', 0) or
                       getattr(acct, 'm_dInstrumentValue', 0) or 0)
            if avail > 0 or mv > 0:
                return avail + mv
    except Exception as e:
        print("[告警] 查询总资产失败: %s" % e)
    return 0.0


def get_market_value(self):
    """持仓总市值"""
    try:
        accounts = get_trade_detail_data(self.acct, self.acct_type, 'account')
        if accounts:
            acct = accounts[0]
            for attr in ('m_dStockValue', 'm_dInstrumentValue', 'm_dMarketValue'):
                val = getattr(acct, attr, None)
                if val is not None and float(val) > 0:
                    return float(val)
    except Exception:
        pass
    return 0.0
```

---

## 四、多策略分账核算（B 方案）

### 问题
QMT 账户是**共享**的（一个 67014907 跑所有策略），账户总资产 1000 万 ≠ 单策略可用本金。多策略并行时，每个策略要"认领"自己的 10 万 + 自己赚的部分。

### 解法
- **每个策略各维护一份累计盈亏文件**（如 `D:/QMT_POOL/endofday_nav_<策略名>.txt`）
- `current_nav = STRATEGY_CAPITAL_BASE + 累计盈利`（STRATEGY_CAPITAL_BASE 配置化，默认 10 万）
- 账户真实总资产**只用于**：
  - 报表显示
  - 现金护栏（`real_cash * 0.80`）
  - 每日盘后校准累计盈亏文件（避免文件漂移）

### 配置（global_config.yaml）
```yaml
strategy:
  capital_base: 100000   # 每策略初始本金
  capital_mode: "rolling"  # rolling = 10万+盈利滚动；fixed = 固定10万；full = 用账户真实总资产
```

---

## 五、诊断脚本

文件：`D:/QMT_STRATEGIES/diag_account.py`

用法：复制到 `D:/国金QMT交易端模拟/python/TEST.py`，QMT 实盘运行，日志输出贴回分析。

输出 3 段：
1. account 对象全部属性 dump
2. position 对象全部属性 dump（取第一条持仓）
3. 常见字段名探测（快速看哪些存在、哪些不存在）

---

## 六、后续：Hermes 每日资金统计

诚哥计划让 Hermes 每天查账户资金 + 统计各策略指标。基础数据链路：

```
QMT account API → endofday_nav_<策略>.txt（累计盈亏）→ Hermes 每日读取 → 统计指标
                                            ↑
                            每日盘后用 get_total_asset() 校准
```

**待定**：
- Hermes 是 SPEC 输出 agent，不直接跑数据采集。需要一个数据采集脚本（Python）每天盘后跑，写入 DuckDB 或 JSON，Hermes 再读。
- 各策略指标口径（净值曲线、回撤、夏普、胜率）需对齐回测工厂 v0.2 的 metrics 定义，避免实盘/回测口径不一致。

待代码落地后再展开设计。

---

## 七、变更记录

| 日期 | 事件 |
|---|---|
| 2026-06-22 | CC 首次实测 account/position 字段映射，定位 `get_total_asset()` fallback 误返回可用资金的 bug；起草 B 方案 MIMO 工单 |
