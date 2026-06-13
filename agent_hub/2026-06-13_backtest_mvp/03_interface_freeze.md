# strategy_core 接口冻结评审帖（Phase 2.0 GATE）

日期：2026-06-13
作者：CC
状态：**待 Hermes 签字** 确认后才能进入 Phase 2 实现
对应 SPEC：`SPEC_BACKTEST_MVP_OFFLINE_FACTORY_v0.2.md` + 继承 v0.1 §3.3 / §3.4
对应 plan：`02_cc_implementation_plan.md` Task 2.0.1（硬约束 #1：Phase 2.0 接口冻结门禁）

---

## 0. 本文件定位

- 本文件**只冻结接口**，不实现 strategy_core 任何代码。
- 等 Hermes 在 §10 末尾签字「确认」后，CC 才会开 Task 2.1（写 `interface.py` / `enums.py` 骨架）。
- 冻结后的接口字段名 / 字段类型 / 字段语义：在 v0.2 实现期内**不可破坏性变更**；如必须变更，需要重新跑 GATE。

> ⚠️ 本接口涉及的 6 个待决策项已在 §9 OPEN_QUESTIONS 列出。Hermes 签字时请同时在 §9 给出每项决策。

---

## 1. evaluate_day 函数签名

```python
def evaluate_day(
    current_date,        # str, "YYYY-MM-DD"
    market_window,       # dict, code(str) -> DataFrame[date(str), open, high, low, close, vol, amount]
    positions,           # list[dict]，结构见 §2
    cash,                # float，可用现金（人民币元）
    universe,            # list[str]，候选股票池（已去 disabled / 去重）
    account_state,       # dict，结构见 §3
    strategy_config,     # dict，结构见 §4
    aux_data,            # dict，结构见 §5
):
    """
    返回 StrategyDecision dict（结构见 §6）。

    语义：
      - 当前日 current_date 收盘后调用一次，决定 T+1（next_open 模型）或 T 日 close
        模型的成交意图。引擎一天只调用一次本函数。
      - market_window 中每只股票的 DataFrame 仅含 current_date 及之前的数据
        （引擎负责切片），strategy_core 严禁读取未来数据。
      - 本函数不做 IO、不写文件、不调用网络、不打印副作用日志（必要日志返回到
        decision["logs"]，由引擎统一持久化到 logs.txt）。
    """
```

**约束：**

1. 函数纯函数语义：相同入参必须返回相同结果（用于 reproducibility 测试）。不得依赖 `time.time()` / 随机数 / 外部文件。
2. 不得 import xtquant / passorder / get_trade_detail_data / QMT ContextInfo（继承 v0.1 §4.4）。
3. 必须 Python 3.6-safe（继承 v0.1 §4.2）：
   - 禁用 `dict[str, ...]` / `list[str]` 类型注解
   - 禁用 `str | None` 联合类型语法
   - 禁用 walrus `:=`
   - 禁用 `match / case`
   - 禁用 dataclass
   - 复杂 f-string 慎用；`u""` 与普通字符串等价即可
4. 8 个参数顺序与 v0.1 §3.3 一致，**不调整顺序**（保证后续 mock 测试稳定）。

---

## 2. positions 结构

```python
positions = [
    {
        "code":             "000001.SZ",     # str, 标准化后缀 (.SZ/.SH)
        "volume":            1000,           # int, 持仓总量（股）
        "available_volume":  1000,           # int, 可卖量（T+1：当日买入为 0）
        "cost_price":        12.50,          # float, 平均成本价（除费用前的成交价）
        "entry_date":        "2024-03-15",   # str, "YYYY-MM-DD"，首次建仓日
        "holding_days":      5,              # int, ≥1，截至 current_date 的持有交易日数（含建仓日）
        "last_price":        13.20,          # float, current_date 收盘价（停牌则为最后可得收盘）
        "unrealized_pnl":    700.0,          # float, (last_price - cost_price) * volume，未扣费用
    },
    ...
]
```

**约束：**

1. `code` 必填且符合 `^\d{6}\.(SZ|SH)$`。
2. `volume` 与 `available_volume` 单位均为「股」（不是「手」）。`available_volume <= volume`。
3. `cost_price` 是**含买入滑点 + 手续费分摊**前的执行价（与 trades.csv 中 buy 行 `price` 字段口径一致）。
4. `entry_date` 是**首次建仓日**；中途加仓的口径在 v0.2 不展开（v0.2 全天版策略不做加仓，参考 CLAUDE.md「换仓条件 评分差≥15 换仓」—— 要么换仓要么持有，不加仓）。
5. `holding_days` 含建仓当日：T 日买入，T 日 evaluate_day 看到的是 `holding_days=1`。
6. `last_price` 在停牌日延续上一交易日值，由引擎在 portfolio 层赋值，strategy_core 直接使用。
7. `unrealized_pnl` 由引擎计算填好，strategy_core 可以直接信任。

---

## 3. account_state 结构

```python
account_state = {
    "current_date":         "2026-02-27",   # str, 与 evaluate_day 入参 current_date 一致
    "trading_day_index":    119,            # int, 自 backtest start 起第几个交易日（含当日）
    "total_asset":          1234567.89,     # float, 总资产 = cash + sum(volume * last_price)
    "market_value":         234567.89,      # float, 持仓市值
    "is_last_trading_day":  False,          # bool, 是否回测区间最后一日（next_open 信号丢弃判定用）
    "max_positions":        5,              # int, 配置项 strategy.max_positions 的回显
}
```

**约束：**

1. `current_date / trading_day_index` 是冗余字段（与 evaluate_day 入参重复），方便 strategy_core 内部子函数不必再传 current_date。
2. `is_last_trading_day=True` 时，strategy_core 仍可正常返回 buy_candidates，但引擎在 next_open 模型下会丢弃这些信号（continue v0.1 §3.6）。strategy_core **不需要**关心模型差异，只管返回意图；丢弃责任在 engine。
3. `max_positions` 等约束的真实裁剪在 strategy_core **必须**完成（不依赖 engine 二次裁剪）；这里回显只为方便阅读 diagnostics。

---

## 4. strategy_config 结构

直接来源于 `base.yaml` 的 `strategy / scoring / risk` 三段合并展开后的 dict。strategy_core 内部不做 yaml 解析，由 engine 解析后整段下发。

```python
strategy_config = {
    # from base.yaml [strategy]
    "max_positions":           5,
    "rebalance_policy":        "daily",      # v0.2 仅支持 "daily"

    # from base.yaml [scoring]
    "min_score":               60.0,
    "min_core":                32.0,
    "max_bias5":               10.0,
    "max_daily_pct":           9.0,
    "sector_heat_mode":        "zero",       # v0.2 仅支持 "zero"
    "score_gap_threshold":     15.0,         # 换仓阈值（CLAUDE.md：评分差≥15 换仓）

    # from base.yaml [risk]
    "early_stop_days":         3,            # int, 持有 ≥ N 天起允许 early_stop 触发
    "early_stop_loss":         -0.05,        # float, 收益率阈值（不含费）
    "stop_loss":               -0.08,        # float, 底线清仓阈值
    "warning_score_threshold": 50.0,         # 预警层评分上限：score < 50 才考虑 warning sell
    "early_stop_holding_days": 5,            # CLAUDE.md「持仓 5 天收益 < 3% 淘汰」中的 N
    "early_stop_min_return":   0.03,         # CLAUDE.md「持仓 5 天收益 < 3% 淘汰」中的阈值
}
```

**约束：**

1. `rebalance_policy` v0.2 仅 `"daily"`，其他值由 engine 在配置加载阶段拒绝。
2. `sector_heat_mode` v0.2 仅 `"zero"`（决策 §3.5 / SPEC v0.2 §3.1 sector_heat_mode）。其他值（如 `"static"` / `"historical"`）留 v0.3。
3. **关键 OPEN_QUESTION（§9 OQ-A）**：CLAUDE.md 中「持仓 5 天收益 < 3% 淘汰」与 SPEC v0.1 §3.9 的 `early_stop_days=3 / early_stop_loss=-0.05` 是**两条不同规则**还是**重命名同一规则**？本文按「两条规则并存」冻结：
   - **early_stop（短期止损）**：持有 `early_stop_days` 天后，若收益 < `early_stop_loss`，触发 `SELL_REASON_EARLY_STOP`。
   - **early_kick（长期淘汰）**：持有 `early_stop_holding_days` 天后，若收益 < `early_stop_min_return`，触发 `SELK_REASON_EARLY_STOP`（同一枚举，不同语义参数）。
   - 这样 `evaluate_day` 在 diagnostics 中可分别记录两类触发计数。
   - 若 Hermes 决策为「合并为同一条规则」，请在 §9 注明，CC 删 4 个新增字段中的 2 个。

---

## 5. aux_data 结构

```python
aux_data = {
    "fundamentals":  None,             # dict[code, dict] or None；MVP 不用，预留
    "sector_map":    None,             # dict[code, sector_str] or None；MVP 不用
    "sector_heat":   {},               # dict, "zero" 模式下永远为空 dict（不是 None）
    "benchmark":     None,             # dict[date_str, close] or None；v0.2 默认 None（决策 E）
    "trading_calendar": ["2025-09-01", ...],  # list[str], 整个回测区间的交易日列表
    "warnings":      [],               # list[str], 引擎预先记录的辅助数据告警（如 "missing PE for 600519.SH"）
}
```

**约束：**

1. **缺失辅助数据时填默认值，不抛异常**（继承 v0.1 §3.4）：strategy_core 的 score_universe 包装层必须做缺失保护。
2. `sector_heat = {}`（空 dict）等价于 `sector_heat_mode == "zero"` 下的零热度近似，summary.json `sector_heat_warning` 字段必须输出。
3. `trading_calendar` 由引擎从 `DuckDBDailyReader.trading_calendar()` 取得后传入；strategy_core 用它判断 holding_days、early_stop_holding_days 等基于交易日的计数（不是自然日）。
4. `warnings` 是引擎累积的告警，strategy_core 可追加内容到 decision["logs"] 但**不修改入参**（保持纯函数）。

---

## 6. StrategyDecision 结构（返回值）

```python
{
    "sell_decisions": [
        {
            "code":            "000001.SZ",       # str
            "action":           "sell",            # "sell" | "reduce"
            "target_volume":    0,                 # int, 0 = 全部清仓；>0 = 减仓目标剩余股数
            "reason":           "stop_loss",       # str, 见 §7 卖出理由枚举
            "layer":            "bottom_line",     # str, "bottom_line" | "confirm" | "warning"
            "priority":         1,                 # int, 1 最高，3 最低（决定执行顺序）
            "diagnostics_ref":  "000001.SZ",       # str, 指回 diagnostics["scores"] 的 key
        },
    ],

    "buy_candidates": [
        {
            "code":            "600519.SH",        # str
            "score_total":      72.5,              # float, 6+2 总分
            "score_core":       38.0,              # float, 6 维核心子和（不含情绪、板块）
            "bias5":            6.5,               # float, 5 日 bias（百分比）
            "daily_pct":        3.2,               # float, current_date 当日涨跌幅（%）
            "rank":             1,                 # int, 候选池内排名（按 score_total 降序）
            "target_weight":    0.20,              # float, 目标仓位占比（0.0 ~ 1.0）
            "target_cash":      200000.0,          # float, 目标使用资金（元）
            "target_volume":    0,                 # int, 0 表示由 engine 按 next_open/close 价格折算
            "reason":           "top_candidate",   # str, "top_candidate" | "replace_target"
        },
    ],

    "target_positions": [
        # MVP 留空 list；预留给 v0.3+ 的目标仓位重新平衡模式
    ],

    "blocked_candidates": [
        {
            "code":             "000002.SZ",
            "blocked_by":       "min_score",       # str, 见 §8 blocked 原因枚举
            "raw_score":        55.0,              # float, 触发拦截前的原始 score_total
            "reason":           "总分 55.0 < 最低分 60",  # str, 给人读的说明
        },
    ],

    "diagnostics": {
        "scores": {
            "000001.SZ": {
                "score_total":         72.5,
                "score_breakout":      18.2,
                "score_trend":         11.0,
                "score_consolidation": 17.5,
                "score_volumeprice":   10.8,       # ⚠️ 命名见 §9 OQ-B
                "score_macd":           9.5,
                "score_valuation":      4.0,
                "score_sentiment":      3.5,
                "score_sector":         0.0,       # zero 模式恒 0
                "bias5":                6.5,
                "signal":              "buy",      # "buy" | "hold" | "sell" | "skip"
            },
        },
        "filter_counts": {
            "blocked_min_score":     12,
            "blocked_min_core":       3,
            "blocked_max_bias5":      8,
            "blocked_max_daily_pct":  2,
            "blocked_already_held":   5,
            "blocked_limit_up":       1,
            "blocked_suspended":      0,
            "candidate_total":      200,
            "candidate_passed":     169,
        },
        "warnings":  [
            "missing PE for 600519.SH",
        ],
        "trigger_counts": {
            # 可观察哪些卖出理由被触发了多少次，方便 RS 排查
            "early_stop":     1,
            "early_kick":     0,
            "stop_loss":      2,
            "score_drop":     0,
            "replace":        1,
            "warning":        0,
            "confirm":        0,
        },
    },

    "logs": [
        # list[str]，每行一条人类可读日志；engine 会按行追加到 logs.txt，
        # 不需要时间戳前缀（engine 统一加），不需要 [INFO] 等级前缀
        "evaluate_day 2026-02-27 candidates=200 passed=169 sell=3 buy=2",
    ],
}
```

**约束：**

1. **6 个顶层 key 必须存在**（即使为空 list / 空 dict）。下游 engine / report 代码假设 key 存在。
2. **sell_decisions 优先级**：CLAUDE.md「底线清仓 > 确认卖出 > 预警卖出」对应 `priority` 字段，1 / 2 / 3 三档；`layer` 字段为可读字符串。引擎按 priority 升序执行。
3. **buy_candidates 排序**：调用方保证 `rank` 与列表顺序一致；engine 按列表顺序申购，资金不足时跳过后续。
4. **target_volume = 0 的语义**：strategy_core 不预先按 current_date close 折算股数（避免与 next_open 模型割裂），统一交给 engine 在撮合阶段按 `target_cash / 成交价` 向下取整 100 股。
5. **diagnostics.scores 的 code 集**：包含**所有进入打分流程**的 code（即 universe ∩ market_window 有数据的子集），不只 buy_candidates。这样 RS 可以审计任意股票的得分链路。
6. **logs 行格式**：`"<event> <key>=<val> ..."`（参考 SPEC §7.5 的 logs.txt 语法），便于 grep。但不强制结构化；strategy_core 写自由文本也可。

---

## 7. 卖出理由枚举（enums.py 中的常量字符串）

| 枚举值 | 含义 | 触发条件（v0.2 默认） | 优先级 layer | priority |
|---|---|---|---|---|
| `SELL_REASON_STOP_LOSS` | 底线清仓 | 持仓收益 ≤ `stop_loss`（默认 -0.08） | `bottom_line` | 1 |
| `SELL_REASON_EARLY_STOP` | 短期止损 | `holding_days >= early_stop_days(3)` 且收益 ≤ `early_stop_loss(-0.05)` | `bottom_line` | 1 |
| `SELL_REASON_EARLY_KICK` | 长期淘汰 | `holding_days >= early_stop_holding_days(5)` 且收益 < `early_stop_min_return(0.03)` | `confirm` | 2 |
| `SELL_REASON_REPLACE` | 换仓 | 持仓评分 vs 候选评分差 ≥ `score_gap_threshold(15)` 且候选可买 | `confirm` | 2 |
| `SELL_REASON_SCORE_DROP` | 评分掉档 | 持仓 score < `min_score`（且未触发更高优先级理由） | `warning` | 3 |
| `SELL_REASON_WARNING` | 预警层 | 持仓 score < `warning_score_threshold(50)`（CLAUDE.md：「预警层评分高于卖出阈值才执行」 反向解读：当 score 跌破阈值时，预警层才触发；高于阈值则不执行预警） | `warning` | 3 |
| `SELL_REASON_CONFIRM` | 确认卖出（保留） | 综合判定的强信号；v0.2 不主动产出，留作后续扩展 | `confirm` | 2 |

**约束：**

1. **OPEN_QUESTION（§9 OQ-C）**：v0.1 §3.3 列了 `confirm` 但没定义触发条件；CLAUDE.md 说「确认卖出」是优先级第 2 层。本文冻结时 **v0.2 不实现 `SELL_REASON_CONFIRM` 的触发器**，仅保留枚举值。Hermes 如希望 v0.2 实现，请在 §9 注明触发条件。
2. **layer 与 priority 的映射**固定不变；任何决策违反这个映射就需要重新冻结接口。
3. 多个理由同时满足时取**优先级最高**那条记录到 sell_decision，其他记到 `diagnostics.trigger_counts`。

---

## 8. blocked 原因枚举

| 枚举值 | 含义 | 触发条件 |
|---|---|---|
| `BLOCKED_MIN_SCORE` | 总分不足 | `score_total < min_score` |
| `BLOCKED_MIN_CORE` | 核心分不足 | 6 维核心子和 `< min_core` |
| `BLOCKED_MAX_BIAS5` | 5 日 bias 过高 | `bias5 > max_bias5` |
| `BLOCKED_MAX_DAILY_PCT` | 当日涨幅过高 | `daily_pct > max_daily_pct` |
| `BLOCKED_ALREADY_HELD` | 已持仓 | `code in {p["code"] for p in positions}` |
| `BLOCKED_LIMIT_UP` | 涨停（无法买入） | `daily_pct >= 9.95`（A 股 10% 涨停近似） |
| `BLOCKED_SUSPENDED` | 停牌 | market_window 中 current_date 无该 code 数据 |
| `BLOCKED_INSUFFICIENT_HISTORY` | 历史数据不足 | `len(market_window[code]) < 60` 无法跑 6+2 评分 |

**约束：**

1. **每只 universe 内 code 经过完整过滤链**：从 `BLOCKED_INSUFFICIENT_HISTORY` 一路过到 score 阈值，**先触发哪条算哪条**（短路），加入 `blocked_candidates` 列表。
2. `filter_counts` 计每条 blocked 多少次，便于 RS 调参（如发现 `blocked_already_held` 占比过高说明持仓过满）。
3. `BLOCKED_LIMIT_UP` 阈值 9.95 是近似（实际 A 股有 ST/科创板/北交所差异），v0.2 不展开，**OPEN_QUESTION（§9 OQ-D）**：是否按板块差异化？

---

## 9. OPEN_QUESTIONS（待 Hermes 决策，v0.2 冻结后不可改）

| # | 问题 | 当前 plan 默认 | 影响范围 | Hermes 决策 |
|---|---|---|---|---|
| OQ-A | early_stop（3 天 -5%）与 early_kick（5 天 < 3%）是**两条规则**还是**一条**？ | 按两条规则并存冻结（§4） | 多 2 个 strategy_config 字段 + 1 个枚举 | ☐ 两条 / ☐ 合并为一条 / ☐ 其他 |
| OQ-B | 6+2 scorer 输出字段是 `score_volumeprice`，本文冻结也用 `score_volumeprice`；但 SPEC v0.1 §3.4 写的是 `score_volume`。是否在 strategy_core 内部统一为 `score_volumeprice`？ | 冻结为 `score_volumeprice`（与 scorer 实际字段一致） | diagnostics / summary / report | ☐ score_volumeprice / ☐ score_volume / ☐ 双名兼容 |
| OQ-C | `SELL_REASON_CONFIRM` v0.2 是否实现触发条件？ | v0.2 仅保留枚举值，不触发 | strategy_core 决策层 | ☐ 不实现 / ☐ 给定触发条件 ___ |
| OQ-D | `BLOCKED_LIMIT_UP` 是否区分主板 / 创业板 / 科创板 / 北交所阈值（10% / 20% / 20% / 30%）？ | v0.2 用 9.95 单一阈值 | strategy_core 过滤层 | ☐ 不区分 / ☐ 区分（请给阈值表） |
| OQ-E | strategy_core 是否需要内部计算 fundamentals (PE/PB)？ | v0.2 不计算，aux_data["fundamentals"] = None；valuation 维度按 scorer 默认行为（缺失则给中性分） | scoring_adapter | ☐ 不计算 / ☐ 从 DuckDB 读 ___ 字段 |
| OQ-F | `target_volume` 由 strategy_core 折算还是 engine 折算？ | engine 折算（避免 next_open/close 模型割裂，§6 约束 4） | engine.execution / strategy_core.decision | ☐ engine（推荐） / ☐ strategy_core |

---

## 10. 与 SPEC v0.1 §3.3 的差异说明

本冻结版相对 SPEC v0.1 §3.3 的变更：

| 项 | v0.1 §3.3 | 本冻结版 v0.2 | 原因 |
|---|---|---|---|
| 卖出理由枚举 | `early_stop / stop_loss / score_drop / replace / bottom_line / warning / confirm`（7 项） | 拆为 `STOP_LOSS / EARLY_STOP / EARLY_KICK / REPLACE / SCORE_DROP / WARNING / CONFIRM`（7 项 + 拆分） | OQ-A 决议前并存 early_stop / early_kick；`bottom_line` 不再是 reason，下沉为 layer |
| sell_decision 字段 | 含 `code / action / target_volume / reason / layer / priority` | + `diagnostics_ref` | 方便回溯到 diagnostics.scores |
| diagnostics.scores 字段 | 列了 11 项 | 完全对齐 11 项；将 v0.1 的 `score_volume` 改为 `score_volumeprice` | 与 6+2 scorer 实际字段一致（OQ-B 待决） |
| account_state | v0.1 未明确 schema | 给定 7 字段（§3） | 引擎需要把 trading_day_index / total_asset 传给 strategy_core，否则 risk 判断会重复计算 |
| aux_data | v0.1 未明确 schema | 给定 6 字段（§5） | 收口缺失数据保护契约 |
| diagnostics.filter_counts | 未明确 key | 8 个固定 key + candidate_total / candidate_passed | RS 汇总用 |
| diagnostics.trigger_counts | v0.1 没有 | 新增 7 个 key | 方便观察哪些卖出理由被触发 |

其他字段（positions schema 8 字段、buy_candidates 8 字段、blocked_candidates 4 字段）与 v0.1 §3.3 一致。

---

## 11. 给后续 Phase 2 / Phase 3 / Phase 4 的引用约定

冻结后：

- Phase 2 实现的 `interface.py` `evaluate_day` 签名 / `enums.py` 常量名必须与本文 §1 / §7 / §8 完全一致。
- Phase 2.5 的输出 schema 冻结（GATE #2）将引用本文 §6 的 diagnostics / scores 字段名作为 summary.json `diagnostics` 子字段的来源。
- Phase 3 engine 在 `daily_engine.py` 主循环中按本文 §3 构造 `account_state`，按 §5 构造 `aux_data`。
- Phase 4 report 在 `summary.json` 中聚合本文 §6 的 `diagnostics.filter_counts / trigger_counts`，便于 RS 跨 run 对比。

---

## 12. 验收 / 签字栏

请 Hermes 在以下三项分别签字：

### 12.1 OPEN_QUESTIONS 决策（必填）

> 在 §9 表格的最后一列填 ☑ 选择项 + 必要补充说明。

### 12.2 接口字段同意

```
☐ §1 evaluate_day 签名 OK
☐ §2 positions 8 字段 OK
☐ §3 account_state 7 字段 OK
☐ §4 strategy_config 全字段 OK（含 OQ-A 决策后字段调整）
☐ §5 aux_data 6 字段 OK
☐ §6 StrategyDecision 6 顶层 key OK
☐ §7 卖出理由 7 枚举 OK（含 OQ-A / OQ-C 决策后枚举调整）
☐ §8 blocked 8 枚举 OK（含 OQ-D 决策后阈值表）
```

### 12.3 总决议

```
☐ 接口冻结通过，CC 可进入 Phase 2 实现
☐ 接口冻结需修订，修订点：______________________
```

签字：Hermes ___________
日期：__________________
