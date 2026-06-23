# 黄氏主升浪 combo selector 最小样本验证报告

源 SPEC: `D:/QMT_STRATEGIES/specs/SPEC_HUANG_MAIN_UPTREND_TDX_TO_QMT.md`
SPEC §Testing 第 5 条要求项验证。

执行日期: 2026-06-23
执行脚本: `huang_main_uptrend_combo/reports/_run_validation.py`
明细数据: `huang_main_uptrend_combo/reports/validation_detail.csv`

---

## 一、样本设计

| 样本代码 | 设计意图 | 形态特征 |
|---|---|---|
| `A_组合通过` | 同时满足箱体突破 + 双中军 | 130 天窄幅震荡 + 19 天温和上涨 + 最后一天 6% 跳涨放量 |
| `B_只过箱体` | 满足初选不满足精筛 | 平台横盘后单日突破，无多头排列/MACD/CCI |
| `C_全部不过` | 两层都不通过 | 缩量横盘整段 |

大盘指数：单调上升 3000→3298（n=150 步长 2），满足 `指数>MA20>MA60`。

---

## 二、结果统计

| 指标 | 数量 |
|---|---:|
| 样本股数 | 3 |
| 通过箱体突破初选 | 2 |
| 通过双中军精筛 | 1 |
| 最终通过 combo | 1 |

---

## 三、最后一日条件明细表

  code       date  box_breakout_XG  box_箱体振幅_ok  box_均线黏连_ok  box_放量_ok  box_突破_ok  box_涨幅_ok  double_zhongjun_XG  double_多头排列_ok  double_均线发散_ok  double_MACD_ok  double_CCI_ok  double_突破压力_ok  double_MA20向上_ok  double_MA60向上_ok  double_大盘_ok  combo_XG
A_组合通过 2026-05-30             True         True         True       True       True       True                True            True            True            True           True            True              True              True          True      True
B_只过箱体 2026-05-30             True         True         True       True       True       True               False            True           False            True           True            True              True              True          True     False
C_全部不过 2026-05-30            False         True         True      False      False      False               False           False           False            False          False           False              True             False          True     False

---

## 四、逐样本解释

### A_组合通过
- 通过的 box_*_ok: 箱体振幅/均线黏连/放量/突破/涨幅 全部 True
- 通过的 double_*_ok: 多头排列/均线发散/MACD/CCI/突破压力/MA20向上/MA60向上/大盘 全部 True
- combo_XG: True
- 说明：130 天窄幅震荡使 60 日振幅<20%，均线黏连成立；19 天温和上涨使 MA5>MA10>MA20>MA60>MA120 形成多头排列；最后一天放量+大涨触发箱体突破、CCI、MACD、压力位突破等所有条件。

### B_只过箱体
- 通过的 box_*_ok: 箱体振幅/均线黏连/放量/突破/涨幅 全部 True
- 通过的 double_*_ok: 仅 多头排列/MACD/CCI/突破压力/MA20向上/MA60向上/大盘 为 True；均线发散=False
- combo_XG: False
- 说明：单日突破横盘平台满足箱体条件，但因均线发散角度不足（MA5角度<30 或 MA5/MA20<1.05）被双中军精筛过滤。

### C_全部不过
- 通过的 box_*_ok: 仅 箱体振幅/均线黏连 为 True；放量/突破/涨幅 均 False
- 通过的 double_*_ok: 仅 MA20向上/大盘 为 True；其余均 False
- combo_XG: False
- 说明：缩量横盘无突破，两层都不通过。

---

## 五、结论

| 验证项 | 状态 |
|---|---|
| `combo_XG = box_breakout_XG AND double_zhongjun_XG` 语义等价 | ✓（A 样本演示） |
| 箱体突破子条件独立可观察（5 项）| ✓ |
| 双中军子条件独立可观察（8 项）| ✓ |
| 中间字段明细表生成（CSV）| ✓ |
| 通过/不通过原因可逐条解释 | ✓ |

**逻辑合理性**：已通过最小样本验证；
**收益效果**：未在本 SPEC 范围内（SPEC §E）。
