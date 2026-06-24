# T-20260624-004 QMT 内置回测可行性验证 — 任务大盘

更新：2026-06-24
负责：CC（规划）+ MIMO（执行）
SPEC：`D:\QMT_STRATEGIES\specs\SPEC_QMT_BUILTIN_BACKTEST_FEASIBILITY.md`

---

## 0. 一句话目标

验证 `xtquant.qmttools.stgentry.run_file()` 能否在外部 Python 中触发 QMT 内置回测，并把"逐笔交易 + 每日净值 + 汇总指标"导出落盘，与自建回测工厂跑相同参数做对比。

---

## 1. 源码已啃完的关键事实（CC 读 qmttools/ 三个文件得到）

| # | 事实 | 来源 | 验证脚本必须照办 |
|---|------|------|------------------|
| F1 | `stgentry.run_file()` 走 `exec(user_module)` 把用户脚本 `init/after_init/handlebar/stop` + 5 个 callback 绑到 `_C`（ContextInfo 实例） | `stgentry.py:38-49` | 验证脚本本身就是 `run_file()` 的入参，不能是普通 main 模块 |
| F2 | `StrategyLoader.init()` 通过 `xtdata.get_client()` 与 `client.createFormula/callFormula` 跟 MiniQMT 进程通信 | `stgframe.py:138-150` | **MiniQMT 必须在后台跑**，否则 `get_client()` 拿不到 RPC 句柄 |
| F3 | `load_main_history()` 用 `xtdata.get_market_data_ex(stock_list=[C.stock_code]...)` 拉主图 timelist | `stgframe.py:122-128` | 主图只支持**单标的**，多标的要循环 `run_file()` |
| F4 | ContextInfo 默认 backtest_ar 没有 `start_time/end_time`，stgentry 把整个 param 存进 `C._param` 但不直接赋值到 `C.start_time` | `contextinfo.py:14-28`, `stgframe.py:23-42` | **时间区间要么走 `param['start_time']`（注意：`stgframe.init()` 里没有显式取 start_time，需实测）**，要么在用户脚本 `init(C)` 里手工赋值 |
| F5 | `run_file()` 末尾 `return`（空），没有结果对象 | `stgentry.py:67` | 拿结果只能靠 callback / `C.paint` / 自己落盘 |
| F6 | QMT 自带 Python = 3.6.8 在 `D:/国金证券QMT交易端/bin.x64/pythonw.exe`；项目主 venv 没装 xtquant | `tasklist`, import 实测 | **所有验证脚本必须用 QMT 自带 Python 执行**，工单里显式写解释器路径 |
| F7 | 用户脚本会被 `compile(open(path, 'rb').read(), ..., 'exec', optimize=2)` | `stgentry.py:14` | 编码：源文件第一行必须有 `#coding:gbk` 或 `# coding=utf-8`；用户脚本不能依赖 `__file__`（用绝对路径） |
| F8 | `dividend_type` 在 `stgframe.init()` 里走 `C._param.get('dividend_type', 'none')` | `stgframe.py:46` | 必须显式传 `'front'`（前复权），否则默认 none |

---

## 2. 拆单总览（5 个 MIMO 工单 + CC 终审）

| 工单 | 范围 | 关键产物 | 阻塞 |
|------|------|----------|------|
| **PART-A 环境探活** | 用 QMT 自带 Python 调用 `run_file()` 跑空脚本；分别在 MiniQMT 未启动 / 已启动两种状态下记录返回与报错 | `reports/01_environment_verification.md` + 报错原文截图 | 无 |
| **PART-B 单标的最小可跑** | 写 `_qmt_probe_strategy.py`（独立验证策略，**不复用 strategy_main.py**），通过 callback 落盘 trades + nav；000001.SZ 2024-01-01~2024-03-31 日线 | `data/qmt_backtest_trades.json` + `data/qmt_backtest_nav.csv` + `reports/02_single_stock_backtest.md` | PART-A 通过 |
| **PART-C 多标的循环 + 隔离性** | 循环跑算力池前 5 只；测试两两之间 ContextInfo / xtdata 状态是否残留；记录单只耗时 + 总耗时 | `data/multi_stock/*.json` + `reports/03_multi_stock_backtest.md` | PART-B 通过 |
| **PART-D 与自建回测对比** | 用 `scripts/run_backtest.py` 跑相同 5 只 + 相同区间 + 相同初始资金；输出对比表 | `reports/04_comparison_report.md` | PART-C 通过 |
| **PART-E 终审报告** | CC 自己写，把 SPEC 6 大问题一条条回答，标注"已验证 / 合理假设 / 待进一步验证" | `reports/05_conclusion.md` | PART-D 通过 |

每个 PART 一份独立工单，单独 commit，单独验收；任何一 PART 失败立即停在那个 PART，不冒进往下走。

---

## 3. CC 已下决策的边界（红线）

| 项 | 决策 | 原因 |
|---|------|------|
| 不复用 `strategy_main.py` 跑 QMT 回测 | 写独立的 `_qmt_probe_strategy.py` 探针 | 生产策略依赖 `D:/QMT_POOL` 文件交换 + 时间守卫 + 真 passorder，灌进回测会产生未知副作用；SPEC Boundaries 也写明"不修改生产策略文件" |
| 用 QMT 自带 Python | `D:\国金证券QMT交易端\bin.x64\pythonw.exe` | xtquant 只在那个解释器下能 import |
| 测试区间用 SPEC 给的 2024-01-01~2024-03-31 | 不自创区间 | 保持与 SPEC 一致便于复核 |
| 多标的取算力池前 5 只 | 不全跑 32 只 | SPEC 明确说前 5，且耗时未知必须先点测 |
| 任何一 PART 报错就停 | 不许 MIMO "判定无关继续往下"（参见 `mimo-must-stop-on-any-failure`） | 已经栽过一次 |

---

## 4. 风险登记

| 风险 | 触发条件 | 处理 |
|------|---------|------|
| MiniQMT 未启动直接卡死 / 无报错 | PART-A 时复现 | 给 60s 超时，强杀 + 记录现象，列为 BLOCKED |
| `run_file()` 把整个进程 hold 住不返回 | PART-B/C 复现 | 用 subprocess 包装 + 超时，单只 600s 上限 |
| 多标的循环时 xtdata 状态残留导致结果污染 | PART-C 同一标的跑两次结果不一致 | 每只用独立 subprocess 跑，进程级隔离 |
| QMT 回测口径与自建差异 > 5% | PART-D 比对超阈值 | 不强行下"不一致"结论，先逐字段拆：滑点/手续费/复权口径/T+1 是否一致；不一致先列偏差来源，不下"QMT 错"或"自建错"的结论 |
| 写入 GBK 编码错误 | strategy_main.py 是 GBK，QMT 验证脚本是 UTF-8 | 探针脚本统一第一行 `# coding=utf-8`；验证脚本只读不写生产文件 |

---

## 5. 验收映射（SPEC 5 条验收 → 哪个 PART 兑现）

| SPEC 验收 | 兑现 PART | 验收文件 |
|-----------|-----------|----------|
| ✅ 成功调用 `run_file()` 完成一次回测 | PART-A + PART-B | `reports/01_environment_verification.md`, `reports/02_single_stock_backtest.md` |
| ✅ 输出 JSON 包含 trades + nav + summary | PART-B | `data/qmt_backtest_trades.json` |
| ✅ 与自建回测对比报告 | PART-D | `reports/04_comparison_report.md` |
| ✅ 已验证 / 合理假设 / 待进一步验证 三分标注 | PART-E | `reports/05_conclusion.md` |
| ✅ 6 大核心问题全部回答 | PART-E | `reports/05_conclusion.md` |

---

## 6. 下一步

1. 诚哥确认本 brief 拆分合理 → CC 把 PART-A 工单挂到 `Mimo_PART_A_env_probe.md`
2. MIMO 跑 PART-A，回执到 `Mimo_PART_A_REPLY.md`
3. CC 验收 PART-A → 出 PART-B 工单
4. 依次 B → C → D → E

任何一步报错都停在该步等诚哥决策；不许"判定无关"自动继续往下走。
