# 工单：导出功能加 init 立即导入口（盘后部署即导出）

**日期**: 2026-07-01
**作者**: CC
**目的**: 诚哥盘后部署策略发现 15:05 后点执行不导出数据。根因：导出绑在 handlebar 1458 分支，但 handlebar 开头有 `_is_in_cooling_off()` 守卫（策略启动后 60 秒内每帧 return），盘后部署前 60 秒走不到 1458 分支的导出块。改：init() 加盘后立即导入口，策略启动即检查导出（带时间锁，盘中启动跳过、盘后启动导），handlebar 1458 分支保留兜底。
**预计工时**: ≤ 20 分钟

---

## 〇、背景（必读，不要改这段）

### 诚哥拍板
- 双入口：**init 立即导 + handlebar 定时**（都保留）
- init 在策略启动时调一次，盘后部署立即导出，不依赖 handlebar tick、不被 cooling-off 挡
- handlebar 15:05 自动触发保留（盘中一直跑到收盘的情况）

### 关键时序（必须理解）
- init 带 `_is_export_time()` 时间锁（已在 `export_daily_data` 内）：盘中启动（<15:05）init 调 export 被锁跳过返回[]；盘后启动（≥15:05 工作日）init 立即导出
- `_g_exported_today` 标志联动 init 和 handlebar：init 导成功设 True，handlebar 检测到 True 跳过，防同一天重复导
- init 不被 cooling-off 挡（cooling-off 只在 handlebar line 3924）

### 已落地（不要重复改/不要动）
- `export_daily_data` / `_is_export_time` / `export_deals/positions/account` 函数：已在 qmt_wrapper.py（line 867 附近）
- `_g_exported_today` 全局标志 + 跨日重置（line 3855）：已就位
- handlebar 1458 分支的 15:05 自动触发块（line 3963-3969）：**保留不动**
- `adapters/qmt_wrapper.py` 实测 UTF-8（文件头 `# coding=gbk` 是历史遗留错误标注，不要改文件头）
- Python 3.6.8 兼容（禁 f-string / dict[str,..] / walrus `:=` / match-case）

---

## 一、必做（2 项）

### TASK-1. qmt_wrapper.py init() 末尾加盘后立即导出块

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`

**内容/做法**:
找到 `StrategyRunner.init()` 方法（line 3772 附近 `def init(self, C):`）。在 init 末尾——`_g_init_done = True` 之后、init 的 return/结束之前——加盘后立即导出块。

先 grep 定位 init 里 `_g_init_done = True` 的位置（应在打印"初始化完成"系列之后）。在该行**之后**加：

```python
        # 盘后部署立即导出当日数据（Hermes 每日数据，防忘）
        # 带 _is_export_time 时间锁：盘中启动跳过，盘后(>=15:05工作日)立即导
        if not _g_exported_today:
            try:
                files = export_daily_data(C)
                if files:
                    _g_exported_today = True
                    print("  [导出] init 盘后部署导出完成: %d 个文件" % len(files))
            except Exception as e:
                print("  [导出] init 自动导出失败: %s" % e)
```

**关键点**：
- 必须在 `_g_init_done = True` **之后**（确保 Trader/配置/全局状态已就绪）
- `export_daily_data(C)` 内已有 `_is_export_time()` 时间锁，盘中启动自动跳过返回 `[]`，`if files` 判断不设标志
- `not _g_exported_today` 防重复（init 只调一次，保险）
- 缩进 8 空格（init 方法内，与 `_g_init_done = True` 同级）

### TASK-2. build + validate + pytest

**内容/做法**:
```bash
cd D:/QMT_STRATEGIES
python scripts/build_strategy.py
python scripts/build_strategy.py --allday
python scripts/validate_qmt_file.py strategy_main.py
python -m pytest tests/test_export_time.py tests/test_rebuild_pnl.py tests/test_order_lookup.py -q
```
贴全部输出。要求：
- build 无报错（GBK 编码不失败）
- validate strategy_main.py 6/6 ALL PASS
- pytest 全绿（22 passed）

---

## 二、严禁

1. 禁止 git add / commit / push（等诚哥验完另出工单）
2. 禁止改动本工单上方
3. 禁止动 handlebar 1458 分支的导出块（line 3963-3969，保留兜底）
4. 禁止动 `export_daily_data` / `_is_export_time` / `_g_exported_today` 已有逻辑（只加 init 调用）
5. 禁止改 `scripts/qmt_daily_export.py` / `scripts/build_strategy.py` / config / 测试文件
6. 禁止改 `strategy_main.py` / `strategy_dev.py` / `strategy_allday.py`（build 产物，build 自动更新）
7. 禁止用 f-string / dict[str,..] / walrus / match-case（Python 3.6.8 兼容）
8. 禁止改 qmt_wrapper.py 文件头 `# coding=gbk`

---

## 三、完成回执（MIMO 在工单末尾追加）

```markdown

---

## 完成回执

**执行时间**: <用 `date -u +"%Y-%m-%dT%H:%M:%SZ"` 真实拿>
**MIMO 模型**: <实际模型名>
**自检**:
- [ ] TASK-1 init() 末尾加盘后立即导出块（_g_init_done=True之后，带时间锁+防重复标志）
- [ ] TASK-2 build + validate 6/6 PASS + pytest 22 passed，贴输出
- [ ] 未 commit / 未动 handlebar 1458 导出块 / 未改其他文件
- [ ] 仅末尾追加，未改动工单上方
```

---

## 完成回执

**执行时间**: 2026-07-01T08:36:16Z
**MIMO 模型**: mimo-auto
**自检**:
- [x] TASK-1 init() 末尾加盘后立即导出块（_g_init_done=True之后，带时间锁+防重复标志）
- [x] TASK-2 build + validate 6/6 PASS + pytest 22 passed，贴输出
- [x] 未 commit / 未动 handlebar 1458 导出块 / 未改其他文件
- [x] 仅末尾追加，未改动工单上方

### TASK-1 输出
`adapters/qmt_wrapper.py` line 3834-3843 插入盘后立即导出块（`_g_init_done = True` + print 之后、`handlebar` 之前），带 `_is_export_time` 时间锁 + `_g_exported_today` 防重复。

### TASK-2 输出
**build (tailored)**:
```
Building strategy_main.py ...
OK: strategy_main.py (生产版, 不含MOCK)
Size: 256654 bytes
First line: # coding=gbk
Encoding: GBK (verified by reading with gbk)
Validating... OK
Done.
```

**build (allday)**:
```
Building strategy_allday.py ...
  [allday] 硬编码 DEBUG_MODE = True
OK: strategy_allday.py (全天调试版, 不含MOCK)
Size: 256623 bytes
First line: # coding=gbk
Encoding: GBK (verified by reading with gbk)
Validating... OK
Done.
```

**validate strategy_main.py**:
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

**pytest**:
```
......................                                                   [100%]
22 passed in 1.11s
```
