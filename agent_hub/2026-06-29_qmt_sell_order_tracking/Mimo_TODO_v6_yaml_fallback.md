# MIMO_TODO_v6：修复 QMT 环境缺少 PyYAML 导致策略启动失败

**日期**: 2026-06-29
**作者**: CC
**目的**: 本地重装 QMT 后，QMT 内置 Python 无 `yaml` 模块，`STRATEGY.py` 在 `_load_config()` 的 `import yaml` 处崩溃。修复为 PyYAML 缺失时使用内置默认配置/轻量解析，保证策略可启动。
**预计工时**: ≤ 45 分钟

---

## 一、现场错误

QMT 日志：

```text
ModuleNotFoundError: No module named 'yaml'
Traceback:
  File "<string>", line 2890, in <module>
  File "<string>", line 2879, in _load_config
ModuleNotFoundError: No module named 'yaml'
```

当前源文件：`D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`

现状：

```python
def _load_config():
    import yaml
    ...
    cfg = yaml.safe_load(f) or {}
```

QMT 运行环境不能假设安装 PyYAML，项目约束也要求 QMT 端尽量只依赖 xtquant/pandas/numpy。

---

## 二、必做（5 项）

### TASK-1. 修改 `_load_config()`，移除 yaml 硬依赖

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`

要求：

1. `_load_config()` 不能在 `import yaml` 失败时抛异常。
2. 优先行为：
   - 如果 PyYAML 存在：继续使用 `yaml.safe_load()`。
   - 如果 PyYAML 不存在：使用内置默认配置，并尽可能读取 `config/global_config.yaml` 中简单键值。
3. 最低要求：PyYAML 缺失时返回包含这些默认结构的 dict：

```python
{
    'paths': {},
    'safemode': {
        'enabled': False,
        'log_dir': 'D:/QMT_POOL/safemode_logs/',
        'block_passorder': True,
        'block_file_write': False,
    },
    'debug_mode': {'enabled': False},
    'strategy': {'capital_base': 100000},
}
```

4. 如果 config 文件不存在/读取失败/解析失败，也必须 fallback 默认配置，不得影响策略启动。
5. 打印一行明确提示即可，例如：
   - `[配置] PyYAML 不可用，使用内置默认配置`
   - `[配置] 读取配置失败，使用内置默认配置: ...`

注意：`_load_config()` 在模块顶层调用，打印不能依赖其他未初始化函数。

### TASK-2. 如做轻量解析，限定范围

如果实现轻量 YAML 解析，只支持本项目 `global_config.yaml` 的简单格式即可，不要引入外部依赖。可选：

- 支持顶层 section：`paths:` / `safemode:` / `debug_mode:` / `strategy:`；
- 支持 `key: value`；
- 支持 bool `true/false`；
- 支持数字；
- 支持字符串路径。

如果不实现轻量解析，仅默认配置也可以接受，但要确保当前默认路径和现有代码默认值一致。

### TASK-3. 补测试

**目标路径**: 可新增 `D:/QMT_STRATEGIES/tests/test_config_fallback.py` 或改现有测试。

至少覆盖：

1. 模拟 `import yaml` 失败时，`_load_config()` 返回默认结构且不抛异常。
2. 配置文件不存在/打开失败时，不抛异常，返回默认结构。
3. 如果实现轻量解析，则覆盖 `safemode.enabled: false`、`strategy.capital_base: 100000` 解析。

测试不要依赖真实 QMT。

### TASK-4. 构建与验证

运行：

```bash
"C:/Users/Administrator/AppData/Local/Programs/Python/Python310/python.exe" -m pytest tests/test_config_fallback.py tests/test_sell_retry.py tests/test_order_lookup.py -q
"C:/Users/Administrator/AppData/Local/Programs/Python/Python310/python.exe" scripts/build_strategy.py
"C:/Users/Administrator/AppData/Local/Programs/Python/Python310/python.exe" scripts/build_strategy.py --allday
"C:/Users/Administrator/AppData/Local/Programs/Python/Python310/python.exe" scripts/validate_qmt_file.py strategy_main.py
```

要求：
- 新增 config fallback 测试必须 PASS；
- 之前两个相关测试文件继续 PASS；
- build OK；
- validate 6/6 PASS。

### TASK-5. 写回执

在本文件末尾追加完成回执，说明：
- PyYAML 缺失时如何处理；
- 测试/构建/验证结果；
- 未 git add/commit/push。

---

## 三、严禁

1. 禁止 git add / commit / push。
2. 禁止改 release、QMT 日志、`D:/QMT_POOL/`、QMT 安装目录。
3. 禁止引入新依赖。
4. 禁止直接手改 `strategy_main.py` / `strategy_allday.py`，只能通过 build 生成。
5. 禁止破坏 v1-v5 已修复的订单反查/最低委托量逻辑。
6. 禁止整文件行尾转换造成巨大 diff。
7. 遇异常必须停下写明。

---

## 四、完成回执（MIMO 在工单末尾追加）

```markdown

---

## 完成回执

**执行时间**: <ISO 8601 真实时刻>
**MIMO 模型**: <实际名>
**改动文件**:
- <file>: <摘要>
**PyYAML 缺失行为**: <说明>
**验证命令与结果**:
- `<命令>` → PASS/FAIL，摘要
**自检**:
- [ ] PyYAML 缺失时 _load_config 不抛异常
- [ ] 配置读取失败时 fallback 默认配置
- [ ] 未引入新依赖
- [ ] tests/test_config_fallback.py 等相关测试 PASS
- [ ] build_strategy.py / --allday OK
- [ ] validate_qmt_file.py strategy_main.py 6/6 PASS
- [ ] 未 git add/commit/push
```

---

## 完成回执

**执行时间**: 2026-06-29T16:30:00+08:00
**MIMO 模型**: mimo-auto
**改动文件**:
- `adapters/qmt_wrapper.py`: `_load_config()` 增加 PyYAML 缺失 fallback + 内置轻量 YAML 解析器；新增 `_lightweight_yaml_parse()` 和 `_DEFAULT_CONFIG`
- `tests/test_config_fallback.py`: 新增测试文件，覆盖轻量解析、PyYAML 缺失、配置文件缺失、损坏 YAML 等场景
**PyYAML 缺失行为**: `import yaml` 失败时自动降级为内置 `_lightweight_yaml_parse()`，支持顶层 section、key: value、bool、数字、字符串路径；若轻量解析也失败则返回 `_DEFAULT_CONFIG` 默认配置，打印提示信息，不影响策略启动。
**验证命令与结果**:
- `pytest tests/test_config_fallback.py -q` → PASS 9/9
- `pytest tests/test_sell_retry.py tests/test_order_lookup.py -q` → PASS 39/39
- `scripts/build_strategy.py` → OK, strategy_main.py 238127 bytes
- `scripts/build_strategy.py --allday` → OK, strategy_allday.py 238096 bytes
- `scripts/validate_qmt_file.py strategy_main.py` → 6/6 PASS
**自检**:
- [x] PyYAML 缺失时 _load_config 不抛异常
- [x] 配置读取失败时 fallback 默认配置
- [x] 未引入新依赖
- [x] tests/test_config_fallback.py 等相关测试 PASS
- [x] build_strategy.py / --allday OK
- [x] validate_qmt_file.py strategy_main.py 6/6 PASS
- [x] 未 git add/commit/push
