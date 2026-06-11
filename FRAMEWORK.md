# QMT_STRATEGIES 框架全景

> 生成时间: 2026-06-11

## 目录结构

```
D:\QMT_STRATEGIES\
├── core/                        # 纯逻辑层（零 QMT 依赖）
│   ├── utils.py                 # 技术指标：MA/EMA/MACD/KDJ/RSI/ATR/CMF/角度/影线检测
│   ├── scoring/
│   │   ├── dimension6plus2.py   # ★ 主力评分器：6+2 维度（突破22+趋势13+盘整20+量价12+MACD12+估值7+情绪7+板块7=100）
│   │   └── switch_scorer.py     # 评分器切换器：6plus2 / 8d / round_robin 三种模式
│   ├── signal_main_rise.py      # 8D 加权评分系统（旧版100分制+市场系数）+ SectorAnalyzer
│   ├── risk_manager.py          # ★ 四层卖出风控引擎（底线清仓→确认卖出→预警卖出→清仓层）
│   ├── pool_filter.py           # 筹码密集突破选股（功能冗余，未接入主流程）
│   └── position_sizer.py        # 凯利公式仓位 + 移动止盈
├── adapters/                    # QMT 运行时桥接层
│   ├── qmt_wrapper.py           # ★ 核心适配器：Trader/StrategyRunner/数据加载/订单管理/文件IO/SAFEMODE
│   └── context_mock.py          # MockContextInfo（终端测试用，构建时排除）
├── config/
│   └── global_config.yaml       # 全局配置（策略参数/账户/路径/safemode/debug）
├── scripts/
│   ├── build_strategy.py        # ★ 构建脚本：合并→GBK→3种产物
│   ├── validate_qmt_file.py     # ★ 6项合规检查（编码/语法/MOCK残留/长小数）
│   ├── backtest_6plus2_full.py  # 回测脚本
│   ├── backtest_dimension6plus2.py
│   ├── backtest_params.py       # 回测参数
│   ├── diagnose_buy.py          # 买入诊断
│   ├── diagnose_dimension6plus2.py
│   ├── diagnose_score_8d.py     # 8D评分诊断
│   ├── fix_formatting.py        # 格式化修复
│   ├── fix_gbk.py               # GBK编码修复
│   ├── rebuild_risk_only.py     # 仅重建风控模块
│   ├── reconstruct_from_pyc.py  # 从.pyc还原源码
│   ├── run_backtest.py          # 运行回测
│   ├── run_integration_test.py  # 集成测试
│   ├── setup_xtquant.py         # xtquant环境配置
│   ├── test_miniqmt_full.py     # MiniQMT全量测试
│   └── test_sell_engine.py      # 卖出引擎测试
├── tests/                       # 13个测试文件 + conftest.py（pytest fixtures）
│   ├── conftest.py              # fixtures: mock_klines, mock_context, safemode_reset
│   ├── test_utils.py
│   ├── test_signal.py
│   ├── test_signal_main_rise.py
│   ├── test_dimension6plus2.py
│   ├── test_backtest_dimension6plus2.py
│   ├── test_backtest_6plus2_full.py
│   ├── test_diagnose_dimension6plus2.py
│   ├── test_pool_filter.py
│   ├── test_safemode.py
│   ├── test_sell_retry.py
│   ├── test_fix_sync_my_codes.py
│   └── test_run_backtest.py
├── specs/                       # Hermes 输出的 SPEC 共享目录
├── research/                    # 策略研究文档
│   ├── 00_A股交易制度.md
│   ├── 01_因子库.md
│   ├── 02_策略模型库.md
│   ├── 03_回测坑位.md
│   ├── 04_实盘风控规则.md
│   ├── 05_历史策略复盘.md
│   ├── 06_诚哥策略偏好.md
│   ├── paper_notes/             # 论文笔记
│   ├── specs_drafts/            # SPEC草稿
│   └── strategy_cards/          # 策略卡片
├── release/                     # 发布版（v1.0已发布）
├── worklog/                     # 每日工作日志
├── strategy_main.py             # 生产版（构建产物）
├── strategy_dev.py              # 开发版含MOCK（构建产物）
└── strategy_allday.py           # 全天调试版（构建产物）
```

## 构建流水线

| 命令 | 产物 | 说明 |
|------|------|------|
| `python scripts/build_strategy.py` | `strategy_main.py` | 生产版（尾盘模式） |
| `python scripts/build_strategy.py --dev` | `strategy_dev.py` | 开发版（含MOCK） |
| `python scripts/build_strategy.py --allday` | `strategy_allday.py` | 全天版（DEBUG_MODE硬编码True） |

### 构建流程

按依赖顺序合并以下源文件：

```
core/utils.py
core/scoring/dimension6plus2.py
core/signal_main_rise.py
core/scoring/switch_scorer.py
core/risk_manager.py
core/position_sizer.py
adapters/qmt_wrapper.py        # 生产版不含 context_mock.py
adapters/context_mock.py       # 仅 --dev 模式
```

构建步骤：

1. 读取源文件，移除 `# coding=xxx` 头
2. 移除项目内部 import（`from core.xxx` / `from adapters.xxx`）
3. 合并为一个文件，添加 `# coding=gbk` 头
4. UTF-8 → GBK 编码转换
5. AST 静态校验未定义变量（排除 QMT 内置函数）
6. 追加 QMT 生命周期模板（init/handlebar/exit）
7. 编译期语法校验

### 验证命令

```cmd
python scripts/validate_qmt_file.py strategy_main.py
```

**6 项检查必须 ALL PASS：**

| 检查项 | 说明 |
|--------|------|
| 1. 文件存在 | 路径可读 |
| 2. 编码 GBK | 二进制解码验证 |
| 3. 文件头 `# coding=gbk` | 首行声明 |
| 4. Python 3.6 语法 | compile + AST + 禁用语法检测 |
| 5. 无 MOCK 残留 | 仅生产版检查 |
| 6. 无长小数输出 | 评分值必须 `%.2f` |

## 核心模块

### 评分系统

**主力评分器：ScoreCalculator6Plus2** (`core/scoring/dimension6plus2.py`)

| 维度 | 权重 | 说明 |
|------|------|------|
| 1. Breakout Validity | 22 | 突破有效性：20日振幅+突破幅度+量比 |
| 2. Trend Health | 13 | 趋势健康度：5日均线乖离率 |
| 3. Consolidation Strength | 20 | 盘整强度：近5日最低价守住MA5的天数 |
| 4. Volume-Price Health | 12 | 量价健康度：量比衰减评分 |
| 5. MACD Momentum | 12 | MACD动能：柱线方向+位置组合 |
| 6. Valuation Safety | 7 | 估值安全：动态PE vs 静态PE |
| 7. Sentiment | 7 | 情绪：截面5日收益率百分位映射 |
| 8. Sector Heat | 7 | 板块热度：预计算文件或QMT API |
| **Total** | **100** | |

**备用评分器：ScoreCalculator8D** (`core/signal_main_rise.py`)

- 8维加权：基本面18 + 估值12 + 技术面18 + 资金面15 + 成长性15 + 情绪面8 + 风险7 + 板块7 = 100
- 支持腾讯接口获取实时PE/PB
- 市场系数调整（多头1.0 / 震荡0.85 / 空头0.60）

**切换器：SwitchScorer** (`core/scoring/switch_scorer.py`)

- `mode='6plus2'`：始终使用6+2
- `mode='8d'`：始终使用8D
- `mode='round_robin'`：按交易日奇偶轮换

### 卖出风控引擎

**SellStrategyEngine** (`core/risk_manager.py`) — 四层优先级：

| 层级 | 触发条件 | 动作 |
|------|----------|------|
| 底线层 | 累计亏损 ≤ -5% 或 单日跌幅 ≤ -7% | 清仓 |
| 清仓层 | 连续3日收盘价 < MA20 | 清仓 |
| 预警层 | B1放量/B2量价背离/C2 MACD缩短/KDJ死叉 | 减仓30% |
| 确认层 | A2破MA10/C1长上影/B3高位放量阴线 | 再减50% |

特性：
- 状态持久化到 JSON 文件
- 预警层减仓后支持反弹恢复（3日窗口）
- 清仓后 20 日禁入
- 跌停暂缓队列（跌停中暂不卖，开板即卖，超5天强制卖）

### 交易执行

**Trader** (`adapters/qmt_wrapper.py`)

- 封装 `passorder` 买卖委托
- 卖一价限价单 + 市价单回退
- 重试自动切换市价单确保成交
- SAFEMODE 拦截 + CSV 日志

**StrategyRunner** — 主流程：

1. `init()`: 加载配置 → 初始化评分器 → 加载数据 → 恢复持仓状态
2. `handlebar()`: 刷新数据 → 检查待成交订单 → 卖出检查 → 买入决策 → 全天版操作点调度
3. `exit()`: 写持仓/净值文件 → 生成策略日志

### 全天版操作点

| 操作点 | 时间 | 说明 |
|--------|------|------|
| 0924 | 开盘集合竞价后 | 首次全流程 |
| 1000 | 方向确立 | 首次决策 |
| 1330 | 下午开盘 | 方向确认决策 |
| 1430 | 尾盘冲刺 | 最后决策 |

全天版使用独立文件（`allday_*`），避免与尾盘版互相干扰。

### 文件通信

策略运行时通过 `D:/QMT_POOL/` 目录进行文件交换：

| 文件 | 用途 |
|------|------|
| `selected.txt` / `QMTselected.txt` | 外部股票池 |
| `*_holdings*.txt` | 持仓跟踪（CSV格式：code,highest_price） |
| `*_nav*.txt` | 累计盈亏净值 |
| `sector_heat.json` | 板块热度预计算数据 |
| `成交记录_*.txt` | 交易记录 |
| `*_sell_state_*.json` | 卖出状态持久化 |
| `strategy_log_*.txt` | 每日策略执行日志 |

## 关键红线

| 规则 | 说明 |
|------|------|
| GBK 编码 | 所有 QMT 文件必须 `# coding=gbk`，禁止用 patch 工具编辑 |
| Python 3.6.8 | 禁用 `dict[str,...]`、`str\|None`、`:=`、match-case、f-string |
| MOCK 排除 | `build_strategy.py` 的 SOURCE_FILES 不含 `adapters/context_mock.py` |
| SAFEMODE | `context_mock.py` 的全局 `passorder()` 会覆盖真实交易函数 |

## 测试框架

- **13 个测试文件**，覆盖 utils、评分、回测、safemode、信号、卖出重试、池筛选
- **conftest.py** 提供：
  - `mock_klines`：随机60行OHLCV数据
  - `mock_context`：已注入K线的 MockContextInfo
  - `safemode_reset`：跨测试 SAFEMODE 状态隔离（autouse）
- 测试环境使用外部 Python 3.11（`.venv`），与 QMT 运行时 Python 3.6.8 隔离
