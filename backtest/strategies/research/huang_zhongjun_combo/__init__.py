# coding: utf-8
"""research/huang_zhongjun_combo —— 黄氏双中军信号 + 6+2 评分 + V1.1 无状态风控。

策略意图（实盘等价的离线版）：
  - 每日收盘后用日 K 算 zhongjun 信号
  - zhongjun_XG=True 的票送 6+2 评分排序入场
  - V1.1 触发器（无状态）做卖出（移动止盈等有状态部分已砍）
  - T+1 next_open 成交（工厂硬约束，撮合时点等价 QMT 实盘 passorder）

SPEC: D:/QMT_STRATEGIES/specs/SPEC_HUANG_MAIN_UPTREND_TDX_TO_QMT.md
"""
from backtest.strategies.research.huang_zhongjun_combo.strategy import evaluate_day  # noqa: F401
