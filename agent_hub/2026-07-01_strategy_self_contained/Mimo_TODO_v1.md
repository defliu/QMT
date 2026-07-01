# 工单：策略自包含 config 内置 + 去路径依赖

**日期**: 2026-07-01
**作者**: CC
**目的**: 诚哥把新版 strategy_main.py 粘到运行设备（192.168.31.131，无 D:/QMT_STRATEGIES 开发目录）QMT 终端跑，实盘显示 `[DUAL_BAND]` 而非 `主升浪6+2`。根因：`_load_config()` 用 `__file__` 算 config 路径，运行设备无 config 文件也无开发目录 → 读不到 → 走 `_DEFAULT_CONFIG`，但那版 _DEFAULT_CONFIG 的 strategy 段没补全 display_name。诚哥诉求：**策略自包含，拿哪个设备都能跑，不依赖开发目录**。本次：①`_DEFAULT_CONFIG` 补全四段运行配置；②`_load_config()` 去掉 `__file__`，改候选路径 + 自包含 fallback。
**预计工时**: ≤ 30 分钟

---

## 〇、背景（必读，不要改这段）

### 诚哥诉求（拍板）
**策略自包含：拿到哪个设备都能正常运行，不依赖 D:/QMT_STRATEGIES/ 开发目录。**

### 关键发现（必读）
- 代码只读 config 的 **4 段**：`paths/safemode/debug_mode/strategy`（line 120-143）。**不读 sell/account/kdj/vol_ma_period**（config 文件里有但策略代码没用，历史遗留，本次不内置）
- 每个配置项 `.get()` 都有硬编码 fallback（line 123-165，全指向 `D:/QMT_POOL/` 运行时通信区，运行设备有这目录）
- 所以策略已基本自包含，只需：_DEFAULT_CONFIG 补全四段 + 去掉 `__file__` 路径依赖
- `adapters/qmt_wrapper.py` 实测 UTF-8（文件头 `# coding=gbk` 历史遗留错误标注，不要改文件头）
- Python 3.6.8 兼容（禁 f-string / dict[str,..] / walrus `:=` / match-case / `str|None`）

### 上一轮已修（不要重复）
- init global 加 `_g_exported_today`（line 3777，已修 UnboundLocalError）。不要动。

---

## 一、必做（3 项）

### TASK-1. _DEFAULT_CONFIG 补全四段运行配置

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`

**内容/做法**:
找到 `_DEFAULT_CONFIG`（line 33-43 附近）。当前 strategy 段可能已补了 name/display_name/capital_base，但 paths 段是空 `{}`。改为补全 strategy + paths + safemode + debug_mode 四段（与 config/global_config.yaml 值一致）：

```python
_DEFAULT_CONFIG = {
    'strategy': {
        'name': 'DUAL_BAND',
        'display_name': '主升浪6+2',
        'capital_base': 100000,
    },
    'paths': {
        'pool_file': 'D:/QMT_POOL/QMTselected.txt',
        'intraday_hold_file': 'D:/QMT_POOL/endofday_holdings_beat.txt',
        'endofday_hold_file': 'D:/QMT_POOL/intraday_holdings.txt',
        'intraday_nav_file': 'D:/QMT_POOL/endofday_nav_beat.txt',
        'endofday_nav_file': 'D:/QMT_POOL/endofday_nav.txt',
        'sector_heat_file': 'D:/QMT_POOL/sector_heat.json',
        'pool_path': 'D:/QMT_POOL/selected.txt',
        'trade_log_file': 'D:/QMT_POOL/成交记录_尾盘_外部池_beat.txt',
        'score_history_file': 'D:/QMT_POOL/endofday_score_history_beat.json',
        'intraday_sell_state_file': 'D:/QMT_POOL/endofday_sell_state_beat.json',
        'cumulative_pnl_file': 'D:/QMT_POOL/cumulative_pnl_DUAL_BAND.txt',
    },
    'safemode': {
        'enabled': False,
        'log_dir': 'D:/QMT_POOL/safemode_logs/',
        'block_passorder': True,
        'block_file_write': False,
    },
    'debug_mode': {'enabled': False},
}
```

**关键点**：
- paths 段每个值与 config 文件 + line 155-165 硬编码 fallback 一致
- `cumulative_pnl_file` 写死 `cumulative_pnl_DUAL_BAND.txt`（因默认 name=DUAL_BAND；line 165 动态拼 `%s % STRATEGY_KEY`，_DEFAULT_CONFIG 里写死即可）
- 不要加 sell/account/kdj 段（策略不读）

### TASK-2. _load_config() 去掉 __file__，改候选路径 + 自包含 fallback

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`

**内容/做法**:
找到 `_load_config()`（line 86-117）。当前用 `__file__` 算路径（line 93-96），QMT exec 环境 `__file__` 行为不明 + 运行设备无开发目录。改为候选路径 + 自包含 fallback：

```python
def _load_config():
    """加载 config。策略自包含：读不到 config 文件时用内置默认配置。
    候选路径按优先级尝试，都不存在则用 _DEFAULT_CONFIG（拿任何设备都能跑）。
    """
    candidates = [
        'D:/QMT_STRATEGIES/config/global_config.yaml',  # 本地开发
        'config/global_config.yaml',                     # 相对运行目录
    ]
    config_path = None
    for cp in candidates:
        try:
            if os.path.exists(cp):
                config_path = cp
                break
        except Exception:
            continue
    if config_path is None:
        return dict(_DEFAULT_CONFIG)  # 自包含：无 config 用默认
    try:
        with open(config_path, encoding='utf-8') as f:
            text = f.read()
    except Exception:
        return dict(_DEFAULT_CONFIG)
    try:
        import yaml
        cfg = yaml.safe_load(text) or {}
    except ImportError:
        cfg = _lightweight_yaml_parse(text)
    except Exception:
        cfg = _lightweight_yaml_parse(text)
    if not cfg:
        cfg = dict(_DEFAULT_CONFIG)
    return cfg
```

**关键点**：
- **去掉 `__file__`**（line 93-96 的 try NameError 逻辑删掉）——这是矛盾根源
- 候选路径：`D:/QMT_STRATEGIES/config/...`（本地开发）+ `config/global_config.yaml`（相对运行目录）
- `os.path.exists` 判断，都读不到 → `dict(_DEFAULT_CONFIG)`（自包含，零依赖）
- 本地开发：第一个候选命中，覆盖默认值，开发行为不变
- 运行设备：无 config → 用 _DEFAULT_CONFIG → 显示主升浪6+2、路径全对

### TASK-3. tests/test_config_fallback.py 加自包含用例 + build + validate + pytest

**目标路径**: `D:/QMT_STRATEGIES/tests/test_config_fallback.py`

**内容/做法**:
参考现有 test_config_fallback.py 风格，加用例：

1. `test_no_config_uses_default`：monkey-patch `os.path.exists` 全返回 False（无任何 config 文件），reload qmt_wrapper，断言 `STRATEGY_NAME == '主升浪6+2'`、`STRATEGY_KEY == 'DUAL_BAND'`、`STRATEGY_CAPITAL == 100000`
2. `test_config_self_contained_paths`：无 config 时，断言 `INTRADAY_NAV_FILE == 'D:/QMT_POOL/endofday_nav_beat.txt'`、`CUMULATIVE_PNL_FILE == 'D:/QMT_POOL/cumulative_pnl_DUAL_BAND.txt'`、`POOL_PATH == 'D:/QMT_POOL/selected.txt'`
3. `test_load_config_no_file_attribute`：调用 `_load_config()` 不应抛 NameError（不依赖 `__file__`）；mock 无 config 文件时返回 _DEFAULT_CONFIG

**关键**：
- 参考 test_config_fallback.py 已有的 reload/import 手法（注意 xtquant 占位，参考 test_rebuild_pnl.py 的 `sys.modules` 注入）
- 测试要能独立跑（不依赖真实 config 文件存在与否，用 monkey-patch）

然后 build + validate + pytest：
```bash
cd D:/QMT_STRATEGIES
python scripts/build_strategy.py
python scripts/build_strategy.py --allday
python scripts/validate_qmt_file.py strategy_main.py
python -m pytest tests/test_config_fallback.py tests/test_export_time.py tests/test_rebuild_pnl.py tests/test_order_lookup.py -q
```
贴全部输出。要求：
- build 无报错
- validate strategy_main.py 6/6 ALL PASS
- pytest 全绿

---

## 二、严禁

1. 禁止 git add / commit / push
2. 禁止改动本工单上方
3. 禁止动 init global 修复（line 3777 `_g_exported_today`，已修）
4. 禁止动 export_daily_data / _is_export_time / rebuild / handlebar 1458 导出块（已落地）
5. 禁止加 sell/account/kdj 段到 _DEFAULT_CONFIG（策略不读）
6. 禁止改 `config/global_config.yaml`（本地开发用，保持）
7. 禁止改 `scripts/qmt_daily_export.py` / `scripts/build_strategy.py`
8. 禁止改 `strategy_main.py` / `strategy_dev.py` / `strategy_allday.py`（build 产物）
9. 禁止用 f-string / dict[str,..] / walrus / match-case
10. 禁止改 qmt_wrapper.py 文件头 `# coding=gbk`

---

## 三、完成回执（MIMO 在工单末尾追加）

---

## 完成回执

**执行时间**: 2026-07-01T09:43:04Z
**MIMO 模型**: mimo-auto
**自检**:
- [x] TASK-1 _DEFAULT_CONFIG 补全 strategy/paths/safemode/debug_mode 四段
- [x] TASK-2 _load_config() 去 __file__，改候选路径 + 自包含 fallback
- [x] TASK-3 test_config_fallback 加3用例 + build + validate 6/6 + pytest 全绿，贴输出
- [x] 未 commit / 未动 init global / 未加 sell段 / 未改 config文件
- [x] 仅末尾追加，未改动工单上方

**build 输出**:
```
Building strategy_main.py ...
OK: strategy_main.py (生产版, 不含MOCK)
Size: 257339 bytes
First line: # coding=gbk
Encoding: GBK (verified by reading with gbk)
Validating... OK
Done.

Building strategy_allday.py ...
  [allday] 硬编码 DEBUG_MODE = True
OK: strategy_allday.py (全天调试版, 不含MOCK)
Size: 257308 bytes
First line: # coding=gbk
Encoding: GBK (verified by reading with gbk)
Validating... OK
Done.
```

**validate strategy_main.py 输出**:
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

**pytest 输出**:
```
..................................                                       [100%]
34 passed in 1.39s
```

**改动文件**:
- `adapters/qmt_wrapper.py`: _DEFAULT_CONFIG 补全 paths 段 + _load_config() 去 __file__
- `tests/test_config_fallback.py`: 加 3 个自包含用例 + 修复 2 个旧测试（不再依赖 __file__）
