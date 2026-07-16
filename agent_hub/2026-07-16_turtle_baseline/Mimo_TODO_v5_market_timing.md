# 海龟策略 v2.1 - 大盘择时版(沪深300 MA20 开仓过滤)

**日期**: 2026-07-16
**作者**: CC
**目的**: 基线 v1.0(标准海龟)结论是年化0.5%保本微赚,核心病灶是没大盘择时(熊市反复假突破止损)。诚哥拍板先做"大盘择时版"看效果:沪深300收盘>沪深300MA20 时才允许开仓(大盘多头过滤),止损/离场照常。新建独立脚本保留基线对比。
**预计工时**: ≤ 40 分钟
**基线参考**: `scripts/backtest_turtle_baseline.py`(v2 标准海龟,commit 191535a)+ `backtest_results/turtle_baseline/result_summary.json`(基线结果对照)

---

## 0. 背景与约束

1. **基线已完成**:v1.0 标准海龟(沪深300/2022-2025,astock qfq,标准海龟1%风险)结果:年化0.5%/胜率34%/盈亏比2.41/正收益55.3%/100%跑赢沪深300(基准-19.96%)/最大回撤24%/5623笔。
2. **本版加一个过滤**:入场额外要求"沪深300当日收盘 > 沪深300 MA20"(大盘多头)。**只过滤开仓**,已持仓的止损/离场照常(不强平)。
3. **独立脚本**:新建 `scripts/backtest_turtle_with_timing.py`,**不改基线脚本**。可参考基线脚本结构(数据加载/海龟规则/成本一致),但独立可跑。
4. **数据源**:个股 astock parquet 前复权(同基线);沪深300指数 akshare `ak.stock_zh_index_daily(symbol="sh000300")` 取日线 close 算 MA20(指数不复权,同基线 get_hs300_benchmark)。
5. **Python**: Python310(`/c/Users/Administrator/AppData/Local/Programs/Python/Python310/python.exe`)。Code style 同基线(UTF-8/`# coding=utf-8`/无 f-string/无 dict[str,]/无 walrus)。

---

## 一、必做

### TASK-1. 新建大盘择时版脚本

**目标路径**: `D:/QMT_STRATEGIES/scripts/backtest_turtle_with_timing.py`
**文件头**: `# coding=utf-8`
**入口**: `python scripts/backtest_turtle_with_timing.py`(Python310)

**硬编码参数**(同基线 + 新增择时参数):
```
# 同基线
START_DATE="2022-01-01"  END_DATE="2025-06-30"  WARMUP_START="2021-11-01"
INITIAL_CASH=1000000.0  SINGLE_RISK_PCT=0.01  ATR_PERIOD=20
ENTRY_BREAKOUT=20  EXIT_BREAKOUT=10  STOP_LOSS_ATR_MULT=2.0  MAX_POSITION_PCT=0.20
COMMISSION=0.00025  STAMP_TAX=0.001  TRANSFER_FEE=0.00001  SLIPPAGE=0.001
DATA_PARQUET="E:/astock/daily/stock_daily.parquet"
# 新增:大盘择时
MARKET_TIMING_MA = 20          # 沪深300 MA20
MARKET_TIMING_INDEX = "sh000300"  # akshare 沪深300指数代码
OUT_DIR = "D:/QMT_STRATEGIES/backtest_results/turtle_with_timing"
```

### TASK-2. 大盘择时数据加载

函数 `load_market_timing()`:
- akshare `ak.stock_zh_index_daily(symbol="sh000300")` 取沪深300指数日线(返回 date/open/high/low/close/volume)
- filter `WARMUP_START <= date <= END_DATE`,按 date 升序
- 算 `hs300_ma20 = close.rolling(MARKET_TIMING_MA, min_periods=MARKET_TIMING_MA).mean()`
- 返回 DataFrame: `date(str), close, hs300_ma20`(对齐交易日历)
- 缓存到 `OUT_DIR/_hs300_index.csv` 避免重复取(同基线成分股缓存逻辑)
- 失败处理:akshare 失败则 raise(不静默降级)

### TASK-3. 海龟规则 + 大盘择时入场过滤

**完全复用基线逻辑**(入场20日突破/ATR20仓位/2ATR移动止损/10日离场/标准海龟仓位 shares=单笔风险/(2×ATR)/成本明细/每只独立回测)。**唯一改动:入场信号加大盘多头条件**:

```
信号日 T 的入场条件(全部满足):
  1. close[T] > entry_high[T]  (20日突破,基线规则)
  2. atr[T] > 0  (ATR除零防护,基线规则)
  3. 【新增】hs300_close[T] > hs300_ma20[T]  (大盘多头:沪深300收盘>其MA20)
     - hs300_close[T]/hs300_ma20[T] 取信号日T的沪深300数据(对齐交易日历)
     - 若 T 日沪深300数据缺失(非交易日等):跳过该信号(不开仓)
```

- **止损/离场不变**:已持仓的移动止损(2ATR)/离场(10日低点)照基线,**不因大盘空头强平**(只过滤开仓)
- 仓位公式同基线 v2: `shares = SINGLE_RISK_PCT × INITIAL_CASH / (2 × atr_at_entry)`(标准海龟1%风险),20%单票上限不变

### TASK-4. 输出4文件 + 基线对比

输出到 `OUT_DIR`(`D:/QMT_STRATEGIES/backtest_results/turtle_with_timing/`):
- `result_summary.json`(同基线结构:meta/per_stock_summary/aggregate/position_diagnostic/cost_diagnostic/data_completeness;meta 加 `market_timing_ma: 20`)
- `equity_curve.csv`(code,date,equity)
- `trades.csv`(同基线列)
- `report.md`(**含基线对比表**,见下)

**report.md 基线对比表**(读 `backtest_results/turtle_baseline/result_summary.json` 的 aggregate 填基线列):

| 指标 | 基线(无择时) | 择时版(MA20) | 变化 |
|---|---|---|---|
| 年化收益均值 | 0.51% | ? | ? |
| 年化收益中位数 | 0.27% | ? | ? |
| 胜率均值 | 34% | ? | ? |
| 盈亏比均值 | 2.41 | ? | ? |
| 正收益占比 | 55.3% | ? | ? |
| 跑赢沪深300占比 | 100% | ? | ? |
| 最大回撤均值 | 24.17% | ? | ? |
| 交易笔数 | 5623 | ? | ? |
| 平均仓位 | 16.3% | ? | ? |
| 平均单笔风险 | 0.89% | ? | ? |

report.md 顶部一句话结论:大盘择时版 vs 基线,年化/胜率/盈亏比是否改善。
report.md 含仓位诊断(同基线,avg_risk_pct 应≈1%)、成本诊断、数据完整性、抽查3只信号(含大盘多头判断数值:hs300_close vs hs300_ma20)。

### TASK-5. 跑回测 + 验证

- 用 Python310 跑 `python scripts/backtest_turtle_with_timing.py`
- 4文件生成到 OUT_DIR
- 验证:avg_risk_pct≈1%(标准海龟仓位未变);交易笔数应**少于**基线5623(择时过滤减少开仓);无崩溃
- 脚本末尾 print 总结行(同基线格式 + 标注 "with market timing MA20")

---

## 二、严禁

1. 禁止 git add / commit / push(本工单不授权 git,先看效果)
2. 禁止改动基线脚本 `scripts/backtest_turtle_baseline.py`(基线 v1.0 已定稿)
3. 禁止改动 backtest/、core/、strategy_*.py、config/
4. 禁止改海龟规则(入场20日突破/2ATR止损/10日离场/标准海龟仓位1%/成本明细)--**只加入场大盘多头过滤,其它一律不动**
5. 禁止用 hermes venv python 3.13(用 Python310)
6. 禁止改时间范围/标的池(同基线:沪深300,2022-2025)
7. 禁止静默吞异常
8. 禁止读本工单目录外项目文件(除基线脚本只读参考 + 基线 result_summary.json 读对比 + parquet 数据)

---

## 三、完成回执(MIMO 在工单末尾追加)

```markdown

---

## 完成回执

**执行时间**: <date -u 真实时刻,禁止 placeholder>
**MIMO 模型**: <实际名>
**Python**: <路径+版本>
**自检**:
- [ ] TASK-1 新建 scripts/backtest_turtle_with_timing.py(独立,不改基线)
- [ ] TASK-2 沪深300指数+MA20 加载(akshare,缓存)
- [ ] TASK-3 入场加 hs300_close>hs300_ma20 过滤;止损/离场/仓位同基线不变
- [ ] TASK-4 四文件生成 + report.md 含基线对比表(贴对比表原文)
- [ ] TASK-5 跑通;avg_risk_pct≈1%;交易笔数<5623
- [ ] 仅末尾追加回执,未改动工单上方
- [ ] 无工单外文件改动 / git 操作
- [ ] 脚本已实际跑通(贴完整 print 输出 + 基线对比表原文)
```

**关键提醒**:
- 时间戳用 `date -u` 真实拿,禁止 placeholder
- 回执必须贴:①完整 print 输出 ②report.md 基线对比表原文 ③position_diagnostic(avg_risk_pct)
- CC 会独立验证:择时版交易笔数<基线5623、avg_risk_pct≈1%、对比表数值合理
