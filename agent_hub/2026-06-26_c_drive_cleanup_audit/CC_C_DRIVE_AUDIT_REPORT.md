# C 盘空间清理排查报告

**日期**: 2026-06-26  
**执行时间**: 2026-06-26T14:18:39Z  
**执行者**: MIMO (mimo-auto)  
**目的**: C 盘 100% 满，排查占用并分类报告，供决策清理。

---

## TASK-1: C 盘顶层目录占用 TOP 15

使用 `du -sh /c/*` 扫描，按大小降序取 TOP 15：

```
48G	/c/Users
26G	/c/Windows
11G	/c/Program Files
5.2G	/c/ProgramData
4.2G	/c/Program Files (x86)
663M	/c/Thunisoft
256M	/c/swapfile.sys
127M	/c/libcef.dll
114M	/c/$Recycle.Bin
10M	/c/icudtl.dat
6.7M	/c/resources.pak
5.6M	/c/libGLESv2.dll
5.2M	/c/AppData
3.5M	/c/d3dcompiler_47.dll
2.7M	/c/swiftshader
```

---

## TASK-2: 已知可清理热点排查

逐项排查结果（按工单顺序）：

| # | 热点路径 | 是否存在 | 大小 (GB) |
|---|---|---|---|
| 1 | `C:\Users\Administrator\AppData\Local\Temp` | 是 | 0.16 |
| 2 | `C:\Windows\Temp` | 是 | 0.06 |
| 3 | npm-cache (`C:\Users\Administrator\AppData\Local\npm-cache`) | 是 | 2.50 |
| 4 | `C:\Users\Administrator\AppData\Local\pip\cache` | 是 | 0.16 |
| 5 | `.claude` 子目录（见下表） | 是 | 见子表 |
| 6 | `C:\Users\Administrator\Downloads` | 是 | 1.50 |
| 7 | `C:\Users\Administrator\AppData\Local\Microsoft\Windows\INetCache` | 是 | 0.00 |
| 8 | `C:\Windows\SoftwareDistribution\Download` | 是 | 0.02 |
| 9 | `C:\$Recycle.Bin` | 是 | 0.11 |
| 10 | `C:\hiberfil.sys` | 否 | 无 |
| 11 | `C:\pagefile.sys` | 否 | 无 |
| 12 | `C:\Windows\Logs` | 是 | 0.16 |
| 12 | `C:\Windows\Panther` | 是 | 0.00 |
| 13 | `C:\Users\Administrator\AppData\Local\CrashDumps` | 是 | 0.20 |
| 14 | Docker/WSL (`C:\Users\Administrator\AppData\Local\Docker\wsl`) | 是 | 0.00 |
| 15 | `node_modules` TOP 10（见下表） | 是 | 见子表 |
| 15 | `__pycache__` TOP 10（见下表） | 是 | 见子表 |

### `.claude` 子目录详情

| 子目录 | 大小 (GB) |
|---|---|
| `.claude/backups/` | 0.00 |
| `.claude/cache/` | 0.00 |
| `.claude/file-history/` | 0.01 |
| `.claude/ide/` | 0.00 |
| `.claude/paste-cache/` | 0.00 |
| `.claude/plans/` | 0.00 |
| `.claude/plugins/` | 0.00 |
| `.claude/projects/` | 0.05 |
| `.claude/session-env/` | 0.00 |
| `.claude/sessions/` | 0.00 |
| `.claude/shell-snapshots/` | 0.00 |
| `.claude/skills/` | 0.00 |
| `.claude/tasks/` | 0.00 |
| `.claude/telemetry/` | 0.00 |
| **总计** | **0.06** |

### `node_modules` TOP 10

| 路径 | 大小 (GB) |
|---|---|
| `.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules` | 0.30 |
| `AppData/Local/npm-cache/_npx/2fdb3b6849710270/node_modules` | 0.27 |
| `AppData/Roaming/npm/node_modules/@mimo-ai/cli/node_modules` | 0.27 |
| `AppData/Roaming/npm/node_modules` | 0.27 |
| `AppData/Local/OpenAI/Codex/runtimes/cua_node/789504f803e82e2b/bin/node_modules` | 0.18 |
| `.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/.pnpm/node_modules` | 0.12 |
| `.workbuddy/binaries/node/cli-connector-packages/node_modules` | 0.08 |
| `AppData/Local/npm-cache/_npx/6de2aa2fded2970c/node_modules` | 0.07 |
| `.vscode/extensions/continue.continue-2.0.0-win32-x64/out/node_modules` | 0.06 |
| `AppData/Roaming/QQ/qqex/dynamic_package/exMiniDoc/3.8.1.69/node_modules` | 0.06 |
| **总计** | **1.41** |

### `__pycache__` TOP 10

| 路径 | 大小 (GB) |
|---|---|
| `.workbuddy/binaries/python/envs/default/Lib/site-packages/numpy/_core/tests/__pycache__` | 0.00 |
| `.workbuddy/binaries/python/envs/default/Lib/site-packages/pygments/lexers/__pycache__` | 0.00 |
| `.cache/codex-runtimes/codex-primary-runtime/dependencies/python/Lib/site-packages/numpy/_core/tests/__pycache__` | 0.00 |
| `.cache/codex-runtimes/codex-primary-runtime/dependencies/python/Lib/__pycache__` | 0.00 |
| `.cache/codex-runtimes/codex-primary-runtime/dependencies/python/Lib/site-packages/pandas/core/__pycache__` | 0.00 |
| `.workbuddy/binaries/python/envs/default/Lib/site-packages/pandas/core/__pycache__` | 0.00 |
| `.workbuddy/binaries/python/envs/default/Lib/site-packages/pandas/tests/frame/methods/__pycache__` | 0.00 |
| `.cache/codex-runtimes/codex-primary-runtime/dependencies/python/Lib/site-packages/PIL/__pycache__` | 0.00 |
| `.cache/codex-runtimes/codex-primary-runtime/dependencies/python/Lib/site-packages/pandas/tests/frame/methods/__pycache__` | 0.00 |
| `.workbuddy/binaries/python/envs/default/Lib/site-packages/rich/__pycache__` | 0.00 |
| **总计** | **0.02** |

---

## TASK-3: 分类报告

| 路径 | 大小GB | 类别 | 清理建议命令 (不执行) | 备注 |
|---|---|---|---|---|
| `C:\Users\Administrator\AppData\Local\Temp` | 0.16 | A | `Remove-Item -Path "$env:TEMP\*" -Recurse -Force` | 用户临时文件 |
| `C:\Windows\Temp` | 0.06 | A | `Remove-Item -Path "C:\Windows\Temp\*" -Recurse -Force` | 系统临时文件 |
| `C:\Users\Administrator\AppData\Local\npm-cache` | 2.50 | B | `npm cache clean --force` | 可能需重装包 |
| `C:\Users\Administrator\AppData\Local\pip\cache` | 0.16 | A | `pip cache purge` | pip缓存 |
| `.claude` 子目录 (总计) | 0.06 | B | 手动清理各子目录 | 含工作树、会话历史 |
| `C:\Users\Administrator\Downloads` | 1.50 | B | 手动选择删除 | 用户下载文件 |
| `C:\Users\Administrator\AppData\Local\Microsoft\Windows\INetCache` | 0.00 | A | 清理IE/Edge缓存 | 已很小 |
| `C:\Windows\SoftwareDistribution\Download` | 0.02 | A | 停止Windows Update服务后删除 | Windows更新缓存 |
| `C:\$Recycle.Bin` | 0.11 | A | 清空回收站 | 回收站 |
| `C:\Windows\Logs` | 0.16 | A | 删除旧日志文件 | 系统日志 |
| `C:\Windows\Panther` | 0.00 | A | 删除旧安装日志 | 已很小 |
| `C:\Users\Administrator\AppData\Local\CrashDumps` | 0.20 | A | 删除所有 .dmp 文件 | 崩溃转储 |
| Docker/WSL (`C:\Users\Administrator\AppData\Local\Docker\wsl`) | 0.00 | B | 管理WSL虚拟磁盘 | 可能含容器数据 |
| `node_modules` TOP 10 (总计) | 1.41 | B | 手动删除不需要的node_modules | 项目依赖缓存 |
| `__pycache__` TOP 10 (总计) | 0.02 | A | 删除所有 `__pycache__` 目录 | Python字节码缓存 |

### 汇总

如果全清 **A 类**（低风险）项目，预计可释放约 **0.97 GB**（0.16 + 0.06 + 0.16 + 0.00 + 0.02 + 0.11 + 0.16 + 0.00 + 0.20 + 0.02）。

**注意**：以上大小为近似值，实际清理效果可能略有差异。所有操作需人工确认后执行。