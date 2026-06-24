# 黄氏 zhongjun + 6+2 + V1.1 聚宽 (joinquant) 策略

## 目的

把 huang_main_uptrend_combo (黄氏 zhongjun 选股) + production/ima_uptrend_v31/scoring_adapter (6+2 评分) + core/risk_manager.py (V1.1 风控) 移植到聚宽平台跑回测.

平台对比目的: 验证 QMT/独立脚本与聚宽的回测一致性, 也看聚宽真实"当日尾盘 14:55 成交"的实际表现.

## 文件

- `huang_zhongjun_jq_close.py`: 尾盘版 (14:55 决策 + 14:55 撮合)
- `huang_zhongjun_jq_open.py`: 盘中版 (10:00 决策 + 10:00 撮合)

## 使用方法

1. 登录聚宽 https://www.joinquant.com
2. 进策略 → 新建 → 复制粘贴对应 .py 文件全文
3. 回测设置:
   - 时间: 2023-06-01 ~ 2026-04-03
   - 初始资金: 1,000,000
   - 频率: 日 (尾盘版) 或 分钟 (盘中版)
   - 标的池: 自定义 (策略内部用 get_all_securities + 市值 < 100亿 过滤构造中小盘池)

## 与本地回测的对应

| 项 | 本地 | 聚宽 |
|---|---|---|
| 选股 | huang_main_uptrend_combo selector.double_zhongjun_XG | 内嵌, 等价复刻 |
| 评分 | production/ima_uptrend_v31/scoring_adapter.score_universe (sector_heat=zero) | 内嵌, 等价复刻 |
| 风控 | core/risk_manager.py V1.1 (commit 503f475) | 内嵌, 等价复刻 |
| 数据源 | huicexitong | 聚宽内置 |
| 撮合 | T 日 close / T+1 next_open | 聚宽 14:55 (尾盘) / 10:00 (盘中) 同日撮合 |

## 已知简化

1. 6+2 板块情绪 (sector_heat) 用 zero 模式跳过 (聚宽里没有 D:/QMT_POOL/sector_heat.json)
2. V1.1 状态持久化用 g.* 全局对象 (聚宽自动跨 bar 保留, 无 json 文件)
3. 股票代码格式: 000001.SZ → 000001.XSHE, 600000.SH → 600000.XSHG

## 参考

- 黄氏 SPEC v1.2: `specs/SPEC_HUANG_MAIN_UPTREND_TDX_TO_QMT.md`
- 本地回测报告: `huang_main_uptrend_combo/backtest/reports/backtest_report_full_engine_compare.md`
- Hermes 双中军评审: `agent_hub/2026-06-23_huang_main_uptrend/90_hermes_summary.md`
