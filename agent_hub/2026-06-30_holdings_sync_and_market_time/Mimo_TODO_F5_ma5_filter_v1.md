# 工单F5：main 版 _execute_trade 补 MA5 乖离过滤（对齐全天版 line 3221）

**日期**: 2026-06-30
**作者**: CC
**目的**: main 版 `_execute_trade` 选股循环缺 MA5 乖离过滤(全天版 `_execute_full_cycle` line 3221 有),导致 main 版会追高买入乖离率>10% 的票。补齐,对齐全天版顺序(check_buy→MA5→ST)。这是 F 系列最后一个工单。
**预计工时**: ≤ 15 分钟

---

## 〇、背景（必读，不要改这段）

排查发现:全天版 `_execute_full_cycle`(line 3221)有 `_passes_buy_bias_filter`(MA5 乖离率>10% 跳过,防追高),但 main 版 `_execute_trade` 的选股循环(line 2893-2905)自己内联了 check_buy+ST,**漏了 MA5 过滤**。

`_passes_buy_bias_filter`(line 1184):检查 MA5 乖离率 > `MAX_BUY_BIAS5`(10.0%, line 150)则跳过。是好的过滤,main 版应补齐。

诚哥拍板:插在 check_buy 之后、ST 之前,对齐全天版顺序。

---

## 一、必做（2 项）

### TASK-1. 在 _execute_trade 选股循环插入 MA5 过滤

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`（`_execute_trade` 函数，line 2899-2905）

**当前代码**（line 2899-2905）：
```python
        buy, signal, buy_type = check_buy(df)
        if not buy:
            continue
        if _is_st_stock(code, C):
            print("  [ST过滤] %s 跳过" % code)
            continue
        signal_candidates.append({'code': code, 'signal': signal, 'buy_type': buy_type})
```

**改为**（在 `if not buy: continue` 之后、`if _is_st_stock` 之前插入一行）：
```python
        buy, signal, buy_type = check_buy(df)
        if not buy:
            continue
        if not _passes_buy_bias_filter(code, df, label='盘中买入过滤'):
            continue
        if _is_st_stock(code, C):
            print("  [ST过滤] %s 跳过" % code)
            continue
        signal_candidates.append({'code': code, 'signal': signal, 'buy_type': buy_type})
```

**关键**：
- 用现有的 `_passes_buy_bias_filter(code, df, label=...)`(line 1184),不要新写。
- 插入位置精确:`if not buy: continue`(line 2900-2901)之后、`if _is_st_stock`(line 2902)之前。
- label 用 `'盘中买入过滤'`(对齐全天版用 `'全天买入过滤'` 的命名风格)。
- **只插一行,不动其他**。

### TASK-2. 验证

**目标路径**: `D:/QMT_STRATEGIES/`

**内容/做法**:
1. `python scripts/build_strategy.py` + `python scripts/build_strategy.py --allday`
2. 两个 validate 都 6 项 ALL PASS：
   - `python scripts/validate_qmt_file.py strategy_main.py`
   - `python scripts/validate_qmt_file.py strategy_allday.py`
3. grep 确认：
   ```bash
   grep -n "盘中买入过滤" adapters/qmt_wrapper.py
   # main 版 build 产物含此标记
   iconv -f GBK -t UTF-8 strategy_main.py | grep -c "盘中买入过滤"
   ```
   贴 grep + validate。

---

## 二、严禁

1. 禁止 git add / commit / push
2. 禁止改动本工单上方
3. 禁止做工单外动作
4. 禁止改 `_passes_buy_bias_filter` 函数本身
5. 禁止改全天版 `_execute_full_cycle` 的 MA5 过滤(已有,不动)
6. 禁止动 F1/F2/F3 已改的全天版代码
7. 禁止改 _execute_trade 的其他逻辑(只插一行 MA5 过滤)
8. 禁止跑实盘/模拟交易验证
9. **文件编码 GBK，`# coding=gbk`；禁止 patch 工具直接编辑，用 Read+Edit；Python 3.6.8 语法（禁 f-string/dict[str,..]/walrus/match-case），用 % 格式化**

---

## 三、完成回执（MIMO 在工单末尾追加）

```markdown

---

## 完成回执

**执行时间**: <用 `date -u +"%Y-%m-%dT%H:%M:%SZ"` 真实拿，禁止 placeholder>
**MIMO 模型**: <实际模型名>
**自检**:
- [ ] TASK-1: _execute_trade 选股循环已插入 MA5 过滤（check_buy后ST前），贴改后代码块
- [ ] TASK-2: strategy_main.py + strategy_allday.py 都 build + validate 6 项 ALL PASS + grep，贴输出
- [ ] 未动 _passes_buy_bias_filter / 全天版 / F1-F3 代码 / _execute_trade 其他逻辑
- [ ] 仅末尾追加，未改动工单上方
    - [ ] 无 git 操作 / 无实盘模拟交易
```

---

## 完成回执

**执行时间**: 2026-06-30T07:29:13Z
**MIMO 模型**: mimo/mimo-auto
**自检**:
- [x] TASK-1: _execute_trade 选股循环已插入 MA5 过滤（check_buy后ST前）：
  ```python
        buy, signal, buy_type = check_buy(df)
        if not buy:
            continue
        if not _passes_buy_bias_filter(code, df, label='盘中买入过滤'):
            continue
        if _is_st_stock(code, C):
            print("  [ST过滤] %s 跳过" % code)
            continue
        signal_candidates.append({'code': code, 'signal': signal, 'buy_type': buy_type})
  ```
- [x] TASK-2: strategy_main.py + strategy_allday.py 都 build + validate 6 项 ALL PASS + grep（grep -c 结果=1）
- [x] 未动 _passes_buy_bias_filter / 全天版 / F1-F3 代码 / _execute_trade 其他逻辑
- [x] 仅末尾追加，未改动工单上方
- [x] 无 git 操作 / 无实盘模拟交易
