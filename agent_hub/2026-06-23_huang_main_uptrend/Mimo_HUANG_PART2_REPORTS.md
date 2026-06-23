# MIMO 工单：黄氏主升浪组合选股 — Part 2 / 2 (config + 映射报告 + 最小样本验证 + lookahead 测试补强 + commit)

## 目的

Part 1 已完成 selector 核心 + 17 单测 + 37 回归（未 commit）。本工单完成剩余 4 件事：
1. `config.yaml`：把 DEFAULT_PARAMS 24 项与 SPEC §D 落到配置文件
2. `reports/tdx_mapping_report.md`：TDX 函数 → Python 表达式 + 源代码行号 + 注意点
3. `reports/validation_report.md`：构造可观察样本，跑 selector，输出每股每日条件明细表 + 通过统计
4. 补强 `test_no_lookahead_hhv` 测试（CC 验收时发现深度不够）+ 精确 commit 6 文件

**前置 commit**: `44bd768`
**Part 1 落地（未 commit）**:
- `huang_main_uptrend_combo/__init__.py`
- `huang_main_uptrend_combo/huang_main_uptrend_combo_selector.py`
- `huang_main_uptrend_combo/tests/__init__.py`
- `huang_main_uptrend_combo/tests/test_huang_main_uptrend_combo_selector.py`

**预计工时**：30-45 分钟

---

## 一、必做（8 项）

### TASK-0. 时间戳

```bash
date -u +"%Y-%m-%dT%H:%M:%SZ"
```

### TASK-1. 预检

```bash
cd D:/QMT_STRATEGIES
git status --short huang_main_uptrend_combo/
git log -1 --oneline
ls huang_main_uptrend_combo/
ls huang_main_uptrend_combo/tests/
```

期望：
- HEAD = `44bd768`
- 4 个 ?? 文件存在（Part 1 产物）

把输出贴回执。**如果 Part 1 4 个文件缺失或已 commit，立刻停下报告**。

### TASK-2. 补强 `test_no_lookahead_hhv`（必须更严格）

打开 `huang_main_uptrend_combo/tests/test_huang_main_uptrend_combo_selector.py`，找到 `test_no_lookahead_hhv` 函数，**整段替换**为更严格的版本。

定位（精确匹配，only 1 处）：
```python
    def test_no_lookahead_hhv(self):
        n = 100
        dates = pd.date_range('2026-01-01', periods=n)
        close_list = [10.0 + i * 0.1 for i in range(n)]
        high_list = [c + 0.5 for c in close_list]
        low_list = [c - 0.5 for c in close_list]
        vol_list = [1000.0 + i * 10.0 for i in range(n)]

        df1 = pd.DataFrame({
            'open': close_list, 'high': high_list, 'low': low_list,
            'close': close_list, 'volume': vol_list,
        }, index=dates)

        p = dict(DEFAULT_PARAMS)
        result1 = _calc_box_breakout_conditions(df1, p)
        last_before = result1.iloc[-1].copy()

        close_list2 = close_list[:-1] + [999.0]
        high_list2 = [c + 0.5 for c in close_list2]
        low_list2 = [c - 0.5 for c in close_list2]
        df2 = pd.DataFrame({
            'open': close_list2, 'high': high_list2, 'low': low_list2,
            'close': close_list2, 'volume': vol_list,
        }, index=dates)

        result2 = _calc_box_breakout_conditions(df2, p)
        last_after = result2.iloc[-1]

        self.assertFalse(np.isnan(last_before['box_箱顶']))
        self.assertFalse(np.isnan(last_after['box_箱顶']))
```

替换为（**真正的 lookahead 测试：篡改前面的数据后，比较倒数第二天及更早的输出不变**；并新增 `near_high` 不含当日的断言）：
```python
    def test_no_lookahead_hhv(self):
        """无未来数据: 篡改第 30 行的数据, 第 0..29 行的指标输出必须保持不变.
        若发现某行输出受到未来数据影响, 说明 HHV/LLV/REF 等含 lookahead 漏洞.
        """
        n = 100
        dates = pd.date_range('2026-01-01', periods=n)
        close_list = [10.0 + i * 0.1 for i in range(n)]
        high_list = [c + 0.5 for c in close_list]
        low_list = [c - 0.5 for c in close_list]
        vol_list = [1000.0 + i * 10.0 for i in range(n)]

        df1 = pd.DataFrame({
            'open': close_list, 'high': high_list, 'low': low_list,
            'close': close_list, 'volume': vol_list,
        }, index=dates)

        p = dict(DEFAULT_PARAMS)
        result1 = _calc_box_breakout_conditions(df1, p)

        # 篡改第 30 行 high 到一个极端值
        TAMPER_IDX = 30
        high_list2 = list(high_list)
        high_list2[TAMPER_IDX] = 999.0
        df2 = pd.DataFrame({
            'open': close_list, 'high': high_list2, 'low': low_list,
            'close': close_list, 'volume': vol_list,
        }, index=dates)

        result2 = _calc_box_breakout_conditions(df2, p)

        # 第 0..29 行的所有 box_* 指标必须不受第 30 行篡改影响
        for i in range(0, TAMPER_IDX):
            for col in result1.columns:
                v1 = result1.iloc[i][col]
                v2 = result2.iloc[i][col]
                if isinstance(v1, float) and np.isnan(v1):
                    self.assertTrue(np.isnan(v2),
                        '行 %d 列 %s: 篡改后变为 %s, 应仍为 NaN (lookahead!)' % (i, col, v2))
                else:
                    self.assertEqual(v1, v2,
                        '行 %d 列 %s: 篡改前 %s, 篡改后 %s (lookahead!)' % (i, col, v1, v2))

    def test_no_lookahead_near_high(self):
        """近期高点 = REF(HHV(HIGH,20),1) 必须不含当日 high.
        构造: 倒数第二天前的 HIGH 都是 10, 最后一天 HIGH=100.
        近期高点 在最后一日应是 REF(HHV([10,...,10,100],20),1) = HHV([10,...,10],20)
        = 10, 而不是 100. 严格 < 当日 high.
        """
        n = 100
        dates = pd.date_range('2026-01-01', periods=n)
        high = [10.0] * (n - 1) + [100.0]
        close = high
        df = pd.DataFrame({
            'open': close, 'high': high, 'low': [c - 0.5 for c in close],
            'close': close, 'volume': [1000.0] * n,
        }, index=dates)
        index_df = pd.DataFrame({'close': [3000.0 + i for i in range(n)]}, index=dates)
        p = dict(DEFAULT_PARAMS)
        result = _calc_double_zhongjun_conditions(df, index_df, p)
        # 最后一行 近期高点 必须 = 10 (不是 100, 不含当日)
        last_near_high = result.iloc[-1]['double_近期高点']
        self.assertAlmostEqual(last_near_high, 10.0, places=4,
            msg='近期高点 取到了当日 high=100, 含 lookahead!')
```

### TASK-3. 新增 `huang_main_uptrend_combo/config.yaml`

**编码 utf-8**，结构按 SPEC §D 全 24 项参数 + 注释：

```yaml
# 黄氏主升浪「箱体突破初选 + 双中军精筛」组合选股配置
# SPEC: D:/QMT_STRATEGIES/specs/SPEC_HUANG_MAIN_UPTREND_TDX_TO_QMT.md
# 所有默认值必须与 SPEC §D 一致, 不得擅改

# ===== 箱体突破版（初选层） =====
box:
  N: 60                    # 箱体观察周期（日）
  amp_thresh: 20.0         # 箱体振幅阈值 <20%
  ma_short: 5              # MA_SHORT, 原公式定义但未参与 XG, 保留不参与
  ma_adhere_thresh: 5.0    # 均线差阈值 <5%
  vol_ratio: 1.5           # V > MA(V,5) * 1.5
  break_tol: 0.995         # C >= 箱顶 * 0.995
  pct_thresh: 0.05         # 涨幅阈值 >0.05

# ===== 双中军版（精筛层） =====
zhongjun:
  ma5: 5
  ma10: 10
  ma20: 20
  ma60: 60
  ma120: 120
  angle_thresh: 30.0       # MA5 角度阈值 >30
  divergence_thresh: 1.05  # MA5/MA20 发散阈值 >1.05
  macd_fast: 12            # MACD DIF EMA 快线
  macd_slow: 26            # MACD DIF EMA 慢线
  macd_signal: 9           # MACD DEA EMA 周期
  cci_period: 14
  cci_thresh: 100.0
  breakout_N: 20           # 突破压力位回看周期
  breakout_upper: 1.08     # CLOSE/近期高点 <1.08
  ma20_up_n: 5             # MA20 向上回看周期
  ma60_up_n: 5             # MA60 向上回看周期

# ===== 大盘指数 (INDEXC) =====
benchmark:
  code: '000001.SH'        # 上证综指（诚哥 2026-06-23 拍板）
```

### TASK-4. 新增 `huang_main_uptrend_combo/reports/tdx_mapping_report.md`

**编码 utf-8**，建目录 `huang_main_uptrend_combo/reports/`，写表格 + 注意点：

```markdown
# 黄氏主升浪策略 TDX → Python 映射报告

源 SPEC: `D:/QMT_STRATEGIES/specs/SPEC_HUANG_MAIN_UPTREND_TDX_TO_QMT.md`
目标模块: `huang_main_uptrend_combo/huang_main_uptrend_combo_selector.py`
生成日期: <填本工单执行日 yyyy-mm-dd>

---

## 一、TDX 工具函数映射表

| 通达信函数 | Python 映射 | selector.py 行号 | 注意点 |
|---|---|---:|---|
| `MA(X,N)` | `s.rolling(window=n, min_periods=n).mean()` | 46-48 | `min_periods=n` 保证 N 日内返 NaN，与通达信"前 N-1 日无值"一致 |
| `EMA(X,N)` | `s.ewm(alpha=2/(n+1), adjust=False).mean()` | 51-53 | 通达信口径 alpha=2/(N+1)，首值取 X[0]，递归 |
| `REF(X,N)` | `s.shift(n)` | 56-58 | 仅向后引用，前 N 日 NaN |
| `HHV(X,N)` | `s.rolling(window=n, min_periods=n).max()` | 61-63 | 含当日；常配合 `REF(...,1)` 实现"不含当日" |
| `LLV(X,N)` | `s.rolling(window=n, min_periods=n).min()` | 66-68 | 含当日 |
| `CROSS(A,B)` | `(a > b) & (a.shift(1) <= b.shift(1))` | 71-73 | 当日 A>B 且昨日 A<=B；首日 NaN/False |
| `COUNT(COND,N)` | `cond.astype(float).rolling(n, min_periods=n).sum()` | 76-78 | 返回浮点；前 N-1 日 NaN |
| `AVEDEV(X,N)` | `rolling.apply(lambda x: mean(abs(x-mean(x))))` | 81-85 | 平均绝对偏差；与 numpy std 不同 |
| `ATAN(x)*180/3.1416` | `np.degrees(np.arctan(x))` | 175 | 角度换算；arctan + np.degrees 等价 |
| `INDEXC` | 显式传入 `index_df['close']` 后 `reindex(df.index, method='ffill')` | 222-223 | 默认 `000001.SH` 上证综指（config benchmark.code） |

---

## 二、箱体突破层 公式逐行映射

| TDX 原公式 | selector.py 行号 | Python 实现 |
|---|---:|---|
| `N:=60` | DEFAULT_PARAMS['box_N']=60 | 参数 |
| `MA_SHORT:=5` | DEFAULT_PARAMS['box_ma_short']=5 | **保留参数不参与 XG**（SPEC §A 第 3 条） |
| `箱顶:=HHV(H,N)` | 103 | `tdx_hhv(df['high'], N)` |
| `箱底:=LLV(L,N)` | 104 | `tdx_llv(df['low'], N)` |
| `箱体振幅:=(箱顶-箱底)/箱底*100` | 105 | `(hi - lo) / lo * 100` |
| `均线差1:=ABS(MA5-MA10)/MA5*100` | 111 | `(MA5-MA10).abs()/MA5*100` |
| `均线差2:=ABS(MA10-MA20)/MA10*100` | 112 | 同上结构 |
| `均线黏连:=均线差1<5 AND 均线差2<5` | 127 | `(差1<5) & (差2<5)` |
| `前5日量:=MA(V,5)` | 115 | `tdx_ma(volume, 5)` |
| `放量:=V>前5日量*1.5` | 128 | `volume > MA(V,5)*1.5` |
| `突破:=C>=箱顶*0.995` | 129 | `close >= 箱顶*0.995` |
| `涨幅:=C/REF(C,1)-1` | 117 | `close/tdx_ref(close,1) - 1` |
| `XG: 振幅<20 AND 黏连 AND 放量 AND 突破 AND 涨幅>0.05` | 132-135 | 5 项 `& ` |

---

## 三、双中军层 公式逐行映射

| TDX 原公式 | selector.py 行号 | Python 实现 |
|---|---:|---|
| `MA5/10/20/60/120` | 159-163 | `tdx_ma(close, n)` × 5 |
| `多头排列条件` | 169-171 | `(MA5>MA10) & (MA10>MA20) & (MA20>MA60) & (MA60>MA120)` |
| `发散确认:=CLOSE>MA20` | — | **原公式定义但未参与 XG**, 代码中亦未加入（SPEC §B 第 1 条） |
| `MA5角度:=ATAN((MA5/REF(MA5,1)-1)*100)*180/3.1416` | 174-175 | `np.degrees(np.arctan(angle_pct))` |
| `均线发散条件 := MA5角度>30 AND MA5/MA20>1.05` | 176-179 | 2 项 `&` |
| `DIF:=EMA(C,12)-EMA(C,26)` | 182 | `tdx_ema(close,12) - tdx_ema(close,26)` |
| `DEA:=EMA(DIF,9)` | 183 | `tdx_ema(DIF, 9)` |
| `MACD红柱:=(DIF-DEA)*2` | 186 | **未参与 XG**（SPEC §B 第 2 条），仅 debug 字段 |
| `MACD条件 := (CROSS(DIF,DEA) AND DEA>0) OR (DIF>DEA AND DIF>REF(DIF,1) AND DEA>REF(DEA,1))` | 187-190 | OR 双分支 |
| `TYP:=(H+L+C)/3` | 193 | `(high+low+close)/3` |
| `CCI14 := (TYP-MA(TYP,14))/(0.015*AVEDEV(TYP,14))` | 196 | 通达信 CCI 标准公式 |
| `CCI条件 := CROSS(CCI14,100) OR (CCI14>100 AND CCI14>REF(CCI14,1))` | 199-202 | OR 双分支；`pd.Series(100)` 作为常数序列入参 |
| `N:=20; 近期高点:=REF(HHV(HIGH,N),1)` | 206 | `tdx_ref(tdx_hhv(high, 20), 1)` **不含当日** |
| `突破压力条件 := CLOSE>近期高点 AND CLOSE/近期高点<1.08` | 208-210 | 2 项 `&` |
| `MA20向上 := MA20 > REF(MA20,5)` | 213 | `MA20 > tdx_ref(MA20, 5)` |
| `MA60向上 := MA60 > REF(MA60,5)` | 214 | 同上 |
| `大盘指数 := INDEXC` | 222-223 | `index_df['close'].reindex(df.index, method='ffill')` |
| `大盘MA20/60` | 224-225 | `tdx_ma(idx_close, 20/60)` |
| `大盘条件 := 大盘指数>大盘MA20 AND 大盘MA20>大盘MA60` | 229-231 | 2 项 `&` |
| `主升浪启动 := 8 项 AND` | 234-243 | 8 项 `&` |

---

## 四、最终组合

```text
combo_XG = box_breakout_XG AND double_zhongjun_XG  (selector.py:279)
```

`select_huang_main_uptrend_combo(data, index_data, params)` 主入口（247-286）三步执行：
1. `_calc_box_breakout_conditions` → box_breakout_XG
2. `_calc_double_zhongjun_conditions` → double_zhongjun_XG
3. AND 组合 → combo_XG

---

## 五、关键决策点

| 决策点 | 选择 | 理由/来源 |
|---|---|---|
| EMA alpha | `2/(N+1)`, `adjust=False` | 通达信口径 |
| INDEXC 默认 | `000001.SH` 上证综指 | 诚哥 2026-06-23 拍板 |
| 滚动窗口 NaN | `min_periods=n` | 与通达信"前 N-1 日无值"一致 |
| `*_ok` 子条件 NaN | `.fillna(False)` | 保证起步阶段不污染最终 XG |
| `MA_SHORT=5` / `发散确认` / `MACD红柱` | 保留计算但**不参与最终 XG** | SPEC §A 第 3 条 / §B 第 1-2 条 |
| 大盘指数缺失 | 大盘条件全 False（保守不选股）| 无指数数据时无法判断大盘环境 |

---

## 六、验证状态

| 项 | 状态 |
|---|---|
| 公式语义已复刻 | ✓ |
| 17 个单测全 PASS | ✓ |
| 8 个 TDX 工具函数手算对比 | ✓ |
| HHV/LLV/REF 无 lookahead | ✓（test_no_lookahead_hhv + test_no_lookahead_near_high） |
| 逻辑合理性 | 待最小样本验证（见 validation_report.md） |
| 收益效果 | 待回测（不属于本 SPEC 范围）|
```

### TASK-5. 新增 `huang_main_uptrend_combo/reports/validation_report.md` + 生成脚本

**编码 utf-8**，建立一个一次性脚本 `huang_main_uptrend_combo/reports/_run_validation.py`，构造 3 个不同形态的样本股 + 1 个样本大盘，跑 selector 输出条件明细表 + 写报告。

**脚本** `huang_main_uptrend_combo/reports/_run_validation.py`：

```python
# coding=utf-8
"""黄氏主升浪 combo selector 最小样本验证.
生成 reports/validation_detail.csv 和回填 reports/validation_report.md.
独立运行: python huang_main_uptrend_combo/reports/_run_validation.py
"""
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

import numpy as np
import pandas as pd

from huang_main_uptrend_combo.huang_main_uptrend_combo_selector import (
    select_huang_main_uptrend_combo, DEFAULT_PARAMS,
)


def _make_index(n, start=3000.0, step=2.0):
    """大盘指数: 单调上升, 满足 大盘指数>MA20>MA60"""
    dates = pd.date_range('2026-01-01', periods=n)
    close = [start + i * step for i in range(n)]
    return pd.DataFrame({'close': close}, index=dates)


def _make_stock_A_combo_pass(n=150):
    """A 股: 130 天窄幅震荡 + 19 天温和上涨 + 最后一天 6% 跳涨, 满足 combo"""
    dates = pd.date_range('2026-01-01', periods=n)
    closes = []
    for i in range(n):
        if i < 130:
            c = 10.0 + (i % 5) * 0.01
        elif i < n - 1:
            c = 10.04 + (i - 130) * 0.06
        else:
            prev = 10.04 + (n - 2 - 130) * 0.06
            c = prev * 1.06
        closes.append(c)
    return pd.DataFrame({
        'open': closes, 'high': closes, 'low': [c - 0.1 for c in closes],
        'close': closes,
        'volume': [10000.0 if i == n - 1 else 1000.0 for i in range(n)],
    }, index=dates)


def _make_stock_B_box_only(n=150):
    """B 股: 满足箱体突破但不满足双中军 (例: MA60 平台, 无多头排列)"""
    dates = pd.date_range('2026-01-01', periods=n)
    closes = [10.0 + (i % 3) * 0.05 for i in range(n - 1)] + [10.7]
    return pd.DataFrame({
        'open': closes, 'high': closes, 'low': [c - 0.1 for c in closes],
        'close': closes,
        'volume': [10000.0 if i == n - 1 else 1000.0 for i in range(n)],
    }, index=dates)


def _make_stock_C_neither(n=150):
    """C 股: 缩量横盘, 既不满足箱体突破也不满足双中军"""
    dates = pd.date_range('2026-01-01', periods=n)
    closes = [10.0 + (i % 7) * 0.02 for i in range(n)]
    return pd.DataFrame({
        'open': closes, 'high': closes, 'low': [c - 0.05 for c in closes],
        'close': closes, 'volume': [1000.0] * n,
    }, index=dates)


def main():
    n = 150
    data = {
        'A_组合通过': _make_stock_A_combo_pass(n),
        'B_只过箱体': _make_stock_B_box_only(n),
        'C_全部不过': _make_stock_C_neither(n),
    }
    index_df = _make_index(n)
    result = select_huang_main_uptrend_combo(data, index_df)

    # 只看最后一日
    last_per_code = result.groupby('code').tail(1).reset_index(drop=True)

    cols = [
        'code', 'date',
        'box_breakout_XG',
        'box_箱体振幅_ok', 'box_均线黏连_ok', 'box_放量_ok',
        'box_突破_ok', 'box_涨幅_ok',
        'double_zhongjun_XG',
        'double_多头排列_ok', 'double_均线发散_ok', 'double_MACD_ok',
        'double_CCI_ok', 'double_突破压力_ok',
        'double_MA20向上_ok', 'double_MA60向上_ok', 'double_大盘_ok',
        'combo_XG',
    ]
    detail = last_per_code[cols]
    out_csv = os.path.join(os.path.dirname(__file__), 'validation_detail.csv')
    detail.to_csv(out_csv, index=False, encoding='utf-8')

    # 统计
    n_box = int(last_per_code['box_breakout_XG'].sum())
    n_zhongjun = int(last_per_code['double_zhongjun_XG'].sum())
    n_combo = int(last_per_code['combo_XG'].sum())

    print('=== 最小样本验证结果 ===')
    print('样本股数:', len(data))
    print('通过箱体突破初选:', n_box)
    print('通过双中军精筛:', n_zhongjun)
    print('最终通过 combo:', n_combo)
    print()
    print(detail.to_string(index=False))

    return detail, n_box, n_zhongjun, n_combo


if __name__ == '__main__':
    main()
```

**跑脚本**：

```bash
cd D:/QMT_STRATEGIES
python huang_main_uptrend_combo/reports/_run_validation.py
```

把完整输出贴回执。

**然后**写 `huang_main_uptrend_combo/reports/validation_report.md`（**真实回填脚本输出**，不要 placeholder）：

```markdown
# 黄氏主升浪 combo selector 最小样本验证报告

源 SPEC: `D:/QMT_STRATEGIES/specs/SPEC_HUANG_MAIN_UPTREND_TDX_TO_QMT.md`
SPEC §Testing 第 5 条要求项验证。

执行日期: <填本工单 date 真实值>
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
| 通过箱体突破初选 | <填脚本输出> |
| 通过双中军精筛 | <填脚本输出> |
| 最终通过 combo | <填脚本输出> |

---

## 三、最后一日条件明细表

<把脚本输出的 detail.to_string(index=False) 贴在这里>

---

## 四、逐样本解释

### A_组合通过
- 通过的 box_*_ok: <从 detail 表读>
- 通过的 double_*_ok: <从 detail 表读>
- combo_XG: <True>
- 说明：130 天窄幅震荡使 60 日振幅<20%，均线黏连成立；19 天温和上涨使 MA5>MA10>MA20>MA60>MA120 形成多头排列；最后一天放量+大涨触发箱体突破、CCI、MACD、压力位突破等所有条件。

### B_只过箱体
- 通过的 box_*_ok: <从 detail 表读>
- 通过的 double_*_ok: <从 detail 表读>
- combo_XG: <False>
- 说明：单日突破横盘平台满足箱体条件，但因无多头排列/角度<30/MACD 未金叉等原因被双中军精筛过滤。

### C_全部不过
- 通过的 box_*_ok: <从 detail 表读>
- 通过的 double_*_ok: <从 detail 表读>
- combo_XG: <False>
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
```

### TASK-6. 跑全单测 + 完整性验证

```bash
cd D:/QMT_STRATEGIES

# 6a. 新模块单测（含补强的 lookahead 测试 + 1 个新增近期高点测试）
python -m unittest huang_main_uptrend_combo.tests.test_huang_main_uptrend_combo_selector -v

# 6b. P1+P2+P3 回归
python -m unittest tests.test_risk_timegate_p1 tests.test_risk_timegate_p2 tests.test_risk_timegate_p3 -v
```

期望：
- 6a: 18 PASS（原 17 + 新增 test_no_lookahead_near_high，原 test_no_lookahead_hhv 整段替换更严格）
- 6b: 37 PASS

**任一 FAIL 立刻停下报告**。把两步最后 5 行贴回执。

### TASK-7. 精确 add + commit（7 文件）

```bash
cd D:/QMT_STRATEGIES
git add huang_main_uptrend_combo/__init__.py
git add huang_main_uptrend_combo/huang_main_uptrend_combo_selector.py
git add huang_main_uptrend_combo/tests/__init__.py
git add huang_main_uptrend_combo/tests/test_huang_main_uptrend_combo_selector.py
git add huang_main_uptrend_combo/config.yaml
git add huang_main_uptrend_combo/reports/tdx_mapping_report.md
git add huang_main_uptrend_combo/reports/validation_report.md
git add huang_main_uptrend_combo/reports/_run_validation.py
git add huang_main_uptrend_combo/reports/validation_detail.csv
git add agent_hub/2026-06-23_huang_main_uptrend/Mimo_HUANG_PART1_SELECTOR.md
git add agent_hub/2026-06-23_huang_main_uptrend/Mimo_HUANG_PART2_REPORTS.md
```

**严禁** `git add .` / `git add -A` / `git add huang_main_uptrend_combo/`（整目录）。

验证 staged 范围：

```bash
git diff --cached --name-only
```

**期望输出（且只有这 11 行）**：
```
agent_hub/2026-06-23_huang_main_uptrend/Mimo_HUANG_PART1_SELECTOR.md
agent_hub/2026-06-23_huang_main_uptrend/Mimo_HUANG_PART2_REPORTS.md
huang_main_uptrend_combo/__init__.py
huang_main_uptrend_combo/config.yaml
huang_main_uptrend_combo/huang_main_uptrend_combo_selector.py
huang_main_uptrend_combo/reports/_run_validation.py
huang_main_uptrend_combo/reports/tdx_mapping_report.md
huang_main_uptrend_combo/reports/validation_detail.csv
huang_main_uptrend_combo/reports/validation_report.md
huang_main_uptrend_combo/tests/__init__.py
huang_main_uptrend_combo/tests/test_huang_main_uptrend_combo_selector.py
```

把输出贴回执。**staged 多/少任何一个文件立刻停下报告，禁止 commit**。

```bash
git commit -m "$(cat <<'EOF'
feat(selector): 黄氏主升浪「箱体突破初选 + 双中军精筛」组合选股复刻

新增（纯离线选股模块, 不接 QMT 实盘）:
- huang_main_uptrend_combo/huang_main_uptrend_combo_selector.py:
  * 8 个 TDX→Python 映射函数 (tdx_ma/ema/ref/hhv/llv/cross/count/avedev)
  * _calc_box_breakout_conditions: 箱体突破 5 项子条件
  * _calc_double_zhongjun_conditions: 双中军 8 项子条件
  * select_huang_main_uptrend_combo: 主入口
  * combo_XG = box_breakout_XG AND double_zhongjun_XG
- config.yaml: SPEC §D 24 项参数 (INDEXC=000001.SH 上证综指)
- reports/tdx_mapping_report.md: 通达信公式逐行映射 + 行号对照
- reports/validation_report.md: 最小样本验证 (3 股 × 150 日)
- reports/_run_validation.py + validation_detail.csv: 验证脚本与明细
- tests/test_huang_main_uptrend_combo_selector.py: 18 单测全 PASS
  * 8 TDX 映射 + 2 箱体 + 2 双中军 + 2 combo + 4 完整性/边界 (含 2 个 lookahead 严格测试)

37 P1+P2+P3 回归全 PASS。本模块离线纯 Python, 不进 build_strategy.py。
不动 adapters/qmt_wrapper.py / strategy_*.py / core/。

Refs: specs/SPEC_HUANG_MAIN_UPTREND_TDX_TO_QMT.md
EOF
)"

git log -1 --stat HEAD
```

把 `git log -1 --stat HEAD` 完整输出贴回执。

### TASK-8. 最终核查

```bash
cd D:/QMT_STRATEGIES
git status --short huang_main_uptrend_combo/
ls huang_main_uptrend_combo/
ls huang_main_uptrend_combo/reports/
```

期望：
- `git status --short` 无输出（全部已 commit）
- 目录结构完整：`__init__.py`, `huang_main_uptrend_combo_selector.py`, `config.yaml`, `tests/`, `reports/`
- `reports/` 含：`tdx_mapping_report.md`, `validation_report.md`, `_run_validation.py`, `validation_detail.csv`

贴输出。

---

## 二、严禁

1. **严禁** `git add .` / `git add -A` / `git add huang_main_uptrend_combo/`（整目录 add）
2. **严禁** push / amend / --no-verify / --force
3. **严禁** 改 `selector.py` 已有逻辑（只允许追加 README/config/reports；本工单不应修改 selector.py 任何一行；TASK-2 仅改 tests 文件）
4. **严禁** 改 `adapters/qmt_wrapper.py` / `strategy_*.py` / `core/` / 现有 `tests/test_risk_*`
5. **严禁** 改 `scripts/build_strategy.py` 把本模块加进生产构建（本模块离线）
6. **严禁** 引入 mock/passorder/xttrader/xtquant
7. **严禁** 用 placeholder 时间戳 / placeholder 报告内容（validation_report.md 必须真实回填脚本输出）
8. **严禁段加死**：config.yaml 所有键都要有对应代码消费（box_ma_short 例外, SPEC §A 第 3 条注明保留不参与）
9. **遇任一异常必停**：单测 FAIL / staged 范围异常 / commit 报错——立刻停下报告，**不得自判"无关"继续**
10. **回执只能在工单 EOF 追加**

---

## 三、完成回执（在工单 EOF 追加）

```markdown

---

## 完成回执

**执行时间**: <真实 date -u 输出>
**MIMO 模型**: <实际名>

### TASK-0: 真实时间戳
<贴 date 输出>

### TASK-1: 预检
<贴 git status + git log + ls 输出>

### TASK-2: test_no_lookahead_hhv 补强 + test_no_lookahead_near_high 新增
- [ ] test_no_lookahead_hhv 改为篡改第30行+断言0..29行所有列不变
- [ ] test_no_lookahead_near_high 新增

### TASK-3: config.yaml
- [ ] 24 项参数（与 SPEC §D 一致）
- [ ] benchmark.code='000001.SH'

### TASK-4: tdx_mapping_report.md
- [ ] 10 行 TDX 工具函数映射表
- [ ] 箱体突破公式逐行映射表
- [ ] 双中军公式逐行映射表
- [ ] 关键决策点表

### TASK-5: validation_report.md + 脚本
**脚本输出**:
<贴 _run_validation.py 完整 stdout>

**validation_report.md 已真实回填**:
- [ ] 通过箱体: <填数值>
- [ ] 通过双中军: <填数值>
- [ ] 通过 combo: <填数值>
- [ ] 3 个样本逐条解释已写

### TASK-6: 单测 + 回归
**6a 新模块单测（18 PASS）**:
<贴 unittest -v 最后 5 行>

**6b P1+P2+P3 回归（37 PASS）**:
<贴最后 5 行>

### TASK-7: git diff --cached --name-only + commit
**staged 11 文件**:
<贴 git diff --cached --name-only 输出, 必须 11 行>

**commit log**:
<贴 git log -1 --stat HEAD 完整输出>

### TASK-8: 最终核查
<贴 git status --short + ls 输出>

### 自检
- [ ] 时间戳真跑 date 命令
- [ ] staged 只有 11 个文件
- [ ] commit 成功，未 push / amend / --no-verify
- [ ] 新模块单测 18 PASS（含 2 个严格 lookahead 测试）
- [ ] P1+P2+P3 回归 37 PASS
- [ ] config.yaml 24 项参数与 SPEC §D 一致
- [ ] validation_report.md 真实回填脚本输出
- [ ] tdx_mapping_report.md 含 10 项工具函数 + 双层公式逐行映射
- [ ] 未改 adapters/qmt_wrapper.py / strategy_*.py / core/
- [ ] 回执在工单 EOF 追加（未插中间）
```
