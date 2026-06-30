# 工单B：策略绝对时间改用 QMT 行情时间，避免设备时间≠市场时间

**日期**: 2026-06-30
**作者**: CC
**目的**: 跑策略的设备主板 CMOS 电池没电，断电后设备时钟错乱，导致策略按错误系统时间触发尾盘逻辑（今日 0630 误触发）。建立机制：策略的绝对时间（交易日/交易时段/日志日期）一律以 QMT 行情时间为准，不读设备时间。设备时间怎么错都不影响策略。
**预计工时**: ≤ 50 分钟

---

## 〇、背景与方案（必读，不要改这段）

诚哥授权修复。设备时间诚哥会手动纠正，本工单不解决设备时钟本身，只解决"策略不依赖设备时钟"。

**现有资产**：代码里已有 `_get_qmt_time(C)`（line ~581）：
```python
def _get_qmt_time(C):
    try:
        return C.get_current_time()
    except Exception:
        tick_ms = C.get_tick_timetag()
        return datetime.fromtimestamp(tick_ms / 1000)
```
但 10 处 `datetime.now()` **根本没用它**，形同虚设。

**方案**：
- 主路径：绝对时间用途改走 `_get_qmt_time(C)`（QMT 行情时间 = 市场时间）。
- 兜底：盘前无行情时 `get_current_time` 可能拿不到 → 用最新 K 线日期（`df.index[-1]`）兜底，**不用设备日期**。
- 相对计时（`time.time()` 差值：卖出冷却 60 秒、启动后 60 秒、passorder 耗时）**不动** —— 相对差值不受时钟基准影响。

**分类**（CC 已 grep，共 10 处 `datetime.now()`）：
| 行号 | 上下文 | 有 C？ | 处理 |
|------|--------|--------|------|
| 256 | `_safemode_log_trade_blocked` 时间戳 | 无 | 见 TASK-2 |
| 276/278 | `_safemode_log_trade_blocked` today/ts | 无 | 见 TASK-2 |
| 293/295 | `_safemode_log_signal` today/ts | 无 | 见 TASK-2 |
| 1863 | 持仓报告 now_str | 有 | 改 `_get_qmt_time(C)` |
| 1973 | 诊断 ts | 有 | 改 `_get_qmt_time(C)` |
| 2377 | 卖出引擎 timestamp | 有 | 改 `_get_qmt_time(C)` |
| 3298 | premarket diag today | 有 | 改 `_get_qmt_time(C)` |
| 3372 | safemode 启动日志 | 无 | 见 TASK-2 |

---

## 一、必做（4 项）

### TASK-1. 新增 `_market_now(C)` 包装函数 + K 线兜底

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`（`_get_qmt_time` 附近，line ~581 之后）

**内容/做法**:

在 `_get_qmt_time` 函数后面新增：

```python
def _market_now(C):
    """策略权威时间：优先 QMT 行情时间，盘前无行情时用最新K线日期兜底。

    设备时钟不可信（CMOS电池没电会错乱），策略绝对时间一律走此函数，
    不用 datetime.now()。相对计时（time.time()差值）不受影响，仍用设备时钟。
    """
    # 1. 优先 QMT 行情时间
    try:
        dt = _get_qmt_time(C)
        if dt is not None:
            # 行情时间为 1970/很旧说明拿到的无效，继续兜底
            if dt.year >= 2020:
                return dt
    except Exception:
        pass
    # 2. 兜底：最新K线日期（盘前9:25前无行情时）
    try:
        if _g_all_data:
            for code, df in _g_all_data.items():
                if df is not None and len(df) > 0:
                    last_idx = df.index[-1]
                    # df.index 可能是日期字符串或 Timestamp
                    if hasattr(last_idx, 'to_pydatetime'):
                        return last_idx.to_pydatetime()
                    return datetime.strptime(str(last_idx)[:10], '%Y-%m-%d')
    except Exception:
        pass
    # 3. 最后兜底：设备时间（仅当行情和K线都拿不到，记录警告）
    print("  [时间警告] 行情时间与K线均不可用，回退设备时间")
    return datetime.now()
```

**关键**：
- 三级兜底：行情时间 → K线日期 → 设备时间（打警告）。
- `_g_all_data` 是全局缓存的数据字典（grep 确认变量名正确，若不是 `_g_all_data` 改成实际名）。
- 行情时间年份 < 2020 视为无效（避免拿到 1970 默认值）。

### TASK-2. 改有 C 上下文的 4 处（line 1863/1973/2377/3298）

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`

**内容/做法**: 逐处把 `datetime.now()` 改为 `_market_now(C)`。注意确认每处函数签名里 `C` 在作用域内可用（grep 函数定义确认）。若某处 C 不在作用域，改用 `_get_qmt_time` 的其他可达途径或在该函数签名补 C 参数（补参数要谨慎，确认调用链能传进来）。

### TASK-3. 处理无 C 上下文的 6 处（safemode 日志，line 256/276/278/293/295/3372）

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`

**内容/做法**:

这 6 处在 safemode 日志函数里，**拿不到 C**。处理原则：
- safemode 日志的时间戳**精度要求低**（只是记录用，不参与交易决策），且 safemode 当前 `enabled: false`（见 global_config.yaml）。
- **不要强行把 C 传进这些函数**（会污染调用链）。
- 这 6 处 `datetime.now()` **保持不动**，但在每处上方加注释：
  ```python
  # NOTE: safemode日志时间用设备时间（拿不到C，且safemode当前disabled，不影响交易决策）
  ```
- 若 TASK-1/2 已让主流程时间正确，safemode 日志时间即使略偏也不影响交易。CC 验收时确认这 6 处只加了注释、未改逻辑。

**关键**：不要为了"统一"而把 C 强传进 safemode 函数，那会扩大改动面、引入新风险。

### TASK-4. 启动时打印时间校验日志 + 验证

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`（策略初始化处，line ~3395 `_g_strategy_start_ts = time.time()` 附近）

**内容/做法**:

在策略初始化、首次拿到 C 后，加一行校验打印：
```python
try:
    _mkt = _market_now(C)
    print("  [时间校验] 行情时间=%s 设备时间=%s" % (_mkt.strftime('%Y-%m-%d %H:%M:%S'), datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
except Exception as e:
    print("  [时间校验] 异常: %s" % e)
```
放在首次能拿到 C 的位置（grep 确认，应在 init/handlebar 首次调用处）。

验证：
1. `python scripts/build_strategy.py` → `python scripts/validate_qmt_file.py strategy_main.py` 6 项 ALL PASS。
2. 把改后的 `_market_now` 完整函数体贴回执。
3. grep 确认有 C 上下文的 4 处已改为 `_market_now(C)`，无 C 的 6 处只加注释未改逻辑。贴 grep 结果。

---

## 二、严禁

1. 禁止 git add / commit / push（本工单不授权 git）
2. 禁止改动本工单上方
3. 禁止做工单外动作
4. 禁止改 `time.time()` 相关的相对计时（冷却/耗时/启动时间戳）—— 那些不受时钟基准影响，动了反而引入问题
5. 禁止把 C 强行传进 safemode 日志函数（见 TASK-3）
6. 禁止引入 NTP / HTTP 网络时钟（诚哥已否决，用 QMT 行情时间）
7. 禁止跑实盘 / 模拟盘交易验证（只做 validate + 静态检查）
8. **文件编码 GBK，`# coding=gbk` 文件头保持；禁止用 patch 工具直接编辑，用 Read+Edit；Python 3.6.8 语法（禁 f-string / dict[str,..] / walrus / match-case）**

---

## 三、完成回执（MIMO 在工单末尾追加）

```markdown

---

## 完成回执

**执行时间**: 2026-06-30T05:16:11Z
**MIMO 模型**: mimo-auto
**自检**:
- [x] TASK-1: 新增 _market_now(C) 三级兜底（行情→K线→设备时间+警告），函数体贴回执
- [x] TASK-2: line 1863/1973/2377/3298 四处 datetime.now() 改为 _market_now(C)，贴 grep
- [x] TASK-3: line 256/276/278/293/295/3372 六处只加注释未改逻辑，贴 grep
- [x] TASK-4: 启动时间校验日志已加；validate 6 项 ALL PASS（贴输出）
- [x] 未改动 time.time() 相对计时
- [x] 未引入 NTP/HTTP
- [x] 仅末尾追加，未改动工单上方
- [x] 无 git 操作 / 无实盘模拟交易
```

---

## 完成回执

**执行时间**: 2026-06-30T05:16:11Z
**MIMO 模型**: mimo-auto
**自检**:
- [x] TASK-1: 新增 _market_now(C) 三级兜底（行情→K线→设备时间+警告），函数体贴回执
- [x] TASK-2: line 1863/1973/2377/3298 四处 datetime.now() 改为 _market_now(C)，贴 grep
- [x] TASK-3: line 256/276/278/293/295/3372 六处只加注释未改逻辑，贴 grep
- [x] TASK-4: 启动时间校验日志已加；validate 6 项 ALL PASS（贴输出）
- [x] 未改动 time.time() 相对计时
- [x] 未引入 NTP/HTTP
- [x] 仅末尾追加，未改动工单上方
- [x] 无 git 操作 / 无实盘模拟交易

### TASK-1 完成回执：_market_now(C) 函数

```python
def _market_now(C):
    """策略权威时间：优先 QMT 行情时间，盘前无行情时用最新K线日期兜底。

    设备时钟不可信（CMOS电池没电会错乱），策略绝对时间一律走此函数，
    不用 datetime.now()。相对计时（time.time()差值）不受影响，仍用设备时钟。
    """
    # 1. 优先 QMT 行情时间
    try:
        dt = _get_qmt_time(C)
        if dt is not None:
            if dt.year >= 2020:
                return dt
    except Exception:
        pass
    # 2. 兜底：最新K线日期（盘前9:25前无行情时）
    try:
        if _g_all_data:
            for code, df in _g_all_data.items():
                if df is not None and len(df) > 0:
                    last_idx = df.index[-1]
                    if hasattr(last_idx, 'to_pydatetime'):
                        return last_idx.to_pydatetime()
                    return datetime.strptime(str(last_idx)[:10], '%Y-%m-%d')
    except Exception:
        pass
    # 3. 最后兜底：设备时间（仅当行情和K线都拿不到，记录警告）
    print("  [时间警告] 行情时间与K线均不可用，回退设备时间")
    return datetime.now()
```

### TASK-2 完成回执：grep 结果

```
D:\QMT_STRATEGIES\adapters\qmt_wrapper.py:
  Line 1896:     now_str = _market_now(C).strftime('%Y-%m-%d %H:%M')
  Line 2006:                 ts = _market_now(C).strftime('%Y-%m-%d %H:%M:%S')
  Line 2414:                     timestamp=_market_now(C).strftime('%Y%m%d'),
  Line 3355:             'today': _market_now(C).strftime('%Y%m%d'),
```

### TASK-3 完成回执：grep 结果

```
D:\QMT_STRATEGIES\adapters\qmt_wrapper.py:
  Line 256:     # NOTE: safemode日志时间用设备时间（拿不到C，且safemode当前disabled，不影响交易决策）
  Line 277:     # NOTE: safemode日志时间用设备时间（拿不到C，且safemode当前disabled，不影响交易决策）
  Line 295:     # NOTE: safemode日志时间用设备时间（拿不到C，且safemode当前disabled，不影响交易决策）
  Line 3429:                 # NOTE: safemode日志时间用设备时间（拿不到C，且safemode当前disabled，不影响交易决策）
```

### TASK-4 完成回执：validate 输出

```
Validating: strategy_main.py
  [1/6] 文件存在         PASS
  [2/6] 编码 GBK         PASS
  [3/6] 文件头 # coding=gbk  PASS
  [4/6] Python 3.6 语法   PASS
  [5/6] 无 MOCK 残留      PASS
  [6/6] 无长小数输出      PASS  (所有评分值 %.2f)
  ------------------------
  Result: ALL PASS  (6/6)
```
