# TASK: 写等权持仓5年回测脚本(对比5只版)

**日期**: 2026-07-16
**作者**: CC
**目的**: 对比5只选股 vs 等权持有全部C3+C4通过股, 近5年回测
**状态**: 待MIMO执行

---

## 背景
5只版回测(t016_5hold_5y.py)由CC后台跑。等权版让MIMO写, 参数相同, 区别是不选top5(全部通过等权持有)。

## 源参考
**读** `scripts/t016_5hold_5y.py`(CC已写, 5只版回测脚本, 参考其结构)

## 改动: 新建 `scripts/t017_equal_weight_5y.py`

和t016_5hold_5y.py**完全相同**的参数, 仅以下区别:

| 项 | t016(5只版) | t017(等权版) |
|---|---|---|
| max_hold | 5 | **不限**(C3+C4通过的全部买入) |
| 选股 | C3+C4通过 + 成交额排序选top5 | C3+C4通过的**全部等权持有**(不排序) |
| 资金分配 | capital/5 | **capital/N**(N=通过数, 每只至少100股, 不够跳过) |
| sell engine | 止损-8%/止盈+20%/移动止盈-10% | **相同** |
| 成本 | 买*1.0051 卖*0.9939 | **相同** |
| 择时 | MA20/60 BEAR限30% | **相同** |
| universe | top1000(2020-12截面) | **相同** |
| 时间 | 2021-07~2026-06 | **相同** |

### 关键实现
1. 选股时不用`cands[:slots]`, 改为全部`cands`买入
2. `pos_target = cash / len(cands)`(每只等权)
3. 每只至少100股, `shares = int(pos_target / (bp*BUY_F) / 100) * 100`, <100跳过
4. 505失效退出/sell engine逻辑相同
5. 输出`F:/backtest_workspace/results/t017_equal_weight_5y.json`(格式同t016)

### 输出字段(同t016)
cum, dd, sharpe, trades, win, exit_stats, bull, final, period, maxhold(写"等权N"), annual_returns

## 验收
- [ ] `scripts/t017_equal_weight_5y.py` 创建成功
- [ ] `python scripts/t017_equal_weight_5y.py` 能跑完(可能5-10分钟)
- [ ] 输出`F:/backtest_workspace/results/t017_equal_weight_5y.json`
- [ ] commit(只add t017脚本)

## ⚠️ 注意
- t016可能还在后台跑, 读其源码参考但不要等它跑完
- 不要改t016, 只新建t017
- astock数据路径`E:/astock/daily/stock_daily.parquet`
- TMPDIR设`/f/tmp`(C盘满)
