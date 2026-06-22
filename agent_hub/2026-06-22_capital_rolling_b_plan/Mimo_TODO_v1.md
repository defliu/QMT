# B 方案落地：策略基准 10万 + 盈利滚动 + get_total_asset 字段修复

**日期**: 2026-06-22
**作者**: CC
**目的**: 让每策略按"初始 10万 + 累计盈利滚动"算 current_nav，并修复 `get_total_asset()` 在国金 QMT 版本下误返回可用资金的 bug
**预计工时**: ≤ 40 分钟
**解冻授权**: 诚哥 2026-06-22 明确指示"先这么改吧"
**背景知识**: [[QMT账户资金数据获取]]（已写入 knowledge_base/60_工程知识库/）

---

## 一、必做（M 项）

### TASK-1. 修复 `Trader.get_total_asset()` 字段优先级

**目标路径**: `D:/QMT_STRATEGIES/strategy_main.py` 第 3283-3301 行
**背景**: 国金 QMT 实测 account 对象**没有** `m_dTotalAsset` / `totalAsset` / `m_dTotal`，老 fallback 链走到 `m_dMarketValue`（也不存在），最终只剩 `m_dAvailable` —— 把可用资金误当总资产返回。
**做法**: 替换为下面这版（新字段优先级按 2026-06-22 实测 dump）：

```python
def get_total_asset(self):
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
```

### TASK-2. 新增 `Trader.get_market_value()` 方法

**目标路径**: `D:/QMT_STRATEGIES/strategy_main.py`，紧接 `get_total_asset()` 之后
**做法**: 新增方法，返回持仓总市值：

```python
def get_market_value(self):
    """持仓总市值（从 account 对象读，不遍历 position）"""
    try:
        accounts = get_trade_detail_data(self.acct, self.acct_type, 'account')
        if accounts:
            acct = accounts[0]
            for attr in ('m_dStockValue', 'm_dInstrumentValue', 'm_dMarketValue'):
                val = getattr(acct, attr, None)
                if val is not None and float(val) > 0:
                    return float(val)
    except Exception as e:
        print("[告警] 查询市值失败: %s" % e)
    return 0.0
```

### TASK-3. `STRATEGY_CAPITAL` 改为从配置读取

**目标路径**: `D:/QMT_STRATEGIES/strategy_main.py` 第 2906 行
**现状**: `STRATEGY_CAPITAL = 100000`（硬编码）
**做法**: 改为从 `_path_config` 读，保留 100000 作为默认值：

```python
STRATEGY_CAPITAL = float(_strategy_config.get('capital_base', 100000))
```

**前置**: 在文件头部加载 `_strategy_config` 的位置（搜 `_path_config =` 附近），增加：

```python
_strategy_config = _config.get('strategy', {}) if isinstance(_config, dict) else {}
```

（如果 `_strategy_config` 已存在则跳过此步，仅确认它有 `capital_base` 字段访问能力）

### TASK-4. global_config.yaml 增加 capital_base 字段

**目标路径**: `D:/QMT_STRATEGIES/config/global_config.yaml` 第 2-8 行 `strategy:` 段
**做法**: 在 `strategy:` 段新增 `capital_base: 100000`：

```yaml
strategy:
  name: "DUAL_BAND"
  capital_base: 100000     # 每策略初始本金（B 方案：10万 + 盈利滚动）
  max_hold: 5
  target_ratio: 0.16
  # ... 其余保持不变
```

### TASK-5. current_nav 计算逻辑保持不变（验证即可，不改）

**目标路径**: `D:/QMT_STRATEGIES/strategy_main.py` 第 5142 行
**现状**:
```python
current_nav = STRATEGY_CAPITAL + _g_cumulative_pnl
```
**做法**: **不要改**。因为 TASK-3 已经让 `STRATEGY_CAPITAL` 变成配置驱动的 10万，`_g_cumulative_pnl` 是累计盈利 —— 这就是 B 方案的 `current_nav = 10万 + 累计盈利`。
**验证**: 在该行下方临时加一行 print（MIMO 不要加，CC 验收时手动查日志）：

```python
# 验证用 print（MIMO 不要加这行）
# print("[B方案] base=%.0f pnl=%.0f nav=%.0f" % (STRATEGY_CAPITAL, _g_cumulative_pnl, current_nav))
```

### TASK-6. 现金护栏保持不变（验证即可，不改）

**目标路径**: `D:/QMT_STRATEGIES/strategy_main.py` 第 5307-5316 行
**现状**:
```python
real_cash = _g_trader.get_available_cash()
max_buy_from_cash = real_cash * 0.80
```
**做法**: **不要改**。这是用账户真实可用资金做护栏，符合 B 方案"账户真实总资产只用于显示/护栏"的原则。

### TASK-7. 报表显示保持不变（验证即可）

**目标路径**: `D:/QMT_STRATEGIES/strategy_main.py` 第 4495-4526 行
**现状**: `get_total_asset()` / `get_available_cash()` 用于"五、账户概述"报表
**做法**: **不要改**。TASK-1 修好后，报表会自动显示正确的总资产（1002.5万 而不是 996.6万）。

### TASK-8. 验证：跑 6 项必须 ALL PASS

**目标路径**: `D:/QMT_STRATEGIES/`
**命令**:
```cmd
python scripts\validate_qmt_file.py strategy_main.py
```
**要求**: 6 项必须 ALL PASS。失败则修到 PASS 为止，不要跳过。

### TASK-9. 重新构建 strategy_main.py

**目标路径**: `D:/QMT_STRATEGIES/`
**命令**:
```cmd
python scripts\build_strategy.py
```
**说明**: 如果 strategy_main.py 是 build_strategy.py 生成的，改源文件后要重新 build。如果 strategy_main.py 是直接编辑的（不在 build 链里），跳过此 TASK。
**判断**: 看 build_strategy.py 的 SOURCE_FILES 是否包含本次改的源文件，包含则必须 rebuild。

---

## 二、严禁

1. 禁止 git add / commit / push（本工单不授权任何 git 动作）
2. 禁止改动本工单上方列出的路径之外的任何文件
3. 禁止改 `current_nav = STRATEGY_CAPITAL + _g_cumulative_pnl` 这个核心公式（B 方案就是靠它）
4. 禁止改现金护栏 `real_cash * 0.80` 逻辑
5. 禁止改报表显示逻辑（TASK-1 修好后报表自动正确）
6. 禁止读 `D:/QMT_STRATEGIES/` 之外的文件（`D:/QMT_POOL/` 只读不写）
7. 禁止动 `_g_cumulative_pnl` 的读写逻辑（endofday_nav_beat.txt 是策略各自累计盈亏的真相源，不能动）
8. 禁止跳过 validate_qmt_file.py 验证
9. 禁止在 strategy_main.py 里加任何"验证用 print"（CC 验收时自己加）
10. 禁止改 `scripts/build_strategy.py` 和 `scripts/validate_qmt_file.py`

---

## 三、完成回执（MIMO 在工单末尾追加）

```markdown

---

## 完成回执

**执行时间**: <ISO 8601 真实时刻，用 `date -u +"%Y-%m-%dT%H:%M:%SZ"` 拿>
**MIMO 模型**: <实际名>
**自检**:
- [ ] TASK-1 get_total_asset 字段优先级已替换
- [ ] TASK-2 get_market_value 已新增
- [ ] TASK-3 STRATEGY_CAPITAL 改为配置驱动
- [ ] TASK-4 global_config.yaml capital_base 已加
- [ ] TASK-5/6/7 未动核心公式/护栏/报表逻辑
- [ ] TASK-8 validate_qmt_file.py 6 项 ALL PASS（贴输出）
- [ ] TASK-9 build_strategy.py 已跑（如适用，贴输出末尾 5 行）

**改动文件清单**:
- <绝对路径 1>
- <绝对路径 2>

**风险提示**:
- <任何 CC 没考虑到的情况>
```

---

## 完成回执

**执行时间**: 2026-06-22T14:00:48Z
**MIMO 模型**: mimo-auto
**自检**:
- [x] TASK-1 get_total_asset 字段优先级已替换
- [x] TASK-2 get_market_value 已新增
- [x] TASK-3 STRATEGY_CAPITAL 改为配置驱动
- [x] TASK-4 global_config.yaml capital_base 已加
- [x] TASK-5/6/7 未动核心公式/护栏/报表逻辑
- [x] TASK-8 validate_qmt_file.py 6 项 ALL PASS（见下方）
- [x] TASK-9 build_strategy.py 已跑（见下方）

**TASK-8 验证输出**:
```
Validating: strategy_main.py
  [1/6] 文件存在         PASS
  [2/6] 编码 GBK         PASS
  [3/6] 文件头 # coding=gbk  PASS
  [4/6] Python 3.6 语法   PASS
  [5/6] 无 MOCK 残留      PASS
  [6/6] 无长小数输出      PASS  (最大浮点值 %.2f)
  ------------------------
  Result: ALL PASS  (6/6)
```

**TASK-9 构建输出末尾 5 行**:
```
Building strategy_main.py ...
OK: strategy_main.py (生产版, 不含MOCK)
Size: 216999 bytes
First line: # coding=gbk
Encoding: GBK (verified by reading with gbk)
Validating... OK
Done.
```

**改动文件清单**:
- D:/QMT_STRATEGIES/adapters/qmt_wrapper.py（TASK-1: get_total_asset 重写 + TASK-2: get_market_value 新增 + TASK-3: _strategy_config/STRATEGY_CAPITAL 配置化）
- D:/QMT_STRATEGIES/config/global_config.yaml（TASK-4: 增加 capital_base 字段）
- D:/QMT_STRATEGIES/strategy_main.py（TASK-9: build_strategy.py 重新构建产物）

**风险提示**:
- get_total_asset 字段优先级已按国金 QMT 实测 dump 重排，m_dAssetBalance / m_dBalance / m_dAssureAsset 优先于 m_dTotalAsset。若后续 QMT 版本变更字段名，可能需要再次调整 fallback 链。
- get_market_value 为新增方法，当前未被核心逻辑调用，仅作未来扩展备用，无副作用。
