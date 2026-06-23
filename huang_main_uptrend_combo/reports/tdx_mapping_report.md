# 黄氏主升浪策略 TDX → Python 映射报告

源 SPEC: `D:/QMT_STRATEGIES/specs/SPEC_HUANG_MAIN_UPTREND_TDX_TO_QMT.md`
目标模块: `huang_main_uptrend_combo/huang_main_uptrend_combo_selector.py`
生成日期: 2026-06-23

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
| `INDEXC` | 显式传入 `index_df['close']` 后 `reindex(df.index, method='ffill')` | 223 | 默认 `000001.SH` 上证综指（config benchmark.code） |

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
| `大盘指数 := INDEXC` | 223 | `index_df['close'].reindex(df.index, method='ffill')` |
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
