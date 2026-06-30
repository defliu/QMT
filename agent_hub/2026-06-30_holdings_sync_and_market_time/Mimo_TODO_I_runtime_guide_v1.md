# 工单I：生成中文运行策略说明书《运行策略说明书_双带主升浪_QMT.md》

**日期**: 2026-06-30
**作者**: CC
**目的**: 当前 QMT 双带主升浪策略没有一份完整说明书；现有信息分散在 CLAUDE.md、worklog、SPEC、工单和源码中。生成一份中文说明书,覆盖当前正在跑的 main 版与全天版、仓位/资金管理、持仓同步、时间机制、部署验证和近期坑位。并从这份说明书开始建立版本号记录。
**预计工时**: ≤ 45 分钟

---

## 〇、背景（必读，不要改这段）

诚哥要求文件名中文: `运行策略说明书_双带主升浪_QMT.md`。

说明书要基于**当前代码实际状态**（含今天 commit 04e4091、3c36743、230aa06 以及工作区当前 build 产物），不能写过时结论。

需要参考的关键文件/信息：
- `D:/QMT_STRATEGIES/.claude/CLAUDE.md`：构建/验证/目录/运行前情
- `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`：核心运行逻辑
- `D:/QMT_STRATEGIES/scripts/build_strategy.py`：三种 build 产物
- `D:/QMT_STRATEGIES/DEPLOY.md`：部署信息
- `D:/QMT_STRATEGIES/worklog/系统更新日志.md`：历史概要
- `D:/QMT_STRATEGIES/specs/SPEC_20260612_卖出策略V1.0.md`：卖出层说明
- `D:/QMT_STRATEGIES/specs/SPEC_SELL_LOOKUP_AND_HOLDINGS_SYNC.md`：反查/持仓同步
- `D:/QMT_STRATEGIES/agent_hub/2026-06-30_holdings_sync_and_market_time/Mimo_TODO_E_dedup_buy_v1.md`
- `D:/QMT_STRATEGIES/agent_hub/2026-06-30_holdings_sync_and_market_time/Mimo_TODO_F1_check_pending_v1.md`
- `D:/QMT_STRATEGIES/agent_hub/2026-06-30_holdings_sync_and_market_time/Mimo_TODO_F2_position_gate_v1.md`
- `D:/QMT_STRATEGIES/agent_hub/2026-06-30_holdings_sync_and_market_time/Mimo_TODO_F3_per_stock_amount_v1.md`
- `D:/QMT_STRATEGIES/agent_hub/2026-06-30_holdings_sync_and_market_time/Mimo_TODO_F5_ma5_filter_v1.md`

**版本号要求**：
- 说明书顶部必须写：`文档版本：v2026.06.30-runtime-01`。
- 说明书顶部必须写：`适用策略版本：双带主升浪 QMT Runtime v2026.06.30-f1f5`。
- 说明书顶部必须写：`对应代码提交：04e4091 + 3c36743 + 230aa06（本地 master）`。
- 增加 `## 0. 版本信息` 小节，记录版本号、更新时间、覆盖的修复范围(A/B/E/F1/F2/F3/F5)、适用文件(strategy_main.py/strategy_allday.py)。
- 若代码中暂未有 `STRATEGY_VERSION` 常量,不要擅自改代码；只在说明书记录"代码内版本号待后续工单加入"。


   - `strategy_main.py`：生产/main 版,`DEBUG_MODE=False`,走 `_execute_trade`
   - `strategy_allday.py`：全天调试版,`DEBUG_MODE=True`,build 脚本硬编码,走 `_execute_full_cycle` / `_all_day_decision_matrix`
   - `strategy_dev.py`：开发版/测试版(含 MOCK,不要实盘)
2. 构建命令：
   - `python scripts\build_strategy.py`
   - `python scripts\build_strategy.py --allday`
   - `python scripts\build_strategy.py --dev`
   - 验证：`python scripts\validate_qmt_file.py <file>` 必须 6 项 ALL PASS
3. main/全天版核心链路：外部池 → check_buy → MA5乖离过滤 → ST过滤 → 6+2评分 → 买入；卖出走卖出引擎（底线/预警/确认/清仓）。
4. 仓位/资金管理：`MAX_HOLD=3`、`TARGET_RATIO=0.30`、`MAX_TOTAL_RATIO=0.90`；单次买入总额再受 `real_cash*0.80` 约束；每只金额 `min(current_nav*TARGET_RATIO, budget/买入只数)`。
5. 全天版最近深度对齐：
   - E：防重复买入（账户实际持仓加入买入排除集 + 下单前 get_position 拦截）
   - F1：`_check_pending_orders` 在 DEBUG_MODE 可达,成交回写 `_g_my_codes`
   - F2：总仓位门控/名额/holdings_value 用账户持仓只读计算
   - F3：per_stock_amount 均分 budget + 0.80 资金门控,`_place_buy_order` 瘦身
   - F5：main 版补 MA5 乖离过滤
6. 方案C：账户持仓参与仓位/名额/holdings_value 计算,但不写 `_g_my_codes`、不进卖出引擎,避免误管手动仓。策略自己买的票通过 `_check_pending_orders` 写回 `_g_my_codes`,卖出引擎可管理。
7. 时间机制：`_market_now(C)` 使用 QMT 行情时间,不依赖设备时钟；设备 CMOS 时间错乱不应影响策略时段判断；启动看 `[时间校验]`。
8. 持仓/净值/成交通过 `D:/QMT_POOL/` 文件通信；生产版与全天版持仓文件不同（全天版 `allday_holdings.txt` 等）。
9. 部署后必看日志关键字：`初始化完成`、`时间校验`、`全天] 仓位`、`买入排除`、`买入拦截`、`成交确认`、`持仓清理`。
10. 近期坑位：QMT position 缓存延迟、passorder 异步、GBK build 产物 grep 中文需转码、strategy_allday 是 build 产物需重新 build 才含修复。

---

## 一、必做（3 项）

### TASK-1. 阅读关键文件并确认当前代码事实

**内容/做法**:

只读以下文件,提取事实,不要凭记忆写：
- `adapters/qmt_wrapper.py` 中常量、路径覆盖、`_market_now`、`_execute_trade`、`_execute_full_cycle`、`_all_day_decision_matrix`、`_place_buy_order`、`_check_pending_orders`、`_finish_pending_sell`
- `scripts/build_strategy.py` 三个构建模式
- `.claude/CLAUDE.md` 构建/验证/部署约束
- 今天 E/F1/F2/F3/F5 工单回执

### TASK-2. 生成说明书

**目标路径**: `D:/QMT_STRATEGIES/运行策略说明书_双带主升浪_QMT.md`

**内容要求**:

用中文 Markdown,结构清晰,建议章节：

1. `# 运行策略说明书：双带主升浪 QMT版`
   - 标题下方写版本号三行：
     - `文档版本：v2026.06.30-runtime-01`
     - `适用策略版本：双带主升浪 QMT Runtime v2026.06.30-f1f5`
     - `对应代码提交：04e4091 + 3c36743 + 230aa06（本地 master）`
2. `## 0. 版本信息`
   - 记录版本号、更新时间、适用文件、覆盖修复范围、代码内版本号待后续工单加入
3. `## 1. 适用范围与版本`
   - main/allday/dev 三版区别
3. `## 2. 构建、验证与部署`
   - build/validate 命令,部署到 QMT 的路径,必看日志
4. `## 3. 运行入口与模式差异`
   - QMT init/handlebar/exit,main 版 `_execute_trade`,全天版 `_execute_full_cycle` / `_all_day_decision_matrix`,操作点
5. `## 4. 买入流程`
   - 外部池→check_buy→MA5乖离→ST→6+2评分→排除已有/挂单→下单
6. `## 5. 卖出与风控流程`
   - 卖出引擎分层,`_check_and_execute_sell`,反查,`_finish_pending_sell`,持仓清理
7. `## 6. 仓位与资金管理`
   - MAX_HOLD/TARGET_RATIO/MAX_TOTAL_RATIO/0.80资金上限,main版和全天版现在已对齐
8. `## 7. 持仓同步与文件通信`
   - D:/QMT_POOL 文件,main/allday 文件区别,方案C只读计数,`_check_pending_orders` 成交回写
9. `## 8. 时间机制`
   - `_market_now(C)`,QMT行情时间,设备时间只作日志对比/兜底
10. `## 9. 近期关键修复（2026-06-30）`
    - A/B/E/F1/F2/F3/F5 简表
11. `## 10. 运行后检查清单`
    - 部署后看哪些日志,异常现象对应什么问题
12. `## 11. 已知限制与注意事项`
    - 全天版调试用,不应与 main 版同时跑;手动仓不纳管;QMT缓存延迟;build产物需重建;GBK转码

**写作要求**:
- 面向诚哥和后续 Agent,不是写给新手金融小白,但要能一眼查到关键路径。
- 关键函数/文件名要写具体。
- 不要过度展开代码,但关键行号/函数要标。
- 明确说明"资金上限 0.90 是总仓位上限;0.80 是单次买入总额相对可用资金的保护线"。
- 明确说明"全天版和 main 版现在仓位/资金管理已深度对齐,但全天版仍是调试版,不建议和 main 版同时跑"。

### TASK-3. 自检

**内容/做法**:

1. 确认文件已创建且非空。
2. grep 必须命中以下关键词：
   - `strategy_main.py`
   - `strategy_allday.py`
   - `_market_now`
   - `_check_pending_orders`
   - `MAX_TOTAL_RATIO`
   - `方案C`
   - `0.80`
   - `MA5乖离`
3. 不需要 build/validate（只写 md）。
4. 不 git add / commit。

---

## 二、严禁

1. 禁止 git add / commit / push
2. 禁止改代码文件
3. 禁止改动本工单上方
4. 禁止写错 build/validate 命令
5. 禁止把全天版说成生产版；全天版是调试版(DEBUG_MODE=True)
6. 禁止说账户持仓会全部纳管进 _g_my_codes —— 当前方案C是只读计数,不纳管手动仓
7. 禁止跑实盘/模拟交易

---

## 三、完成回执（MIMO 在工单末尾追加）

```markdown

---

## 完成回执

**执行时间**: <用 `date -u +"%Y-%m-%dT%H:%M:%SZ"` 真实拿>
**MIMO 模型**: <实际模型名>
**自检**:
- [ ] 已创建 `运行策略说明书_双带主升浪_QMT.md`
- [ ] 说明书包含文档版本 `v2026.06.30-runtime-01` 和适用策略版本 `双带主升浪 QMT Runtime v2026.06.30-f1f5`
- [ ] 说明书包含 0.版本信息 + 11 个建议章节或等价结构
- [ ] grep 关键词全部命中
- [ ] 未改代码文件
- [ ] 未 git add / commit / push
- [ ] 仅末尾追加，未改动工单上方
```

---

## 完成回执

**执行时间**: 2026-06-30T14:03:00Z
**MIMO 模型**: mimo-auto
**自检**:
- [x] 已创建 `运行策略说明书_双带主升浪_QMT.md`（17985 bytes）
- [x] 说明书包含文档版本 `v2026.06.30-runtime-01` 和适用策略版本 `双带主升浪 QMT Runtime v2026.06.30-f1f5`
- [x] 说明书包含 0.版本信息 + 11 个章节（1.适用范围 2.构建验证部署 3.运行入口 4.买入流程 5.卖出风控 6.仓位资金 7.持仓同步文件通信 8.时间机制 9.近期修复 10.运行后检查 11.已知限制）
- [x] grep 关键词全部命中（strategy_main.py / strategy_allday.py / _market_now / _check_pending_orders / MAX_TOTAL_RATIO / 方案C / 0.80 / MA5乖离）
- [x] 未改代码文件
- [x] 未 git add / commit / push
- [x] 仅末尾追加，未改动工单上方
