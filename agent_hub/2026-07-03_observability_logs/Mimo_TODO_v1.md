# C：可观测性日志增强（handlebar时段/导出明细/init耗时/持仓对账）

**日期**: 2026-07-03
**作者**: CC
**目的**: 部署后能快速发现 QMT 集成层问题，对应 SPEC `specs/SPEC_20260703_sim_verify_observability.md` 方案 C 的 4 项日志
**预计工时**: ≤ 40 分钟

---

## 背景（必读）

- 目标源文件：`D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`（GBK，`# coding=gbk`）。strategy_main.py 是构建产物，改完 rebuild。
- **只加日志，不改业务逻辑**。信号/止损/反查/导出/纳管的逻辑一个字不动。
- 现有日志（保留不重复加）：`[时间校验]`/`[持仓纳管]`/`[卖出评估]`/`[反查诊断]`/`[持仓同步]`/`premarket_diag`。

---

## 一、必做（6 项）

### TASK-1. C-1 handlebar 时段进入日志

**目标**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`
**做法**:
1. 模块级（`_g_exported_today = False` 附近，约行233）新增 `_g_phase_printed = set()`。
2. 新增函数 `_log_phase(now)`（放在 `_get_allowed_sell_layers` 附近）：
```python
def _log_phase(now):
    key, desc = None, None
    if '0925' <= now < '0930':
        key, desc = '0925', '集合竞价预埋窗口'
    elif '0930' <= now < '0935':
        key, desc = '0930', '开盘卖出评估(底线层)'
    elif '0935' <= now < '0940':
        key, desc = '0935', '底线+清仓层'
    elif '0940' <= now < '1000':
        key, desc = '0940', '全层卖出开启'
    elif '1000' <= now < '1010':
        key, desc = '1000', '买入窗口10:00-10:10'
    elif '1458' <= now < '1500':
        key, desc = '1458', '收盘序列'
    elif '1500' <= now < '1505':
        key, desc = '1500', '收盘帧导出'
    if key and key not in _g_phase_printed:
        _g_phase_printed.add(key)
        print("  [时段] %s %s" % (key, desc))
```
3. 在 `_handlebar_impl` 算出 `now` 之后（`now = dt.strftime('%H%M')` 紧接着）调用 `_log_phase(now)`。
4. `_handlebar_impl` 的 global 声明补 `_g_phase_printed`。
5. 日期切换块（`if today != _g_last_date:` 内，`_g_sell_skip_printed.clear()` 附近）加 `_g_phase_printed.clear()`。

### TASK-2. C-2 导出结果明细

**目标**: `export_daily_data` 函数（`def export_daily_data(ContextInfo):` 约 qmt_wrapper.py 行1072）
**做法**: 在 `return files` 之前加汇总打印：
```python
    _ok = [f for f in files if f]
    if _ok:
        print('[导出] 完成 产出%d文件: %s' % (len(_ok), _ok))
    else:
        print('[导出] 完成 但无文件产出（检查各 export_* 是否异常）')
```
不动现有各 `try/except` 的失败打印。

### TASK-3. C-3 init 步骤耗时

**目标**: `StrategyRunner.init` 方法（grep `def init` 定位）
**做法**: 在 init 关键步骤前后用 `time.time()` 计时，打 `[init] <步骤> 耗时<Ns>`。至少覆盖这 4 步（用 grep 在 init 内定位各自位置）：
- config 读取（`_load_config` 调用处）
- 数据加载（`_load_data` 调用处）
- 交易通道就绪（`[trade]start trading mode` 相关 / `get_holdings` 首次调用处）
- 持仓同步（`_sync_holdings_from_account` 调用处）
- 累计盈亏重建（`rebuild_cumulative_pnl_from_csv` 调用处）
格式示例：
```python
    _t0 = time.time()
    <原步骤>
    print("  [init] <步骤名> 耗时%.2fs" % (time.time() - _t0))
```
若某步骤在 init 里不存在或无法定位，跳过并在回执注明，不要硬塞。

### TASK-4. C-4 持仓对账

**目标**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`
**做法**:
1. 新增函数 `_log_holdings_reconcile(C, tag)`（放 `_sync_holdings_from_account` 附近）：
```python
def _log_holdings_reconcile(C, tag):
    try:
        acct_codes = set(_g_trader.get_holdings().keys()) if _g_trader else set()
        my_codes = set(_g_my_codes.keys())
        only_acct = acct_codes - my_codes
        only_my = my_codes - acct_codes
        print("  [对账] %s _g_my_codes(%d只) vs account(%d只)" % (tag, len(my_codes), len(acct_codes)))
        if only_acct or only_my:
            print("  [对账告警] %s 仅账户=%s 仅策略=%s" % (tag, sorted(only_acct), sorted(only_my)))
    except Exception as e:
        print("  [对账] %s 失败: %s" % (tag, e))
```
2. `init` 末尾（`_g_init_done = True` 之前）调用 `_log_holdings_reconcile(C, 'init')`。
3. `_handlebar_impl` 的 1500 收盘导出块（`if now >= '1500' and not _g_exported_today:` 内，`export_daily_data(C)` 之后）调用 `_log_holdings_reconcile(C, 'close')`。

### TASK-5. 版本号 bump + rebuild + validate

1. 行158 `STRATEGY_VERSION = 'v2026.07.03-export-fix-g3'` 改为 `STRATEGY_VERSION = 'v2026.07.03-observability'`
2. `python scripts/build_strategy.py` 重建 strategy_main.py
3. `python scripts/validate_qmt_file.py strategy_main.py` 6/6 ALL PASS（贴 6 项）
4. grep strategy_main.py 确认 `[时段]` / `[导出] 完成` / `[init]` / `[对账]` / `v2026.07.03-observability` 都已同步进产物

### TASK-6. commit（只 add 3 个目标，严禁 git add -A）

1. `git add adapters/qmt_wrapper.py strategy_main.py agent_hub/2026-07-03_observability_logs/`
2. `git status` 确认 staged 只有上述 3 个目标；诚哥的其他 dirty（core/signal_main_rise.py 等）必须 unstaged
3. `git commit -m "feat(qmt): 可观测性日志增强(handlebar时段/导出明细/init耗时/持仓对账)；版本号observability"`
4. `git show --stat HEAD` 确认 commit 只含 3 个目标（贴出）
5. `git status --short` 确认诚哥 dirty 仍在（贴前 10 行）
**严禁 push**。

---

## 二、严禁

1. 禁止改任何业务逻辑（信号/止损/反查过滤/sell()buy()轮询/导出条件/纳管逻辑/盘前预埋）
2. 禁止 `git add -A` / `git add .` / `git add -u`
3. 禁止 commit 诚哥 dirty（core/signal_main_rise.py、core/scoring/dimension6plus2.py、strategy_dev.py、.claude/*、backtest/* 等）
4. 禁止 push
5. 禁止改本轮 3 目标以外文件
6. 禁止手改 strategy_main.py（只通过 build 重建）
7. 禁止用 patch 工具编辑 GBK（用 Edit）
8. 文件头 `# coding=gbk`，Python 3.6.8 语法兼容（禁 f-string / walrus / match-case / dict[str,..]）
9. 禁止删现有日志（`[时间校验]`/`[持仓纳管]`/`[卖出评估]`/`[反查诊断]`/`[持仓同步]` 保留）
10. 禁止改 v2 已落地的导出修复/BUG5诊断/盘前预埋代码

---

## 三、完成回执（MIMO 在工单末尾追加）

```markdown

---

## 完成回执

**执行时间**: <date -u 真实拿>
**MIMO 模型**: <实际名>
**自检**:
- [ ] TASK-1 `_log_phase` 函数 + 调用 + global `_g_phase_printed` + 日期清空（grep 确认 `[时段]`）
- [ ] TASK-2 `export_daily_data` 末尾汇总（grep 确认 `[导出] 完成`）
- [ ] TASK-3 init 各步骤耗时（grep 确认 `[init]`，注明实际覆盖哪几步）
- [ ] TASK-4 `_log_holdings_reconcile` 函数 + init 末尾 + 1500收盘帧调用（grep 确认 `[对账]`）
- [ ] TASK-5 版本号 `v2026.07.03-observability` + rebuild + validate 6/6（贴结果）+ strategy_main.py grep 确认同步
- [ ] TASK-6 commit 成功（贴 `git show --stat HEAD`）+ 诚哥 dirty 仍在（贴 `git status --short` 前10行）
- [ ] 业务逻辑未改（grep 确认 `lookup_diag`/`if now >= '1500'`/`PREMARKET_HARD_STOP_MODE = 'G3_ONLY'` 仍在）
- [ ] 现有日志未删
- [ ] 未 push / 未改 3 目标以外文件
- [ ] 仅末尾追加回执
```
