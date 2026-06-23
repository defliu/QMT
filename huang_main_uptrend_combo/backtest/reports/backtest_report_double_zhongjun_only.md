# 黄氏主升浪 double_zhongjun 单独 3 年回测报告 (Part 6 / Hermes 汇总首推)

执行日期: 2026-06-23T22:48:44Z
SPEC: D:/QMT_STRATEGIES/specs/SPEC_HUANG_MAIN_UPTREND_TDX_TO_QMT.md (v1.2)
依据: agent_hub/2026-06-23_huang_main_uptrend/90_hermes_summary.md (Hermes Top 1 推荐)
脚本: huang_main_uptrend_combo/backtest/run_backtest_huang_combo.py --signal-source double_zhongjun_XG

## 背景

Hermes 汇总：4 个 profile 中 3 个把"双中军版"评为主升浪 Top 1（DeepSeek Quant / Doubao CIO / 平均推荐）。
理由：唯一同时覆盖趋势 + 动能 + 突破 + 大盘环境的完整公式；不依赖难复现指标。

Part 5 v1.2 combo_XG (= box_window_hit AND zhongjun) 跑 119 信号、胜率 25-27% 全面跑输大盘。
本报告把箱体突破初选丢掉，只用 double_zhongjun_XG 作为最终信号源。

## 一、回测参数

| 项 | 值 |
|---|---|
| 时间区间 | 2023-06-01 ~ 2026-04-03 |
| 实际交易日数 | 688 |
| 股票池 | huang_small_mid_20260403.csv (3633 只, 流通市值<100亿) |
| 实际可得股票数 | 3633 |
| 大盘指数 | 000001.SH (huicexitong basic_data."板块指数") |
| 持有期 | 5 / 10 / 20 日 |
| **信号源** | **double_zhongjun_XG 单独** |

## 二、信号统计

| 字段 | Part 5 (combo_XG) | **Part 6 (double_zhongjun_XG)** |
|---|---:|---:|
| 信号总数 | 119 | **6899** |
| 涉及股票数 | 74 | 2438 |
| 涉及交易日数 | 87 | 248 |
| 空仓日 | 601 / 688 (87.4%) | 440 / 688 (64.0%) |

## 三、持有期收益对比

### Part 6 (double_zhongjun_XG)

| hold_n | n_signals | win_rate | avg_return | median_return | max_drawdown |
|---:|---:|---:|---:|---:|---:|
| 5 | 6899 | 0.3432 | -0.0178 | -0.0353 | -1.0000 |
| 10 | 6898 | 0.3350 | -0.0265 | -0.0481 | -1.0000 |
| 20 | 6787 | 0.3470 | -0.0312 | -0.0578 | -1.0000 |

### Part 5 对比 (combo_XG)

| hold_n | n_signals | win_rate | avg_return | max_drawdown |
|---:|---:|---:|---:|---:|
| 5 | 119 | 0.2689 | -0.0370 | -0.9946 |
| 10 | 119 | 0.2605 | -0.0487 | -0.9992 |
| 20 | 113 | 0.2566 | -0.0653 | -0.9998 |

## 四、与大盘对比

### Part 6 (double_zhongjun_XG)

| hold_n | bench_n | bench_avg_return | bench_win_rate |
|---:|---:|---:|---:|
| 5 | 248 | 0.0014 | 0.5484 |
| 10 | 248 | 0.0025 | 0.5605 |
| 20 | 244 | 0.0040 | 0.5410 |

### Part 5 大盘数据 (便于对照基准)

| hold_n | bench_n | bench_avg_return | bench_win_rate |
|---:|---:|---:|---:|
| 5 | 87 | -0.0019 | 0.4253 |
| 10 | 87 | -0.0006 | 0.5287 |
| 20 | 83 | 0.0019 | 0.4819 |

## 五、结论

- 5 日胜率 Part 6 34.3% vs Part 5 26.9% vs 大盘 54.8%: Part 6 比 Part 5 高 7.4pp，但仍大幅跑输大盘
- 10 日胜率 Part 6 33.5% vs Part 5 26.1% vs 大盘 56.0%: Part 6 比 Part 5 高 7.4pp，仍大幅跑输大盘
- 20 日胜率 Part 6 34.7% vs Part 5 25.7% vs 大盘 54.1%: Part 6 比 Part 5 高 9.0pp，仍大幅跑输大盘
- 平均收益: Part 6 -1.78% / -2.65% / -3.12% vs Part 5 -3.70% / -4.87% / -6.53% vs 大盘 +0.14% / +0.25% / +0.40%
- 最大回撤: Part 6 -100% vs Part 5 -99.5% / -99.9% / -100.0% (两者都极端)
- 信号数量: Part 6 6899 vs Part 5 119 (~58 倍)
- 空仓比例: Part 6 64.0% vs Part 5 87.4%

**判断**:
- 双中军单独是否优于 box+window 组合？**是**，各持有期胜率提升 7-9pp，平均亏损缩小，但绝对表现仍然为负
- Hermes 汇总"双中军条件偏严, 大盘条件可能导致熊市无票"**部分成立**：空仓率从 87.4% 降到 64.0%，信号数增加 58 倍，说明去掉箱体初选确实大幅放宽了条件
- 是否值得继续？**需谨慎**：虽然相对 Part 5 有改善，但绝对胜率仍不到 35%，平均收益仍为负，最大回撤 100%。需考虑加入大盘择时过滤或调整评分权重
- 主要风险点：信号过于稀疏（248 个交易日中有 440 天无信号）；6899 信号在 2438 只股中分散，单股信号质量难保证；最大回撤 -100% 暗示存在单笔极端亏损
