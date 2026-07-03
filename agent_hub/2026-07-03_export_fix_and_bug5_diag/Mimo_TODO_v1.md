# 盘后导出修复 + BUG5 反查失败诊断日志

**日期**: 2026-07-03
**作者**: CC
**目的**: 修复盘后CSV导出永不触发（1505条件>15:00收盘handlebar不再触发 + _handlebar_impl缺global）；为BUG5反查失败加诊断日志抓现场（不改反查逻辑）
**预计工时**: ≤ 40 分钟

---

## 背景（必读）

- 目标源文件：`D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`（GBK，`# coding=gbk`）。**strategy_main.py 是构建产物，禁改**，改完源文件后重新 build。
- 当前部署版：v2026.07.02-orphan-adopt2（commit 43299f6）。
- 现场证据（2026-07-03 局域网QMT模拟端 `\\192.168.31.131` 日志）：
  - **导出**：`strategy_log_20260703.txt` 在 15:00:05 写出，但成交/持仓/资金 CSV 没产出。根因：handlebar 里 `if now >= '1505'` 条件 > 15:00 收盘时间，QMT 15:00 收盘后 handlebar 不再触发，1505 导出永不执行。
  - **BUG5**：603283 10:00:08 passorder 卖单 → 4×0.2s 轮询反查全失败 → `[卖出反查失败]`+60s冷却，但 10:00:59 实际成交 300股@67.9。根因未定死（疑 `get_trade_detail_data('order')` 列表延迟 或 `_lookup_recent_order_id` 过滤误杀），**本轮只加诊断不改逻辑**。

---

## 一、必做（2 项）

### TASK-1. 修复盘后导出永不触发

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`

**内容/做法**（3 处改动，每处都用 grep 双重定位确认）：

1. **补 global**：在 `_handlebar_impl` 方法的 global 声明里补 `_g_exported_today`。
   - 定位：`grep -n "def _handlebar_impl" adapters/qmt_wrapper.py` 找到方法定义行，其下连续若干行 `global ...`。
   - 在其中任一行的末尾追加 `, _g_exported_today`。
   - 原因：当前缺失，`_handlebar_impl` 内 `_g_exported_today = True` 赋值会创建局部变量，读 `not _g_exported_today` 时 UnboundLocalError（被 try 吞掉，导出静默失败）。

2. **handlebar 导出条件 1505→1500**：定位 `if now >= '1505' and not _g_exported_today:`（在 `elif now >= '1458':` 分支内、`if not _g_today_done:` 块外，约行4035），改为 `if now >= '1500' and not _g_exported_today:`。
   - 同步把该行上方注释 `# 15:05 后自动导出当日 CSV` 改为 `# 15:00 收盘帧自动导出当日 CSV`。
   - 原因：QMT 15:00 收盘后 handlebar 不再触发，1505 永不执行；改 1500 让 15:00 收盘帧（handlebar 最后一次触发）导出。

3. **`_is_export_time` 阈值 1505→1500**：定位 `def _is_export_time()`（约行906）内 `if hm < '1505':`，改为 `if hm < '1500':`。
   - 原因：handlebar 15:00 调 `export_daily_data` → 内部调 `_is_export_time()`，若仍 1505 则 15:00 返回 False 还是不导出。两处必须同步。

**不要改**：init 导出入口（`if not _g_exported_today:` 约258行附近，init 方法内）逻辑不动，那个是对的。`_is_export_time` 仍用 `datetime.now()`（系统时间）本轮不改时间源（那台机器系统时间基本准），只改阈值。

### TASK-2. BUG5 反查失败诊断日志（不改反查逻辑）

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`

**内容/做法**：

在 `_lookup_recent_order_id` 方法里，定位 `if not candidates: return None`（candidates 为空即将返回 None 处）。在 `return None` **之前**插入诊断段：

```python
# BUG5 诊断：反查失败时 dump orders 列表字段，抓现场定根因（临时，不改过滤逻辑）
try:
    from datetime import datetime as _diag_dt
    _diag_path = 'D:/QMT_POOL/lookup_diag_%s.csv' % _diag_dt.now().strftime('%Y%m%d')
    _diag_header = 'code,m_nOrderID,m_strInstrumentID,m_nOrderVolume,m_nOrderStatus,m_strInsertTime,m_strOptName,m_strRemark'
    print("  [反查诊断] %s expected_vol=%s direction=%s orders_count=%d" % (stock_code, expected_vol, direction, len(orders)))
    import os as _diag_os
    _diag_write_header = not _diag_os.path.exists(_diag_path)
    _diag_f = open(_diag_path, 'a')
    try:
        if _diag_write_header:
            _diag_f.write(_diag_header + '\n')
        for _diag_o in orders[:5]:
            _diag_f.write(','.join([
                stock_code,
                str(getattr(_diag_o, 'm_nOrderID', '')),
                str(getattr(_diag_o, 'm_strInstrumentID', '')),
                str(getattr(_diag_o, 'm_nOrderVolume', '')),
                str(getattr(_diag_o, 'm_nOrderStatus', '')),
                str(getattr(_diag_o, 'm_strInsertTime', '')),
                str(getattr(_diag_o, 'm_strOptName', '')),
                str(getattr(_diag_o, 'm_strRemark', '')),
            ]) + '\n')
    finally:
        _diag_f.close()
except Exception as _diag_e:
    print("  [反查诊断] 写诊断失败: %s" % _diag_e)
```

注意：GBK 文件中文注释 OK（GBK 支持中文），但字符串里的 `%s` 等用 ASCII。变量名加 `_diag_` 前缀避免与外层冲突。`orders` 变量在 `_lookup_recent_order_id` 作用域内可见（`get_trade_detail_data` 返回的列表）。

**不要改**：`_lookup_recent_order_id` 的过滤逻辑（code/vol/status/time/remark 那些过滤条件）、`sell()`/`buy()` 的轮询逻辑（`SELL_LOOKUP_RETRIES`/`BUY_LOOKUP_RETRIES` 循环）都不动。**只加诊断段**。

---

## 二、严禁

1. 禁止 git add / commit / push（本工单不授权 git 操作）
2. 禁止改动本工单上方
3. 禁止改 `strategy_main.py`（构建产物，改了会被覆盖；改完源文件重新 build 即可）
4. 禁止改 `_lookup_recent_order_id` 的过滤逻辑 / `sell()` / `buy()` 轮询（TASK-2 只加诊断）
5. 禁止改 init 导出入口逻辑（TASK-1 只改 handlebar 的 1505→1500 + `_is_export_time` 阈值 + global）
6. 禁止改 `PREMARKET_HARD_STOP_MODE`（本工单不动盘前预埋）
7. 禁止用 patch 工具直接编辑 GBK 文件（用 Edit/Write，注意 GBK 编码）
8. 文件头保持 `# coding=gbk`，Python 3.6.8 语法兼容（禁 f-string / walrus `:=` / match-case / `dict[str,..]` / `str|None`）
9. 禁止改 `_is_export_time` 的时间源（`datetime.now()` 本轮保留，只改阈值 1505→1500）

---

## 三、完成回执（MIMO 在工单末尾追加）

```markdown

---

## 完成回执

**执行时间**: <用 `date -u +"%Y-%m-%dT%H:%M:%SZ"` 真实拿，禁止 placeholder>
**MIMO 模型**: <实际名，如 mimo-auto>
**自检**:
- [ ] TASK-1.1 `_handlebar_impl` global 补 `_g_exported_today`（grep 确认 `global .*_g_exported_today` 命中 _handlebar_impl 区段）
- [ ] TASK-1.2 handlebar `if now >= '1500' and not _g_exported_today:`（grep 确认，且 `'1505'` 在该行已消失）
- [ ] TASK-1.3 `_is_export_time` 内 `if hm < '1500':`（grep 确认）
- [ ] TASK-1.4 注释已更新为 `15:00 收盘帧`
- [ ] TASK-2 诊断段已插入 `_lookup_recent_order_id` 的 `if not candidates:` 分支（grep 确认 `lookup_diag` 写入逻辑存在）
- [ ] 过滤逻辑 / sell() / buy() 轮询未改（grep 确认 `SELL_LOOKUP_RETRIES` 循环结构未变）
- [ ] 跑 `python scripts/build_strategy.py` 重新构建 strategy_main.py 成功
- [ ] 跑 `python scripts/validate_qmt_file.py strategy_main.py` 6/6 ALL PASS（贴出 6 项结果）
- [ ] 构建后的 strategy_main.py 里 grep `'1505'` 在导出相关行已消失、`'1500'` 存在
- [ ] 仅末尾追加，未改动工单上方
- [ ] 无 git 操作 / 无其它文件改动
```

---

## 完成回执

**执行时间**: 2026-07-03T08:33:49Z
**MIMO 模型**: mimo-auto
**自检**:
- [x] TASK-1.1 `_handlebar_impl` global 补 `_g_exported_today`（grep 确认 `global .*_g_exported_today` 命中 _handlebar_impl 区段）— line 3943: `global _g_timegate_skip_printed, _g_cooling_printed, _g_exported_today`
- [x] TASK-1.2 handlebar `if now >= '1500' and not _g_exported_today:`（grep 确认 `'1505'` 在该行已消失）— line 4062
- [x] TASK-1.3 `_is_export_time` 内 `if hm < '1500':`（grep 确认）— line 939
- [x] TASK-1.4 注释已更新为 `15:00 收盘帧` — line 4061
- [x] TASK-2 诊断段已插入 `_lookup_recent_order_id` 的 `if not candidates:` 分支（grep 确认 `lookup_diag` 写入逻辑存在）— line 547
- [x] 过滤逻辑 / sell() / buy() 轮询未改（grep 确认 `SELL_LOOKUP_RETRIES` 循环结构未变）— line 265/459
- [x] 跑 `python scripts/build_strategy.py` 重新构建 strategy_main.py 成功
- [x] 跑 `python scripts/validate_qmt_file.py strategy_main.py` 6/6 ALL PASS（贴出 6 项结果）— 文件存在 PASS / 编码 GBK PASS / 文件头 # coding=gbk PASS / Python 3.6 语法 PASS / 无 MOCK 残留 PASS / 无长小数输出 PASS
- [x] 构建后的 strategy_main.py 里 grep `'1505'` 在导出相关行已消失、`'1500'` 存在
- [x] 仅末尾追加，未改动工单上方
- [x] 无 git 操作 / 无其它文件改动
