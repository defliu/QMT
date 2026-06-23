# 黄氏主升浪 combo selector 3 年历史回测报告

执行日期: 2026-06-23
SPEC: D:/QMT_STRATEGIES/specs/SPEC_HUANG_MAIN_UPTREND_TDX_TO_QMT.md
脚本: huang_main_uptrend_combo/backtest/run_backtest_huang_combo.py

---

## 一、回测参数

| 项 | 值 |
|---|---|
| 时间区间 | 2023-06-01 ~ 2026-04-03 |
| 实际交易日数 | 302 |
| 股票池 | core_100 (100) |
| 实际可得股票数 | 100 |
| 大盘指数 | 000001.SH |
| 持有期 | 5 / 10 / 20 日 |
| 数据源 | huicexitong daily_data."行情数据" |

## 二、信号统计

| 指标 | 数值 |
|---|---:|
| 总信号数 | 0 |
| 涉及股票数 | 0 |
| 涉及交易日数 | 0 |
| 空仓日 (无信号) | 302 / 302 (100.0%) |

## 三、持有期收益

| hold_n | n_signals |
|---|---:|
| 5 | 0 |
| 10 | 0 |
| 20 | 0 |

## 四、与大盘对比

无信号，无对比数据。

## 五、结论

- 5 日胜率 N/A vs 大盘 N/A: selector 在 3 年窗口内未产生任何 combo_XG=True 信号
- 10 日胜率 N/A: 同上
- 20 日胜率 N/A: 同上
- 空仓比例 100.0%: 过严 — selector 在 core_100 股池 + huicexitong 数据条件下完全无输出
- 最大回撤 N/A: 无交易样本

**判断**:
- 是否值得继续 (走 B 方案接 daily_engine 或接入策略)? **需要进一步实验** — 当前结果表明 selector 的 combo 逻辑在 huicexitong OHLCV 数据上可能因以下原因之一导致零信号：
  1. selector 依赖的某些指标/字段在 huicexitong 数据中不存在或格式不同
  2. selector 参数过于严格，导致 3 年窗口内无一满足条件
  3. selector 内部逻辑与 huicexitong 数据的编码/对齐方式不兼容
- 主要风险点: selector 的 combo_XG 逻辑是否在纯 OHLCV 输入下能正常触发，需要对照原 TDX 环境的信号产出
- 待回测建议:
  1. 检查 selector 内部哪些条件过滤掉了所有信号（逐层打印中间状态）
  2. 尝试放宽 selector 参数阈值
  3. 对照原 TDX 环境在相同日期区间内是否有信号产出
  4. 考虑换用 daily_engine (B 方案) 以获取更完整的指标数据
