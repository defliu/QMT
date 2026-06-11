# QMT 策略开发 — 项目级技术指令

## 🏗️ 构建命令

```cmd
python scripts\build_strategy.py                    → strategy_main.py（生产版）
python scripts\build_strategy.py --dev              → strategy_dev.py（开发版）
python scripts\build_strategy.py --allday           → strategy_allday.py（全天调试版）
```

## ✅ 验证命令

```cmd
python scripts\validate_qmt_file.py strategy_main.py
```
**6 项必须 ALL PASS** 才算完成。构建后必须跑。

## ⚡ 自动验证

CC 停止时自动触发 validate（已配置 `settings.json` Stop hook）。但建议手动跑一遍确认。

## 💻 代码风格约束

| 约束 | 说明 |
|------|------|
| 编码 | GBK，`# coding=gbk` 文件头 |
| Python 版本 | 3.6.8 语法兼容 |
| 禁用语法 | `dict[str,...]`、`str\|None`、walrus `:=`、match-case、f-string |
| 文件编辑 | **禁止用 patch 工具直接编辑 GBK 文件** |
| 模块合入 | `build_strategy.py` 的 SOURCE_FILES 排除 `adapters/context_mock.py` |
| 文件路径 | QMT `exec()` 环境无 `__file__`，用绝对路径 `D:/QMT_STRATEGIES/` |
| 依赖 | 只能用 QMT 自带包（xtquant、pandas、numpy） |
| 文件通信 | 持仓/净值/成交通过 `D:/QMT_POOL/` 文本文件传递 |

## 📁 关键目录

| 路径 | 用途 |
|------|------|
| `D:\QMT_STRATEGIES\` | 项目根目录，所有源文件 |
| `D:\QMT_STRATEGIES\specs\` | Hermes 输出 SPEC 的共享目录 |
| `D:\QMT_STRATEGIES\config\` | 策略配置文件（global_config.yaml） |
| `D:\QMT_STRATEGIES\scripts\` | 构建/验证脚本 |
| `D:\QMT_STRATEGIES\release\` | 运营版发布目录 |
| `D:\QMT_POOL\` | 运行时文件交换区 |
| `D:\QMT_STRATEGIES\worklog\` | 每日工作日志 |

## 📋 前情提要

- 当前策略：双带主升浪策略，双模式（尾盘生产版 + 全天调试版）
- 两个 QMT 终端：模拟端（`D:\国金QMT交易端模拟\`）和实盘端（`D:\国金证券QMT交易端\`）
- 模拟端用测试账号 67014907 验证
