# 新设备生产部署清单

把 QMT 策略（`strategy_main.py`）从老设备搬到新设备上跑实盘/模拟，照这份走。

## 一、装第三方包

QMT 自带 Python 是 3.6.8，缺 `pyyaml`，必须先装。

### Python 解释器位置

| QMT 客户端 | Python 路径 |
|------|------|
| 模拟端 | `D:\国金QMT交易端模拟\bin.x64\pythonw.exe` |
| 实盘端 | `D:\国金证券QMT交易端\bin.x64\pythonw.exe` |

（注：bin.x64 目录里**没有 `python.exe`，只有 `pythonw.exe`**；`pythonw.exe` 同样能跑 `-m pip`，命令一样使。）

### 安装命令

**用哪个 QMT 客户端跑策略，就在那个客户端的 Python 上装。** 在 Windows **CMD 或 PowerShell** 里执行（不需要管理员，普通用户即可；bash 也行）：

```cmd
"D:\国金QMT交易端模拟\bin.x64\pythonw.exe" -m pip install pyyaml
```

或实盘端：

```cmd
"D:\国金证券QMT交易端\bin.x64\pythonw.exe" -m pip install pyyaml
```

**验证装好了**：

```cmd
"D:\国金QMT交易端模拟\bin.x64\pythonw.exe" -c "import yaml; print(yaml.__version__)"
```

打印出版本号（如 `6.0.3`）就 OK。再报 `ModuleNotFoundError: No module named 'yaml'` 就是装错 Python 了。

### 网络/代理问题

如果 pip 装不动（公司网/QMT 网络受限）：

```cmd
"D:\国金QMT交易端模拟\bin.x64\pythonw.exe" -m pip install pyyaml -i https://pypi.tuna.tsinghua.edu.cn/simple
```

或者从本机离线拷：本机已装 PyYAML 6.0.3，位置 `D:\国金QMT交易端模拟\bin.x64\lib\site-packages\yaml\` 整个目录拷到新设备同位置即可。

## 二、建目录

新设备建好下面这些（**全部在 D 盘**，路径写死的）：

```cmd
mkdir D:\QMT_STRATEGIES
mkdir D:\QMT_STRATEGIES\config
mkdir D:\QMT_POOL
mkdir D:\QMT_POOL\safemode_logs
mkdir D:\QMT_POOL\inbox
mkdir D:\QMT_POOL\sector
```

bash 写法：

```bash
mkdir -p /d/QMT_STRATEGIES/config
mkdir -p /d/QMT_POOL/safemode_logs /d/QMT_POOL/inbox /d/QMT_POOL/sector
```

## 三、拷贝文件

### 必拷（不拷启动直接挂）

| 源（老设备） | 目标（新设备） | 说明 |
|------|------|------|
| `D:\QMT_STRATEGIES\strategy_main.py` | 同路径 | 策略本体，**GBK 编码必须二进制拷**，别用文本编辑器粘贴 |
| `D:\QMT_STRATEGIES\config\global_config.yaml` | 同路径 | 主配置（safemode/path/账号） |

### 强烈建议拷（不拷功能降级）

| 源 | 目标 | 不拷的后果 |
|------|------|------|
| `D:\QMT_POOL\sector_heat.json` | 同路径 | 板块热度全 0，板块加分用不上 |
| `D:\QMT_POOL\QMTselected.txt` | 同路径 | 选股池入口空 |
| `D:\QMT_POOL\selected.txt` | 同路径 | 备用选股池空 |
| `D:\QMT_POOL\endofday_score_history_beat.json` | 同路径 | 历史分数空，部分判定降级 |
| `D:\QMT_POOL\endofday_score_history.json` | 同路径 | 同上 |

### 接管现有持仓时才拷（从空仓重启就不用拷）

| 文件 | 作用 |
|------|------|
| `D:\QMT_POOL\endofday_holdings_beat.txt` | 尾盘持仓快照 |
| `D:\QMT_POOL\intraday_holdings.txt` | 盘中持仓 |
| `D:\QMT_POOL\endofday_nav_beat.txt` | 尾盘净值 |
| `D:\QMT_POOL\endofday_nav.txt` | 收盘净值 |
| `D:\QMT_POOL\endofday_sell_state_beat.json` | 卖出状态（移动止盈追踪用） |
| `D:\QMT_POOL\intraday_sell_state_beat.json` | 盘中卖出状态 |
| `D:\QMT_POOL\成交记录_尾盘_外部池_beat.txt` | 历史成交日志（文件名 GBK） |

### 完全不用拷

- `strategy_log_*.txt`、`risk_log_*.txt`、`api_test*.txt`、`auto_*.py`、`__pycache__/`、`*.bak_*`、`*.html`、`*.xml`
- `D:\QMT_STRATEGIES\` 下除了 `strategy_main.py` + `config/global_config.yaml` 之外的**全部内容**（`core/`、`adapters/`、`backtest/`、`tests/`、`scripts/`、`worklog/`、`knowledge_base/`、`agent_hub/`、`.git/`） —— 因为 `strategy_main.py` 是 build 产物，已经把源码合并进去了，生产运行**不依赖源码目录**

## 四、配置改账号（实盘必改）

打开 `D:\QMT_STRATEGIES\config\global_config.yaml`，找：

```yaml
account:
  id: "67014907"   # 这是模拟账号
```

实盘部署改成你的真实资金账号（GBK or UTF-8 编辑器都行，文件本身是 UTF-8）。

## 五、在 QMT 客户端里挂载策略

1. 打开 QMT 客户端（模拟端或实盘端）
2. 顶部菜单 → 策略交易 → 公式管理
3. 添加 / 导入 `D:\QMT_STRATEGIES\strategy_main.py` 为 Python 公式
4. 公式名设为 `DUAL_BAND`（与 `global_config.yaml` 的 `strategy.name` 一致）
5. 加载到任意股票图表（如 600110.SH）触发运行
6. 看 QMT FormulaOutput 日志确认无报错（`D:\国金QMT交易端模拟\userdata\log\XtClient_FormulaOutput_YYYYMMDD.log`）

## 六、首次运行自检

策略加载后看日志，按顺序确认：

| 日志关键字 | 含义 |
|------|------|
| `[策略启动]` 类信息 | 加载成功 |
| `[选股池] 读取 X 只` | `QMTselected.txt` 读到了 |
| `[板块热度] ...` | `sector_heat.json` 读到了 |
| `ModuleNotFoundError: No module named 'xxx'` | 缺包，回到第一步 pip install |
| `FileNotFoundError: ... D:/QMT_POOL/...` | 文件没拷，回到第三步 |
| `[卖出反查失败]`（仅 v2 修复后） | 委托没到交易所（券商网络/账户问题，不是部署问题） |

## 七、常见坑

1. **盘符必须 D:** —— 所有路径写死 `D:/QMT_STRATEGIES/` 和 `D:/QMT_POOL/`。新设备如果没有 D: 盘，要么造一个（分区/挂载点/`subst`），要么改 `global_config.yaml` 的 `paths.*`（仍有少量硬编码默认值在 `strategy_main.py` 里改不了，必须配 D 盘最省事）
2. **GBK 编码不能用 git/文本工具误转** —— 拷 `strategy_main.py` 用 U 盘 / 网盘 / `xcopy /B` / `robocopy`，**不要**复制粘贴文件内容到新设备的编辑器
3. **模拟端和实盘端 Python 各自独立** —— `pyyaml` 要在你要用的那个客户端的 Python 上装，模拟端装的实盘端用不了
4. **`pythonw.exe` 没控制台窗口** —— 直接双击不会显示输出，所有验证命令在 cmd/PowerShell 里跑
5. **`pip` 装到 user 目录** —— 默认安装到 `%APPDATA%\Python\Python36\site-packages\`，QMT Python 能找到；如果想装到 QMT 自己的 site-packages，加 `--target "D:\国金QMT交易端模拟\bin.x64\lib\site-packages"` 参数

## 八、最小化离线包（一键备份）

如果要打包给新设备/异地，最小集是这些（约几 MB）：

```
deploy_package/
├── strategy_main.py                              # GBK
├── config/
│   └── global_config.yaml
├── QMT_POOL_data/
│   ├── sector_heat.json
│   ├── QMTselected.txt
│   ├── selected.txt
│   └── endofday_score_history_beat.json
├── pyyaml-6.0.3-cp36-cp36m-win_amd64.whl         # 离线 pip 包（可选）
└── DEPLOY.md                                      # 本文件
```

新设备解包后按本文档第一~五节操作即可。
