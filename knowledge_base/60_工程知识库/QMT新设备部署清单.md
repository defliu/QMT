# QMT 新设备生产部署清单

## 核心结论

把 QMT 策略（`strategy_main.py`）从老设备搬到新设备跑实盘 / 模拟，**只需要拷 2-7 个文件 + 装 1 个第三方包 + 建几个目录**。完整版见仓库根目录 `DEPLOY.md`。

## 三步走

### 1. 装 `pyyaml`（建议装，但不强制）

QMT 自带 Python 是 3.6.8（位于 `bin.x64\pythonw.exe`，**不是 `python\`**），自带 numpy/pandas/xtquant，但**缺 pyyaml**。

PowerShell 命令（必须加 `&` 调用运算符）：

```powershell
& "D:\国金QMT交易端模拟\bin.x64\pythonw.exe" -m pip install pyyaml
```

cmd 不需要 `&`：

```cmd
"D:\国金QMT交易端模拟\bin.x64\pythonw.exe" -m pip install pyyaml
```

验证：

```powershell
& "D:\国金QMT交易端模拟\bin.x64\pythonw.exe" -c "import yaml; print(yaml.__version__)"
```

> **2026-06-29 更新**：策略 `_load_config()` 已移除 yaml 硬依赖。**不装 pyyaml 也能启动**——会自动降级到内置轻量 YAML 解析器,读 `global_config.yaml` 的简单键值;配置缺失/损坏则用 `_DEFAULT_CONFIG` 默认配置。所以这步从"必须"降级为"建议"(装了用标准 yaml.safe_load,更稳)。详见 [[QMT_passorder异步与反查订单号]] 同期 worklog。
>
> 但注意:**重装/换设备后第一次启动,务必看日志确认出现 `初始化完成`**,而不是卡在 `ModuleNotFoundError`。2026-06-29 重装 QMT 后就因为没确认这点,以为策略在跑实际启动失败,600641 跌 8.41% 没卖出。

### 2. 建目录

```cmd
mkdir D:\QMT_STRATEGIES\config
mkdir D:\QMT_POOL\safemode_logs
mkdir D:\QMT_POOL\inbox
mkdir D:\QMT_POOL\sector
```

**盘符必须 D:** —— 项目路径全部写死。新设备没 D 盘要么造一个，要么改 `global_config.yaml` 的 `paths.*`（仍有少量硬编码默认值在 `strategy_main.py` 里改不掉）。

### 3. 拷贝文件

**必拷**：

- `D:\QMT_STRATEGIES\strategy_main.py`（GBK 编码，**必须二进制拷**，别用文本编辑器粘贴）
- `D:\QMT_STRATEGIES\config\global_config.yaml`

**强烈建议拷**：

- `D:\QMT_POOL\sector_heat.json`（板块热度，不拷加分全 0）
- `D:\QMT_POOL\QMTselected.txt` + `selected.txt`（外部选股池，不拷池子空）
- `D:\QMT_POOL\endofday_score_history*.json`（历史分数）

**接管持仓时才拷**：`endofday_holdings_*.txt` / `endofday_nav_*.txt` / `endofday_sell_state_*.json`

**完全不用拷**：`strategy_log_*.txt` / `risk_log_*.txt` / `__pycache__/` / `*.bak_*`，以及 `D:\QMT_STRATEGIES\` 下除上述两个外的**全部内容**（`core/` `adapters/` `backtest/` 等源码） —— `strategy_main.py` 是 build 产物，运行不依赖源目录。

## 常见坑

### 1. QMT Python 路径不是 `python\` 是 `bin.x64\pythonw.exe`

`D:\国金QMT交易端模拟\python\` 下是策略 `.py` 文件，**不是** Python 解释器。真正的 Python 在 `D:\国金QMT交易端模拟\bin.x64\pythonw.exe`（Python 3.6.8，pip 21.0.1）。

### 2. `pythonw.exe` 没有控制台窗口

直接双击不会显示输出。所有 pip / 自检命令必须在外部 cmd / PowerShell 跑。

### 3. PowerShell 调用带引号路径要加 `&`

PowerShell 把开头带引号的字符串当文本而不是命令。错的：

```
"D:\国金QMT交易端模拟\bin.x64\pythonw.exe" -m pip install pyyaml
→ 表达式或语句中包含意外的标记"-m"
```

对的：

```powershell
& "D:\国金QMT交易端模拟\bin.x64\pythonw.exe" -m pip install pyyaml
```

cmd 不需要 `&`。

### 4. 历史 K 线数据要在 QMT 客户端补全

新设备 QMT 首次启动时，历史日 K 线缓存是空的。`check_buy(min_bars=60)` 要求每只股票**至少 60 根日 K**，否则全军覆没，日志显示：

```
[买入信号] 外部池无股票通过技术信号/ST过滤
```

**这不是策略 bug，是数据不足**。补全方法：QMT 客户端 → 系统 / 数据下载 → 选日 K → 向前 ≥120 个交易日 → 全市场或池子里的股票。

或最暴力：把老设备 `D:\国金QMT交易端模拟\userdata\datadir\` 整个拷过来。

### 5. 模拟端 vs 实盘端是两个独立 Python 环境

- 模拟端：`D:\国金QMT交易端模拟\bin.x64\pythonw.exe`
- 实盘端：`D:\国金证券QMT交易端\bin.x64\pythonw.exe`

要在哪个客户端跑策略，就在哪个的 Python 上装包。模拟端装的实盘端用不了。

### 6. `selected.txt` 是外部选股 feeder 写入的

策略本身不生成 `selected.txt`，它读外部选股系统的输出。新设备要么连同一个 feeder，要么手动同步。两台机器 `selected.txt` 内容不一致时，行为差异不是策略 bug。

## strategy_main.py 真实依赖（仅 3 个第三方包）

扫描所有 `import` 语句确认：

| 包 | QMT 自带 | 备注 |
|------|------|------|
| `numpy` | ✓ | 通常 1.19.x |
| `pandas` | ✓ | 通常 0.22.x（老版本！注意 API 兼容） |
| `yaml`（PyYAML） | ✗ | **建议 pip install pyyaml**;不装也能跑(2026-06-29 起内置 fallback) |

其他全是 Python 标准库：`os` / `re` / `sys` / `json` / `math` / `time` / `datetime` / `enum` / `warnings` / `csv` / `urllib`。

`xtquant` 是 QMT 自带交易 API，不需要 pip 装。

## 相关链接

- 完整部署清单：仓库根目录 `DEPLOY.md`
- [[QMT_passorder异步与反查订单号]]
- [[QMT编码制度]]
- Python 解释器路径：`D:\国金QMT交易端模拟\bin.x64\pythonw.exe` / `D:\国金证券QMT交易端\bin.x64\pythonw.exe`
