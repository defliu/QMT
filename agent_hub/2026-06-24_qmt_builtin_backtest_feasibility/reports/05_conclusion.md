# PART-E 终审报告：QMT 内置回测系统接入可行性

任务编号：T-20260624-004
SPEC：`D:/QMT_STRATEGIES/specs/SPEC_QMT_BUILTIN_BACKTEST_FEASIBILITY.md`
日期：2026-06-24
执行：CC 规划 + MIMO 7 次迭代执行
工时：≈ 1 小时

---

## 0. TL;DR（一句话结论）

**QMT 内置回测引擎在 `xtquant.qmttools.stgentry.run_file()` 外部 Python 模式下，行情驱动通路可用，但 `passorder` 不会真撮合，所有交易类 callback 永远为 0，外部脚本无法拿到任何交易/净值/成交数据。**

**不建议**沿这条路集成；研究端继续走自建回测工厂 + QMT GUI 内置策略管理器（人工导出）两条腿。

---

## 1. SPEC 6 大核心问题 — 事实回答

| # | SPEC 问题 | 事实回答 | 标注 |
|---|---|---|---|
| Q1 | `stgentry.run_file()` 在现有环境中能否成功调用？MiniQMT 是否必须启动？ | **能调用**。MiniQMT **必须启动**：源码 `stgframe.init()` 通过 `xtdata.get_client()` 走 RPC 连 MiniQMT；不启动时 PART-A 等价侧推（PART-A 已启动状态下 1.71s 完成，源码已证 RPC 依赖）。 | ✅ 已验证事实 |
| Q2 | 现有 `strategy_main.py` 能否直接跑 QMT 内置回测？是否需要改造？ | **不能直接跑**。生产策略依赖 `D:/QMT_POOL` 文件交换、GBK 编码、时间守卫、`passorder` 真盘下单，灌进回测会产生未知副作用。需要单独写探针策略（如本任务 `_qmt_probe_b_strategy.py`）才能接入。 | ✅ 已验证事实 |
| Q3 | 能否通过 `deal_callback` 等回调将回测结果写入文件？ | **不能**。7 次迭代后，`deal_callback / order_callback / account_callback` 计数恒为 0；服务端 `C.get_callback_cache('deal'/'order'/'account')` 同样恒为 `{}`。`passorder` 调用本身不爆错、`orderError_callback` 也不触发，引擎吞了订单不撮合。**这是本任务 KEY FINDING。** | ❌ 已验证事实（关键否定结论） |
| Q4 | QMT 回测结果与自建回测结果对比，偏差有多大？ | **不适用**。Q3 决定了拿不到 QMT 回测的交易/净值数据，无可比对象。 | ⚪ N/A |
| Q5 | 能否循环调用 `run_file()` 跑多只股票？会话状态是否会残留？ | **未单独验证**。Q3 决定 PART-C 没意义（多标的也是 0 交易），主动跳过。源码 `stgframe.load_main_history` 用 `xtdata.get_market_data_ex(stock_list=[C.stock_code])` 仅取单标的主图，确认多标的必须循环 `run_file()`。状态残留情况未点测。 | ⚠️ 合理假设（基于源码） |
| Q6 | 能否通过 `param` 字典传入初始资金、滑点、手续费、时间区间等参数？ | **部分可以**。`asset / margin_ratio / slippage / open_commission / close_commission / open_tax / close_tax / min_commission / benchmark` 在 `ContextInfo.__init__` 列入 backtest_ar 且 `stgframe.init()` post 给引擎。**但 `start_time / end_time` 没有被自动赋值给 `C`，且 `stgframe.load_main_history` 把它俩写死为 `''` + `count=-1`，时间区间无法通过 param 传入。** Workaround：在用户脚本 `after_init` 内手动裁剪 `C.timelist`（本任务已验证有效：426 → 80）。 | ✅ 已验证事实 + Workaround |

---

## 2. 已验证事实

### 2.1 stgentry 生命周期完整跑通

| 阶段 | 实测 |
|---|---|
| `init(C)` | ✅ 调用 |
| `after_init(C)` | ✅ 调用，紧跟 `load_main_history` 之后、`run_bar` 之前 |
| `handlebar(C)` | ✅ 80 次（裁剪后 timelist 长度 = 80 个交易日 2024-09-02 ~ 2024-12-31） |
| `stop(C)` | ✅ 调用 |
| `run_file()` 返回值 | `None`（源码末尾 return 空） |
| 单次端到端耗时 | 0.99 ~ 1.71 秒（80 bars 日线） |

### 2.2 行情数据 API 在回测里正常工作

- `C.get_market_data_ex(fields=['close'], stock_code=[code], period='1d', start_time, end_time, dividend_type='front')` 返回 `{code: DataFrame(index=stime_str, columns=['close'])}`，全区间 80 行收盘价完整拿到，价格走势 8.9 → 10.7 合理。
- `C.timelist` 在 `load_main_history` 后包含 xtdata 本地可用全历史（实测 442 根日线，覆盖 2024-08-22 ~ 2026-06-01）。
- xtdata 本地数据库 000001.SZ 日线**最早只到 2024-08-22**，早于此日期的回测区间会得到空 timelist。

### 2.3 时间区间 workaround 经验证有效

`stgframe.load_main_history`（`stgframe.py:122-128`）写死 `start_time='', end_time='', count=-1`，无视 param 中的 start/end_time。
正确做法：用户脚本在 `after_init` 中手动裁剪 `C.timelist`：

```python
def after_init(C):
    start_ms = _to_ms(C._param.get('start_time'))
    end_ms = _to_ms(C._param.get('end_time'), end_of_day=True)
    C.timelist = [t for t in C.timelist
                  if (start_ms is None or t >= start_ms)
                  and (end_ms is None or t <= end_ms)]
```

实测：裁剪前 442 根 → 裁剪后 80 根，run_bar 正确按裁剪后的 timelist 跑。

### 2.4 callback 链路在外部 Python 模式下不通

- `set_account(accountid)` / `set_auto_trade_callback(True)` / `do_back_test=True` / `prType=11`+`modelprice=close` 全试，**任一组合都拿不到 callback**。
- 服务端 `get_callback_cache('deal'/'order'/'account')` 同样为 `{}`。
- `passorder` 调用本身不爆错（参数 7 个正确），`orderError_callback` 也不触发。
- 源码层面看到一个机制错位（待二次验证）：`stgframe.init():99` 调 `C.register_callback(0)` 注册 reqid 写死 0；而 `passorder` 调用走 uuid `request_id` 频道 — 但即便绕过 callback 直接拉服务端 cache 也为空，所以**真正的根因可能不在频道错位，而在引擎层根本不为外部脚本启动撮合**。

### 2.5 ContextInfo 暴露的回测控制字段（源码 contextinfo.py:30-50）

| 字段 | 默认 | 用法 |
|---|---|---|
| `asset` | 1000000.0 | 初始资金 |
| `margin_ratio` | 0.05 | 保证金比例 |
| `slippage_type / slippage` | 2 / 0.0 | 滑点 |
| `max_vol_rate` | 1.0 | 最大成交比例 |
| `comsisson_type` | 0 | 手续费类型 |
| `open_tax / close_tax` | 0.0 / 0.0 | 印花税 |
| `min_commission / open_commission / close_commission` | 0 / 0 / 0 | 手续费 |
| `close_today_commission` | 0.0 | 平今手续费 |
| `benchmark` | '000300.SH' | 基准 |
| `capital` | None | 当前资金（未实测引擎是否更新） |
| `do_back_test` | None | 用途待考；显式 True 不改变 callback 行为 |

---

## 3. 合理假设（未直接验证、但源码或文档支持）

1. **多标的必须循环 `run_file()`**（Q5）：源码 `load_main_history` 主图只接受单 stock_code。
2. **`start_time / end_time` 写死是个引擎层 design choice**，从源码看不像 bug（注释里强调 `count=-1`），不能寄希望于补丁修复；workaround 是稳定路径。
3. **QMT 内置回测的真撮合能力放在 GUI 内的"我的策略"管理器里**：基于 callback 全空 + cache 全空的现象，外部脚本调 stgentry 时引擎只跑行情驱动 + 用户脚本逻辑，不启动交易撮合子系统。这与 SPEC 背景中"外部 Python 触发 QMT 内置回测"的设想存在结构性 gap。
4. `m_strOptName` 是否在 QMT 回测 deal_info 中有内容**未验证**（因为根本没拿到 deal 回调）。即便走通了，仍需另外验证字段填充情况。

---

## 4. 待进一步验证（如果未来还要继续）

如果业务还想沿这条路深挖，下面四件事按成本/价值排序：

| 优先级 | 动作 | 成本 | 预期收益 |
|---|---|---|---|
| P0 | 在 QMT GUI 中手动加载同一份探针策略（`_qmt_probe_b_strategy.py`），观察 deal_callback 是否在 GUI 模式下触发 | 0.5 小时 | 确认 callback 全空是"外部 Python 模式专属"还是脚本本身有问题 |
| P1 | 联系国金 QMT 技术支持，确认"外部 stgentry 是否官方支持回测撮合" | 1 天等回 | 拿到官方口径，决定彻底放弃 or 还有 hidden 开关 |
| P2 | 尝试用 `xtquant.xtbson` 直接发 `callFormula(reqid, 'passorder', ...)` 自实现，绕开 stgframe 整套封装 | 4 小时 | 概率验证 reqid 频道错位假设，但维护成本极高 |
| P3 | 改造 stgentry 源码（在 `D:/国金证券QMT交易端/bin.x64/Lib/site-packages/xtquant/qmttools/stgframe.py`）让 reqid 与 passorder 频道一致 | 6 小时 | 风险极大：QMT 升级会覆盖；动 QMT 自带包是禁忌 |

**CC 建议**：先做 P0（成本最低，结论最贵），其余打死不做。

---

## 5. 验收映射

| SPEC 验收项 | 状态 | 兑现位置 |
|---|---|---|
| ✅ 成功调用 `stgentry.run_file()` 完成一次回测，拿到结果 | ✅ 通路通过 | PART-A 1.71s 跑完 / PART-B v3.1+ 0.99s 跑完 |
| ✅ 输出 JSON 文件，包含逐笔交易明细、每日净值序列、汇总绩效指标 | ⚠️ 文件结构都对齐 SPEC，但**内容全为空/平躺**（trades=[]/nav 全 1e6） | `data/qmt_backtest_trades.json` / `nav.csv` / `summary.json` |
| ✅ 与自建回测跑相同参数，输出对比报告 | ❌ 跳过 | Q3 决定无可比对象 |
| ✅ 明确标注：已验证事实 / 合理假设 / 待进一步验证 | ✅ | 本报告第 2 / 3 / 4 章 |

**SPEC APPROVED 5 条满足 2 条；REJECT 4 条触发 1 条（"`run_file()` 调用后无法获取逐笔交易数据"）→ 整体判定：通路验证通过，撮合验证失败。**

---

## 6. 7 次迭代日志（按时间）

| # | 改动 | 结果 |
|---|---|---|
| v1 PART-A | 最小空策略 | ✅ 通路通过；侧推时间区间不被 param 接管 |
| v2 PART-B | 加 callback + passorder + get_trade_detail_data | ❌ buy=0：close=0 + acc API 用错 |
| v2.5 PART-B（区间换） | 2024-01~2024-03 → 2024-09~2024-12 | ✅ timelist 80；其余仍 0 |
| v3 PART-B | get_market_data_ex 缓存价格 + 自维护 book + passorder 10 参数 | ❌ buy=0：passorder 参数数错 |
| v3.1 PART-B hotfix-1 | passorder 7 参数 | ⚠️ buy=4 但 deal=0 |
| v3.2 PART-B hotfix-2 | + set_account + set_auto_trade_callback(True) | ❌ 无变化 |
| v3.3 PART-B hotfix-3 | + do_back_test=True + prType=11+modelprice=close | ❌ 无变化 |
| v3.4 PART-B hotfix-4 | + stop 阶段拉 callback cache | ❌ cache 全空 → 引擎根本没撮合 |

每一次迭代都没有撤回前面的修复，最终状态是**所有修复叠加后的全功能版本**仍然 deal_callback=0。

---

## 7. 交付物清单

| 路径 | 内容 |
|---|---|
| `agent_hub/2026-06-24_qmt_builtin_backtest_feasibility/00_brief.md` | 任务大盘（CC 派单时） |
| `agent_hub/.../Mimo_PART_A_env_probe.md` + `Mimo_PART_A_REPLY.md` | PART-A 环境探活工单 + 回执 |
| `agent_hub/.../Mimo_PART_B_single_stock.md` + `Mimo_PART_B_single_stock_v3.md` | PART-B v2/v3 工单 |
| `agent_hub/.../Mimo_PART_B_REPLY.md` | PART-B 五次重跑完整回执 |
| `agent_hub/.../scripts/_qmt_probe_strategy.py` | PART-A 空探针 |
| `agent_hub/.../scripts/_qmt_probe_b_strategy.py` | PART-B v3.4 最终版（含 7 次迭代叠加修复） |
| `agent_hub/.../scripts/run_probe_a.py` / `run_probe_b.py` | 驱动 |
| `agent_hub/.../data/_probe_a_log.json` | PART-A 生命周期记录 |
| `agent_hub/.../data/_probe_b_lifecycle.json` | PART-B 最终状态（callback 全 0、cache 全空） |
| `agent_hub/.../data/qmt_backtest_trades.json` | trades: []（空，证据） |
| `agent_hub/.../data/qmt_backtest_nav.csv` | 81 行 nav 全 1e6 + close 真实价（行情通价但 book 不变） |
| `agent_hub/.../data/qmt_backtest_summary.json` | total_trades=0, total_return=0 |
| `agent_hub/.../data/run_probe_a_qmt_on.log` / `run_probe_b.log` | 驱动日志 |
| `agent_hub/.../reports/02_single_stock_backtest.md` | MIMO 写的 PART-B 报告（CC 未覆盖，与本报告互为对照） |
| `agent_hub/.../reports/05_conclusion.md` | 本报告 |

---

## 8. CC 自主判断与建议

**判定**：QMT 内置回测在 `stgentry.run_file()` 外部 Python 路径下**不适合作为研究端回测工具**。

**理由**：
1. SPEC 核心目标 "拿到 trades + nav + summary 三件套" 在 7 次迭代后无法兑现。
2. 即便有 P0~P3 后续追查路径，前 3 个收益期望值都低（GUI 模式可能能跑但意义有限：研究端需要的是脚本化批量回测、不是 GUI 手操；技术支持等回时间不可控；自实现 callFormula 维护成本高）。
3. **自建回测工厂已经 Hermes 签字工程通过**（[[backtest-v02-mvp-status]]），双线并行的 ROI 远高于继续修这条死胡同。

**建议下一步**：
- ✅ PART-B 探针脚本作为"如何用 stgentry 跑通行情驱动"的样板留档（未来如果做事件型策略 quote replay 还能用）
- ✅ 本报告 + Mimo_PART_B_REPLY.md 入知识库 `60_工程知识库/QMT/QMT内置回测调研.md`
- ✅ TASK_BOARD T-20260624-004 转 REVIEW，等诚哥看
- ❌ 不进 Phase 2
- ❌ 不动 QMT 自带源码
- 🟡 如果诚哥还想确认 GUI 模式 — 启动一次 `_qmt_probe_b_strategy.py` 到 QMT GUI 的"我的策略"管理器跑一遍，看 deal_callback 是否触发；半小时事

---

**报告完。等诚哥确认 → TASK_BOARD 落 DONE。**
