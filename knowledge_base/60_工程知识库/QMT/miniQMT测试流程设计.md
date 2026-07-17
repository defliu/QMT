# MiniQMT 测试流程设计

#待验证

> 需求：CC 在改完代码后，用 miniQMT 跑自动化测试，验证策略能正常加载数据、选股、生成信号，避免类似 `_load_pool()` 空池问题直到部署后才暴露。
>
> 日期：2026-07-17

## 环境现状

| 项目 | 状态 |
|------|------|
| 本机（CC 运行环境） | 无 QMT 安装，`import xtquant` 失败 |
| 远程模拟端（192.168.31.131） | 完整 QMT 模拟端安装，含 `xtquant` + `xtdata` |
| MiniQMT 可执行文件 | `\\192.168.31.131\国金qmt交易端模拟\bin.x64\XtMiniQmt.exe` |
| 远程 Python | `bin.x64\pythonw.exe`（Python 3.6.8），xtquant 可导入 |
| 限制 | 远程无 `pyyaml`，Python 3.6.8 语法兼容 |

实测验证：远程 Python 的 `from xtquant import xtdata` 可正常导入，API 函数齐全。

## 测试架构

```
┌─────────────────────────┐      subprocess       ┌──────────────────────────────┐
│  本机 CC                │ ──────────────────→   │  远程模拟端 (192.168.31.131)  │
│                         │ ←──────────────────   │                              │
│  1. 修改代码            │    stdout/stderr       │  bin.x64\pythonw.exe         │
│  2. rebuild             │                        │  \scripts\qmt_test_*.py     │
│  3. 调远程 Python 跑测试 │                        │  xtquant + xtdata            │
│  4. 读结果              │                        │  ←→ XtMiniQmt.exe (RPC)      │
└─────────────────────────┘                        └──────────────────────────────┘
```

### 前置条件

1. **远程设备 miniQMT 必须运行中**（QMT 模拟端主程序启动时 miniQMT 自动在后台运行）
2. CC 通过 `subprocess` 调远程 `pythonw.exe` 执行测试脚本
3. 测试脚本通过 `xtdata` API 与 miniQMT 进程 RPC 通信

### 验证范围（分层递进）

```
Layer 1: 数据通路
  - xtdata.get_stock_list_in_sector('沪深A股')  → 能取到全市场代码
  - xtdata.get_market_data_ex()                  → 能取到日线/分钟线
  - xtdata.download_history_data()               → 能下载历史数据

Layer 2: 策略组件
  - _load_config()                               → 能从远程 config 路径正确加载配置
  - _run_hold_pool_selection(C)                  → S010 全市场505筛选能跑出候选股
  - check_buy(df)                                → 对真实数据能正常计算信号
  - _run_scoring(C, candidates, dt)              → 评分不抛异常

Layer 3: 完整交易窗口模拟
  - 模拟 14:50 时间点，跑一次完整的 _execute_trade 流程
  - 验证：数据加载 → 选股池 → 信号 → 评分 → 买入候选列表
  - **不实际下单**（外部 Python 路径 passorder 不撮合，已知限制）
```

## 测试脚本设计

### 脚本存放位置

测试脚本放在远程设备的 `D:\QMT_STRATEGIES\scripts\qmt_test_` 下：
```
\\192.168.31.131\国金qmt交易端模拟\python\qmt_test\
  ├── test_01_data_path.py        # Layer 1: 数据通路
  ├── test_02_pool_selection.py   # Layer 2: 选股池
  ├── test_03_signal_scoring.py   # Layer 2: 信号+评分
  └── test_04_full_flow.py        # Layer 3: 完整流程
```

但注意：远程设备不一定有 `D:\QMT_STRATEGIES\` 目录。更稳妥的方式是把测试脚本直接部署到 QMT 的 `python\` 目录下，与策略文件同路径。

### CC 调用方式

```python
import subprocess, json

REMOTE_PYTHON = r'\\192.168.31.131\国金qmt交易端模拟\bin.x64\pythonw.exe'
TEST_SCRIPT   = r'\\192.168.31.131\国金qmt交易端模拟\python\qmt_test_01_data_path.py'

result = subprocess.run(
    [REMOTE_PYTHON, TEST_SCRIPT],
    capture_output=True, text=True, timeout=120
)
# 解析 stdout 中的 JSON 结果
```

### 测试结果格式

每个测试脚本输出 JSON 到 stdout：

```json
{
  "test": "test_01_data_path",
  "status": "PASS" | "FAIL",
  "summary": "沪深A股: 5200只, 日线取数成功",
  "details": {...},
  "errors": []
}
```

## 实施步骤

### Step 1: 环境准备（诚哥操作）

- [ ] 确认远程模拟端 `XtMiniQmt.exe` 在运行（QMT 主程序开着就行）
- [ ] 在远程 `bin.x64\python\` 下创建 `qmt_test\` 目录
- [ ] 确认 `pyyaml` 是否安装（如缺失：把本地 `site-packages\yaml` 目录复制过去）
- [ ] 把 `D:\QMT_STRATEGIES\config\global_config.yaml` 复制到远程可访问路径

### Step 2: 编写测试脚本（CC 操作）

按分层逐步写 4 个测试脚本，每个验证一层。

### Step 3: 集成到构建流程

在 `validate_qmt_file.py` 之后加一步：如果远程 miniQMT 可用，跑测试脚本。

```python
# validate 6/6 PASS 后
if MINIQMT_AVAILABLE:
    run_miniqmt_tests()
```

### Step 4: 验证

改代码 → rebuild → validate 6/6 → miniQMT 测试 → 通过 → commit

## 注意事项

1. **pythonw.exe 无控制台窗口**：用 `subprocess` 时 stdout 可能缓冲，脚本里加 `sys.stdout.flush()` 或 `print(..., flush=True)`
2. **Python 3.6.8 兼容**：禁止 f-string、dict[str,int] 等 3.6+ 语法（与策略代码同一约束）
3. **pyyaml 缺失**：`_load_config()` 会失败，要么装 pyyaml，要么测试脚本直接用 `json.loads` 读配置
4. **miniQMT 行情数据**：取决于远程设备已下载的数据范围，不是全历史
5. **不测 passorder**：外部 Python 路径 `passorder()` 不产生成交回调，已知限制，不浪费 token 验证

## 相关链接

- [[QMT内置回测调研]] — 外部 Python 路径撮合不可用的详细验证
- [[QMT_Python_API速查]]
- [[QMT新设备部署速查]] — 远程环境 Python 路径
- [[回测工厂不适合事件型策略]]
