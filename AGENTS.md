# QMT_STRATEGIES Agent 开发指南

本文件适用于 `D:\QMT_STRATEGIES` 下的全部文件。参与本项目开发时，必须优先遵守以下规则。

## 项目定位

- 本项目是面向 QMT/miniQMT 的 A 股策略工程，目标是形成“评分买入 + 分层卖出风控 + QMT 单文件构建 + 实盘安全防护”的闭环。
- `core/` 是纯策略逻辑层，必须保持零 QMT 运行时依赖。
- `adapters/` 是 QMT 运行时桥接层，负责 `passorder`、数据加载、订单管理、文件 IO、SAFEMODE 等。
- `specs/` 是 Hermes Agent 输出 SPEC 的共享目录，可作为需求、设计和验收依据。

## 核心模块认知

- 主力评分器是 `core/scoring/dimension6plus2.py` 中的 `ScoreCalculator6Plus2`。
- `core/signal_main_rise.py` 中的 `ScoreCalculator8D` 是备用评分器或对照方案。
- `core/scoring/switch_scorer.py` 负责在 `6plus2`、`8d`、`round_robin` 模式之间切换。
- `core/risk_manager.py` 中的 `SellStrategyEngine` 是核心安全模块，任何改动都必须谨慎处理并优先验证。
- `adapters/qmt_wrapper.py` 中的 `Trader` 和 `StrategyRunner` 是实盘执行主入口。

## 构建与产物

- 构建入口是 `scripts/build_strategy.py`。
- 生产尾盘版产物是 `strategy_main.py`。
- 开发 MOCK 版产物是 `strategy_dev.py`。
- 全天调试版产物是 `strategy_allday.py`。
- 构建过程会按依赖顺序合并源文件、移除项目内部 import、追加 QMT 生命周期模板，并转换为 GBK 编码。
- 修改源模块后，应通过构建脚本重新生成产物，不要手工长期维护构建产物中的重复逻辑。

## QMT 红线

- 所有 QMT 运行产物必须是 GBK 编码，并且首行必须是 `# coding=gbk`。
- QMT 运行环境按 Python 3.6.8 兼容处理。
- 禁止在 QMT 运行产物或会被合并进产物的代码中使用 Python 3.6 不支持的语法，包括但不限于：
  - `dict[str, ...]`
  - `list[str]`
  - `str | None`
  - `:=`
  - `match/case`
  - f-string
- 生产版不得混入 `adapters/context_mock.py`。
- 严防 `context_mock.py` 中的全局 `passorder()` 覆盖真实交易函数。
- 涉及真实下单、SAFEMODE、卖出重试、跌停暂缓队列的改动必须格外保守。

## 风控优先级

- 卖出风控优先级高于买入优化。
- 不得为了提高买入频率、评分命中率或回测收益，绕过 `SellStrategyEngine` 的底线层、清仓层、预警层或确认层。
- 涉及清仓、减仓、禁入期、状态持久化、跌停暂缓的逻辑改动，需要补充或更新测试。

## 文件通信

- 策略运行时主要通过 `D:/QMT_POOL/` 交换文件。
- 常见文件包括：
  - `selected.txt` / `QMTselected.txt`：外部股票池
  - `*_holdings*.txt`：持仓跟踪
  - `*_nav*.txt`：累计盈亏净值
  - `sector_heat.json`：板块热度预计算数据
  - `成交记录_*.txt`：交易记录
  - `*_sell_state_*.json`：卖出状态持久化
  - `strategy_log_*.txt`：每日策略执行日志

## 测试与验证

- 测试使用外部 Python 3.11 / `.venv`，但生产运行必须保持 Python 3.6.8 兼容。
- 优先运行与改动相关的 pytest 测试，再视情况运行更大范围测试。
- 构建生产产物后，应运行：`python scripts/validate_qmt_file.py deploy/strategy_main.py`。
- 验证项必须关注：文件存在、GBK 编码、`# coding=gbk` 文件头、Python 3.6 语法、无 MOCK 残留、无长小数输出。

## 开发原则

- 优先修根因，避免只改构建产物或做表面补丁。
- 保持最小改动，不顺手重构无关模块。
- 修改策略参数、评分权重、风控阈值前，先确认 SPEC、研究文档或用户明确要求。
- 对 Hermes 提供的 SPEC，应先理解验收标准，再实现、测试和汇报。
- 如需编辑 QMT 生产产物，必须注意编码；默认应改源文件并重新构建。
