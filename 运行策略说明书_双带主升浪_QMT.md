# 运行策略说明书：双带主升浪 QMT版

**文档版本**：v2026.06.30-runtime-01
**适用策略版本**：双带主升浪 QMT Runtime v2026.06.30-f1f5-lookup
**对应代码提交**：04e4091 + 3c36743 + 230aa06 + fad14cd（本地 master）

---

## 0. 版本信息

| 项目 | 内容 |
|------|------|
| 版本号 | v2026.06.30-runtime-01 |
| 更新时间 | 2026-06-30 |
| 适用文件 | `strategy_main.py`（生产版）、`strategy_allday.py`（全天调试版） |
| 覆盖修复范围 | A（卖出反查兜底）、B（持仓强制同步）、E（防重复买入/方案C）、F1（全天版成交回写）、F2（总仓位门控/名额/holdings_value）、F3（per_stock_amount均分/0.80资金门控）、F5（main版MA5乖离过滤）、lookup（买卖委托反查加短轮询防异步误判） |
| 代码内版本号 | `STRATEGY_VERSION = 'v2026.06.30-f1f5-lookup'`（已加入） |

---

## 1. 适用范围与版本

本策略有三个构建产物，用途和权限完全不同：

| 版本 | 构建命令 | 产物 | DEBUG_MODE | 用途 |
|------|----------|------|------------|------|
| **生产版** | `python scripts\build_strategy.py` | `strategy_main.py` | False | 尾盘实盘/模拟，走 `_execute_trade` |
| **全天调试版** | `python scripts\build_strategy.py --allday` | `strategy_allday.py` | True（硬编码） | 全天调试，走 `_execute_full_cycle` / `_all_day_decision_matrix` |
| **开发版** | `python scripts\build_strategy.py --dev` | `strategy_dev.py` | False | 含 MOCK，测试用，**不可实盘** |

**重要区分**：全天版是调试版（`DEBUG_MODE=True`），不建议与 main 版同时运行。全天版和 main 版的仓位/资金管理已深度对齐（F系列工单），但全天版仍只用于调试目的。

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

QMT 挂载步骤：策略交易 → 公式管理 → 添加 `D:\QMT_STRATEGIES\strategy_main.py` → 加载到任意图表触发运行。

详细部署流程见 `DEPLOY.md`。

### 2.4 必看日志关键字

| 日志关键字 | 含义 |
|------------|------|
| `初始化完成` | 策略加载成功 |
| `[时间校验]` | 时间机制启动正常 |
| `[全天] 仓位` | 全天版仓位计算输出 |
| `[买入排除]` | 方案C排除集输出 |
| `[买入拦截]` | _place_buy_order 重复买入兜底 |
| `[成交确认]` | 买单成交回写 _g_my_codes |
| `[持仓清理]` | 已清仓票从 _g_my_codes 移除 |

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
2. `_sync_holdings_from_account(C, today)` — 买入前强制同步实际持仓
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
  → 排除已有/挂单（方案C：账户实际持仓只排除不纳管）
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

### 4.3 买入排除集（方案C）

全天版和 main 版都使用"方案C"——账户实际持仓参与仓位/名额/holdings_value 计算，但不写入 `_g_my_codes`、不进卖出引擎，避免误管手动仓。策略自己买的票通过 `_check_pending_orders` 写回 `_g_my_codes`，卖出引擎可管理。

排除集组成：
```
already_held_or_pending = _g_my_codes | _g_pending_buys | _g_pending_sells | account_held
```

---

## 5. 卖出与风控流程

### 5.1 四层卖出引擎

卖出系统采用四层优先级递减的分层引擎（`core/risk_manager.py` `SellStrategyEngine`）：

```
底线层（硬止损） > 清仓层（技术破位） > 预警层（减仓30%） > 确认层（追加减仓50%）
```

| 层 | 条件 | 动作 |
|----|------|------|
| 底线层 | 累计亏损 ≤ -5% 或 单日跌幅 ≤ -7% | 清仓 |
| 清仓层 | 破 MA20 连续 3 天 / 破最高日低点 / 移动止盈 | 清仓 |
| 预警层 | 爆量分歧 / 量价背离 / MACD 红柱缩短 / KDJ 死叉 | 减仓 30% |
| 确认层 | 破 MA10 / 高位长上影 / 高位天量收阴 | 减仓 50% |

### 5.2 卖出执行链路

```
_sell_engine.evaluate(today, _g_my_codes, all_data, positions_data, rt_prices)
  → _check_and_execute_sell(C, today, allowed_layers)    # P2 时段路由过滤
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

### 5.3 反查失败兜底（A修复）

`_check_pending_sells` 中，当 `found_order is None` 时：
1. 先查 `_g_trader.get_position(code)` 的实际 volume
2. 若 `actual_vol <= 0` → 全部成交，走 `_finish_pending_sell`
3. 若 `actual_vol < prev_vol` → 部分成交，按已减部分确认，剩余继续等
4. 若 `actual_vol >= prev_vol` → 确实没成交，走原撤单重试

这避免了 QMT 异步分配 order_id 延迟导致的误判"委托失败"（600641 类 bug）。

### 5.4 持仓强制同步（B修复）

`_sync_holdings_from_account(C, today)` 在两个时机执行：
1. **开盘首帧**：`today != _g_last_date` 当日首次
2. **买入前**：`_execute_trade` 开头

同步逻辑：实际 `volume<=0` 的 `_g_my_codes` 票 pop 掉，卖出引擎标 `cleared`；实际有 volume 但 `_g_my_codes` 没有的不自动加入（避免误纳手动仓）。

### 5.5 辅助机制

| 机制 | 说明 |
|------|------|
| 反弹回购 | 预警减仓后 3 天内满足条件（价>MA5、价>开盘价、价>昨最高）→ 买回减仓量 |
| 禁止重入 | 清仓后 20 个交易日内不得再次买入同一标的 |
| 跌停暂缓 | 跌停中移入等待队列，开板即卖，超 5 天强制卖出 |
| 卖出失败冷却 | 卖出委托失败后 60 秒冷却 |
| 尾盘处理 | 14:58 后撤销所有未成交买单/卖单，执行最后一次强制卖出检查 |

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
holdings_value = Σ(每只持仓 volume × 当前价)   # 含账户全部持仓（方案C只读计数）
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
| 净值 | `endofday_nav_beat.txt` / `endofday_nav.txt` | `allday_nav.txt` | 累计盈亏净值 |
| 成交记录 | `成交记录_尾盘_外部池_beat.txt` | `成交记录_全天版.txt` | 交易记录 |
| 卖出状态 | `endofday_sell_state_beat.json` | — | 卖出状态持久化 |
| 板块热度 | `sector_heat.json` | 共享 | 板块热度预计算数据 |

### 7.2 方案C：只读计数

账户持仓（含手动仓）参与仓位/名额/holdings_value 计算，但**不写入 `_g_my_codes`、不进卖出引擎**，避免误管手动仓。策略自己买的票通过 `_check_pending_orders` 的成交回写路径写入 `_g_my_codes`。

### 7.3 成交回写（F1）

`_check_pending_orders` 在全天版的 `_execute_full_cycle` 开头执行（`adapters/qmt_wrapper.py` ~line 3205），解决 DEBUG_MODE 下 handlebar 不可达 line 3661 导致成交不写回 `_g_my_codes` 的问题。

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

策略绝对时间一律走 `_market_now(C)`，不依赖设备时钟。设备 CMOS 电池没电导致时间错乱不应影响策略时段判断。

### 8.2 操作点（全天版）

| 操作点 | 时间 | 说明 |
|--------|------|------|
| 0924 | 09:24 | 策略首次启动时执行一次全流程 |
| 1000 | 10:00 | 方向确立后的首次决策 |
| 1330 | 13:30 | 下午方向确认后的决策 |
| 1430 | 14:30 | 尾盘冲刺前的最后一次决策 |

### 8.3 买入委托窗口（main 版）

`BUY_WINDOW_START = '1000'`，`BUY_WINDOW_END = '1010'`，即 10:00-10:10 为买入委托窗口。

---

## 9. 近期关键修复（2026-06-30）

| 工单 | 问题 | 修复内容 |
|------|------|----------|
| **A** | 卖出反查失败误判委托失败（600641 类 bug） | `_check_pending_sells` 反查失败先查实际持仓再判成败，避免误撤活着的限价卖单 |
| **B** | 卖出反查失败后实盘已清仓但 `_g_my_codes` 残留占名额（603618 类 bug） | `_sync_holdings_from_account` 开盘首帧 + 买入前双保险强制同步 |
| **E** | 全天版冷启动时 `_g_my_codes` 为空导致重复买入（688396 重复买 300 股） | 方案C：`account_held` 并入买入排除集 + `_place_buy_order` 开头重复买入兜底 |
| **F1** | 全天版 `_check_pending_orders` 不可达，成交不写回 `_g_my_codes` | 在 `_execute_full_cycle` 开头插入 `_check_pending_orders` 调用 |
| **F2** | 全天版仓位无上限、名额虚高、holdings_value 漏算 | 第三步整体重构：总仓位门控 + 账户持仓只读计算 + 名额用实际持仓 |
| **F3** | 全天版不均分 budget、不查可用资金 | 矩阵层算 `per_stock_amount` 传入 `_place_buy_order` + 0.80 资金门控 |
| **F5** | main 版选股循环缺 MA5 乖离过滤 | 在 `check_buy` 后、ST 前插入 `_passes_buy_bias_filter` |
| **lookup** | 买/卖 passorder 后 order_id 反查异步延迟误判失败 | 买/卖 passorder 后 order_id 反查短轮询（4 次 × 0.2s，最多 0.8s），避免 QMT 异步分配 order_id 的约 100ms 延迟导致即时反查误判失败 |

---

## 10. 运行后检查清单

部署后按顺序检查日志：

| 步骤 | 日志关键字 | 异常对应问题 |
|------|------------|--------------|
| 1 | `初始化完成` | 加载成功；若缺失则 QMT 公式加载失败 |
| 2 | `[时间校验]` | 时间机制正常；若缺失则 `_market_now` 回退设备时间 |
| 3 | `[外部池] 读取 X 只` | 池文件读到；若缺失则 `selected.txt` 不存在或为空 |
| 4 | `[全天] 仓位` | 全天版仓位计算输出 |
| 5 | `[买入排除]` | 方案C排除集输出，确认账户持仓被正确排除 |
| 6 | `[买入拦截]` | `_place_buy_order` 兜底拦截，确认无重复买入 |
| 7 | `[成交确认]` | 买单成交回写 `_g_my_codes` |
| 8 | `[持仓清理]` | 已清仓票移除 |
| 9 | `[卖出委托]` / `[卖出确认]` | 卖出流程正常 |
| 10 | `ModuleNotFoundError` | 缺包，需 pip install |
| 11 | `FileNotFoundError` | 文件没拷，需按 DEPLOY.md 补充 |
| 12 | `[卖出反查失败]` | 委托可能未到交易所（券商网络/账户问题） |

---

## 11. 已知限制与注意事项

1. **全天版是调试版**：`DEBUG_MODE=True`，不建议与 main 版同时运行，不应视为生产版。
2. **手动仓不纳管**：方案C 下账户实际持仓只参与仓位/名额/holdings_value 只读计算，不写入 `_g_my_codes`，不进卖出引擎。策略自己买的票通过 `_check_pending_orders` 成交回写。
3. **QMT position 缓存延迟**：`get_trade_detail_data('position')` 返回的 `m_nVolume` 可能有延迟，卖出成交确认后立即以策略侧判定为准 pop `_g_my_codes`，不等缓存刷新。
4. **passorder 异步**：`passorder` 调用后 QMT 异步分配 `order_id` 有约 100ms 延迟，买入/卖出都有短轮询反查机制（4 次 × 0.2s）。
5. **GBK build 产物**：`strategy_main.py` / `strategy_allday.py` 是 GBK 编码，grep 中文需转码（`iconv -f GBK -t UTF-8`）。
6. **build 产物需重建**：修改源模块后必须通过构建脚本重新生成产物，不要手工长期维护构建产物中的重复逻辑。
7. **Python 3.6.8 兼容**：QMT 运行环境按 Python 3.6.8 兼容处理，禁止使用 f-string、walrus、match-case、`dict[str, ...]` 等新语法。
8. **代码内版本号**：`STRATEGY_VERSION = 'v2026.06.30-f1f5-lookup'`（已加入 `adapters/qmt_wrapper.py` 参数常量区）。
9. **STRATEGY_CAPITAL**：默认 100000（`global_config.yaml` 的 `strategy.capital_base`），`current_nav = STRATEGY_CAPITAL + _g_cumulative_pnl`。
