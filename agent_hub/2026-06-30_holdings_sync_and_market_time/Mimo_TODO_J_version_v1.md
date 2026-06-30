# 工单J：加入代码内策略版本号 + 更新说明书版本到 lookup 修复

**日期**: 2026-06-30
**作者**: CC
**目的**: 从当前运行版本开始正式加版本号。另一个 CC 已提交 `fad14cd fix(qmt): 买卖委托反查加短轮询防异步误判`，说明书版本与代码内版本号需纳入 lookup 修复。新增 `STRATEGY_VERSION` 常量并在启动日志打印，更新说明书顶部版本信息。
**预计工时**: ≤ 25 分钟

---

## 〇、背景（必读，不要改这段）

当前最新相关提交：
- `04e4091`：清仓残留 + 行情时间
- `3c36743`：全天版深度对齐 main 版 + 重复买入修复
- `230aa06`：工单G回执 hash 文档 fixup
- `fad14cd`：买卖委托 passorder 后 order_id 反查加短轮询，避免 QMT 异步分配延迟导致误判失败

说明书当前写的是 `v2026.06.30-f1f5`，需要升级为 `v2026.06.30-f1f5-lookup`。

---

## 一、必做（4 项）

### TASK-1. 在 qmt_wrapper.py 加 STRATEGY_VERSION 常量

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`（参数常量区，line ~138）

**当前代码**：
```python
ACCOUNT_ID = '67014907'
STRATEGY_NAME = '双带主升浪_尾盘_外部池_beat四层版'

STRATEGY_CAPITAL = float(_strategy_config.get('capital_base', 100000))
```

**改为**：
```python
ACCOUNT_ID = '67014907'
STRATEGY_NAME = '双带主升浪_尾盘_外部池_beat四层版'
STRATEGY_VERSION = 'v2026.06.30-f1f5-lookup'

STRATEGY_CAPITAL = float(_strategy_config.get('capital_base', 100000))
```

**关键**：
- Python 3.6 语法,普通字符串常量。
- 放在 `STRATEGY_NAME` 后面,便于日志和说明书对应。

### TASK-2. 初始化日志打印版本号

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`（`StrategyRunner.init`，line ~3556）

**当前代码**：
```python
        _g_init_done = True
        print("[%s] 初始化完成  账号=%s" % (STRATEGY_NAME, ACCOUNT_ID))
        print("[%s] 策略本金=%d  累计盈亏=%+.0f  当前净值=%.0f" % (
            STRATEGY_NAME, STRATEGY_CAPITAL, _g_cumulative_pnl, current_nav))
```

**改为**：
```python
        _g_init_done = True
        print("[%s] 初始化完成  账号=%s" % (STRATEGY_NAME, ACCOUNT_ID))
        print("[%s] 策略版本=%s" % (STRATEGY_NAME, STRATEGY_VERSION))
        print("[%s] 策略本金=%d  累计盈亏=%+.0f  当前净值=%.0f" % (
            STRATEGY_NAME, STRATEGY_CAPITAL, _g_cumulative_pnl, current_nav))
```

**关键**：部署后日志必须能看到 `策略版本=v2026.06.30-f1f5-lookup`。

### TASK-3. 更新说明书版本信息

**目标路径**: `D:/QMT_STRATEGIES/运行策略说明书_双带主升浪_QMT.md`

**内容/做法**:

1. 顶部 `适用策略版本` 从：
   `双带主升浪 QMT Runtime v2026.06.30-f1f5`
   改为：
   `双带主升浪 QMT Runtime v2026.06.30-f1f5-lookup`
2. 顶部 `对应代码提交` 从：
   `04e4091 + 3c36743 + 230aa06（本地 master）`
   改为：
   `04e4091 + 3c36743 + 230aa06 + fad14cd（本地 master）`
3. `## 0. 版本信息` 表里同步更新策略版本和对应提交。
4. `代码内版本号` 从待后续工单加入改为：
   `STRATEGY_VERSION = 'v2026.06.30-f1f5-lookup'`
5. `近期关键修复` 或 `已知限制/注意事项` 中补一条 lookup 修复：
   - 买/卖 passorder 后 order_id 反查短轮询（4 次 × 0.2s，最多 0.8s），避免 QMT 异步分配 order_id 的约 100ms 延迟导致即时反查误判失败。

### TASK-4. build + validate + grep 验证

**内容/做法**:

```bash
python scripts/build_strategy.py
python scripts/build_strategy.py --allday
python scripts/validate_qmt_file.py strategy_main.py
python scripts/validate_qmt_file.py strategy_allday.py
```

必须两个文件都 6 项 ALL PASS。

grep 验证：
```bash
grep -n "STRATEGY_VERSION" adapters/qmt_wrapper.py
iconv -f GBK -t UTF-8 strategy_main.py | grep -c "策略版本=v2026.06.30-f1f5-lookup"
iconv -f GBK -t UTF-8 strategy_allday.py | grep -c "策略版本=v2026.06.30-f1f5-lookup"
grep -n "v2026.06.30-f1f5-lookup\|fad14cd\|短轮询" "运行策略说明书_双带主升浪_QMT.md"
```

---

## 二、严禁

1. 禁止 git add / commit / push（本工单不授权 git）
2. 禁止改动本工单上方
3. 禁止改策略逻辑，只加版本常量/启动日志/说明书版本文字
4. 禁止改 build_strategy.py
5. 禁止跑实盘/模拟交易
6. **文件编码 GBK，`# coding=gbk`；禁止 patch 工具直接编辑，用 Read+Edit；Python 3.6.8 语法（禁 f-string）**

---

## 三、完成回执（MIMO 在工单末尾追加）

```markdown

---

## 完成回执

**执行时间**: <用 `date -u +"%Y-%m-%dT%H:%M:%SZ"` 真实拿>
**MIMO 模型**: <实际模型名>
**自检**:
- [ ] qmt_wrapper.py 已加 STRATEGY_VERSION = 'v2026.06.30-f1f5-lookup'
- [ ] 初始化日志已打印 策略版本
- [ ] 说明书版本/提交/代码内版本号/lookup短轮询说明已更新
- [ ] strategy_main.py + strategy_allday.py build + validate 6 项 ALL PASS
- [ ] grep 验证全部命中
- [ ] 未改策略逻辑 / 未 git add commit push / 未跑实盘模拟
- [ ] 仅末尾追加，未改动工单上方
```

---

## 完成回执

**执行时间**: 2026-06-30T14:12:49Z
**MIMO 模型**: mimo-auto
**自检**:
- [x] qmt_wrapper.py 已加 STRATEGY_VERSION = 'v2026.06.30-f1f5-lookup'
- [x] 初始化日志已打印 策略版本
- [x] 说明书版本/提交/代码内版本号/lookup短轮询说明已更新
- [x] strategy_main.py + strategy_allday.py build + validate 6 项 ALL PASS
- [x] grep 验证全部命中
- [x] 未改策略逻辑 / 未 git add commit push / 未跑实盘模拟
- [x] 仅末尾追加，未改动工单上方
