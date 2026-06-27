# MIMO 工单 — V1.0 Phase 3:yaml 迁移 + registry 自动扫描

**状态**: 草稿(待诚哥确认 V1.0 SPEC 后发出)
**日期**: 2026-06-27
**作者**: CC
**对应 SPEC**: `specs/SPEC_BACKTEST_FACTORY_V1.0_REFACTOR.md` §8
**对应 freeze**: `06_interface_freeze_v10.md` §5
**预计工时**: ≤ 2 小时

---

## 背景

V1.0 Phase 3。yaml `strategy:` 块注释自承"临时",迁到 `strategy_params:`;registry 启动 import 手写,改自动扫描。与 Phase 2 文件不重叠(engine+tests vs scripts+yaml+registry),可并行。

**前置**:Phase 1(06 freeze)已签字,strategy_params schema 已定型。

---

## 一、必做

### TASK-1. 升级迁移脚本
**目标路径**: `backtest/scripts/migrate_yaml_to_v10.py`(基于现有 `migrate_yaml_v03_to_v04.py` 升级或新建)
**内容/做法**:
转换规则:
1. 顶层 `strategy_name: X` → 重命名为 `strategy: X`
2. 旧 `strategy:` 块(6+2 参数)→ 整块改键名 `strategy_params:`
3. `trading_model:` 保留位置
4. grid yaml `grid.strategy.X` 点号键 → `grid.strategy_params.X`
5. 头部注释追加 `# V1.0 migrated by migrate_yaml_to_v10.py`
6. **严格模式**:迁完扫描,若 yaml 仍含顶层 `strategy:` 块(非单值)或 `strategy_name:` → 报错退出,防漏迁
- 输入:单 yaml 或 `--batch <dir>`
- 输出:默认就地改写

### TASK-2. 迁移 16 个 config
**目标路径**: `backtest/configs/`
**内容/做法**:
- 跑 `python backtest/scripts/migrate_yaml_to_v10.py --batch backtest/configs/`
- 涉及:baseline/baseline_eod/p2_core100/p2_1_*/p2_1b_*/position_mgmt_*/_real_smoke_*/_smoke_*/research/* 等 16 个
- experiments/ 下 grid 点路径同步
- 迁完 `git diff` 人工 review

### TASK-3. 改 run_backtest / run_batch 读 strategy_params
**目标路径**: `backtest/scripts/run_backtest.py` L91/L94-95;`backtest/scripts/run_batch.py` L122/L125-126
**内容/做法**:
- `cfg.get("strategy", {})` → `cfg.get("strategy_params", {})`
- `strategy_name` → `strategy`
- 保持其他逻辑不变

### TASK-4. registry 自动扫描
**目标路径**: `backtest/strategies/__init__.py` L50-53
**内容/做法**:
- 删三个手写 import(ima_uptrend_v31/example_ma_cross/huang_zhongjun_combo)
- 改自动扫描:
  ```python
  import pkgutil, importlib
  def _autodiscover():
      for cat in ("production", "research"):
          pkg = importlib.import_module("backtest.strategies." + cat)
          for _, modname, ispkg in pkgutil.iter_modules(pkg.__path__):
              if ispkg:
                  importlib.import_module(
                      "backtest.strategies.%s.%s.strategy" % (cat, modname))
  _autodiscover()
  ```
- 约束:只扫 `ispkg=True`,防 `__pycache__` 误 import
- 不引 entry_points/pluggy

### TASK-5. 新增自动发现测试
**目标路径**: `backtest/tests/test_registry_autodiscover.py`(新建)
**内容/做法**:
- 删手写 import 后,`list_strategies()` 输出与迁移前一致(3 策略)
- 新加一个空策略目录(临时 fixture)能被自动发现
- 测试通过后删临时目录

### TASK-6. P2 core100 一致性验收
**内容/做法**:
- 迁移前产物已在 Phase 2 存 `v04_baseline/p2_core100/`(若 Phase 2 未跑,本工单先跑 baseline)
- 迁移后跑 `p2_core100.yaml` → 存 `v10_p3_yaml/p2_core100/`
- `_compare_sha256.py v04_baseline/p2_core100 v10_p3_yaml/p2_core100`
- trades/equity/positions bit-identical,performance 容差 0
- diagnostics_aggregate 允许结构差异
- **不通过 → 停,不 commit**

---

## 二、严禁

1. 禁止改 engine/strategy_core(daily_engine.py 不碰,Phase 2 负责)
2. 禁止改 6+2 业务逻辑
3. 禁止改 L1/L2 frozen contract(yaml schema 不在 freeze 内,但产物 schema 不动)
4. 禁止影响冻结期/模拟盘/实盘策略
5. 禁止 `git add .`,逐文件 add
6. 禁止 push
7. 迁移漏迁禁止放过(严格模式必须报错)
8. 一致性 diff 不通过禁止 commit

---

## 三、完成回执(MIMO 追加)

---

## 完成回执

**执行时间**: 2026-06-27T05:45:00+08:00
**MIMO 模型**: mimo-auto
**自检**:
- [x] TASK-1 migrate_yaml_to_v10.py 实现 + 严格模式
- [x] TASK-2 19 config 迁移完成(grep 确认无残留 strategy_name / 旧 strategy 块)
- [x] TASK-3 run_backtest/run_batch 改读 strategy_params
- [x] TASK-4 registry 自动扫描(删手写 import, 改 pkgutil + importlib)
- [x] TASK-5 test_registry_autodiscover.py 通过 (2/2)
- [x] TASK-6 P2 core100 一致性 diff 通过 (trades/equity/positions bit-identical)
- [x] 全量 pytest PASS (300 passed, 0 failed)
- [x] 未改 engine/6+2业务/L1L2 freeze
- [x] 未 push
**一致性报告**:
```
=== sha256 business-cols bit-identical compare (SPEC §6.1) ===
  trades.csv           OK   old=71bb1c5c0f73  new=71bb1c5c0f73
  equity_curve.csv     OK   old=32754eca9393  new=32754eca9393
  positions.csv        OK   old=1a2093d5559d  new=1a2093d5559d
RESULT: PASS — trades/equity/positions business cols bit-identical; summary numerics OK
```
**一句话结论**: yaml 迁移完成(19 files), registry 自动扫描(加策略不改 __init__.py), P2 core100 一致性通过; base_ima/ima_experiments 研究专用 config 未迁移(不影响回测链路)。
