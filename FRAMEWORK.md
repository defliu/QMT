# QMT_STRATEGIES 框架全景

> 生成时间: 2026-06-11 | 更新: 2026-07-03（同步到 `v2026.07.03-observability`，commit 00a066c）

## 目录结构

```
D:\QMT_STRATEGIES\
├── core/                        # 纯逻辑层（零 QMT 依赖）
│   ├── utils.py                 # 技术指标：MA/EMA/MACD/KDJ/RSI/ATR/CMF/角度/影线检测
│   ├── scoring/
│   │   ├── dimension6plus2.py   # ★ 主力评分器：6+2 维度（突破22+趋势13+盘整20+量价12+MACD12+估值7+情绪7+板块7=100）
│   │   └── switch_scorer.py     # 评分器切换器：6plus2 / 8d / round_robin 三种模式
│   ├── signal_main_rise.py      # 8D 加权评分系统（旧版100分制+市场系数）+ SectorAnalyzer
│   ├── risk_manager.py          # ★ 四层卖出风控引擎（底线>清仓>预警>确认）
│   ├── pool_filter.py           # 筹码密集突破选股（功能冗余，未接入主流程）
│   └── position_sizer.py        # 凯利公式仓位 + 移动止盈
├── adapters/                    # QMT 运行时桥接层
│   ├── qmt_wrapper.py           # ★ 核心适配器：Trader/StrategyRunner/数据加载/订单管理/文件IO/SAFEMODE/持仓纳管/盘前预埋/盘后导出/可观测日志
│   └── context_mock.py          # MockContextInfo（终端测试用，构建时排除；只测信号逻辑，测不到QMT集成层）
├── config/
│   └── global_config.yaml       # 全局配置（策略参数/账户/路径/safemode/debug）
├── scripts/
│   ├── build_strategy.py        # ★ 构建脚本：合并→GBK→3种产物
│   ├── validate_qmt_file.py     # ★ 6项合规检查（编码/语法/MOCK残留/长小数）
│   ├── backtest_6plus2_full.py  # 回测脚本
│   ├── backtest_dimension6plus2.py
│   └── ...                      # 诊断/回测/格式化脚本
├── tests/                       # 测试文件 + conftest.py（pytest fixtures）
├── deploy/                      # 部署产物（build 输出目录）
│   ├── strategy_main.py         # 生产版主策略 → QMT 部署为 STRATEGY_MAIN.py
│   ├── strategy_dev.py          # 开发版含MOCK
│   ├── qmt_daily_export.py      # 数据导出脚本 → QMT 部署为 数据导出.py
│   └── global_config.yaml       # 配置文件
├── specs/                       # Hermes 输出的 SPEC 共享目录
├── research/                    # 策略研究文档（00_A股交易制度 ~ 06_诚哥策略偏好）
├── knowledge_base/              # Obsidian 量化知识库（junction → F: 云盘）
├── release/                     # 发布版
├── worklog/                     # 每日工作日志
```

## 构建流水线

| 命令 | 产物 | 说明 |
|------|------|------|
| `python scripts/build_strategy.py` | `deploy/strategy_main.py` | 生产版（尾盘模式） |
| `python scripts/build_strategy.py --dev` | `deploy/strategy_dev.py` | 开发版（含MOCK） |
| `python scripts/build_strategy.py --allday` | `deploy/strategy_allday.py` | 全天版（DEBUG_MODE硬编码True） |

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

构建步骤：读取源文件 → 移除 `# coding=xxx` 头和项目内部 import → 合并加 `# coding=gbk` 头 → UTF-8→GBK → AST 静态校验 → 追加 QMT 生命周期模板（init/handlebar/exit）→ 编译期语法校验。

### 验证命令

```cmd
python scripts/validate_qmt_file.py deploy/strategy_main.py
```

**6 项检查必须 ALL PASS：** 文件存在 / 编码 GBK / 文件头 `# coding=gbk` / Python 3.6 语法 / 无 MOCK 残留 / 无长小数输出。

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

> 参数以 `dimension6plus2.py` 代码为准。

**备用评分器：ScoreCalculator8D** (`core/signal_main_rise.py`) — 8维加权（基本面18+估值12+技术面18+资金面15+成长性15+情绪面8+风险7+板块7=100），支持腾讯接口获取实时PE/PB，市场系数调整。

**切换器：SwitchScorer** (`core/scoring/switch_scorer.py`) — `mode='6plus2'`/`'8d'`/`'round_robin'`（按交易日奇偶轮换）。

### 卖出风控引擎

**SellStrategyEngine** (`core/risk_manager.py`) — 四层优先级递减：

```
底线层（硬止损）> 清仓层（技术破位）> 预警层（减仓30%）> 确认层（追加减仓50%）
```

| 层级 | 触发条件 | 动作 |
|------|----------|------|
| 底线层 | 累计亏损 ≤ -8%（`HARD_STOP_LOSS`）或 单日跌幅 ≤ -7%（`BOTTOM_LINE_DAILY_DROP_PCT`）| 清仓 |
| 清仓层 | 连续3日收盘价 < MA20 / 破最高日低点 / 移动止盈 | 清仓 |
| 预警层 | B1放量 / B2量价背离 / C2 MACD红柱缩短 / KDJ死叉 | 减仓30% |
| 确认层 | A2破MA10 / C1长上影 / B3高位放量阴线 | 再减50% |

特性：
- 状态持久化到 JSON 文件
- 预警层减仓后支持反弹恢复（3日窗口）
- 清仓后 20 日禁入
- 跌停暂缓队列（跌停中暂不卖，开板即卖，超5天强制卖）
- **时段路由**（`_get_allowed_sell_layers`）：0930-0935 只放底线层；0935-0940 放底线+清仓层；0940-1458 全部层

**盘前预埋硬止损**（`_check_pre_market_hard_stop`，0703 启用）：
- `PREMARKET_HARD_STOP_MODE = 'G3_ONLY'`（0703 结束 P3 观察期启用，原 OFF）
- 09:25-09:29:59 扫描持仓，按集合竞价价算 grade（G3：累计亏≤-5% 或 日跌≤-7%），预埋卖出单（限价=prev_close*0.91）
- 每天只跑一次，诊断写 `D:/QMT_POOL/premarket_diag_YYYYMMDD.csv`

### 交易执行

**Trader** (`adapters/qmt_wrapper.py`)

- 封装 `passorder` 买卖委托，卖一价限价单 + 市价单回退
- **反查短轮询**（lookup 修复）：passorder 后 4×0.2s 轮询 `_lookup_recent_order_id` 查 order_id，避免 QMT 异步分配 ~100ms 延迟误判
- **BUG5 诊断**（0703）：反查失败时 dump orders 前5条字段到 `D:/QMT_POOL/lookup_diag_YYYYMMDD.csv`，打 `[反查诊断]`（BUG5 单子真成交但策略误判失败，待抓现场精修）
- SAFEMODE 拦截 + CSV 日志

**StrategyRunner** — 主流程：

1. `init()`: 加载配置（自包含，去 `__file__` 依赖）→ 初始化评分器 → 加载数据 → 交易通道就绪 → 恢复持仓状态 → **持仓纳管**（`_sync_holdings_from_account`）→ **持仓对账**（`[对账]`）→ 盘后立即导出（`_is_export_time`）
2. `handlebar()`: `[时段]` 日志 → 刷新数据 → 检查待成交订单 → 卖出检查（每轮前补 sync，0702 BUG2）→ 买入决策 → 全天版操作点调度 → 15:00 收盘帧导出 + 持仓对账
3. `exit()`: 写持仓/净值文件 → 生成策略日志

**持仓纳管**（0702 反转方案C）：
- `_sync_holdings_from_account` 用 `get_holdings()` 拿账户全量持仓，`volume>0 且 not in _g_my_codes` 的票纳入 `_g_my_codes[code]=cost`（m_dOpenPrice），打 `[持仓纳管]`
- 三时机：开盘首帧 / 买入前 / 卖出评估前每轮补 sync
- 治孤儿持仓（账户有票 holdings 没记录→卖出引擎不评估→信号触发也不卖）

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
| `endofday_holdings_beat.txt` / `intraday_holdings.txt` | 持仓跟踪 |
| `endofday_nav_beat.txt` / `cumulative_pnl_DUAL_BAND.txt` | 累计盈亏净值 |
| `sector_heat.json` | 板块热度预计算数据 |
| `成交记录_*.txt` | 交易记录 |
| `endofday_sell_state_beat.json` | 卖出状态持久化 |
| `strategy_log_*.txt` | 每日策略执行日志（文件名用系统时间，CMOS 错乱会变 2023 年，看内容 today=）|
| `成交明细_YYYYMMDD.csv` / `持仓明细_*.csv` / `资金概况_*.csv` | 盘后导出（15:00 收盘帧，Hermes 重建盈亏用）|
| `premarket_diag_*.csv` | 盘前预埋诊断 |
| `lookup_diag_*.csv` | 反查失败诊断（BUG5）|

### 可观测性日志（0703 增强）

| 日志 | 含义 |
|------|------|
| `策略版本=v2026.07.03-observability` | 新代码生效确认 |
| `[时间校验] 行情时间= 设备时间=` | 时钟正常（CMOS 检查）|
| `[init] <步骤> 耗时Ns` | init 各步骤耗时 |
| `[对账] _g_my_codes vs account` | 持仓对账，不一致打 `[对账告警]` |
| `[时段] HHMM <描述>` | handlebar 时段进入（0925/0930/0940/1000/1458/1500）|
| `[持仓纳管] 已纳入` | 孤儿持仓纳管 |
| `[卖出评估] <code>` | 卖出引擎评估每只持仓 |
| `[反查诊断] <code> orders_count=N` | BUG5 诊断 |
| `[导出] 完成 产出N文件` | 15:00 收盘导出 |

## 关键红线

| 规则 | 说明 |
|------|------|
| GBK 编码 | 所有 QMT 文件必须 `# coding=gbk`，禁止用 patch 工具编辑 |
| Python 3.6.8 | 禁用 `dict[str,...]`、`str\|None`、`:=`、match-case、f-string |
| MOCK 排除 | `build_strategy.py` 的 SOURCE_FILES 不含 `adapters/context_mock.py`（生产版）|
| SAFEMODE | `context_mock.py` 的全局 `passorder()` 会覆盖真实交易函数 |
| **MOCK 局限** | `context_mock.py` 只测信号逻辑（passorder 同步、MockPos 空仓、时间固定），QMT 集成层 BUG（时序/异步/字段/文件/生命周期）测不到。最近 BUG 8成在集成层 |
| **模拟端验证** | 部署实盘前必须在模拟端 `\\192.168.31.131`（67014907）跑1交易日过 8 项 checklist（`knowledge_base/60_工程知识库/QMT模拟端部署验证清单.md`），不通过不上实盘 |
| **部署归诚哥** | CC 只到改源文件 + rebuild + commit 为止，部署到 QMT 终端（加密 STRATEGYBEAT.py）诚哥自己做 |

## 测试框架

- 测试文件覆盖 utils、评分、回测、safemode、信号、卖出重试、池筛选、持仓同步、订单反查
- **conftest.py** 提供：`mock_klines`（随机60行OHLCV）/ `mock_context`（已注入K线的 MockContextInfo）/ `safemode_reset`（跨测试 SAFEMODE 状态隔离，autouse）
- 测试环境使用外部 Python 3.11（`.venv`），与 QMT 运行时 Python 3.6.8 隔离

## 关联文档

- `运行策略说明书_双带主升浪_QMT.md` — 运行说明（部署/检查清单/已知限制）
- `specs/SPEC_20260612_卖出策略V1.0.md` — 四层卖出引擎详细 SPEC
- `specs/SPEC_20260703_sim_verify_observability.md` — 模拟端验证流程 + 可观测性增强（A+C 方案）
- `knowledge_base/60_工程知识库/QMT模拟端部署验证清单.md` — 部署前 8 项 checklist
- `AGENTS.md` — Agent 开发指南
