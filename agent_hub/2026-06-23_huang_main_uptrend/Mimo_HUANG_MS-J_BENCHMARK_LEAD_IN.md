# MIMO 工单：MS-J —— benchmark lead-in fix（修 _load_benchmark_series 没带历史数据导致策略 MA60/MA20 失效）

## 背景

`research/huang_zhongjun_combo` smoke run（commit `18e5975`）跑出 **0 成交**。

根因诊断 by CC：MS-I 通路本身没问题，但 `daily_engine.py::_load_benchmark_series` 把 `load_series` 的 start_date 直接设成 `calendar[0]`，**没有任何 lead-in**。

实测验证：smoke window `2025-09-02 ~ 2025-12-31`（81 个交易日）：

| 大盘条件 | engine 实际灌的 bench 序列 | 正确情形（带 60 天 lead-in） |
|---|---|---|
| `close>MA20>MA60` 命中天数 | **1/81 (1.2%)** | **41/81 (50.6%)** |
| `bench_ok` 首次=True 的日期 | 2025-12-08（第 64 个交易日，刚好凑够 60 根 MA60） | 应该 2025-09-02 当天就有可能 True |

黄氏策略 `_benchmark_ok` 要求 `len(bench_series) >= 60`，前 60 天因 bench 序列不足直接被裁掉 → 整个 9-11 月几乎不可能触发任何 zhongjun_XG → 0 成交。

**这是引擎工程 bug，不是策略业务问题。** 修完之后才能讨论"是否进一步放宽大盘条件"。

**当前 HEAD**：`18e5975` (feat(huang_combo): research/huang_zhongjun_combo 接入回测工厂 v0.4)
**预计工时**：30 分钟
**MIMO 模型**：mimo-auto

---

## 一、设计概览

修 `daily_engine.py::_load_benchmark_series`：

1. `load_series` 的 start_date 从 `calendar[0]` 改为"calendar[0] 往前推 N 个自然日"，N=120（足以覆盖 MA120 等长窗口指标）
2. `closes` 字典扩成 **bm_map ∪ calendar forward-fill**，即：
   - bm_map 里所有 `date <= calendar[-1]` 的 (date, close) 都进 closes（暴露 lead-in 给 evaluate_day）
   - calendar 内的天数仍走原有 forward-fill 逻辑（保证 equity_curve.benchmark_close 对齐）
3. head_gap 处理逻辑（calendar 起点早于 bench 首条的 14 天容忍）**保留不动**

equity_curve 路径 `daily_engine.py:444-466` 用 `benchmark_closes.get(row["date"])` 查 calendar 内的 key，**对 extra lead-in key 透明**——零破坏。

零业务影响：
- 现有任何**不读 aux_data["benchmark_closes"]** 的策略：行为完全不变
- 黄氏 zhongjun：bench_series 现在能拿到 lead-in，`_benchmark_ok` 能正常工作
- ima_uptrend_v31：不读 benchmark_closes，零影响

---

## 二、必做（6 步）

### TASK-0. 时间戳

```bash
date -u +"%Y-%m-%dT%H:%M:%SZ"
```

### TASK-1. 预检

```bash
cd D:/QMT_STRATEGIES
git status --short backtest/engine/daily_engine.py
git status --short backtest/tests/
git log -1 --oneline backtest/engine/daily_engine.py
git log -1 --oneline
```

期望：
- `daily_engine.py` 无 dirty
- `tests/` 无 dirty
- daily_engine.py 最近 commit: `4253605` (MS-I)
- 全局 HEAD: `18e5975` (HUANG-ZJ-V04)

异常 → 停，贴输出。

### TASK-2. 改 `backtest/engine/daily_engine.py`

#### 2.1 在文件顶部 import 区附近找现有的常量定义区域

定位（精确字符串，约在第 38-42 行）：

```python
_STRATEGY_CORE_VERSION = "0.2.0"
_SUMMARY_SCHEMA_VERSION = "0.2"

DEFAULT_BENCHMARK_DB = "F:/backtest_workspace/data/duckdb/benchmark_index.duckdb"
```

替换为：

```python
_STRATEGY_CORE_VERSION = "0.2.0"
_SUMMARY_SCHEMA_VERSION = "0.2"

DEFAULT_BENCHMARK_DB = "F:/backtest_workspace/data/duckdb/benchmark_index.duckdb"

# MS-J: benchmark 序列往前多取 N 个自然日的 lead-in，让策略侧 evaluate_day
# 拿到的 bench 序列足以算 MA60 / MA120 等长窗口指标。
# 120 天 ≈ 6 个月日 K，覆盖黄氏 MA120 + 留 30 天余量。
_BENCHMARK_LEAD_IN_DAYS = 120
```

#### 2.2 改 `_load_benchmark_series` 内部

定位（精确字符串，约在第 57-66 行附近）：

```python
    try:
        from backtest.data_tools.benchmark_reader import BenchmarkIndexReader
        br = BenchmarkIndexReader(benchmark_db_path)
        try:
            # Pull a small lead-in window so we can forward-fill the first day
            # if the calendar's first date predates the first benchmark bar.
            rows = br.load_series(benchmark_code, calendar[0], calendar[-1])
        finally:
            br.close()
    except Exception as e:
        return None, u"benchmark 加载失败: %s" % e
```

替换为：

```python
    # MS-J: 往前推 _BENCHMARK_LEAD_IN_DAYS 自然日, 让策略侧拿到足够 lead-in
    # 算 MA60/MA120 等长窗口指标 (HUANG-ZJ-V04 smoke 0 成交 root cause)。
    import datetime as _dt2
    try:
        _cal0 = _dt2.datetime.strptime(calendar[0], "%Y-%m-%d").date()
    except Exception:
        _cal0 = None
    if _cal0 is not None:
        _bench_start = (_cal0 - _dt2.timedelta(days=_BENCHMARK_LEAD_IN_DAYS)).strftime("%Y-%m-%d")
    else:
        _bench_start = calendar[0]
    try:
        from backtest.data_tools.benchmark_reader import BenchmarkIndexReader
        br = BenchmarkIndexReader(benchmark_db_path)
        try:
            rows = br.load_series(benchmark_code, _bench_start, calendar[-1])
        finally:
            br.close()
    except Exception as e:
        return None, u"benchmark 加载失败: %s" % e
```

**注意**：
- `import datetime as _dt2` 是本函数局部 import，**避免**与文件顶部已有 `import datetime as _dt`（第 26 行）的命名冲突；不要去删顶部那个 import
- `calendar[0]` 解析失败时退化到原行为（保险，单测会盖到）

#### 2.3 改 closes 字典构造

定位（精确字符串，约在第 73-86 行）：

```python
    bm_dates_sorted = sorted(bm_map.keys())
    # Forward-fill onto the run calendar. Days before the first benchmark
    # row are left out of closes_by_date; the engine will treat them as gaps.
    closes = {}
    last = None
    bi = 0
    for d in calendar:
        while bi < len(bm_dates_sorted) and bm_dates_sorted[bi] <= d:
            last = bm_map[bm_dates_sorted[bi]]
            bi += 1
        if last is not None:
            closes[d] = last
    if not closes:
        return None, (u"benchmark 起点晚于回测窗口 (首条=%s)" % bm_dates_sorted[0])
```

替换为：

```python
    bm_dates_sorted = sorted(bm_map.keys())
    # MS-J: 先把 lead-in 的 bm_map 数据全塞进 closes (key 是真实交易日),
    # 让策略侧 evaluate_day 切片 d<=current_date 时能拿到历史 lead-in。
    # equity_curve 路径只查 calendar 内的 key, 对 extra lead-in key 透明。
    closes = {}
    for bd in bm_dates_sorted:
        closes[bd] = bm_map[bd]
    # Forward-fill onto the run calendar. Days before the first benchmark
    # row are left out of closes_by_date; the engine will treat them as gaps.
    last = None
    bi = 0
    for d in calendar:
        while bi < len(bm_dates_sorted) and bm_dates_sorted[bi] <= d:
            last = bm_map[bm_dates_sorted[bi]]
            bi += 1
        if last is not None and d not in closes:
            closes[d] = last
    if not closes:
        return None, (u"benchmark 起点晚于回测窗口 (首条=%s)" % bm_dates_sorted[0])
```

**注意**：
- 第一个 for 把 bm_map 全部 (date, close) 塞进 closes（包括 lead-in 范围内、calendar 之前的日期）
- 第二个 for 仍然处理 calendar 内的 forward-fill；加 `if d not in closes` 判断**避免覆盖**已经从 bm_map 直接塞过的日子
- 不要动 head_gap_tolerance 那段（第 87-101 行）—— 那是处理 calendar 头几天比 bench 首条还早的容忍逻辑，与本修复正交

### TASK-3. 新增测试 `backtest/tests/test_benchmark_lead_in.py`

```python
# coding: utf-8
"""MS-J: 验证 _load_benchmark_series 注入 lead-in 数据。

测试用最小 mock benchmark_reader, 不依赖真 DuckDB。
"""
import os
import datetime as _dt
import pytest


# ---- 复用 daily_engine.py 内部函数 ----
from backtest.engine import daily_engine as _de


class _MockBenchReader(object):
    """模拟 BenchmarkIndexReader。"""
    def __init__(self, db_path):
        self.db_path = db_path
        # 提供 2025-04-01 到 2025-12-31 的日 close (252 条左右,
        # 含 lead-in 范围 2025-05-05 ~ 2025-09-01)。
        rows = []
        d = _dt.date(2025, 4, 1)
        end = _dt.date(2025, 12, 31)
        close = 3500.0
        while d <= end:
            if d.weekday() < 5:  # 简化: 跳过周末
                rows.append((d.strftime("%Y-%m-%d"), close))
                close += 1.5
            d += _dt.timedelta(days=1)
        self._rows = rows

    def load_series(self, code, start_date, end_date):
        return [(d, c) for (d, c) in self._rows
                if start_date <= d <= end_date]

    def close(self):
        pass


def _fake_isfile(p):
    return True


def test_lead_in_120_natural_days_loaded(monkeypatch):
    """calendar=2025-09-02..2025-09-05 时, closes 必须含 2025-05-05 起的 lead-in。"""
    monkeypatch.setattr(os.path, "isfile", _fake_isfile)
    import backtest.data_tools.benchmark_reader as _br_mod
    monkeypatch.setattr(_br_mod, "BenchmarkIndexReader", _MockBenchReader)

    calendar = ["2025-09-02", "2025-09-03", "2025-09-04", "2025-09-05"]
    closes, note = _de._load_benchmark_series(
        "000001.SH", calendar, "fake.duckdb")

    assert closes is not None, "lead-in 修复后应该返回 dict, note=%r" % note
    # lead-in 范围应能覆盖 calendar[0] - 120 自然日 ≈ 2025-05-05
    assert "2025-05-05" in closes or "2025-05-06" in closes, \
        "lead-in 未覆盖到 2025-05-05 (calendar[0]=%s, _BENCHMARK_LEAD_IN_DAYS=%d)" % (
            calendar[0], _de._BENCHMARK_LEAD_IN_DAYS)
    # calendar 内 key 仍存在
    for d in calendar:
        assert d in closes, "calendar 日 %s 必须在 closes 中" % d
    # 新增 key 不破坏旧行为: closes 数量 > calendar 长度
    assert len(closes) > len(calendar), \
        "lead-in 后 closes 应严格多于 calendar (len=%d vs %d)" % (
            len(closes), len(calendar))


def test_lead_in_preserves_calendar_alignment(monkeypatch):
    """回归: calendar 内每一天仍能通过 closes[d] 查到值, 与原行为一致。"""
    monkeypatch.setattr(os.path, "isfile", _fake_isfile)
    import backtest.data_tools.benchmark_reader as _br_mod
    monkeypatch.setattr(_br_mod, "BenchmarkIndexReader", _MockBenchReader)

    calendar = ["2025-09-02", "2025-09-03", "2025-09-04"]
    closes, _ = _de._load_benchmark_series(
        "000001.SH", calendar, "fake.duckdb")

    for d in calendar:
        v = closes.get(d)
        assert v is not None and v > 0, \
            "calendar 日 %s 必须有 close 值, 实际=%r" % (d, v)


def test_lead_in_constant_value():
    """_BENCHMARK_LEAD_IN_DAYS 必须 >= 120 (黄氏 MA120 需求)。"""
    assert _de._BENCHMARK_LEAD_IN_DAYS >= 120
```

### TASK-4. 跑测试

```bash
cd D:/QMT_STRATEGIES
py -3.10 -m pytest backtest/tests/test_benchmark_lead_in.py -v
py -3.10 -m pytest backtest/tests/ --tb=line | tail -5
```

期望：
- 新测试全 PASS (3 个)
- 全量 0 failed (应该是 281 passed, 0 failed)

**FAIL → 停**贴 traceback。

### TASK-5. 重跑 HUANG-ZJ-V04 smoke 验证业务效果

```bash
cd D:/QMT_STRATEGIES
py -3.10 -m backtest.scripts.run_backtest --config backtest/configs/research/huang_zhongjun_combo_smoke.yaml
```

期望：
- 退出码 0
- summary.json 里 `zhongjun_counts.benchmark_ok` 的 81 日均值**显著上升**（旧值 0.012，修复后理论值 ≈ 0.5）
- `zhongjun_counts.zhongjun_pass` 可能仍是 0 或很小（这是黄氏 zhongjun 7 条件叠加后的稀疏特性，**不是 bug**），但**至少 benchmark_ok 命中率应该跨 10%**

执行后**贴**：
1. 退出码
2. 新结果目录路径
3. `summary.json` 里 `diagnostics_aggregate.strategy_specific.huang_zhongjun_combo.zhongjun_counts_avg_per_day` 切片
4. 跟旧 smoke (commit 18e5975 后跑的 `20260624_222441_30d202_huang_zhongjun_combo_smoke`) 对比表

```
| 指标 | 旧 (MS-J 前) | 新 (MS-J 后) |
|---|---|---|
| benchmark_ok avg | 0.012 | <新值> |
| zhongjun_pass avg | 0.0 | <新值> |
| n_trades | 0 | <新值> |
```

> **不要试图调任何策略参数**（zj_angle_thresh / zj_breakout_upper 等）—— 那是诚哥业务决策范围，不在本工单。本工单只验证 bench_ok 命中率确实上去了。
>
> **若 benchmark_ok 仍然 < 5%** → 停下贴回执，说明 MS-J 没产生预期效果。

### TASK-6. 精确 add + commit

⚠️ **回执必须在 commit 之前填实**（吸取 MS-I 教训）。

```bash
cd D:/QMT_STRATEGIES
git add backtest/engine/daily_engine.py
git add backtest/tests/test_benchmark_lead_in.py
git add agent_hub/2026-06-23_huang_main_uptrend/Mimo_HUANG_MS-J_BENCHMARK_LEAD_IN.md

git diff --cached --name-only
```

**期望恰好 3 行**。staged ≠ 3 → 停。

```bash
git commit -m "$(cat <<'EOF'
[MS-J] fix(backtest/v0.4): _load_benchmark_series 加 120 天 lead-in

HUANG-ZJ-V04 smoke run (commit 18e5975) 0 成交根因:

  daily_engine._load_benchmark_series 把 load_series 的 start_date 直接
  设成 calendar[0], aux_data["benchmark_closes"] 里只有 81 天数据, 而黄
  氏 _benchmark_ok 要求 len(bench_series) >= 60 才能算 MA20/MA60。前 60
  天 bench 序列不足直接跳过, 全程 benchmark_ok=False。

修复:
- 新增常量 _BENCHMARK_LEAD_IN_DAYS = 120 (覆盖 MA120 + 30 天余量)
- load_series start_date 改为 calendar[0] - 120 自然日
- closes 字典扩成 "bm_map ∪ calendar forward-fill", 暴露 lead-in 给
  evaluate_day, equity_curve 路径透明 (只查 calendar 内的 key)

零业务影响:
- 不读 aux_data["benchmark_closes"] 的策略 (ima_uptrend_v31 等) 行为不变
- equity_curve.csv / summary.json benchmark fields 不变
- head_gap_tolerance 处理逻辑保留

测试 (3 个 PASS):
- lead_in_120_natural_days_loaded
- lead_in_preserves_calendar_alignment (回归)
- lead_in_constant_value

业务验证 (重跑 huang_zhongjun_combo_smoke):
- benchmark_ok avg: 0.012 → <填实测>
- 验证修复有效, 但 zhongjun 7 条件叠加是否触发是策略业务问题, 不在本工单范围

Refs:
- HUANG-ZJ-V04 (commit 18e5975): 暴露问题
- MS-I (commit 4253605): aux_data["benchmark_closes"] 通路
- _BENCHMARK_LEAD_IN_DAYS 选 120 因黄氏 SPEC v1.2 §D 用 MA120 长窗口
EOF
)"

git log -1 --stat HEAD
```

---

## 三、严禁

1. **严禁** `git add .` / `git add -A`
2. **严禁** push / amend / --no-verify
3. **严禁** 改 `huang_zhongjun_combo/strategy.py`（业务问题，不是本工单范围）
4. **严禁** 改 `production/ima_uptrend_v31/` 任何文件
5. **严禁** 改 yaml 任何参数（包括 huang_zhongjun_combo_smoke.yaml）
6. **严禁** 改 head_gap_tolerance / equity_rows benchmark fill 任何逻辑
7. **严禁** 删除文件顶部 `import datetime as _dt`（已有，跟我们的 `_dt2` 不冲突）
8. **严禁** 把 `_BENCHMARK_LEAD_IN_DAYS` 设为 < 120
9. **严禁** 拆 chore commit（[[mimo-receipt-commit-separation]]）
10. **严禁** 用 placeholder 时间戳
11. **严禁** smoke 不跑或失败包装成 PASS

## 四、停手条件

- TASK-1 daily_engine.py 已被改动 → 停
- TASK-2 任一定位字符串非唯一或匹配不到 → 停
- TASK-4 任一测试 FAIL → 停
- TASK-5 smoke 退出码非 0 → 停
- TASK-5 benchmark_ok avg < 5% → 停（说明修复没产生预期效果）
- staged ≠ 3 → 停

[[mimo-must-stop-on-any-failure]]

---

## 五、完成回执

⚠️ **TASK-6 commit 前**必须填好所有占位符。

```markdown

---

## 完成回执

**执行时间**: <date -u 输出>
**MIMO 模型**: <实际名>

### TASK-0: 时间戳

### TASK-1: 预检
<git status / git log -1>

### TASK-2: daily_engine.py 修改
- 新增常量 _BENCHMARK_LEAD_IN_DAYS = 120
- 改 _load_benchmark_series: load_series 起点前移 + closes 字典扩展
<贴 git diff 的关键 3 个 hunk>

### TASK-3: 新测试
- LOC: <数>
- 测试桩: monkeypatch BenchmarkIndexReader + 假数据

### TASK-4: 测试结果
- 新测试: <PASS/FAIL 数>
- 全量: <passed/failed/warnings 数>
- warning 类型: <分类汇总>

### TASK-5: smoke 业务验证
- 退出码: <0/非0>
- 新结果目录: `<F:/backtest_workspace/results/...>`
- 关键对比表:

| 指标 | 旧 (18e5975) | 新 (MS-J 后) |
|---|---|---|
| benchmark_ok avg | 0.012 | <填> |
| zhongjun_pass avg | 0.0 | <填> |
| n_trades | 0 | <填> |
| n_buy | 0 | <填> |
| n_sell | 0 | <填> |

### TASK-6: commit
<贴 3 行 + git log -1 --stat>

### 自检
- [ ] 时间戳真跑 date -u
- [ ] daily_engine.py: 新增常量 + 改 _load_benchmark_series, 未动其他
- [ ] _dt2 局部 import, 未删顶部 import datetime as _dt
- [ ] head_gap_tolerance / equity fill / strategy 文件未改
- [ ] 新测试 3 PASS, 全量 0 failed
- [ ] smoke 退出码 0, benchmark_ok avg >= 0.05
- [ ] staged 恰好 3 个文件, 单 commit
- [ ] 回执模板所有占位符已填实
- [ ] commit 成功
```
