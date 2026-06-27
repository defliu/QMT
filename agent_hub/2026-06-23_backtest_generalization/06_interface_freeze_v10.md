# 06 — 回测工厂 V1.0 接口冻结文档(L2 重冻结 + L3 扩展)

**版本**: v1.0
**日期**: 2026-06-27
**作者**: CC
**状态**: 起草待诚哥签字(或 CC 代签 + 诚哥追认,沿用 v0.4 夜班授权)
**承接**: `05_interface_freeze_v04.md`(v0.4 freeze)
**对应 SPEC**: `specs/SPEC_BACKTEST_FACTORY_V1.0_REFACTOR.md`(§6 Phase 1)

---

## §0 文档定位

本文件是 V1.0 重构的**契约门禁**(GATE),对应 Phase 1。承接 v0.4 的 05 freeze,做两件事:

1. **L2 重冻结**:补登 v0.4 静默打破的 `diagnostics_aggregate` schema(顶层 trigger_counts/filter_counts 已下沉到 strategy_specific,V1.0 正式承认)
2. **L3 扩展**:新增 paradigm 接口位(预留)+ registry 自动扫描契约

**红线**:L1(`03_interface_freeze.md` 的 evaluate_day 8 参 + StrategyDecision 6 顶层键)**V1.0 不动**。

---

## §1 L1 — evaluate_day 8 参签名(V1.0 不变)

沿用 v0.3/v0.4,不调整:

```python
def evaluate_day(current_date, market_window, positions, cash,
                 universe, account_state, strategy_config, aux_data):
```

- 纯函数(相同入参同结果)
- 禁 import xtquant/passorder/ContextInfo
- Python 3.6-safe(禁 dict[str,...] / str|None / walrus / match-case / dataclass)—— 注:V1.0 工厂本体可用现代 Python(Round 4 §7),但 evaluate_day 策略接口仍守 3.6-safe 以兼容 QMT 策略复用
- 不 IO 不写文件不联网

**V1.0 状态**:不变,红线。

---

## §2 L1 — StrategyDecision 6 顶层键(V1.0 不变)

```
sell_decisions / buy_candidates / target_positions /
blocked_candidates / diagnostics / logs
```

**V1.0 状态**:不变,红线。

---

## §3 L2 — diagnostics 子结构(V1.0 重冻结,v0.4 已既成事实)

### v0.4 前形态(L1 03 freeze,扁平)

```python
diagnostics:
  scores: {}                  # 6+2 打分字典
  filter_counts: {10 个 6+2 专用 counter}
  warnings: []
  trigger_counts: {7 个 6+2 trigger}
```

### v0.4 形态(05 freeze,namespace 化,已落地)

```python
diagnostics:
  warnings: [str, ...]
  candidate_total: int
  candidate_passed: int
  strategy_specific:
    ima_uptrend_v31:
      scores: {}
      filter_counts: {8 blocked_*}
      trigger_counts: {7 trigger}
```

### V1.0 形态(本 freeze 重冻结)

```python
diagnostics:
  warnings: [str, ...]
  candidate_total: int
  candidate_passed: int
  strategy_specific:
    <strategy_namespace>:       # 任意策略,引擎不认特定名字
      <自由定义>                # 引擎按值类型聚合,不做语义假设
```

**变更要点**:
- 通用字段 `warnings`/`candidate_total`/`candidate_passed` 提顶(v0.4 已做,V1.0 确认)
- `strategy_specific.{name}` 内部结构**完全自由**,引擎不认 `ima_uptrend_v31` 或任何特定 namespace
- **去掉 v0.4 的 trigger_counts 特例**(`daily_engine.py` L226-229):引擎不再对 `trigger_counts` 做"乘回 n_days 取整 + 改名 _total"的语义假设

---

## §4 L2 — diagnostics_aggregate V1.0 目标 schema(重冻结核心)

### v0.4 前(L2 04 freeze §1.5,已过时)

```json
{
  "diagnostics_aggregate": {
    "trigger_counts_total": {7 key},        # 顶层,6+2 专有
    "filter_counts_avg_per_day": {10 key},  # 顶层,6+2 专有
    "warnings_unique": [...],
    "unfilled_order_count": int
  }
}
```

### v0.4 实际产出(已静默打破 L2,未走重冻结)

```json
{
  "diagnostics_aggregate": {
    "warnings_unique": [...],
    "candidate_total_avg_per_day": float,
    "candidate_passed_avg_per_day": float,
    "unfilled_order_count": int,
    "strategy_specific": {
      "ima_uptrend_v31": {
        "trigger_counts_total": {...},
        "filter_counts_avg_per_day": {...}
      }
    }
  }
}
```

### V1.0 重冻结(本 freeze 正式承认 + 通用化)

```json
{
  "diagnostics_aggregate": {
    "warnings_unique": [str, ...],
    "candidate_total_avg_per_day": float,
    "candidate_passed_avg_per_day": float,
    "unfilled_order_count": int,
    "strategy_specific": {
      "<strategy_namespace>": {
        "<number_dict_key>_avg_per_day": {key: float, ...},
        "<other_key>_present": bool
      }
    }
  }
}
```

**重冻结决策**:
1. **删除** L2(04 §1.5)顶层 `trigger_counts_total` / `filter_counts_avg_per_day` —— v0.4 已下沉到 strategy_specific,V1.0 正式承认
2. 引擎按值类型聚合:`dict[str,number]` → `{key}_avg_per_day`;其他类型 → `{key}_present`
3. 策略想要 total → 自己在 namespace 声明 `{key}_total` 后缀键(策略侧职责,非引擎)
4. **引擎不对策略私有字段做语义假设**(去掉 trigger_counts 特例)

**这是 L2 的破坏性变更,走 GATE**:本 freeze 经诚哥签字即生效。属"承认既成事实"(v0.4 已下沉),非新破坏。

---

## §5 L3 — registry 契约(V1.0 扩展)

### v0.4 形态(05 freeze,已落地)

- `register_strategy(name)` 装饰器 + `_REGISTRY` 全局 dict
- `get_strategy(name)` / `list_strategies()` / `get_strategy_diag(decision, strategy_name, key)`
- 命名空间:`<category>/<strategy_id>`,category ∈ {production, research}
- 启动 import:手写三个 import(`strategies/__init__.py` L50-53)

### V1.0 扩展

1. **自动扫描**:删手写 import,改 `pkgutil.iter_modules` 自动发现 `production/` 和 `research/` 下的策略包
   ```python
   def _autodiscover():
       for cat in ("production", "research"):
           pkg = importlib.import_module("backtest.strategies." + cat)
           for _, modname, ispkg in pkgutil.iter_modules(pkg.__path__):
               if ispkg:
                   importlib.import_module(
                       "backtest.strategies.%s.%s.strategy" % (cat, modname))
   _autodiscover()
   ```
   - 约束:只扫 `ispkg=True` 的子包,防 `__pycache__` 误 import
   - 不引 entry_points/pluggy

2. **`config_schema(strategy_name)` 新增**(Hermes 接口):
   - 策略在 strategy.py 顶层声明 `STRATEGY_PARAM_SCHEMA = {...}`(手写 dict)
   - `config_schema(name)` 从模块读常量,返回字段 schema
   - 策略未声明 → 返回 `{"error": "no schema declared", "strategy": name}`(不抛异常)

3. **namespace key 规则不变**:`get_strategy_diag` 用 `strategy_name.split("/")[-1]` 取末段

---

## §6 L3 — paradigm 接口位(V1.0 预留,决策点)

**推荐方案(更简单)**:V1.0 不引入 paradigm registry 第二级,只留 event_study 函数签名 stub:

```python
def run_event_study(reader, events, label_windows, **kwargs):
    """event_study stub. V1.0 不实现,完整实现后置 Phase 2+。
    see SPEC_BACKTEST_FACTORY_V1.0_REFACTOR.md §12"""
    raise NotImplementedError("event_study paradigm: V1.0 stub, see SPEC §12")
```

**备选方案**:引入 `backtest/paradigms/__init__.py` 第二级注册 `register_paradigm("portfolio"/"event_study")`。若诚哥选此,V1.0 注册 portfolio(包装现有 DailyBacktestEngine)+ event_study stub runner。

**V1.0 默认采用推荐方案**,除非诚哥拍板选备选。

---

## §7 一致性验证基线(V1.0 回归门槛)

任何触碰 engine/数据路径的改动,必须过:

- `p2_core100.yaml` 迁移前后,`_compare_sha256.py` 对 trades/equity/positions 业务列 sha256 **bit-identical**(剥除 run_id)
- summary.json `performance` 四指标(total_return/annualized_return/sharpe/max_drawdown)容差 0
- `diagnostics_aggregate` **允许结构差异**(本 freeze 批准的 L2 破坏),验收单独标注"允许差异项"

v0.4 MS-C 一致性基线(参考):trades/equity/positions sha256 在 v0.3 master (6ff89f6) vs v0.4 phase1 (75df575+) 完全一致。

---

## §8 git tag(回滚锚点)

本 freeze 经诚哥签字后打:
- `tag: freeze-v1.0-L2`
- `tag: freeze-v1.0-L3`

回滚:一致性 diff 不通过 → `git reset --hard` 到 tag 前,本 freeze 作废,回 v0.4 状态。

---

## 附录 C:三层 freeze 变更对照表

| 层 | 文档 | 字段/契约 | v0.4 状态 | V1.0 变更 | 理由 |
|---|---|---|---|---|---|
| L1 | 03_interface_freeze.md | evaluate_day 8 参签名 | 不变 | **不变** | 红线,任何变更需重跑完整 GATE |
| L1 | 03_interface_freeze.md | StrategyDecision 6 顶层键 | 不变 | **不变** | 红线 |
| L1 | 03_interface_freeze.md | positions/account_state/strategy_config/aux_data 子结构 | 不变 | **不变** | 红线 |
| L1 | 03_interface_freeze.md | 7 sell reason 枚举 + layer/priority | 不变 | **不变** | 6+2 语义,reference strategy 保留 |
| L1 | 03_interface_freeze.md | 8 blocked 枚举 | 不变 | **不变** | 6+2 语义,reference strategy 保留 |
| L2 | 04_output_schema_freeze.md | summary.json 23 顶层字段 | 不变 | **不变** | 通用字段不动 |
| L2 | 04_output_schema_freeze.md | trades.csv 13 列 | 不变 | **不变** | — |
| L2 | 04_output_schema_freeze.md | equity_curve.csv 8 列 | 不变 | **不变** | — |
| L2 | 04_output_schema_freeze.md | positions.csv 9 列 | 不变 | **不变** | — |
| L2 | 04_output_schema_freeze.md | logs.txt WARN 块 | 不变 | **不变** | — |
| L2 | 04_output_schema_freeze.md | report.md 段落 | 不变 | **不变** | — |
| L2 | 04_output_schema_freeze.md | `diagnostics_aggregate` 顶层 `trigger_counts_total` | v0.4 已静默下沉 | **删除(重冻结承认)** | v0.4 既成事实,下沉到 strategy_specific |
| L2 | 04_output_schema_freeze.md | `diagnostics_aggregate` 顶层 `filter_counts_avg_per_day` | v0.4 已静默下沉 | **删除(重冻结承认)** | 同上 |
| L2 | 04_output_schema_freeze.md | `diagnostics_aggregate.strategy_specific.{name}` | v0.4 新增 | **通用化(去 trigger_counts 特例)** | 引擎不认特定 namespace,按值类型聚合 |
| L3 | 05_interface_freeze_v04.md | registry 装饰器/get/list/get_diag | 已落地 | **不变** | — |
| L3 | 05_interface_freeze_v04.md | 命名空间 `<category>/<id>` | 已落地 | **不变** | — |
| L3 | 05_interface_freeze_v04.md | ALLOWED_TRADING_MODELS 校验 | 已落地 | **不变**(永远只 next_open) | trading_model 扩展永久不做 |
| L3 | 05_interface_freeze_v04.md | registry 启动 import | 手写三个 | **改自动扫描** | onboarding 痛点,加策略不改 __init__ |
| L3 | 本 freeze(新) | `config_schema(name)` 接口 | 不存在 | **新增** | Hermes/RS 配置校验 |
| L3 | 本 freeze(新) | `run_event_study` stub 签名 | 不存在 | **新增(预留)** | event_study 范式接口位 |

---

## 附录 D: Reference Coupling Pattern(huang_zhongjun_combo 反例)

V1.0 Phase 4 (D9) 记录 huang_zhongjun_combo 策略的 namespace 改名模式,作为反例:

**原始模式**: `huang_main_uptrend_combo/strategy.py` 在 `score_universe()` 返回的 `ss` dict 中:
```python
ss.pop("ima_uptrend_v31")        # 删除原始 key
ss["huang_zhongjun_combo"] = ... # 用自己 namespace 重写
```

**问题**:这是对 `score_universe` 内部 namespace 的**运行时耦合**。如果 `ima_uptrend_v31` 改名或评分器重构,该策略静默失败。

**建议**:不正规化,记为反例。新策略不抄此模式。复用 6+2 评分应直接 import `score_universe` / `make_decision`,在自己 namespace 下独立产出,不做 namespace 改名。

---

## 签字栏

| 角色 | 状态 | 日期 |
|---|---|---|
| CC 起草 | ✅ 完成 | 2026-06-27 |
| 诚哥签字 | ⏳ 待签(或 CC 代签+追认) | — |
| git tag | ⏳ 签字后打 freeze-v1.0-L2 / freeze-v1.0-L3 | — |

---

*本 freeze 是 V1.0 重构 Phase 1 的 GATE 产物。L2 重冻结属"承认 v0.4 既成事实",非新破坏。签字后 Phase 2-4 按本 freeze 实施。*
