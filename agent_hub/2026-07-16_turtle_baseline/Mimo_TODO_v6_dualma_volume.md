# 海龟策略 v6 - 双均线择时 + 量能过滤

**日期**: 2026-07-16
**作者**: CC
**目的**: v5(单MA20择时)年化0.67%小幅改善但不够。诚哥拍板 A+B:择时升级为双均线多头排列(沪深300>MA20 AND MA20>MA60),叠加量能过滤(突破日量比≥1.5)。看能否把年化推到2%+。新建独立脚本,report 三列对比(基线/v5/v6)。
**预计工时**: ≤ 40 分钟
**参考脚本**: `scripts/backtest_turtle_with_timing.py`(v5 单MA20择时)+ `scripts/backtest_turtle_baseline.py`(基线)

---

## 0. 背景与约束

1. **迭代历史**:基线(标准海龟)年化0.5% → v5(+MA20择时)年化0.67%。本版 v6 = v5 基础上择时升级双均线 + 加量能过滤。
2. **独立脚本**:新建 `scripts/backtest_turtle_timing_volume.py`,不改基线/v5 脚本。参考 v5 结构,数据加载/海龟规则/成本一致。
3. **Python**: Python310。Code style 同基线(UTF-8/`# coding=utf-8`/无 f-string/无 dict[str,]/无 walrus)。
4. **数据源**:个股 astock parquet 前复权;沪深300指数 akshare(同 v5)。

---

## 一、必做

### TASK-1. 新建 v6 脚本

**目标路径**: `D:/QMT_STRATEGIES/scripts/backtest_turtle_timing_volume.py`
**文件头**: `# coding=utf-8`
**入口**: `python scripts/backtest_turtle_timing_volume.py`(Python310)

**硬编码参数**(同基线/v5 + 新增):
```
# 同基线/v5
START_DATE="2022-01-01"  END_DATE="2025-06-30"  WARMUP_START="2021-11-01"
INITIAL_CASH=1000000.0  SINGLE_RISK_PCT=0.01  ATR_PERIOD=20
ENTRY_BREAKOUT=20  EXIT_BREAKOUT=10  STOP_LOSS_ATR_MULT=2.0  MAX_POSITION_PCT=0.20
COMMISSION=0.00025  STAMP_TAX=0.001  TRANSFER_FEE=0.00001  SLIPPAGE=0.001
DATA_PARQUET="E:/astock/daily/stock_daily.parquet"
# 择时(升级双均线)
MARKET_TIMING_MA_SHORT = 20
MARKET_TIMING_MA_LONG  = 60
MARKET_TIMING_INDEX = "sh000300"
# 量能过滤(新增)
VOLUME_RATIO_THRESHOLD = 1.5
VOLUME_RATIO_PERIOD = 5
OUT_DIR = "D:/QMT_STRATEGIES/backtest_results/turtle_timing_volume"
```

### TASK-2. 大盘双均线择时 + 量能预计算

**2.1 沪深300双均线**(替换 v5 单 MA20):
```python
# akshare 取沪深300指数日线(同v5),算双均线
hs300["ma20"] = hs300["close"].rolling(MARKET_TIMING_MA_SHORT, min_periods=MARKET_TIMING_MA_SHORT).mean()
hs300["ma60"] = hs300["close"].rolling(MARKET_TIMING_MA_LONG, min_periods=MARKET_TIMING_MA_LONG).mean()
# 双均线多头排列: 收盘>MA20 AND MA20>MA60
hs300["bull"] = (hs300["close"] > hs300["ma20"]) & (hs300["ma20"] > hs300["ma60"])
```
- 缓存 `OUT_DIR/_hs300_index.csv`(含 close/ma20/ma60/bull)
- 对齐交易日历(信号日T取 hs300.bull[T])

**2.2 个股量比**(每只 code 预计算):
```python
# 量比 = 当日vol / 前5日均vol(不含当日, PIT安全)
# 参考 backtest/strategies/research/deepseek/factors.py:84 同款算法
df["vol_ratio"] = df["vol"] / df["vol"].shift(1).rolling(VOLUME_RATIO_PERIOD, min_periods=VOLUME_RATIO_PERIOD).mean()
```
- vol 用 astock 的 vol 字段(**不复权**,成交量不除权)
- vol_ratio[T] 用 vol[T-5:T-1] 均值(shift(1)保证不含当日,PIT安全)

### TASK-3. 海龟规则 + 双均线 + 量能入场过滤

**完全复用基线/v5 逻辑**(入场20日突破/ATR20仓位/2ATR移动止损/10日离场/标准海龟仓位 shares=单笔风险/(2×ATR)/成本明细/每只独立回测)。**入场信号加2个条件**:

```
信号日 T 的入场条件(全部满足):
  1. close[T] > entry_high[T]       (20日突破,基线规则)
  2. atr[T] > 0                      (ATR除零防护,基线规则)
  3. hs300_bull[T] == True           【v6升级】双均线多头(沪深300>MA20 AND MA20>MA60)
  4. vol_ratio[T] >= 1.5             【v6新增】量能过滤(突破日量比≥1.5)
     - 若 T 日 hs300 数据缺失或 vol_ratio 为 NaN:跳过该信号(不开仓)
```

- **止损/离场不变**:已持仓的移动止损(2ATR)/离场(10日低点)照基线,**不因大盘/量能强平**
- 仓位公式同基线 v2: `shares = SINGLE_RISK_PCT × INITIAL_CASH / (2 × atr_at_entry)`(标准海龟1%风险),20%单票上限不变

### TASK-4. 输出4文件 + 三列对比

输出到 `OUT_DIR`(`D:/QMT_STRATEGIES/backtest_results/turtle_timing_volume/`):
- `result_summary.json`(同v5结构;meta 加 `market_timing: "dual_ma20_60"`, `volume_ratio_threshold: 1.5`)
- `equity_curve.csv` / `trades.csv`(同基线列)
- `report.md`(**三列对比表**)

**report.md 三列对比表**(读基线 + v5 的 result_summary.json 填前两列):

| 指标 | 基线(无择时) | v5(MA20) | v6(双均线+量能) |
|---|---|---|---|
| 年化收益均值 | 0.51% | 0.67% | ? |
| 年化收益中位 | 0.27% | 0.39% | ? |
| 胜率均值 | 34.0% | 36.3% | ? |
| 盈亏比均值 | 2.41 | 2.57 | ? |
| 正收益占比 | 55.3% | 61.7% | ? |
| 跑赢沪深300 | 100% | 100% | ? |
| 最大回撤均值 | 24.17% | 23.00% | ? |
| 交易笔数 | 5623 | 4196 | ? |
| 平均仓位 | 16.3% | 16.3% | ? |
| 平均单笔风险 | 0.89% | 0.90% | ? |

report.md 顶部一句话结论:v6(双均线+量能)vs v5(MA20)vs 基线,年化/胜率/盈亏比是否进一步提升。
report.md 含仓位诊断(avg_risk_pct≈1%)、成本诊断、数据完整性、抽查3只信号(含双均线多头判断 + 量比数值)。

### TASK-5. 跑回测 + 验证

- 用 Python310 跑 `python scripts/backtest_turtle_timing_volume.py`
- 4文件生成到 OUT_DIR
- 验证:avg_risk_pct≈1%;交易笔数应**少于**v5的4196(双均线+量能过滤更严);无崩溃
- **注意**:若交易笔数过少(<1000),说明双均线+量能过滤过严,在 report.md 标注"过滤过严,样本不足,建议降阈值",但不改参数继续跑完出结果
- 脚本末尾 print 总结行(标注 "dual_ma20_60 + vol_ratio>=1.5")

---

## 二、严禁

1. 禁止 git add / commit / push(不授权 git,先看效果)
2. 禁止改动基线/v5 脚本(`backtest_turtle_baseline.py` / `backtest_turtle_with_timing.py`)
3. 禁止改动 backtest/、core/、strategy_*.py、config/
4. 禁止改海龟规则(入场20日突破/2ATR止损/10日离场/标准海龟仓位1%/成本明细)--**只加入场双均线+量能过滤,其它不动**
5. 禁止用 hermes venv python 3.13(用 Python310)
6. 禁止改时间范围/标的池/仓位公式
7. 禁止静默吞异常
8. 禁止读本工单目录外项目文件(除基线/v5脚本只读参考 + 基线/v5 result_summary.json 读对比 + parquet 数据)

---

## 三、完成回执(MIMO 在工单末尾追加)

```markdown

---

## 完成回执

**执行时间**: <date -u 真实时刻,禁止 placeholder>
**MIMO 模型**: <实际名>
**Python**: <路径+版本>
**自检**:
- [ ] TASK-1 新建 scripts/backtest_turtle_timing_volume.py(独立,不改基线/v5)
- [ ] TASK-2 沪深300双均线(ma20/ma60/bull)+ 个股量比预计算
- [ ] TASK-3 入场加 hs300_bull + vol_ratio>=1.5;止损/离场/仓位同基线不变
- [ ] TASK-4 四文件生成 + report.md 三列对比表(贴对比表原文)
- [ ] TASK-5 跑通;avg_risk_pct≈1%;交易笔数<4196
- [ ] 仅末尾追加回执,未改动工单上方
- [ ] 无工单外文件改动 / git 操作
- [ ] 脚本已实际跑通(贴完整 print + 三列对比表原文)
```

**关键提醒**:
- 时间戳用 `date -u` 真实拿,禁止 placeholder
- 回执必须贴:①完整 print ②report.md 三列对比表原文 ③position_diagnostic
- CC 独立验证:笔数<4196、avg_risk_pct≈1%、对比表数值合理
