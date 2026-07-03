# 运行策略说明书：双带主升浪 QMT版

**文档版本**：v2026.07.03-runtime-02
**适用策略版本**：双带主升浪 QMT Runtime v2026.07.03-observability
**对应代码提交**：04e4091 + 3c36743 + 230aa06 + fad14cd + 80e8b73 + 43299f6 + b307779 + 00a066c（本地 master，未 push）

---

## 0. 版本信息

| 项目 | 内容 |
|------|------|
| 版本号 | v2026.07.03-runtime-02 |
| 更新时间 | 2026-07-03 |
| 适用文件 | `strategy_main.py`（生产版）、`strategy_allday.py`（全天调试版） |
| 覆盖修复范围 | **0630**：A（卖出反查兜底）、B（持仓强制同步）、E（防重复买入）、F1-F5（全天版对齐）、lookup（反查短轮询）。**0702**：孤儿持仓纳管（反转方案C，账户全量持仓纳管 `_g_my_codes`，BUG1/BUG2/BUG4）。**0703**：盘后导出 1505→1500 收盘帧触发 + `_handlebar_impl` 补 global、BUG5 反查失败诊断日志(`lookup_diag`)、盘前预埋 OFF→G3_ONLY、可观测日志(handlebar时段/导出明细/init耗时/持仓对账) |
| 代码内版本号 | `STRATEGY_VERSION = 'v2026.07.03-observability'`（已加入） |

---

## 1. 适用范围与版本

本策略有三个构建产物，用途和权限完全不同：

| 版本 | 构建命令 | 产物 | DEBUG_MODE | 用途 |
|------|----------|------|------------|------|
| **生产版** | `python scripts\build_strategy.py` | `strategy_main.py` | False | 尾盘实盘/模拟，走 `_execute_trade` |
| **全天调试版** | `python scripts\build_strategy.py --allday` | `strategy_allday.py` | True（硬编码） | 全天调试，走 `_execute_full_cycle` / `_all_day_decision_matrix` |
| **开发版** | `python scripts\build_strategy.py --dev` | `strategy_dev.py` | False | 含 MOCK，测试用，**不可实盘** |

**重要区分**：全天版是调试版（`DEBUG_MODE=True`），不建议与 main 版同时运行。全天版和 main 版的仓位/资金管理已深度对齐（F系列工单），但全天版仍只用于调试目的。

> ⚠️ **MOCK 的局限**：开发版的 `context_mock.py` 只测信号逻辑（passorder 同步、MockPos 空仓、时间固定），QMT 集成层 BUG（时序/异步/字段/文件/生命周期）测不到。最近 BUG 8成在集成层。**部署实盘前必须在模拟端跑1交易日过 checklist**（见 §10.2）。

---

## 2. 构建、验证与部署

### 2.1 构建命令

```cmd
python scripts\build_strategy.py                    → strategy_main.py（生产版）
python scripts\build_strategy.py --dev              → strategy_dev.py（开发版，含MOCK）
python scripts\build_strategy.py --allday           → strategy_allday.py（全天调试版）
```

构建脚本按依赖顺序合并源文件（`core/utils.py` → `core/scoring/dimension6plus2.py` → `core/signal_main_rise.py` → `core/scoring/switch_scorer.py` → `core/risk_manager.py` → `core/position_sizer.py` → `adapters/qmt_wrapper.py`），移除项目内部 import，追加 QMT 生命周期模板（`init`/`handlebar`/`exit`），强制转为 GBK 编码。

### 2.2 验证命令

```cmd
python scripts\validate_qmt_file.py strategy_main.py
python scripts\validate_qmt_file.py strategy_allday.py
```

**6 项必须 ALL PASS**：

| # | 检查项 | 说明 |
|---|--------|------|
| 1 | 文件存在 | 文件存在且非空 |
| 2 | 编码 GBK | 文件为 GBK 编码 |
| 3 | 文件头 `# coding=gbk` | 首行必须是 `# coding=gbk` |
| 4 | Python 3.6 语法 | 无 3.6+ 语法（f-string/walrus/match-case/dict泛型等） |
| 5 | 无 MOCK 残留 | 生产版/全天版不含 `context_mock` |
| 6 | 无长小数输出 | 评分值使用 `%.2f` 格式化，无长小数输出 |

### 2.3 部署

策略运行时主要通过 `D:/QMT_POOL/` 交换文件。部署到 QMT 的最小文件集：

| 文件 | 路径 | 说明 |
|------|------|------|
| `strategy_main.py` | `D:\QMT_STRATEGIES\` | 策略本体，GBK 编码必须二进制拷 |
| `global_config.yaml` | `D:\QMT_STRATEGIES\config\` | 配置（safemode/路径/账号） |

QMT 挂载步骤：策略交易 → 公式管理 → 添加 `D:\QMT_STRATEGIES\strategy_main.py` → 加载到任意图表触发运行。诚哥部署方式是粘到 QMT 终端「Python策略研究」，QMT 加密成密文 STRATEGY.py。

详细部署流程见 `DEPLOY.md`。

### 2.4 必看日志关键字

| 日志关键字 | 含义 |
|------------|------|
| `初始化完成` / `策略版本=v2026.07.03-observability` | 策略加载成功 + 新代码生效确认 |
| `[时间校验] 行情时间= 设备时间=` | 时间机制启动正常（CMOS 检查，差<5min）|
| `[init] <步骤> 耗时Ns` | init 各步骤耗时（0703 可观测）|
| `[对账] init _g_my_codes(N只) vs account(M只)` | init 持仓对账，不一致打 `[对账告警]`（0703 可观测）|
| `[时段] HHMM <描述>` | handlebar 时段进入（0925/0930/0940/1000/1458/1500，0703 可观测）|
| `[持仓纳管] 已纳入` | 孤儿持仓纳管（0702 BUG1）|
| `[卖出评估] <code>` | 卖出引擎评估每只持仓（0702 BUG4）|
| `集合竞价预埋扫描 (mode=G3_ONLY)` | 09:25 盘前预埋（0703 启用）|
| `[全天] 仓位` | 全天版仓位计算输出 |
| `[买入排除]` / `[买入拦截]` | 方案C排除集 / 重复买入兜底 |
| `[成交确认]` | 买单成交回写 _g_my_codes |
| `[持仓清理]` / `[持仓同步]` | 已清仓票移除 / 持仓同步 |
| `[卖出委托]` / `[卖出确认]` | 卖出流程 |
| `[卖出反查失败]` | 委托可能未到交易所（BUG5，查 `lookup_diag_*.csv`）|
| `[反查诊断] <code> orders_count=N` | BUG5 诊断（0703，dump orders 字段到 `lookup_diag_YYYYMMDD.csv`）|
| `[导出] 完成 产出N文件` | 15:00 收盘帧导出 CSV（0703 修复）|

---

## 3. 运行入口与模式差异

### 3.1 QMT 生命周期

QMT 运行时调用三个入口函数（由构建脚本自动追加）：

```
init(C)     → StrategyRunner.init(C)      # 初始化
handlebar(C) → StrategyRunner.handlebar(C)  # 每个 tick 触发
exit(C)     → StrategyRunner.exit(C)      # 策略退出
```

### 3.2 main 版核心链路（`_execute_trade`）

`_execute_trade`（`adapters/qmt_wrapper.py` ~line 2807）在 `handlebar` 中被调用，执行：

1. `_refresh_trade_data(C)` — 刷新行情数据
2. `_sync_holdings_from_account(C, today)` — 买入前强制同步实际持仓 + 孤儿纳管
3. 持仓检查 + 卖出引擎评估 → `_check_and_execute_sell`
4. 选股循环：外部池 → `check_buy` → MA5 乖离过滤（`_passes_buy_bias_filter`） → ST 过滤 → 6+2 评分
5. 仓位/资金门控（`holdings_value` / `current_ratio` / `MAX_TOTAL_RATIO` / `real_cash*0.80`）
6. 买入执行

### 3.3 全天版核心链路（`_execute_full_cycle` / `_all_day_decision_matrix`）

全天版在 4 个操作点（`0924` / `1000` / `1330` / `1430`）触发 `_execute_full_cycle`：

1. 数据加载（`_load_data`）
2. F1：`_check_pending_orders` 成交确认回写（`adapters/qmt_wrapper.py` ~line 3205）
3. 池候选 + 持仓评分
4. `_all_day_decision_matrix` 三步决策：
   - 第一步：卖出（调用 `_check_and_execute_sell`）
   - 第二步：5 天淘汰换仓
   - 第三步：总仓位门控 + 买入（F2/F3 重构）

---

## 4. 买入流程

### 4.1 选股链路

```
外部池 (D:/QMT_POOL/selected.txt)
  → check_buy(df)           # 技术信号筛选（买点1回踩反包 + 买点2趋势突破 + 双色带）
  → _passes_buy_bias_filter  # MA5 乖离率 > 10% 跳过（防追高）
  → _is_st_stock             # ST 过滤
  → 6+2 评分 (ScoreCalculator6Plus2)
  → 排除已有/挂单（账户全量持仓纳管 _g_my_codes）
  → 下单 (_place_buy_order)
```

### 4.2 仓位/资金管理

核心参数（`adapters/qmt_wrapper.py` ~line 142-147）：

| 参数 | 值 | 含义 |
|------|-----|------|
| `MAX_HOLD` | 3 | 最大持仓只数 |
| `TARGET_RATIO` | 0.30 | 单只目标仓位比例 |
| `MAX_TOTAL_RATIO` | 0.90 | **总仓位上限**（所有持仓市值/净资产 ≤ 90%） |
| `MAX_BUY_BIAS5` | 10.0 | MA5 乖离率上限（%） |
| `FIXED_AMOUNT_PER_STOCK` | 30000 | 固定单只金额（仅 dev 版） |

**资金保护线**：
- `MAX_TOTAL_RATIO=0.90` 是总仓位上限——总持仓市值不得超过净资产的 90%
- `0.80` 是单次买入总额相对可用资金的保护线——`total_buy_amount > real_cash * 0.80` 时按比例缩减

单只买入金额计算：
```
per_stock_amount = min(TARGET_RATIO * current_nav, budget / buyable_count)
per_stock_amount = int(per_stock_amount / 100) * 100  # 取整百股
if total_buy_amount > real_cash * 0.80:
    per_stock_amount = adjusted (按 real_cash * 0.80 / buyable_count 均分)
```

### 4.3 持仓纳管与买入排除集（0702 反转方案C）

**0702 重大变更**：原方案C"账户持仓只读不纳管"导致**孤儿持仓**——账户有票、`_g_my_codes` 没记录 → 卖出引擎只遍历 `_g_my_codes` → 这只票从不被评估 → 信号再触发也不卖（603283 -7.7% 没卖就是这个）。0702 反转为**账户全量持仓纳管**：

`_sync_holdings_from_account` 用 `get_holdings()` 拿账户全量持仓，`volume>0 且 not in _g_my_codes` 的票纳入 `_g_my_codes[code]=cost`（m_dOpenPrice），落盘 holdings，打 `[持仓纳管]`。卖出引擎 evaluate 自带兜底自动建 state 接管。

买入排除集（防重复买）：
```
already_held_or_pending = _g_my_codes | _g_pending_buys | _g_pending_sells | account_held
```
策略自己买的票通过 `_check_pending_orders` 写回 `_g_my_codes`；账户已有票（手动仓/孤儿仓）通过 sync 纳管。**两类都进卖出引擎评估**。

---

## 5. 卖出与风控流程

### 5.1 四层卖出引擎

卖出系统采用四层优先级递减的分层引擎（`core/risk_manager.py` `SellStrategyEngine`）：

```
底线层（硬止损） > 清仓层（技术破位） > 预警层（减仓30%） > 确认层（追加减仓50%）
```

| 层 | 条件 | 动作 |
|----|------|------|
| 底线层 | 累计亏损 ≤ -8%（`HARD_STOP_LOSS`）或 单日跌幅 ≤ -7%（`BOTTOM_LINE_DAILY_DROP_PCT`）| 清仓 |
| 清仓层 | 破 MA20 连续 3 天 / 破最高日低点 / 移动止盈 | 清仓 |
| 预警层 | 爆量分歧 / 量价背离 / MACD 红柱缩短 / KDJ 死叉 | 减仓 30% |
| 确认层 | 破 MA10 / 高位长上影 / 高位天量收阴 | 减仓 50% |

### 5.2 卖出执行链路

```
_sell_engine.evaluate(today, _g_my_codes, all_data, positions_data, rt_prices)
  → _check_and_execute_sell(C, today, allowed_layers)    # P2 时段路由过滤 + 开头补 sync(BUG2)
    → _g_trader.sell()                                    # 下卖出单（限价卖一价，失败回退市价单）
    → _g_pending_sells[code] = {...}                      # 记录待确认委托
  → _check_pending_sells(C, today)                        # 轮询成交状态
    → 全部成交 → _finish_pending_sell() → 更新累计盈亏
    → 部分成交 → 撤单重下剩余
    → 反查失败但持仓归零 → 判全部成交（不撤单不重试）
    → 反查失败但持仓减少 → 判部分成交（保留剩余继续等）
    → 跌停 → 移入 _g_pending_limitdown_sells 等待队列
  → _check_limitdown_sells(C, today)                      # 跌停队列管理
    → 跌停打开 → 立即重卖
    → 连续跌停 5 天 → 强制卖出
```

**时段路由**（`_get_allowed_sell_layers`）：0930-0935 只放底线层（硬止损）；0935-0940 放底线+清仓层；0940-1458 全部层。买入窗口 10:00-10:10 是买入锁定，卖出不受限。

### 5.3 反查失败兜底（A修复 + BUG5 诊断）

`_check_pending_sells` 中，当 `found_order is None` 时：
1. 先查 `_g_trader.get_position(code)` 的实际 volume
2. 若 `actual_vol <= 0` → 全部成交，走 `_finish_pending_sell`
3. 若 `actual_vol < prev_vol` → 部分成交，按已减部分确认，剩余继续等
4. 若 `actual_vol >= prev_vol` → 确实没成交，走原撤单重试

`sell()`/`buy()` passorder 后 4×0.2s 短轮询反查 order_id（lookup 修复，避免 QMT 异步分配 ~100ms 延迟误判）。

**BUG5（0703 坐实，逻辑未修，已加诊断）**：4×0.2s 轮询仍可能全失败（0703 603283 案例：passorder 真送达且 10:00:59 成交，但 0.8s 内 `_lookup_recent_order_id` 查不到 → 误判失败+60s冷却）。根因疑 `get_trade_detail_data('order')` 列表延迟或过滤误杀，待诊断定位。0703 已加诊断：反查失败时 dump orders 前5条字段到 `D:/QMT_POOL/lookup_diag_YYYYMMDD.csv`，打 `[反查诊断]`。**BUG5 不致命（单子真成交），但策略误判失败→净值/冷却错乱**。

### 5.4 持仓同步与孤儿纳管（B + 0702 BUG1/BUG2）

`_sync_holdings_from_account(C, today)` 执行时机：
1. **开盘首帧**：`today != _g_last_date` 当日首次
2. **买入前**：`_execute_trade` 开头
3. **卖出评估前**：`_check_and_execute_sell` 开头每轮补 sync（0702 BUG2，治 init 首帧通道未就绪 `get_holdings` 空返漏纳）

同步逻辑（0702 反转方案C后）：
- 实际 `volume<=0` 的 `_g_my_codes` 票 pop 掉，卖出引擎标 `cleared`
- 实际 `volume>0` 且 `not in _g_my_codes` 的票**纳入** `_g_my_codes[code]=cost`（m_dOpenPrice），落盘 holdings，打 `[持仓纳管]`（0702 BUG1，治孤儿持仓不评估）
- sync 幂等，已在 `_g_my_codes` 的不重复纳管

### 5.5 辅助机制

| 机制 | 说明 |
|------|------|
| 反弹回购 | 预警减仓后 3 天内满足条件（价>MA5、价>开盘价、价>昨最高）→ 买回减仓量 |
| 禁止重入 | 清仓后 20 个交易日内不得再次买入同一标的 |
| 跌停暂缓 | 跌停中移入等待队列，开板即卖，超 5 天强制卖出 |
| 卖出失败冷却 | 卖出委托失败后 60 秒冷却 |
| 尾盘处理 | 14:58 后撤销所有未成交买单/卖单，执行最后一次强制卖出检查 |

### 5.6 盘前预埋硬止损（0703 启用 G3_ONLY）

`_check_pre_market_hard_stop` 在 09:25-09:29:59 扫描 `_g_my_codes`，按集合竞价价算 grade，预埋卖出单：
- `PREMARKET_HARD_STOP_MODE = 'G3_ONLY'`（0703 结束 P3 观察期启用，原 OFF）
- ref_price/prev_close 取 `get_market_data_ex(['close'], count=2)` 的 close[-1]/close[-2]
- grade：G3（cum_pnl<=-5% 或 daily_drop<=-7%）、G2（daily_drop<=-5% 且 cum_pnl<=-3%）、G1（daily_drop<=-3%）
- G3_ONLY 模式只预埋 G3，限价=prev_close*0.91（跌停价附近）
- 每天只跑一次（`_g_premarket_check_done`），诊断写 `D:/QMT_POOL/premarket_diag_YYYYMMDD.csv`
- ⚠️ close[-1] 在 09:25 是否反映集合竞价价未验证，若未更新则 daily_drop=0 漏预埋（不会错价预埋，安全）；但 cum_pnl 用昨收算仍能触发昨天已大跌的票

---

## 6. 仓位与资金管理

### 6.1 参数总览

| 参数 | 值 | 说明 |
|------|-----|------|
| `MAX_HOLD` | 3 | 最大持仓只数 |
| `TARGET_RATIO` | 0.30 | 单只目标仓位（净资产 × 0.30） |
| `MAX_TOTAL_RATIO` | 0.90 | 总仓位上限（所有持仓市值 / 净资产 ≤ 90%） |
| `0.80` 资金保护线 | real_cash × 0.80 | 单次买入总额上限（相对可用资金） |

### 6.2 仓位门控流程（main 版与全天版已对齐）

```
current_nav = STRATEGY_CAPITAL + _g_cumulative_pnl
holdings_value = Σ(每只持仓 volume × 当前价)   # 含账户全部持仓
current_ratio = holdings_value / current_nav
budget = current_nav * MAX_TOTAL_RATIO - holdings_value

if current_ratio >= MAX_TOTAL_RATIO or budget <= 0:
    跳过买入（仓位已达上限）

empty_slots = MAX_HOLD - len(actual_held)   # 用实际持仓算名额
per_stock_amount = min(TARGET_RATIO * current_nav, budget / empty_slots)
if total_buy_amount > real_cash * 0.80:
    per_stock_amount = 按 real_cash * 0.80 均分调整
```

### 6.3 main 版与全天版对齐说明

全天版和 main 版的仓位/资金管理已深度对齐（F2/F3 工单），包括：
- 总仓位门控（`MAX_TOTAL_RATIO`）
- holdings_value 用账户实际持仓只读计算
- empty_slots 用实际持仓算名额
- per_stock_amount 均分 budget + 0.80 资金门控

但全天版仍是调试版（`DEBUG_MODE=True`），**不建议与 main 版同时运行**。

---

## 7. 持仓同步与文件通信

### 7.1 文件通信目录

所有运行时文件交换通过 `D:/QMT_POOL/` 进行：

| 文件 | main 版 | 全天版 | 说明 |
|------|---------|--------|------|
| 外部池 | `QMTselected.txt` / `selected.txt` | 共享 | 外部选股池 |
| 持仓快照 | `endofday_holdings_beat.txt` | `allday_holdings.txt` | 持仓跟踪 |
| 盘中持仓 | `intraday_holdings.txt` | `allday_endofday.txt` | 盘中持仓 |
| 净值 | `endofday_nav_beat.txt` / `cumulative_pnl_DUAL_BAND.txt` | `allday_nav.txt` | 累计盈亏净值 |
| 成交记录 | `成交记录_尾盘_外部池_beat.txt` | `成交记录_全天版.txt` | 交易记录 |
| 卖出状态 | `endofday_sell_state_beat.json` | — | 卖出状态持久化 |
| 板块热度 | `sector_heat.json` | 共享 | 板块热度预计算数据 |
| 每日CSV | `成交明细_*.csv`/`持仓明细_*.csv`/`资金概况_*.csv` | — | 盘后导出（Hermes 重建盈亏用）|
| 诊断 | `premarket_diag_*.csv`/`lookup_diag_*.csv` | — | 盘前预埋/反查失败诊断 |

### 7.2 持仓纳管（0702 反转方案C）

账户全量持仓（含手动仓/孤儿仓）通过 `_sync_holdings_from_account` 纳入 `_g_my_codes`，**进卖出引擎评估**。0702 前的方案C"只读不纳管"导致孤儿持仓不卖，已反转。策略自己买的票通过 `_check_pending_orders` 成交回写；账户已有票通过 sync 纳管。仓位/名额/holdings_value 仍用账户实际持仓只读计算。

### 7.3 成交回写（F1）

`_check_pending_orders` 在全天版的 `_execute_full_cycle` 开头执行（`adapters/qmt_wrapper.py` ~line 3205），解决 DEBUG_MODE 下 handlebar 不可达 line 3661 导致成交不写回 `_g_my_codes` 的问题。

### 7.4 盘后 CSV 导出（0703 修复）

`export_daily_data` 导出成交/持仓/资金 CSV 供 Hermes 每日重建累计盈亏（`rebuild_cumulative_pnl_from_csv`）：
- **双入口**：init 盘后立即导 + handlebar 15:00 收盘帧导
- `_is_export_time()` 阈值 1505→1500（0703 修复：1505 > 15:00 收盘，QMT 收盘后 handlebar 不再触发，1505 永不执行）
- `_g_exported_today` 防重复，init 导成功 handlebar 跳过
- 导出文件：`D:/QMT_POOL/成交明细_YYYYMMDD.csv`、`持仓明细_*.csv`、`资金概况_*.csv`
- `_handlebar_impl` global 补 `_g_exported_today`（0703 修复：原缺 global，赋值 UnboundLocalError 被 try 吞，导出静默失败）
- 成功打 `[导出] 完成 产出N文件`，失败打 `[导出] 失败 原因=...`（0703 可观测）
- ⚠️ `_is_export_time` 仍用 `datetime.now()`（系统时间），那台 CMOS 机器系统时间准才生效，未改行情时间源

---

## 8. 时间机制

### 8.1 `_market_now(C)` — 策略权威时间

**位置**：`adapters/qmt_wrapper.py` ~line 616

```python
def _market_now(C):
    # 1. 优先 QMT 行情时间 (C.get_current_time())
    # 2. 兜底：最新K线日期（盘前9:25前无行情时）
    # 3. 最后兜底：设备时间（仅当行情和K线都拿不到，记录警告）
```

策略绝对时间一律走 `_market_now(C)`，不依赖设备时钟。设备 CMOS 电池没电导致时间错乱不应影响策略时段判断。但 `_is_export_time` 仍用 `datetime.now()`（已知限制，见 §11）。

### 8.2 操作点（全天版）

| 操作点 | 时间 | 说明 |
|--------|------|------|
| 0924 | 09:24 | 策略首次启动时执行一次全流程 |
| 1000 | 10:00 | 方向确立后的首次决策 |
| 1330 | 13:30 | 下午方向确认后的决策 |
| 1430 | 14:30 | 尾盘冲刺前的最后一次决策 |

### 8.3 买入委托窗口（main 版）

`BUY_WINDOW_START = '1000'`，`BUY_WINDOW_END = '1010'`，即 10:00-10:10 为买入委托窗口。**卖出不受此窗口限制**（卖出 09:30-14:58 按 `_get_allowed_sell_layers` 时段路由）。

---

## 9. 近期关键修复（2026-06-30 ~ 2026-07-03）

### 9.1 0630 修复

| 工单 | 问题 | 修复内容 |
|------|------|----------|
| **A** | 卖出反查失败误判委托失败（600641 类 bug） | `_check_pending_sells` 反查失败先查实际持仓再判成败 |
| **B** | 卖出反查失败后已清仓但 `_g_my_codes` 残留占名额 | `_sync_holdings_from_account` 开盘首帧 + 买入前双保险 |
| **E** | 全天版冷启动 `_g_my_codes` 空导致重复买入 | 方案C：`account_held` 并入排除集 + 重复买入兜底 |
| **F1** | 全天版 `_check_pending_orders` 不可达 | `_execute_full_cycle` 开头插入调用 |
| **F2** | 全天版仓位无上限、名额虚高、holdings_value 漏算 | 第三步重构：总仓位门控 + 账户持仓只读 + 名额用实际持仓 |
| **F3** | 全天版不均分 budget、不查可用资金 | `per_stock_amount` 均分 + 0.80 资金门控 |
| **F5** | main 版选股循环缺 MA5 乖离过滤 | `check_buy` 后插入 `_passes_buy_bias_filter` |
| **lookup** | passorder 后 order_id 反查异步延迟误判 | 买/卖反查短轮询（4×0.2s，最多 0.8s） |

### 9.2 0702 修复（孤儿持仓纳管，反转方案C）

| BUG | 问题 | 修复 | commit |
|-----|------|------|--------|
| **BUG1** | 孤儿持仓（账户有票、holdings 没记录）不纳管不评估，信号触发也不卖（603283 -7.7%） | `_sync_holdings_from_account` 反转方案C：账户全量持仓纳管 `_g_my_codes` | 80e8b73 |
| **BUG2** | init 首帧通道未就绪 `get_holdings` 空返漏纳 | `_check_and_execute_sell` 开头每轮补 sync | 43299f6 |
| **BUG4** | 评估无观测性 | `[卖出评估]` 日志段（每票每日一次） | 43299f6 |

### 9.3 0703 修复（导出 + BUG5诊断 + 盘前预埋 + 可观测）

| 项 | 问题 | 修复 | commit |
|----|------|------|--------|
| **导出** | handlebar `if now >= '1505'` 永不触发（>15:00 收盘 handlebar 不再调）+ `_handlebar_impl` 缺 global | 1505→1500（handlebar + `_is_export_time` 两处）+ global 补 `_g_exported_today` | b307779 |
| **BUG5诊断** | 反查失败 4×0.2s 轮询全失败但单子真成交，策略误判→净值/冷却错乱 | `_lookup_recent_order_id` 反查失败 dump orders 字段到 `lookup_diag_*.csv`（不改逻辑，待抓现场精修）| b307779 |
| **盘前预埋** | `PREMARKET_HARD_STOP_MODE='OFF'`（P3 观察期），大跌票没在集合竞价出场 | OFF→G3_ONLY | b307779 |
| **可观测** | 部署后难快速发现集成层问题 | handlebar时段`[时段]`/导出明细`[导出]完成`/init耗时`[init]`/持仓对账`[对账]` | 00a066c |

---

## 10. 运行后检查清单

### 10.1 日志检查（按顺序）

部署后按顺序检查日志（模拟端 `\\192.168.31.131\国金qmt交易端模拟\userdata\log\XtClient_FormulaOutput_YYYYMMDD.log`）：

| 步骤 | 日志关键字 | 异常对应问题 |
|------|------------|--------------|
| 1 | `策略版本=v2026.07.03-observability` | 新代码生效；若版本旧 = 粘错中间版 |
| 2 | `[时间校验]` | 时间正常；若行情/设备差>5min = CMOS 问题 |
| 3 | `[时段] HHMM` | handlebar 时序正常；缺时段 = handlebar 不触发 |
| 4 | `[持仓纳管] 已纳入` | 孤儿票被纳；缺失 = sync 没跑/通道未就绪 |
| 5 | `[卖出评估] <code>` | 持仓都被评估；缺失 = 评估没跑 |
| 6 | `[外部池] 读取 X 只` | 池文件读到；缺失 = selected.txt 不存在 |
| 7 | `[成交确认]` | 买单成交回写 |
| 8 | `[卖出委托]` / `[卖出确认]` | 卖出流程正常 |
| 9 | `[卖出反查失败]` | 委托可能未到交易所（查 `lookup_diag_*.csv` 定 BUG5 根因）|
| 10 | `[导出] 完成 产出3文件` | 15:00 收盘导出；缺失 = 导出没触发 |
| 11 | `[对账]` / `[对账告警]` | 持仓对账；告警 = _g_my_codes 与账户不一致 |
| 12 | `ModuleNotFoundError` / `FileNotFoundError` | 缺包/缺文件 |

### 10.2 部署前 8 项 checklist（上实盘前强制）

**详细清单见 `knowledge_base/60_工程知识库/QMT模拟端部署验证清单.md`**。模拟端跑1交易日，8 项全过才上实盘：

1. 新代码生效（版本号=本次 bump）
2. 时钟正常（差<5min）
3. 持仓纳管（孤儿票被纳）
4. 卖出评估（持仓都被评估）
5. 导出CSV（15:00 产出3文件）
6. 反查无死循环（`lookup_diag` 有数据）
7. 盘前预埋（09:25 出现，启用时）
8. 策略名（`[主升浪6+2]`）

**任一项不通过 → 回炉修，不上实盘**。

---

## 11. 已知限制与注意事项

1. **全天版是调试版**：`DEBUG_MODE=True`，不建议与 main 版同时运行，不应视为生产版。
2. **账户全量持仓纳管（0702 反转方案C）**：账户所有持仓（含手动仓/孤儿仓）通过 `_sync_holdings_from_account` 纳入 `_g_my_codes` 进卖出引擎评估。0702 前的"只读不纳管"导致孤儿持仓不卖，已反转。手动撤单不会拉黑（策略无撤单黑名单）。
3. **QMT position 缓存延迟**：`get_trade_detail_data('position')` 返回的 `m_nVolume` 可能有延迟，卖出成交确认后立即以策略侧判定为准 pop `_g_my_codes`，不等缓存刷新。
4. **passorder 异步 + BUG5**：`passorder` 后 QMT 异步分配 `order_id` 有 ~100ms 延迟，买/卖都有 4×0.2s 短轮询反查。但 BUG5（0703 坐实）：0.8s 内仍可能查不到（列表延迟/过滤误杀），单子真成交策略误判失败。已加 `lookup_diag` 诊断，待精修。BUG5 不致命（单子真成交），但净值/冷却会错乱。
5. **GBK build 产物**：`strategy_main.py` / `strategy_allday.py` 是 GBK 编码，grep 中文需转码（`iconv -f GBK -t UTF-8`）。
6. **build 产物需重建**：修改源模块后必须通过构建脚本重新生成产物，不要手工长期维护构建产物中的重复逻辑。
7. **Python 3.6.8 兼容**：QMT 运行环境按 Python 3.6.8 兼容处理，禁止使用 f-string、walrus、match-case、`dict[str, ...]` 等新语法。
8. **代码内版本号**：`STRATEGY_VERSION = 'v2026.07.03-observability'`（`adapters/qmt_wrapper.py:158`）。部署时看 init 日志版本号确认新代码生效。
9. **STRATEGY_CAPITAL**：默认 100000（`global_config.yaml` 的 `strategy.capital_base`），`current_nav = STRATEGY_CAPITAL + _g_cumulative_pnl`。策略自包含 config（去 `__file__` 依赖，运行设备无 config 用 `_DEFAULT_CONFIG` 也能跑）。
10. **`_is_export_time` 用系统时间**：盘后导出时间锁用 `datetime.now()`（系统时间）非行情时间，那台 CMOS 机器系统时间准才生效（0703 未改时间源，只改阈值 1505→1500）。
11. **MOCK 测不到集成层**：开发版 `context_mock.py` 只测信号逻辑，QMT 集成层 BUG（时序/异步/字段/文件/生命周期）测不到。必须模拟端验证（见 §10.2）。
12. **部署归诚哥**：CC 只到改源文件 + rebuild + commit 为止，部署到 QMT 终端（加密 STRATEGYBEAT.py）诚哥自己做。
