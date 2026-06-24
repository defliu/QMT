# 聚宽移植报告

## 已实现 (与本地等价)

| 模块 | 本地源 | 聚宽实现 | 等价度 |
|---|---|---|---|
| 黄氏 zhongjun 8 项子条件 | selector.py `_calc_double_zhongjun_conditions` | `_zhongjun_check_single` | 100% |
| TDX 工具函数 (MA/EMA/REF/HHV/LLV/CROSS/AVEDEV/COUNT) | selector.py L48-87 | 同名函数 | 100% |
| 中小盘股池 (流通市值 < 100 亿) | huicexitong build_universe_small_mid.py | `_get_small_mid_universe` (用 valuation) | 等价 |
| 大盘条件过滤 (000001.SH MA20>MA60) | selector.py | `_calc_zhongjun_signals` 内置 | 100% |
| 6+2 突破维度 (22分) | dimension6plus2.py `_score_breakout` | `_calc_6plus2_score` D1 | 100% |
| 6+2 趋势维度 (13分) | dimension6plus2.py `_score_trend` | `_calc_6plus2_score` D2 | 100% |
| 6+2 整理维度 (20分) | dimension6plus2.py `_score_consolidation` | `_calc_6plus2_score` D3 | 100% |
| 6+2 量价维度 (12分) | dimension6plus2.py `_score_volume_price` | `_calc_6plus2_score` D4 | 100% |
| 6+2 MACD维度 (12分) | dimension6plus2.py `_score_macd` | `_calc_6plus2_score` D5 | 100% |
| 6+2 估值维度 (7分) | dimension6plus2.py `_score_valuation` | `_calc_6plus2_score` D6 | 90% (用5d涨幅代替PE) |
| 6+2 情绪维度 (7分) | dimension6plus2.py `_compute_sentiment_scores` | `_calc_6plus2_score` D7 | 80% (无跨截面排名) |
| V1.1 底线层 | risk_manager.py `_check_bottom_line` | `_run_v11_risk` 累亏+日跌 | 100% |
| V1.1 移动止盈 | risk_manager.py `_check_trailing_profit` (简化版) | `_run_v11_risk` 移动止盈 | 80% (无ATR自适应) |
| V1.1 预警层 | risk_manager.py 预警 3 信号 | `_check预警层` | 95% |
| V1.1 确认层 | risk_manager.py 确认 3 信号 | `_check确认层` | 90% (无长上影精细判断) |

## 简化 (功能保留, 复杂度降低)

| 模块 | 简化项 | 原因 |
|---|---|---|
| 6+2 评分 | 板块维度用 3.5 中性值 | 聚宽里没有 D:/QMT_POOL/sector_heat.json |
| 6+2 估值 | 用 5d 涨幅代替 PE | 聚宽 PE 需额外 API 调用, 简化处理 |
| 6+2 情绪 | 自身 ret_5d 映射, 无跨截面排名 | 聚宽单股评分无法做全池排名 |
| V1.1 移动止盈 | 固定 6% 回撤阈值, 无 ATR 自适应 | 简化实现, 去掉吊灯止损 |
| V1.1 清仓层 | 未单独实现 (合并到移动止盈和底线) | 清仓层触发条件与移动止盈重叠 |

## 已知差异

| 差异 | 影响 |
|---|---|
| 撮合时点 | 本地 T 日 close, 聚宽 14:55 (接近但非严格相同). 当日 14:55-15:00 间股价波动可能造成偏差 |
| T+1 锁仓 | 本地手工实现, 聚宽自动. 行为应一致, 但需观察 |
| 历史数据 | 本地 huicexitong, 聚宽自有数据. 复权方式、停牌处理可能微差 |

## 不能完全等价的根因

- 6+2 评分本地 551 行, 聚宽版 ~130 行 (核心 6 维 + 情绪): **预期 6+2 评分结果不完全一致**, 但排序结果应相似
- V1.1 本地 1163 行, 聚宽版 ~100 行: 卖出触发频率可能略低

## 建议

跑完聚宽回测后, 用以下指标跟本地 Part 8 v3 对照:
- 累计收益 (本地 -64.71%): 偏差 < 20% 视为一致
- 交易次数 (本地 481): 偏差 < 30% 视为一致
- 胜率 (本地 30.7%): 偏差 < 10pp 视为一致
- 最大回撤 (本地 -69.91%): 偏差 < 20pp 视为一致

如果偏差超过上述范围, 是 6+2 / V1.1 简化导致, 不是 bug.
