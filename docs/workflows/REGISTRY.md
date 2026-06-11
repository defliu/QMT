# QMT 主升浪策略 — 工作流注册表

**Version**: 1.0
**Date**: 2026-06-01
**Maintainer**: Workflow Architect

---

## 视图 1: 按工作流（主清单）

| Workflow | Spec file | Status | Trigger | Primary Actor | Last Reviewed |
|---|---|---|---|---|---|
| Development-Coding | WORKFLOW-pipeline.md | Approved | 诚哥编写 Task Spec → CC 执行 | Claude Code | 2026-06-01 |
| Code-Review | WORKFLOW-pipeline.md | Approved | CC 完成编码 → deepseek-v4-pro 审查 | Code Reviewer | 2026-06-01 |
| Unit-Test | WORKFLOW-pipeline.md | Approved | 代码变更 → `pytest tests/ -v` | CI / 开发者 | 2026-06-01 |
| Build-Strategy | WORKFLOW-pipeline.md | Approved | `python scripts/build_strategy.py` | 开发者 | 2026-06-01 |
| Integration-Test | WORKFLOW-pipeline.md | Approved | `python scripts/run_integration_test.py` | 开发者 | 2026-06-01 |
| Backtest-Run | WORKFLOW-pipeline.md | Approved | `python scripts/run_backtest.py [args]` | 开发者 | 2026-06-01 |
| Market-Scan | WORKFLOW-pipeline.md | Approved | `--scan` flag in backtest | Backtest Runner | 2026-06-01 |
| Deploy-QMT | WORKFLOW-pipeline.md | Missing | strategy_main.py → QMT 客户端粘贴 | 诚哥（手动） | — |
| Live-Trading | WORKFLOW-pipeline.md | Missing | QMT 定时任务触发 handlebar | MiniQMT | — |
| Model-Review | WORKFLOW-pipeline.md | Approved | 回测结果不达标 → 调参重跑 | 开发者 | 2026-06-01 |
| Data-Source-Setup | WORKFLOW-pipeline.md | Missing | `python scripts/setup_xtquant.py` | 开发者/DevOps | — |

---

## 视图 2: 按组件

| Component | File(s) | Workflows it participates in |
|---|---|---|
| **core/utils.py** | `core/utils.py` | Development-Coding, Unit-Test, Build-Strategy, Backtest-Run |
| **core/signal_main_rise.py** | `core/signal_main_rise.py` | Development-Coding, Unit-Test, Build-Strategy, Backtest-Run |
| **core/risk_manager.py** | `core/risk_manager.py` | Development-Coding, Unit-Test, Build-Strategy, Backtest-Run |
| **core/position_sizer.py** | `core/position_sizer.py` | Development-Coding, Unit-Test, Build-Strategy, Backtest-Run |
| **core/pool_filter.py** | `core/pool_filter.py` | Development-Coding, Unit-Test, Backtest-Run (Market-Scan) |
| **adapters/qmt_wrapper.py** | `adapters/qmt_wrapper.py` | Development-Coding, Build-Strategy, Backtest-Run, Live-Trading |
| **adapters/context_mock.py** | `adapters/context_mock.py` | Unit-Test, Backtest-Run |
| **scripts/build_strategy.py** | `scripts/build_strategy.py` | Build-Strategy, Backtest-Run (pre-step) |
| **scripts/run_backtest.py** | `scripts/run_backtest.py` | Backtest-Run, Market-Scan |
| **scripts/run_integration_test.py** | `scripts/run_integration_test.py` | Integration-Test |
| **scripts/backtest_params.py** | `scripts/backtest_params.py` | Backtest-Run |
| **scripts/setup_xtquant.py** | `scripts/setup_xtquant.py` | Data-Source-Setup |
| **tests/** | `tests/test_*.py` | Unit-Test, Code-Review (quality gate) |
| **config/global_config.yaml** | `config/global_config.yaml` | Backtest-Run, Deploy-QMT, Live-Trading |
| **strategy_main.py** | `strategy_main.py` | Build-Strategy (output), Deploy-QMT, Live-Trading |
| **qmt37_strategy/** | `qmt37_strategy/*.py` | Development-Coding, Backtest-Run (--strategy qmt37) |

---

## 视图 3: 按用户旅程

### 开发者旅程

| 开发者体验 | 底层工作流 | 入口点 |
|---|---|---|
| 编写/修改策略逻辑 | Development-Coding → Code-Review → Unit-Test | `core/signal_main_rise.py` |
| 加入新模块 | Development-Coding → Code-Review → Unit-Test | `core/` 或 `adapters/` 新建文件 |
| 验证修改不破坏已有功能 | Unit-Test | `pytest tests/ -v` |
| 打包策略给 QMT | Build-Strategy | `python scripts/build_strategy.py` |
| 全链路回测验证 | Backtest-Run | `python scripts/run_backtest.py --scan` |
| 调参优化 | Backtest-Run (不同参数) → Model-Review | `--start/--end/--capital` |
| 切换策略版本 | Backtest-Run (--strategy flag) | `--strategy qmt37` 或 `--strategy default` |
| MiniQMT 真实行情测试 | Integration-Test | `python scripts/run_integration_test.py` |

### 诚哥旅程（策略决策者）

| 诚哥做什么 | 底层工作流 | 入口点 |
|---|---|---|
| 写 Task Spec → CC 执行 | Development-Coding | 编写 TS-*.md → 下发 CC |
| 验收 CC 产出 | Code-Review | 审阅 APPROVED/REJECTED |
| 决策调参方向 | Model-Review | 阅读回测报告 → 调参数 → 重跑 |
| 部署上线 | Deploy-QMT | 把 strategy_main.py 粘贴到 QMT 客户端 |

### 系统间旅程

| 自动发生什么 | 底层工作流 | 触发 |
|---|---|---|
| CC 收到 Task Spec 开始编码 | Development-Coding | 诚哥下发 Task Spec |
| 策略代码被内联合并 | Build-Strategy | `build_strategy.py` 被调用 |
| 全市场扫描选股 | Market-Scan | `--scan` 参数 + mootdx 数据源 |
| 回测引擎逐 K 线运行 | Backtest-Run | `run_backtest.py` 主循环 |
| 回测结果输出 JSON/报告 | Backtest-Run (输出阶段) | 回测完成 |
| MiniQMT 拉取真实行情 | Integration-Test / Live-Trading | MiniQMT 进程活跃 |

---

## 视图 4: 按状态

| 实体状态 | 进入方式 | 退出方式 | 可触发退出的工作流 |
|---|---|---|---|
| **pending** | 新建 Task Spec | → in_progress, cancelled | Development-Coding |
| **in_progress** | CC 开始编码 | → review, failed | Development-Coding, Code-Review |
| **review** | CC 完成编码 | → approved, rejected | Code-Review |
| **approved** | Code-Review PASS | → deployed, (下一阶段) | Build-Strategy, Deploy-QMT |
| **rejected** | Code-Review FAIL | → in_progress (重写) | Development-Coding |
| **built** | Build-Strategy 成功 | → deployed, backtested | Deploy-QMT, Backtest-Run |
| **backtested** | Backtest-Run 完成 | → approved (调参后), model_review | Model-Review |
| **deployed** | strategy_main.py 粘贴到 QMT | → live_trading, rolled_back | Live-Trading, Deploy-QMT (回滚) |
| **live_trading** | QMT handlebar 开始运行 | → stopped, errored | Live-Trading, Recovery |
| **failed** | 任何工作流步骤出错 | → pending (重试), aborted | Recovery, Development-Coding |
| **orphan** | 清理失败，资源泄漏 | → manual_cleanup | Recovery (手动) |

---

## 维护规则

1. **每次发现或编写新工作流时必须更新本注册表**
2. **四个视图必须交叉引用** — 每个组件出现在视图 2 中，它的工作流必须在视图 1 中出现
3. **Missing 状态的工作流必须在下一次迭代中被规格说明覆盖**
4. **永不删除行** — 改为标记 Deprecated，保留历史记录
