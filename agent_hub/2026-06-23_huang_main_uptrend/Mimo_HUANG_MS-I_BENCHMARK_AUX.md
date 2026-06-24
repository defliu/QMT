# MIMO 工单：MS-I —— daily_engine 注入 benchmark_window 到 aux_data

## 背景

回测工厂 v0.4 准备接 `research/huang_zhongjun_combo` 策略。zhongjun_XG 信号有一个硬依赖：**大盘指数日 K 用于判断 close>MA20>MA60**（黄氏 SPEC v1.2 §B "大盘环境过滤"）。

工厂当前 (commit `78958e6` 之后 + MS-G/H 已合) 的 aux_data 注入逻辑只塞了 `trading_calendar`，benchmark 日 K 虽然加载了 (`_load_benchmark_series` 在 `daily_engine.py:44-102`) 但只用于业绩对照 (`equity_rows[i].benchmark_close`)，**没有暴露给 evaluate_day**。

本工单 = 把已加载的 `benchmark_closes` 字典（forward-filled, `{date_str: close}`）通过 `aux_for_eval["benchmark_closes"]` 暴露给 evaluate_day，**完全不改 schema、不动 strategy_core 任何文件、对现有所有策略 transparent**（aux_data 是 dict，新增 key 不会影响 6+2 的 ima_uptrend_v31）。

**当前 HEAD**：`063511d` (fix(huang_combo): 聚宽 Part-JQ-C v2)
**预计工时**：15 分钟
**MIMO 模型**：mimo-auto

---

## 一、必做（6 步）

### TASK-0. 时间戳

```bash
date -u +"%Y-%m-%dT%H:%M:%SZ"
```

### TASK-1. 预检（目标文件粒度）

```bash
cd D:/QMT_STRATEGIES
git status --short backtest/engine/daily_engine.py
git status --short backtest/tests/
git log -1 --oneline backtest/engine/daily_engine.py
```

期望：
- `daily_engine.py` 无 dirty 行（`git status --short` 无输出）
- `tests/` 目录无 dirty
- 最近 commit 是 `6b37105` ([MS-G] fix(backtest/v0.4): daily_engine diagnostics 聚合 namespace 通用化)

**目标文件已被改动 → 停**。把输出贴回执。

### TASK-2. 改 `backtest/engine/daily_engine.py`

定位（精确字符串，在第 308-311 行附近）：

```python
    aux_for_eval = aux_data if aux_data is not None else {}
    if "trading_calendar" not in aux_for_eval or not aux_for_eval.get("trading_calendar"):
        aux_for_eval = dict(aux_for_eval)
        aux_for_eval["trading_calendar"] = calendar
```

替换为：

```python
    aux_for_eval = aux_data if aux_data is not None else {}
    if "trading_calendar" not in aux_for_eval or not aux_for_eval.get("trading_calendar"):
        aux_for_eval = dict(aux_for_eval)
        aux_for_eval["trading_calendar"] = calendar
    # MS-I: 暴露 benchmark close 序列给 evaluate_day（zhongjun 等策略大盘条件依赖）。
    # benchmark_closes 是 forward-filled dict {date_str: close}，evaluate_day 自己切窗口。
    # 未启用 benchmark 时 (benchmark_code=null 或加载失败) 该 key 为 None。
    if "benchmark_closes" not in aux_for_eval:
        aux_for_eval = dict(aux_for_eval)
        aux_for_eval["benchmark_closes"] = benchmark_closes
        aux_for_eval["benchmark_code"] = benchmark_code
```

**注意**：
- 上面块**追加在**已有 trading_calendar 注入逻辑之后，**不要替换** trading_calendar 块
- 两个 `dict(aux_for_eval)` 都保留（每个 if 独立 copy 一次是为了避免 mutate 调用方传入的 dict，与现有约束一致）
- 不要改 `benchmark_closes` 加载逻辑、不要改 equity_rows 那段（第 444 行起的 benchmark fill 仍然走 `benchmark_closes` 局部变量）

### TASK-3. 新增测试 `backtest/tests/test_aux_data_benchmark.py`

测试桩思路 = 抄 `backtest/tests/test_daily_engine.py` 的 `FakeReader` + `_build_market` + `_cfg` 模板（确认存在），用 `register_strategy("_spy/benchmark_test")` 装饰器注册一个 spy evaluate_day 抓 aux_data，调 `daily_engine.run_backtest` 跑 1 个日 K 即可。**绝不**走 yaml / `_load_yaml` 那一套，直接调引擎层。

新建文件：

```python
# coding: utf-8
"""验证 MS-I: daily_engine 注入 benchmark_closes / benchmark_code 到 aux_data。"""
import pandas as pd
import pytest

from backtest.strategies import register_strategy
from backtest.engine.daily_engine import run_backtest


# spy strategy: 抓 aux_data 到模块级变量
_CAPTURED = {}


@register_strategy("_spy/benchmark_test")
def _spy_evaluate_day(current_date, market_window, positions, cash, universe,
                     account_state, strategy_config, aux_data):
    _CAPTURED["last_aux"] = aux_data
    return {
        "sell_decisions": [],
        "buy_candidates": [],
        "target_positions": [],
        "blocked_candidates": [],
        "diagnostics": {
            "warnings": [],
            "candidate_total": 0,
            "candidate_passed": 0,
            "strategy_specific": {"benchmark_test": {}},
        },
        "logs": [],
    }


# spy 的 ALLOWED_TRADING_MODELS:
# resolve_strategy 按 strategy_name 反推 module path
# backtest.strategies._spy.benchmark_test.strategy → ImportError →
# fallback 到 ["next_open"] (daily_engine.py:241-243), 正好满足。
# 因此 spy 不需要显式设置 ALLOWED_TRADING_MODELS。


class _FakeReader(object):
    """最小 FakeReader, 抄自 test_daily_engine.py。"""
    def __init__(self, market, calendar):
        self.market = market
        self.calendar = calendar
        self.db_path = "fake.duckdb"
        self._db_mtime = "2026-06-24T00:00:00"
        self.wal_detected = False
        self.wal_warning_message = ""

    def coverage(self, codes=None, start_date=None, end_date=None):
        return {
            "min_date":           self.calendar[0],
            "max_date":           self.calendar[-1],
            "n_codes":            len(self.market),
            "n_rows_after_dedup": sum(len(df) for df in self.market.values()),
            "dedup_count":        0,
            "db_mtime":           self._db_mtime,
            "universe_coverage": {
                "universe_size":   len(codes or []),
                "codes_with_data": len(self.market),
                "codes_missing":   [],
                "missing_count":   0,
            },
        }

    def trading_calendar(self, start_date, end_date):
        return list(self.calendar)

    def load_window(self, codes, start_date, end_date):
        return {c: self.market[c] for c in codes if c in self.market}


def _build_simple_market():
    dates = ["2025-09-02", "2025-09-03", "2025-09-04", "2025-09-05"]
    df = pd.DataFrame({
        "date":   dates,
        "open":   [10.0, 10.1, 10.2, 10.3],
        "high":   [10.1, 10.2, 10.3, 10.4],
        "low":    [9.9, 10.0, 10.1, 10.2],
        "close":  [10.05, 10.15, 10.25, 10.35],
        "vol":    [10000, 11000, 12000, 13000],
        "amount": [100500.0, 111650.0, 123000.0, 134550.0],
    })
    return {"000001.SZ": df}, dates


_EXEC = {"price": "next_open", "slippage": 0.001,
         "commission_rate": 0.00025, "tax_rate": 0.0001}

_CFG = {"max_positions": 3, "rebalance_policy": "daily",
        "min_score": 0.0, "min_core": 0.0, "max_bias5": 100.0,
        "max_daily_pct": 9.0, "sector_heat_mode": "zero",
        "score_gap_threshold": 15.0,
        "early_stop_days": 3, "early_stop_loss": -0.05,
        "stop_loss": -0.08, "warning_score_threshold": 50.0,
        "early_stop_holding_days": 5, "early_stop_min_return": 0.03}


@pytest.fixture(autouse=True)
def _reset():
    _CAPTURED.clear()
    yield
    _CAPTURED.clear()


def test_aux_data_has_benchmark_keys_when_disabled():
    """benchmark_code=None 时 benchmark_closes 必须存在且为 None。"""
    market, dates = _build_simple_market()
    reader = _FakeReader(market, dates)
    run_backtest(
        reader=reader, universe=["000001.SZ"],
        start_date=dates[0], end_date=dates[-1],
        strategy_config=_CFG, execution_cfg=_EXEC,
        initial_cash=1_000_000.0, config_name="ms_i_test",
        universe_hash="ufake", config_hash="cfake",
        strategy_name="_spy/benchmark_test",
        trading_model="next_open",
        benchmark_code=None,
    )
    aux = _CAPTURED.get("last_aux", {})
    assert "benchmark_closes" in aux, "MS-I 未注入 benchmark_closes key"
    assert "benchmark_code" in aux, "MS-I 未注入 benchmark_code key"
    assert aux["benchmark_closes"] is None
    assert aux["benchmark_code"] is None


def test_trading_calendar_still_present_regression():
    """回归：trading_calendar 注入逻辑没被破坏。"""
    market, dates = _build_simple_market()
    reader = _FakeReader(market, dates)
    run_backtest(
        reader=reader, universe=["000001.SZ"],
        start_date=dates[0], end_date=dates[-1],
        strategy_config=_CFG, execution_cfg=_EXEC,
        initial_cash=1_000_000.0, config_name="ms_i_test",
        universe_hash="ufake", config_hash="cfake",
        strategy_name="_spy/benchmark_test",
        trading_model="next_open",
    )
    aux = _CAPTURED.get("last_aux", {})
    assert "trading_calendar" in aux
    assert aux["trading_calendar"] == dates
```

**注意**：
- `register_strategy` 是装饰器，在文件 import 时（pytest collect 阶段）注册 spy；测试目录在工厂的 import 链外，但 spy 用的 namespace `_spy/` 是预留前缀，不会跟 production/research 冲突
- spy 的 `ALLOWED_TRADING_MODELS` 不用显式设：`resolve_strategy` 在 `daily_engine.py:238-243` 按 strategy_name 反推 module path 找属性，找不到自动 fallback 到 `["next_open"]`，正好满足
- 不需要真 DuckDB，FakeReader 直接拼 in-memory DataFrame
- benchmark 启用路径不测：DuckDB benchmark_index 是 F 盘真实数据，单测里 fake 一份成本高且不是 MS-I 的核心断言；**docstring 注释说明"benchmark 启用路径由 e2e_pipeline 测试覆盖"** 即可

> **若注册装饰器跑两遍报 `KeyError: strategy already registered`** （pytest 多文件 import 同名 spy）→ 在装饰器前加 `if "_spy/benchmark_test" not in list_strategies():` 守卫；**仍跑不通**则停下贴 traceback，**不要**改 strategies/__init__.py 任何东西。

### TASK-4. 跑测试

```bash
cd D:/QMT_STRATEGIES
py -3.10 -m pytest backtest/tests/test_aux_data_benchmark.py -v
py -3.10 -m pytest backtest/tests/ --tb=line | tail -5
```

期望：
- 新测试 PASS
- 全量 0 failed（warning 不算 fail，但要在回执汇报数量和类型，遵循 [[feedback-report-warning-categories]]）

**FAIL → 停**。

### TASK-5. 精确 add + commit（3 文件）

```bash
cd D:/QMT_STRATEGIES
git add backtest/engine/daily_engine.py
git add backtest/tests/test_aux_data_benchmark.py
git add agent_hub/2026-06-23_huang_main_uptrend/Mimo_HUANG_MS-I_BENCHMARK_AUX.md

git diff --cached --name-only
```

**期望恰好 3 行**。staged ≠ 3 → 停。

```bash
git commit -m "$(cat <<'EOF'
[MS-I] feat(backtest/v0.4): daily_engine 注入 benchmark_closes 到 aux_data

为后续 research/huang_zhongjun_combo 策略接入做准备。zhongjun 信号判
大盘 close>MA20>MA60，需要在 evaluate_day 内拿到指数日 K。

工厂当前已加载 benchmark_closes (forward-filled dict)，仅用于业绩对照
equity_rows.benchmark_close，未暴露给策略。本 commit 仅追加 2 行到
aux_for_eval：

  aux_for_eval["benchmark_closes"] = benchmark_closes  # {date_str: close} 或 None
  aux_for_eval["benchmark_code"]   = benchmark_code    # str 或 None

零破坏：
- aux_data 是 dict，新增 key 不影响 ima_uptrend_v31 的 score_universe
- benchmark 未启用 (yaml benchmark_code=null) 时两个 key 都是 None，
  策略自己判 None 跳过大盘条件 (degrade gracefully)
- trading_calendar 注入逻辑不变 (回归测试覆盖)

新增测试 backtest/tests/test_aux_data_benchmark.py 覆盖:
1. benchmark_code=null 时 aux_data["benchmark_closes"] is None
2. trading_calendar 仍然存在 (回归)

Refs:
- v0.4 接口冻结 03_interface_freeze.md §5: aux_data 是 dict, key 可增量
- 黄氏 SPEC v1.2 §B: 大盘 close>MA20>MA60
- 下游工单: Mimo_HUANG_ZJ_V04 (待派)
EOF
)"

git log -1 --stat HEAD
```

---

## 二、严禁

1. **严禁** `git add .` / `git add -A` / `git add backtest/`
2. **严禁** push / amend / --no-verify
3. **严禁** 改 `_load_benchmark_series` / equity_rows 那段 benchmark fill 逻辑
4. **严禁** 改 strategy_core / strategies/production / strategies/research 任何文件
5. **严禁** 改 reader / portfolio / execution / report
6. **严禁** 删除 / 重命名 trading_calendar 注入逻辑
7. **严禁** 把 benchmark_closes 重命名（zhongjun 工单已经约定靠这个 key 拿数据）
8. **严禁** 用 placeholder 时间戳

## 三、停手条件

- TASK-1 daily_engine.py 已被改动 → 停（**先 `git diff backtest/engine/daily_engine.py` 看现状**，可能是诚哥手动改了，不能自动覆盖）
- TASK-2 定位字符串非唯一或匹配不到 → 停（说明文件已变，需要重新对齐）
- TASK-3 测试桩复杂度 > 30 分钟 → 停，回执说明走简化测试方案的想法
- TASK-4 任一测试 FAIL → 停
- staged ≠ 3 → 停

遇异常**必停**贴回执，**不得自判"无关"继续**（[[mimo-must-stop-on-any-failure]]）。

---

## 四、完成回执

在 EOF 后追加：

```markdown

---

## 完成回执

**执行时间**: <真实 date -u 输出>
**MIMO 模型**: <实际名>

### TASK-0: 真实时间戳
### TASK-1: 预检
<贴 git status / git log -1 输出>

### TASK-2: daily_engine.py 修改
<贴 git diff 的关键 hunk>

### TASK-3: test_aux_data_benchmark.py
<贴文件 LOC + 说明用了哪种测试桩方案>

### TASK-4: 测试结果
<贴 pytest 输出 + 全量统计>
- 新测试: <PASS/FAIL 数>
- 全量: <passed/failed/warnings 数>
- warning 类型: <分类汇总，遵循 feedback-report-warning-categories>

### TASK-5: git diff + commit
<贴 3 行 + git log -1 --stat>

### 自检
- [ ] 时间戳真跑 date
- [ ] daily_engine.py 仅追加，未替换 trading_calendar 块
- [ ] _load_benchmark_series / equity_rows 未改
- [ ] strategy_core / strategies/ 任何文件未改
- [ ] 新测试 PASS
- [ ] 全量 0 failed
- [ ] staged 恰好 3 个文件
- [ ] commit 成功
- [ ] 回执在 EOF 追加
```
