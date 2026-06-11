# WORKFLOW: QMT 策略开发 → 回测 → 部署完整流水线

**Version**: 1.0
**Date**: 2026-06-01
**Author**: Workflow Architect
**Status**: Approved
**Implements**: QMT Strategies 全套开发流水线文档化

---

## 概述

本规格说明映射 QMT 主升浪策略从需求提出到实盘运行的全生命周期。涵盖：
1. 需求→Task Spec → CC 编码 → 审查 → 回测 → 调优 → 部署 → 实盘
2. 所有 CLI 入口、脚本调用链、数据流、故障模式

本流水线在三个环境中运行：
- **Hermes（WSL）**: 策略设计、Task Spec 编写、验收
- **Claude Code（Windows）**: 编码、测试、回测执行
- **MiniQMT（Windows）**: 实盘行情 + 交易

---

## 参与者

| 参与者 | 在本流水线中的角色 |
|---|---|
| 诚哥（策略架构师） | 定义需求 → 写 Task Spec → 验收 CC 产出 → 决策调参方向 |
| Claude Code（CC） | 按 Task Spec 编码 + 测试 + build → 提交审查 |
| deepseek-v4-pro（审查模型） | 审查 CC 产出 → APPROVED / REJECTED |
| Build Strategy 脚本 | 内联合并 core/ + adapters/ → GBK 编码 → strategy_main.py |
| Backtest Runner | 程序化回测引擎：build → 加载策略 → 模拟逐 K 线 → 输出报告 |
| MiniQMT | 真实行情接入 + 实盘交易执行 |
| 通达标杆（TDX） | 选股公式源头（COST/MA/振幅等 7 条件） |
| pandas / numpy | K 线数据计算基础设施 |

---

## 前置条件

- WSL Python 3.11+ 环境（Hermes 运行环境）
- Windows Python 3.10+ 环境（CC 执行环境）
- xtquant 包（MiniQMT 数据源，`setup_xtquant.py` 一键安装）
- mootdx 包可用（WSL/Windows 均可，通达信 TCP 直连）
- QMT 模拟端客户端已安装（D:\\国金QMT*模拟* 或 D:\\QMT*模拟*）
- git 仓库已克隆到 `D:\QMT_STRATEGIES\`

---

## 触发器

| 触发场景 | 精确触发 |
|---|---|
| 新策略功能 | 诚哥编写 `TS-YYYYMMDD-NNN_描述.md` → 下发 CC |
| 策略调参 | 阅读回测报告 → 修改 `config/global_config.yaml` → 重跑回测 |
| Bug 修复 | 发现异常 → 写 Task Spec → CC 修复 |
| 部署上线 | 确认回测达标 → `build_strategy.py` → 粘贴到 QMT 客户端 |

---

## 工作流树

### STEP 0: 需求定义（前置步骤，非代码）
**Actor**: 诚哥
**Action**: 根据策略方向/TDX 选股公式更新 → 编写 Task Spec 文档
**Timeout**: 不适用
**Input**: 策略文档、回测报告、TDX 公式变化
**Output on SUCCESS**: `TS-YYYYMMDD-NNN.md` 文件写入 D:\QMT_STRATEGIES\ → GO TO STEP 1
**Output on FAILURE**:
  - `FAILURE(ambiguity)`: 需求不清晰 → 追问澄清，不进入编码

**可观测状态**:
  - 诚哥看到: 已写好的 Task Spec 文件
  - 数据库: TS-*.md 存在于项目根目录
  - 日志: git log 中出现 TS 文件 commit

---

### STEP 1: CC 编码
**Actor**: Claude Code (Windows 侧)
**Action**: 读取 Task Spec → 按需求修改 core/ adapters/ tests/ → 写代码 + 写测试 + 跑测试
**Timeout**: CC 执行时限（通常 5-30 分钟，取决于任务大小）
**Input**: `TS-YYYYMMDD-NNN.md`（Task Spec 含接口定义/输入输出示例/测试清单/文件位置/验收标准）
**Output on SUCCESS**: 代码变更 + 新测试通过 → GO TO STEP 2
**Output on FAILURE**:
  - `FAILURE(compile_error)`: 语法错误/import 缺失 → [CC 自行修复重试]
  - `FAILURE(test_failure)`: pytest 未通过 → [CC 修复代码直到测试全绿]
  - `FAILURE(timeout)`: CC 超时未完成 → [标记 Task Spec 过大，拆分重发]

**可观测状态**:
  - 开发者看到: CC 终端输出进度
  - 数据库: git 中待 commit 的变更文件
  - 日志: CC 输出的 build/test log

**假设**:
  - A1: CC 在 Windows 侧执行，路径为 D:\QMT_STRATEGIES\ → 已验证
  - A2: CC 使用的 Python 版本 >= 3.10 → 已验证

---

### STEP 2: 代码审查 (Code Review)
**Actor**: deepseek-v4-pro (delegation 审查模型)
**Action**: CC 完成编码后 → ACK 审查请求 → deepseek-v4-pro 审阅 diff → 输出 APPROVED 或 REJECTED
**Timeout**: 2-5 分钟
**Input**: git diff (CC 的代码变更)
**Output on APPROVED**: 审查通过 → GO TO STEP 3 (单元测试验证)
**Output on REJECTED**: 审查不通过 → BACK TO STEP 1 (CC 修复问题)
  - `FAILURE(review_reject)`: 代码质量/安全/风格不达标 → [返回 CC 修复]

**可观测状态**:
  - 开发者看到: APPROVED ✓ 或 REJECTED ✗ 标记
  - 数据库: 审查记录在 Hermes 会话中留存
  - 日志: `[Review] [workflow] [file] → {APPROVED|REJECTED}: [reasons]`

---

### STEP 3: 单元测试 (Unit Test)
**Actor**: pytest (CI / 开发者手动)
**Action**: `python -m pytest tests/ -v` — 验证所有已有 + 新测试通过
**Timeout**: 30s
**Input**: `tests/` 下所有 Python 测试文件
**Output on SUCCESS**: 全部测试通过 (exit 0) → GO TO STEP 4
**Output on FAILURE**:
  - `FAILURE(test_error)`: 单个测试失败 → BACK TO STEP 1 (CC 修复)
  - `FAILURE(import_error)`: 模块 import 失败 → BACK TO STEP 1 (CC 修复)
    - 已知问题: `tests/test_signal_main_rise.py` 仍引用已删除的 `check_buy` → 触发 ERROR 而非 FAIL
  - `FAILURE(timeout)`: 测试超时 → 检查死循环或慢测试 → [报告异常]

**可观测状态**:
  - 开发者看到: `91 collected, 90 passed, 1 error` 等概要
  - 数据库: `.pytest_cache/` 缓存
  - 日志: pytest 输出到 stdout

**已知差距**:
  - RC-1: `tests/test_signal_main_rise.py` 仍 import `check_buy`（V1.0 已删除）
    - 严重程度: Medium — ERROR 中断集合但不是运行失败
    - 解析: 待 CC 修复（删除引用 check_buy 的旧测试用例）

---

### STEP 4: 构建策略 (Build Strategy)
**Actor**: `scripts/build_strategy.py`
**Action**: 读取 SOURCE_FILES 列表 → 按依赖顺序合并 → 移除 coding header 和内部 import → 添加 QMT 生命周期模板 → UTF-8→GBK 编码转换 → 输出 strategy_main.py
**Timeout**: 5s
**Input**: 以下源文件（按依赖顺序）:
  1. `core/utils.py`
  2. `core/signal_main_rise.py`
  3. `core/risk_manager.py`
  4. `core/position_sizer.py`
  5. `adapters/context_mock.py`
  6. `adapters/qmt_wrapper.py`
**Output on SUCCESS**: `strategy_main.py` 已生成，验证 GBK 编码 + coding=gbk 头 → GO TO STEP 5 (回测) 或直接跳到部署
**Output on FAILURE**:
  - `FAILURE(gbk_error)`: 合并后字符串含 GBK 不兼容字符 → [检查中文注释/字符串 → 修复编码问题]
  - `FAILURE(missing_file)`: SOURCE_FILES 中的文件不存在 → [检查文件是否被误删或改名]

**可观测状态**:
  - 开发者看到: `Building strategy_main.py ... OK: D:\QMT_STRATEGIES\strategy_main.py`
  - 数据库: `strategy_main.py` 重新生成（原有被覆盖）
  - 日志: 控制台打印生成过程

**关键细节**:
  - `build_strategy.py` 的 `SOURCE_FILES` 列表顺序决定最终的函数覆盖优先级（后合并的覆盖前合并的同名函数）
  - QMT 生命周期模板注入 `init()` / `after_init()` / `handlebar()` / `exit()` 四个钩子
  - `.gitignore` 已排除 `strategy_main.py`（构建产物不入版本控制）

---

### STEP 5a: 回测 — 指定股票
**Actor**: `scripts/run_backtest.py`
**Action**: 
```bash
python scripts/run_backtest.py --start 2024-01-01 --end 2024-03-31 \
  --capital 100000 --stocks "600519.SH,000001.SZ" --output report.json
```
1. 解析 CLI 参数
2. （可选）调用 `build_strategy.py` 产生 `strategy_main.py`
3. 创建 `BacktestRunner` 实例
4. BacktestRunner 加载股票数据（按 datasource 选择）:
   - `xtquant`: MiniQMT 数据（需启动 MiniQMT）
   - `mootdx`: 通达信 TCP 直连（最稳，不限流）
   - `tencent`: 腾讯财经 HTTP（备选）
5. 创建 `BacktestState`（模拟资金/持仓/成交/净值）
6. 逐 K 线循环: 模拟 handlebar → 信号检测 → mock passorder → 更新持仓 → 记录净值
7. 计算绩效指标 (BacktestResult)
8. 输出 JSON 报告 / 可读格式
**Timeout**: 根据股票数量 * K线天数（单股票约 0.5-5s）
**Input**: CLI 参数 / 可选 YAML 参数文件
**Output on SUCCESS**: `BacktestResult.success=True` + 含完整绩效指标的报告 → GO TO STEP 6 (模型评审)
**Output on FAILURE**:
  - `FAILURE(data_source)`: xtquant 未启动 → 降级到 mootdx 重试
    ```text
    [警告] MiniQMT 未连接，xtquant 不可用
    自动降级: 切换到 mootdx 数据源（通达信直连）
    ```
  - `FAILURE(stock_not_found)`: 指定股票代码不存在或无数据 → [跳过该股票，继续其余]
  - `FAILURE(mootdx_rate_limit)`: 通达信限流 → [等待 60s 后重试，仍失败则标记为限流错误]
  - `FAILURE(timeout)`: 总执行时间超限 → [报告部分结果，标记为 incomplete]

**可观测状态**:
  - 开发者看到: 控制台实时输出进度 + 最终绩效摘要
  - 运维人员看到: `report.json`（如指定 `--output`）
  - 日志: 回测过程的每个 bar 的决策记录（内部）

---

### STEP 5b: 回测 — 全市场扫描模式
**Actor**: `scripts/run_backtest.py --datasource mootdx --scan`
**Action**:
1. 调用 `scan_market(ScanParams)`:
   - 使用 mootdx 获取全市场股票列表 (~5600 只)
   - 应用 `_tdx_formula_filter()` 7 条件筛选：
     1. 筹码密集: 60 日振幅 ≤ 25%
     2. 突破密集顶: C > REF(HHV(H,60),1) 三日内突破
     3. 蓄势: 5 日 ≥ 2 天涨跌幅 < 3%
     4. 多头排列: MA5>10>20 + MA60 向上/走平
     5. MA5 角度 ≥ 30°
     6. 阳线: C > O
     7. 排除急拉坑: 18 日坑幅 ≥ 16% + 3 日急拉 ≥ 13%
2. 过滤结果 → 候选池（上限 100 只）
3. 后续同 STEP 5a（逐 K 线回测）

**Timeout**: 全市场筛选约 2-10 分钟（5600 只 * 取日 K 线时间）+ 回测时间
**Input**: `--scan` CLI flag
**Output on SUCCESS**: 候选池股票列表 + 回测绩效报告 → GO TO STEP 6
**Output on FAILURE**:
  - `FAILURE(mootdx_limit)`: 东财/通达信 IP 限流 exit 52/RemoteDisconnected → [提示切换到缓存/等待 30min]
  - `FAILURE(no_candidates)`: `_tdx_formula_filter()` 选出 0 只符合条件的股票 → [报告市场状态：当前市场无符合条件标的，建议调整参数]

**可观测状态**:
  - 开发者看到: `── 全市场扫描 ──` + 进度条 + 筛选结果统计
  - 日志: `scan_market: {count} candidates after tdx filter`

---

### STEP 5c: 回测 — 千问3.7版并行策略
**Actor**: `scripts/run_backtest.py --strategy qmt37`
**Action**:
1. BacktestRunner 加载 `qmt37_strategy/` 替代 `core/signal_main_rise.py`
2. monkey-patch: 替换 `qmt.check_buy` 函数指针为 `signal_qmt37` 的信号函数
3. 回测流程与 STEP 5a 相同
**Timeout**: 同 STEP 5a
**Input**: `--strategy qmt37` CLI flag
**Output on SUCCESS**: 基于千问3.7版策略的回测报告 → GO TO STEP 6
**Output on FAILURE**: 同 STEP 5a

**关键差异**:
  - 千问版使用 90 日振幅替代（vs 默认版 60 日）
  - 买点 1/买点 2 的信号计算参数不同（30日+60日混合/45°角/MACD/买点分型）
  - 1:1 复刻自 `双带趋势_新旧双买点QMT代码千文3.7版.txt`

---

### STEP 6: 模型评审 (Model Review)
**Actor**: 诚哥（策略架构师）
**Action**: 阅读回测报告 → 评估绩效指标 → 决策下一步
**Timeout**: 不适用（人类决策）
**Input**: 回测 JSON 报告含：
  - `total_return`（总收益率）
  - `annualized_return`（年化收益率）
  - `max_drawdown`（最大回撤）
  - `sharpe_ratio`（夏普比率）
  - `volatility`（年化波动率）
  - `win_rate`（胜率）
  - `total_trades`（交易次数）
  - `benchmark_return`（基准收益率）
**Output on APPROVED**: 绩效达标 → GO TO STEP 7 (部署)
**Output on REJECTED**: 绩效不达标 → BACK TO 修改参数 → STEP 5a (重跑回测)
  - 调参入口: `config/global_config.yaml`（kelly 系数/止损线/持仓天数等）

**可观测状态**:
  - 诚哥看到: 结构化报告（JSON + 可读格式 + 关键指标摘要）
  - 运维人员看到: 报告已存档（如指定 `--output`）

---

### STEP 7: 部署 (Deploy to QMT)
**Actor**: 诚哥（手动操作）
**Action**: 
1. `python scripts/build_strategy.py` 确保 strategy_main.py 是最新版本
2. 打开 QMT 客户端
3. 将 strategy_main.py 的完整内容复制粘贴到 QMT 的 Python 策略编辑器
4. 保存并启动策略
**Timeout**: 手动操作，约 5 分钟
**Input**: `strategy_main.py`（GBK 编码，含 # coding=gbk）
**Output on SUCCESS**: 策略在 QMT 中运行 → GO TO STEP 8
**Output on FAILURE**:
  - `FAILURE(gbk_mismatch)`: QMT 报编码错误 → [重新 build，检查 GBK 编码头]
  - `FAILURE(qmt_api)`: QMT 运行时 API 不兼容 → [回滚到上一个已知可用的 strategy_main.py]

**可观测状态**:
  - 诚哥看到: QMT 策略编辑器中代码加载成功
  - 数据库: `strategy_main.py` 已存在于项目根目录
  - 日志: git commit（部署时记得打 tag）

---

### STEP 8: 实盘运行 (Live Trading)
**Actor**: MiniQMT
**Action**: 
1. QMT 定时任务触发 `handlebar(C)`（每个交易日最后一根 K 线）
2. handlebar 内部流程:
   a. 读取池文件 `D:/QMT_POOL/selected.txt`
   b. 对池中每只股票运行 8D 评分 (ScoreCalculator8D)
   c. 选择评分前 3 的股票
   d. 调用 `passorder()` 发出买入指令
   e. 检查持仓 → 运行四层卖出引擎（底线→预警→确认→清仓 + 移动止盈）
   f. 更新持仓文件 `D:/QMT_POOL/endofday_holdings_beat.txt`
   g. 更新净值文件 `D:/QMT_POOL/endofday_nav_beat.txt`
**Timeout**: 每次 handlebar 调用应在 30s 内完成
**Input**: 
  - 通达信选股结果 → `D:/QMT_POOL/selected.txt`
  - 配置 → `config/global_config.yaml`
**Output on SUCCESS**: 正常执行交易 → 更新状态文件
**Output on FAILURE**:
  - `FAILURE(pool_empty)`: selected.txt 为空 → [跳过当日买入，仅检查持仓卖出]
  - `FAILURE(miniqmt_disconnect)`: MiniQMT 断连 → [重启 MiniQMT → 检查持仓是否一致]
  - `FAILURE(trade_rejected)`: passorder 被交易所拒绝 → [记录错误，不重试]
  - `FAILURE(exception_in_handlebar)`: Python 异常 → [QMT 捕获，当日不做任何操作，记录错误]

**可观测状态**:
  - 诚哥看到: QMT 交易日志 + 持仓文件更新
  - 运维人员看到: 状态文件在 `D:/QMT_POOL/` 中更新
  - 数据库: `D:/QMT_POOL/*.txt` 和 `*.json` 文件

---

### STEP 9: 审计 — 实盘与回测偏差分析
**Actor**: 诚哥（定期执行）
**Action**: 对比 QMT_POOL 中的实际成交记录与回测的理论信号，校准滑点/成交价差
**Timeout**: 手动分析，不定期
**Input**: 
  - 回测报告输出的交易记录
  - QMT `成交记录_尾盘_外部池_beat.txt`
**Output on SUCCESS**: 偏差分析报告 → 更新 backtest_params（slippage/commission/tax 校准）
**Output on FAILURE**: 
  - `FAILURE(data_gap)`: 实际成交记录缺失 → [QMT 未正确记录，检查日志源]

---

### ABORT_CLEANUP: 回滚到已知稳定版本
**Triggered by**: 部署后 QMT 运行时出现严重错误 / 实盘交易异常
**Actions** (in order):
  1. 在 QMT 客户端停止当前策略
  2. git checkout 上一个已知可用的 tag/commit
  3. 重新 build: `python scripts/build_strategy.py`
  4. 验证: 在 WSL 跑 `pytest tests/ -v` 确保基础功能正常
  5. 重新部署
**What 诚哥 sees**: QMT 策略停止 → 回滚后重新激活
**What 运营 sees**: git 回滚记录

---

## 状态转换图

```
需求/TS → [CC 编码] → [审查] → [单元测试] → [构建] → [回测] → [模型评审] → [部署] → [实盘]
           ↑            ↑           ↑                      ↕ 调参重跑      ↕ 回滚        ↓
           └────────────┴───────────┘                                      定期审计+校准
```

各阶段状态:
```
[draft] → (CC 编码成功) → [in_review]
[in_review] → (APPROVED) → [tested]
[in_review] → (REJECTED) → [draft]
[tested] → (pytest 全绿) → [built]  
[built] → (build OK) → [backtested]
[backtested] → (绩效达标) → [deployed]
[backtested] → (绩效不达标) → [tuning] → [backtested] (重跑)
[deployed] → (粘贴到 QMT) → [live]
[live] → (回滚) → [deployed] (旧版本)
[live] → (审计发现偏差) → [calibrating] → [backtested] (校准后重跑)
```

---

## 交接契约

### Hermes (WSL) → Claude Code (Windows)
**机制**: 文件系统共享（`/mnt/d/QMT_STRATEGIES/` ↔ `D:\QMT_STRATEGIES\`）
**Payload**: `TS-YYYYMMDD-NNN.md` — Task Spec 文档
**成功响应**: CC 完成编码，git 中有变更
**失败响应**: CC 报告错误 / 任务被标记为 failed
**超时**: CC 单次任务执行时限（项目级配置）
**故障恢复**: 拆分过大任务 → 重新下发 Task Spec

### Build Strategy 脚本 → strategy_main.py
**端点**: `python scripts/build_strategy.py`
**Payload**: 6 个源文件的拼接内容（共 ~6800 行）
**成功响应**: `strategy_main.py` 写入磁盘，GBK 编码验证通过
**失败响应**: `print('ERROR: 文件不是有效的GBK编码')`
**超时**: 5s
**故障恢复**: 检查源文件编码 → 手动修复

### Backtest Runner → 数据源
**datasource=mootdx**:
  - 协议: 通达信 TCP 直连 (mootdx 库)
  - 成功: 返回 DataFrame（含 open/close/high/low/volume）
  - 失败: exit 52 / RemoteDisconnected (IP 限流)
  - 超时: 30s per 股票
  - 恢复: 降级到 tencent 数据源 / 等待 30min

**datasource=xtquant**:
  - 协议: MiniQMT API (xtquant 库)
  - 成功: 返回 DataFrame
  - 失败: MiniQMT 未启动 → ImportError
  - 恢复: 检查 MiniQMT 进程 → 启动 → 重试

### Backtest Runner → 回测结果
**输出**: `BacktestResult` dataclass
**成功响应**: `{"success": true, "total_return": 0.15, ...}`
**失败响应**: `{"success": false, "error": "reason"}`
**输出格式**: JSON (--json) / 可读文本 (默认) / 文件 (--output)

---

## 清理清单

| 资源 | 创建于步骤 | 销毁由 | 销毁方法 |
|---|---|---|---|
| strategy_main.py | STEP 4 | git reset / rm | 被覆盖或手动删除 |
| strategy_main.py（QMT 编辑器中的） | STEP 7 | 回滚策略 | QMT 编辑器手动替换 |
| 回测 JSON 报告 | STEP 5 | 无（保留用于追溯） | 不移除 |
| QMT_POOL/ 下的状态文件 | STEP 8 | 不清除 | 实盘运行持续覆盖 |

---

## 现实检查员发现

| # | 发现 | 严重程度 | 受影响的规格说明章节 | 解析 |
|---|---|---|---|---|
| RC-1 | `tests/test_signal_main_rise.py` 仍 import 已删除的 `check_buy` → pytest collection error | Medium | STEP 3 | 待 CC 修复（V1.0 代码清理遗留） |
| RC-2 | `--scan` CLI 参数未直通 `main()` — 当前需手动 sca + 传参 | Medium | STEP 5b | 记录于 V1.0 待办项 |
| RC-3 | Deploy-QMT 和 Live-Trading 工作流无规格说明 | High | STEP 7, 8 | 当前为手动操作，未自动化 |
| RC-4 | mootdx IP 限流（exit 52/RemoteDisconnected）持续数小时，无自动降级链路 | High | STEP 5b | 需在 backtest runner 中添加重试+降级逻辑 |
| RC-5 | `pool_filter.py` 声明"未接入主流程"但存在代码中 | Low | STEP 5b | `_tdx_formula_filter()` 是实际使用的过滤函数，pool_filter.py 是冗余 |

---

## 测试用例

| 测试 | 触发 | 预期行为 |
|---|---|---|
| TC-01: 正常开发路径 | 新 Task Spec → CC 编码 → 审查 → 测试 | 测试全绿，代码 APPROVED |
| TC-02: build_strategy.py | `python scripts/build_strategy.py` | strategy_main.py 生成，GBK 验证通过 |
| TC-03: 回测单股票 | `--stocks "600519.SH" --datasource mootdx` | 完整回测 + 绩效报告，exit 0 |
| TC-04: 回测全市场扫描 | `--datasource mootdx --scan` | 候选池生成 + 回测报告 |
| TC-05: 数据源降级 | MiniQMT 关闭时跑 `--datasource xtquant` | 报告 xtquant 错误（当前未自动降级） |
| TC-06: 空股票池 | `--stocks ""` + 无 `--scan` | 使用默认股票列表 (`_default_stocks()`) |
| TC-07: 测试覆盖率 | 运行所有 pytest | 91 collected, 90+ passed（已知 1 error 待修） |
| TC-08: 策略切换 | `--strategy qmt37 --stocks "600519.SH"` | 千问版信号回测 |

---

## 假设

| # | 假设 | 验证位置 | 如果错误的风险 |
|---|---|---|---|
| A1 | D:\QMT_STRATEGIES\ 目录在 Hermes (WSL) 和 CC (Windows) 间共享 | 已验证 /mnt/d 挂载 | 文件不同步 → 用旧代码回测 | 
| A2 | CC Python >= 3.10 | 已验证 | 语法兼容性问题 |
| A3 | MiniQMT 数据格式与回测 mock 一致 | 未验证（实盘/回测价差待校准） | 回测结果与实盘偏差大 |
| A4 | mootdx TCP 直连在中国网络环境下始终可用 | 已验证（但有限流可能） | 回测/扫描不可用 |
| A5 | 通达信选股公式（COST/振幅等7条件）与 QMT 策略的 8D 评分体系互补而非冲突 | V1.0 已验证 | check_buy 是冗余门 → 已绕过 |
| A6 | 回测结果与实盘结果的偏差主要由滑点/成交价差导致 | 待验证 | 若偏差有其他原因需修正回测引擎 |

---

## 待决问题

- [ ] Deploy-QMT 工作流能否自动化（通过 MCP / xtquant API 直接写入 QMT 策略编辑器）？
- [ ] Live-Trading 监控是否需要加上自动告警（QMT_POOL 文件变动监测 → 飞书通知）？
- [ ] mootdx 限流场景的自动重试 + 数据源降级链应如何设计？
- [ ] 实盘与回测的成交价差校准是否需要单独的工具脚本？

---

## Spec vs Reality 审计日志

| 日期 | 发现 | 操作 |
|---|---|---|
| 2026-06-01 | 初始版本规格说明 | — |
