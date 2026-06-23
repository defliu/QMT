# 03 → 05 Interface Freeze v0.4（Phase 1 落地版）

**日期**: 2026-06-24
**承接**: `agent_hub/2026-06-13_backtest_mvp/03_interface_freeze.md`（v0.2/0.3 历史，仍作参考）
**适用范围**: 回测工厂 v0.4 Phase 1（commit b278d95 / af2a528 / 75df575 / MS-C）
**SPEC**: `specs/SPEC_BACKTEST_FACTORY_V0.4_GENERALIZATION_PHASE1.md`

---

## §1. evaluate_day 8 参签名（保持不变）

签名与参数名沿用 v0.3 frozen contract：

```python
def evaluate_day(
    current_date,
    market_window,
    positions,
    cash,
    universe,
    account_state,
    strategy_config,
    aux_data,
):
```

变化点：
- **不再硬 import** `from backtest.strategy_core.interface import evaluate_day`
- **新通过 registry 取**：`from backtest.strategies import get_strategy; evaluate_day = get_strategy("production/ima_uptrend_v31")`
- 旧路径仍可 import，但走 DeprecationWarning shim

---

## §2. StrategyDecision 顶层 6 键（保持不变）

```python
{
    "sell_decisions":     [...],
    "buy_candidates":     [...],
    "target_positions":   [...],
    "blocked_candidates": [...],
    "diagnostics":        {...},   # 子结构 §3
    "logs":               [...],
}
```

---

## §3. diagnostics 子结构（**v0.4 变更**）

通用字段提到 diagnostics 顶层；6+2 私有字段下沉到 `strategy_specific.ima_uptrend_v31.*`：

```python
{
    "warnings":         [str, ...],
    "candidate_total":  int,
    "candidate_passed": int,
    "strategy_specific": {
        "ima_uptrend_v31": {
            "scores":         { code: {...} },
            "filter_counts":  { 8 个 blocked_* counter -> int },
            "trigger_counts": { 7 个 trigger -> int },
        }
    },
}
```

取数请用辅助函数：

```python
from backtest.strategies import get_strategy_diag
fc = get_strategy_diag(decision, "production/ima_uptrend_v31", "filter_counts")
```

---

## §4. ALLOWED_TRADING_MODELS（新增）

每个策略在其 `strategy.py` 顶层声明：

```python
ALLOWED_TRADING_MODELS = ["next_open"]
```

`daily_engine.resolve_strategy()` 启动时校验 `config["trading_model"]` ∈ ALLOWED。不在列表内 → ValueError。

---

## §5. registry 命名空间约定

格式 `<category>/<strategy_id>`，category ∈ {`production`, `research`}。

当前注册策略（Phase 1）：
- `production/ima_uptrend_v31` —— 6+2 主升浪 reference strategy

---

## §6. 一致性验证（MS-C 已通过）

|  | v0.3 master (6ff89f6) | v0.4 phase1 (commit 75df575+) |
|---|---|---|
| trades.csv | a7fc0b3fb026 | a7fc0b3fb026 |
| equity_curve.csv | 95cac56f0d21 | 95cac56f0d21 |
| positions.csv | cf926528433c | cf926528433c |

详细 log 见 `_msc_sha_compare.log` + `_msc_v03_run.log` / `_msc_v04_run.log`。

---

## §7. Phase 2+ 预留

事件研究、因子 IC、yaml-DSL 等 → Phase 2+。本 freeze 仅锁 Phase 1 边界。
