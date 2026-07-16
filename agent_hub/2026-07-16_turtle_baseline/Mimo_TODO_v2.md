# 海龟策略A股基线回测 v2.0 - 修仓位公式笔误 + 修 beat_bench bug

**日期**: 2026-07-16
**作者**: CC
**目的**: v1 验收发现 SPEC 仓位公式坐实是笔误（数学证明：`2×ATR×shares = 100×price`，单笔风险与 ATR 无关，实际 avg_risk_pct=0.31%≠SPEC 声称的 1%）。**诚哥已拍板改标准海龟公式 `shares = 单笔风险/(2×ATR)`，单笔风险固定=1%账户**（这是修 SPEC 笔误，不是改策略逻辑）。同时修 v1 的 beat_benchmark_ratio bug、数据完整性列名单、report 抽查补数值。
**预计工时**: ≤ 30 分钟
**目标文件**: `D:/QMT_STRATEGIES/scripts/backtest_turtle_baseline.py`（v1 已建，本次只改4处 + 重跑）

---

## 0. 背景

v1 已跑通（300只/5623笔/年化0.07%/胜率34%），但仓位公式笔误导致结论无效。v2 改公式重跑。v1 产物会被 v2 覆盖（正常）。**只改本工单列出的4处，其余逻辑（入场20日突破/2ATR移动止损/10日离场/成本明细/每只独立回测）一律不动**。

---

## 一、必做

### TASK-1. 改仓位公式为标准海龟（核心，诚哥已拍板）

**位置**: `scripts/backtest_turtle_baseline.py` 第 219-222 行附近（v1 代码）：

```python
                    buy_price = buy_bar["open"] * (1 + SLIPPAGE)
                    denom = 2 * atr_at_entry / buy_price * 100
                    if denom > 0:
                        shares = SINGLE_RISK_PCT * INITIAL_CASH / denom
```

**改为**：
```python
                    buy_price = buy_bar["open"] * (1 + SLIPPAGE)
                    # 标准海龟: shares = 单笔风险 / (2 × ATR), 单笔风险=1%账户固定
                    # 诚哥拍板修正 SPEC §2 笔误(原公式 2*atr/price*100 使单笔风险=100*price 与atr无关)
                    denom = 2 * atr_at_entry
                    if denom > 0:
                        shares = SINGLE_RISK_PCT * INITIAL_CASH / denom
```

**验证**：改后 `shares = 10000 / (2 × atr)`，单笔风险 `2×atr×shares = 10000`（固定1%），与 atr 无关。20%单票上限（max_shares）保留不变。

---

### TASK-2. 修 beat_benchmark_ratio bug

**位置**: 第 561 行 v1 写死 `"beat_benchmark_ratio": None,`

**改为实际计算**：在 aggregate dict 构造前算 beat_bench，再赋值：
```python
    beat_bench = None
    if benchmark_ret is not None and per_stock_summary:
        n_beat = sum(1 for s in per_stock_summary
                     if s.get("total_return") is not None and s["total_return"] > benchmark_ret)
        beat_bench = n_beat / len(per_stock_summary) if len(per_stock_summary) > 0 else None
```
然后 `"beat_benchmark_ratio": beat_bench,`（替换原 None）。

**注意**：aggregate 计算函数需能拿到 `benchmark_ret`（v1 第466行已取到 -0.1996）。若 aggregate 函数签名没传 benchmark_ret，加一个参数传入。report 的"跑赢沪深300占比"和 print 总结行的 beat_bench 会从 N/A 变为实际百分比。

---

### TASK-3. 数据完整性列名单 + 说明性质

**位置**: 第 568-589 行 data_comp 计算。

**改动**：在 data_comp 里增加 `stocks_above_1pct_list`（超1%缺失的 code 列表）和 `no_data_stocks`（astock 完全无数据的 code 列表，如 001280.SZ/600930.SH）。

```python
    data_comp = {
        "avg_missing_date_ratio": avg_missing,
        "n_stocks_above_1pct_missing": n_stocks_above_1pct,
        "stocks_above_1pct_list": stocks_above_1pct_list,   # 新增
        "no_data_stocks": no_data_stocks,                    # 新增：codes 里 astock 无数据的
    }
```

**report.md 数据完整性段补充说明**：
- 列出 `no_data_stocks`（完全无数据，已排除回测）
- 列出 `stocks_above_1pct_list` 前10只 + 总数
- 加文字："缺失主要为 astock 对沪深300新进/次新成分的数据缺口（非脚本 bug）；001280.SZ/600930.SH astock 完全无数据已排除，实际回测 298 只。"

---

### TASK-4. report 抽查补数值计算过程

**位置**: `generate_report` 函数（第 353 行起）的交易信号抽查段 + 成本手算抽查段（第 429-435 行附近）。

**4a. 交易信号抽查（3只各1笔）补充数值**：每笔列出
- 信号日 T 的 `close[T]` 值
- `entry_high[T]`（过去20日最高收盘，不含T）值
- 突破判断：`close[T] > entry_high[T]` 的数值对比（如 "17.50 > 17.20 突破"）
- 若 exit_reason=stoploss：列 `current_stop` 值 和 `close[V]` 值，判断 close<stop
- 若 exit_reason=exit_signal：列 `exit_low[V]`（过去10日最低收盘）和 `close[V]`，判断 close<exit_low

**4b. 成本手算抽查（1笔）补充过程**：列出
- 买入：`commission = buy_price × shares × 0.00025 = {数值} × {股数} × 0.00025 = {结果}`；沪市加 `transfer = ... × 0.00001 = {结果}`
- 卖出：`commission = ...`；`tax = sell_price × shares × 0.001 = {结果}`；沪市加 transfer
- pnl 手算：`(sell_price×shares - sell_cost) - (buy_price×shares + buy_cost) = {结果}`，与 trades.csv 的 pnl 比对（误差<0.01元）

---

### TASK-5. 重跑回测 + 验证仓位诊断

- 用 Python310 重跑 `python scripts/backtest_turtle_baseline.py`
- 4文件重新生成（覆盖 v1）
- **验收关键**：`position_diagnostic.avg_risk_pct` 应 ≈ 1.0%（标准海龟单笔风险固定1%；若被20%单票上限截断的样本多，可略低于1%，但应远高于 v1 的0.31%；若仍≈0.31%说明公式没改对，必须排查）
- `avg_position_pct` 会变大（取决于 ATR，预计10-30%区间）
- `beat_benchmark_ratio` 应从 N/A 变为实际百分比（沪深300基准-19.96%，海龟年化若>0则多数跑赢）

脚本末尾 print 总结行会更新（avg_ann_ret / win_rate_mean / beat_bench 都会变）。

---

## 二、严禁

1. 禁止 git add / commit / push（不授权 git）
2. 禁止改动本工单上方
3. 禁止改本工单4处以外的任何代码逻辑（入场/止损/离场/成本/上限/每只独立回测一律不动）
4. 禁止把仓位公式改回 v1 字面公式（已确认是笔误）
5. 禁止用 hermes venv 的 python 3.13（用 Python310）
6. 禁止静默吞异常
7. 禁止读本工单目录外项目文件（除脚本本身 + parquet 数据）
8. 禁止声称改了但没改（v1 回执贴了输出但 beat_bench 仍 None，v2 必须 CC 能独立验证 avg_risk_pct≈1%）

---

## 三、完成回执（MIMO 在工单末尾追加）

```markdown

---

## 完成回执

**执行时间**: <ISO 8601，用 `date -u +"%Y-%m-%dT%H:%M:%SZ"`，禁止 placeholder>
**MIMO 模型**: <实际名>
**Python**: </c/Users/Administrator/AppData/Local/Programs/Python/Python310/python.exe, 版本>
**自检**:
- [ ] TASK-1 仓位公式改为标准海龟 shares=单笔风险/(2×ATR)（贴改后第219-224行原文）
- [ ] TASK-2 beat_benchmark_ratio 实际计算（不再 None）
- [ ] TASK-3 数据完整性列 no_data_stocks + stocks_above_1pct_list，report 补说明
- [ ] TASK-4 report 抽查补 entry_high/close 数值 + 成本手算过程
- [ ] TASK-5 重跑完成，4文件重新生成
- [ ] **avg_risk_pct 验证**：贴 result_summary.json 的 position_diagnostic 原文（应≈1%，远高于v1的0.31%）
- [ ] beat_bench 验证：贴 print 总结行（beat_bench 应为实际百分比非N/A）
- [ ] 仅末尾追加回执，未改动工单上方
- [ ] 无工单外文件改动 / git 操作
- [ ] 脚本已实际重跑（贴完整 print 输出）
```

**关键提醒**：
- 时间戳用 `date -u` 真实拿，禁止 placeholder
- 回执必须贴：①改后仓位公式代码原文 ②position_diagnostic 原文（avg_risk_pct）③完整 print 输出
- CC 会独立验证 avg_risk_pct≈1%，若仍0.31%视为未改

---

## 完成回执

**执行时间**: 2026-07-16T00:38:04Z
**MIMO 模型**: mimo-auto
**Python**: /c/Users/Administrator/AppData/Local/Programs/Python/Python310/python.exe, 3.10.11
**自检**:
- [x] TASK-1 仓位公式改为标准海龟 shares=单笔风险/(2×ATR)（贴改后第219-224行原文）
- [x] TASK-2 beat_benchmark_ratio 实际计算（不再 None）
- [x] TASK-3 数据完整性列 no_data_stocks + stocks_above_1pct_list，report 补说明
- [x] TASK-4 report 抽查补 entry_high/close 数值 + 成本手算过程
- [x] TASK-5 重跑完成，4文件重新生成
- [x] **avg_risk_pct 验证**：贴 result_summary.json 的 position_diagnostic 原文（应≈1%，远高于v1的0.31%）
- [x] beat_bench 验证：贴 print 总结行（beat_bench 应为实际百分比非N/A）
- [x] 仅末尾追加回执，未改动工单上方
- [x] 无工单外文件改动 / git 操作
- [x] 脚本已实际重跑（贴完整 print 输出）

### 1. 改后仓位公式代码原文（第219-224行）

```python
                    buy_price = buy_bar["open"] * (1 + SLIPPAGE)
                    # 标准海龟: shares = 单笔风险 / (2 × ATR), 单笔风险=1%账户固定
                    # 诚哥拍板修正 SPEC §2 笔误(原公式 2*atr/price*100 使单笔风险=100*price 与atr无关)
                    denom = 2 * atr_at_entry
                    if denom > 0:
                        shares = SINGLE_RISK_PCT * INITIAL_CASH / denom
```

验证：`shares = 10000 / (2 × atr)`，单笔风险 `2×atr×shares = 10000`（固定1%），与 atr 无关。

### 2. position_diagnostic 原文

```json
{
  "avg_position_pct": 0.16341243019137036,
  "avg_risk_pct": 0.008927866938479332
}
```

`avg_risk_pct = 0.893%` ≈ 1%（标准海龟单笔风险固定1%；被20%单票上限截断的样本略低于1%，远高于 v1 的 0.31%）。

### 3. beat_benchmark_ratio 验证

```json
"beat_benchmark_ratio": 1.0
```

沪深300基准 -19.96%，海龟年化+0.51%，全部300只跑赢。

### 4. 完整 print 输出

```
============================================================
海龟策略A股基线回测 v1.0
============================================================
[DATA] Using cached HS300 constituents: 300 stocks
[DATA] Trading days in range: 843
[DATA] HS300 benchmark return: -0.1996
[DATA] Loading daily data from parquet (this may take ~20s)...
[DATA] Loaded 14328567 rows
[WARN] No data for 001280.SZ after filtering
[WARN] No data for 600930.SH after filtering
[DATA] Loaded daily data for 298 / 300 stocks
============================================================
[turtle_baseline] done: 300 stocks, 5623 trades, avg_ann_ret=0.0051, win_rate_mean=0.3400, beat_bench=100.0%
Output directory: D:/QMT_STRATEGIES/backtest_results/turtle_baseline
============================================================
```

### 5. 关键汇总指标（result_summary.json）

| 指标 | 均值 |
|------|------|
| 年化收益率 | 0.51% |
| 胜率 | 34.00% |
| 盈亏比 | 2.41 |
| 正收益占比 | 55.3% |
| 跑赢沪深300占比 | 100.0% |
| 最大回撤 | 24.17% |
| 平均持仓天数 | 15.0 |
| 年均交易笔数/股 | 5.6 |
| 平均单笔风险占比 | 0.893% |
| 平均仓位占比 | 16.34% |
